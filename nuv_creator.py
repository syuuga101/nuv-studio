"""Simple video-only NuppelVideo writer. Python 3.10+, FFmpeg required."""
import argparse
import os
from pathlib import Path
import queue
import shutil
import struct
import subprocess
import tempfile
import threading


def find_ffmpeg(value='ffmpeg'):
    value = str(value).strip().strip('"')
    found = shutil.which(value)
    if found:
        return found
    if value == 'ffmpeg':
        packages = Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft/WinGet/Packages'
        for candidate in packages.glob('Gyan.FFmpeg_*/ffmpeg-*/bin/ffmpeg.exe'):
            return str(candidate)
    raise ValueError('FFmpegが見つかりません。「参照」でffmpeg.exeを指定してください。')


def raw_nuv_info(path):
    """Recognize and validate this tool's exact raw, video-only NUV layout."""
    with open(path, 'rb') as stream:
        metadata = stream.read(72)
        if len(metadata) != 72 or metadata[:17] != b'NuppelVideo\x000.05\x00':
            return None
        width, height = struct.unpack_from('<II', metadata, 20)
        fps = struct.unpack_from('<d', metadata, 48)[0]
        frames, audio, text = struct.unpack_from('<iii', metadata, 56)
        if audio or text or stream.read(12) != packet(b'D', b'R', 0, 512):
            return None
        if stream.read(512) != struct.pack('<128I', *([1] * 128)):
            return None
        if width < 16 or height < 16 or width % 2 or height % 2 or not 1 <= fps <= 120:
            raise ValueError('NUVの解像度またはFPSが不正です。')
        size = width * height * 3 // 2
        if size > 0xffffff or frames <= 0:
            raise ValueError('NUVのフレーム情報が不正です。')
        expected = 596 + frames * (12 + size)
        if os.fstat(stream.fileno()).st_size != expected:
            raise ValueError('NUVのサイズがフレーム数と一致しません。破損・途中切れの可能性があります。')
        for index in range(frames):
            if stream.read(12) != packet(b'V', b'0', round(index * 1000 / fps), size):
                raise ValueError(f'NUVのフレーム{index + 1}のヘッダーが不正です。')
            stream.seek(size, 1)
        return width, height, fps, frames, size


def to_mp4(source, destination, ffmpeg='ffmpeg', cancel=None,
           progress=lambda message: None, **unused):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file():
        raise ValueError('入力ファイルがありません。')
    if destination.exists() or source == destination:
        raise ValueError('出力には、まだ存在しない別のファイル名を指定してください。')
    if destination.suffix.lower() != '.mp4':
        raise ValueError('出力の拡張子は .mp4 にしてください。')
    if not destination.parent.is_dir():
        raise ValueError('出力先フォルダーがありません。')
    executable = find_ffmpeg(ffmpeg)
    cancel = cancel or threading.Event()
    raw_info = raw_nuv_info(source)
    fd, temporary = tempfile.mkstemp(prefix='.mp4-', suffix='.mp4', dir=destination.parent)
    os.close(fd)
    process = None
    try:
        with tempfile.TemporaryFile() as errors:
            input_options = (['-f', 'rawvideo', '-pixel_format', 'yuv420p',
                              '-video_size', f'{raw_info[0]}x{raw_info[1]}',
                              '-framerate', str(raw_info[2]), '-i', 'pipe:0']
                             if raw_info else ['-i', str(source)])
            command = [executable, '-hide_banner', '-loglevel', 'error', '-nostdin',
                       '-y', *input_options, '-map', '0:v:0', '-map', '0:a:0?',
                       '-c:v', 'libx264', '-preset', 'medium', '-crf', '20',
                       '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2', '-pix_fmt', 'yuv420p',
                       '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', temporary]
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=errors,
                                       stdin=subprocess.PIPE if raw_info else subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            feed_errors = []
            feeder = None
            if raw_info:
                def feed():
                    try:
                        with open(source, 'rb') as incoming:
                            incoming.seek(596)
                            for index in range(raw_info[3]):
                                if cancel.is_set():
                                    break
                                incoming.seek(12, 1)
                                frame = incoming.read(raw_info[4])
                                if len(frame) != raw_info[4]:
                                    raise RuntimeError('NUVの映像データが途中で途切れました。')
                                process.stdin.write(frame)
                    except Exception as error:
                        feed_errors.append(error)
                    finally:
                        try:
                            process.stdin.close()
                        except OSError:
                            pass
                feeder = threading.Thread(target=feed, daemon=True)
                feeder.start()
            progress('MP4へ変換中…（元の解像度・フレームレートを使用）')
            while process.poll() is None:
                if cancel.wait(.1):
                    process.kill()
                    process.wait()
                    raise RuntimeError('変換を中止しました。')
            errors.seek(0)
            log = errors.read().decode('utf-8', errors='replace').strip()
            if feeder:
                feeder.join()
            if feed_errors and not cancel.is_set():
                raise RuntimeError(f'NUV読み込み失敗：{feed_errors[0]}\n{log}')
            if cancel.is_set():
                raise RuntimeError('変換を中止しました。')
            if process.returncode or Path(temporary).stat().st_size < 256:
                raise RuntimeError(log or 'MP4への変換に失敗しました。')
        created = False
        try:
            with open(destination, 'xb') as target, open(temporary, 'rb') as incoming:
                created = True
                shutil.copyfileobj(incoming, target)
        except BaseException:
            if created:
                destination.unlink(missing_ok=True)
            raise
        return 'MP4変換完了' + (f'\nFFmpegからのメッセージ：\n{log}' if log else '')
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        Path(temporary).unlink(missing_ok=True)


def header(width, height, fps, frames=-1):
    return struct.pack('<12s5s3xIIIIc3xddiiii', b'NuppelVideo\0', b'0.05\0',
                       width, height, width, height, b'P', width / height,
                       fps, frames, 0, 0, 1)


def packet(kind, subtype, timestamp, size):
    return struct.pack('<ccBBII', kind, subtype, 0, 0, timestamp, size)


def convert(source, destination, ffmpeg='ffmpeg', width=640, height=480,
            fps=30, cancel=None, progress=lambda message: None):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file():
        raise ValueError('入力ファイルがありません。')
    if source == destination or destination.exists():
        raise ValueError('出力には、まだ存在しない別のファイル名を指定してください。')
    if not destination.parent.is_dir():
        raise ValueError(f'出力先フォルダーがありません：{destination.parent}')
    ffmpeg = str(ffmpeg).strip().strip('"')
    executable = find_ffmpeg(ffmpeg)
    if executable is None:
        raise ValueError('FFmpegが見つかりません。FFmpeg欄の「参照」から、'
                         'ダウンロード・展開したffmpeg.exeを選択してください。'
                         f'\n現在の指定：{ffmpeg}')
    if destination.suffix.lower() != '.nuv':
        raise ValueError('出力の拡張子は .nuv にしてください。')
    if width < 16 or height < 16 or width % 2 or height % 2:
        raise ValueError('幅と高さは16以上の偶数にしてください。')
    size = width * height * 3 // 2
    if size > 0xffffff or not 1 <= fps <= 120:
        raise ValueError('解像度が大きすぎるか、FPSが1〜120の範囲外です。')
    command = [executable, '-hide_banner', '-loglevel', 'error', '-nostdin',
               '-i', str(source), '-map', '0:v:0', '-an', '-sn', '-dn',
               '-vf', f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
               f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}',
               '-pix_fmt', 'yuv420p', '-c:v', 'rawvideo', '-f', 'rawvideo', 'pipe:1']
    cancel = cancel or threading.Event()
    fd, temporary = tempfile.mkstemp(prefix='.nuv-', dir=destination.parent)
    process = None
    done = threading.Event()
    try:
        with os.fdopen(fd, 'wb') as output, tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

            def stop_watcher():
                while not done.wait(.1):
                    if cancel.is_set():
                        try:
                            process.kill()
                        except OSError:
                            pass
                        return

            threading.Thread(target=stop_watcher, daemon=True).start()
            output.write(header(width, height, fps))
            # Decoder initialization data; raw frames do not use these tables.
            output.write(packet(b'D', b'R', 0, 512))
            output.write(struct.pack('<128I', *([1] * 128)))
            count = 0
            while True:
                data = bytearray()
                while len(data) < size:
                    chunk = process.stdout.read(size - len(data))
                    if not chunk:
                        break
                    data.extend(chunk)
                if cancel.is_set():
                    raise RuntimeError('変換を中止しました。')
                if not data:
                    break
                if len(data) != size:
                    raise RuntimeError('FFmpegの映像データが途中で途切れました。')
                timestamp = round(count * 1000 / fps)
                if timestamp > 0xffffffff or count >= 0x7fffffff:
                    raise RuntimeError('NUVの時間・フレーム数の上限です。')
                output.write(packet(b'V', b'0', timestamp, size))
                output.write(data)
                count += 1
                if count % fps == 0:
                    progress(f'{count / fps:.0f}秒 / {count}フレーム / {output.tell()/1048576:.1f} MB')
            result = process.wait()
            if result:
                errors.seek(max(0, errors.seek(0, 2) - 6000))
                raise RuntimeError(errors.read().decode('utf-8', errors='replace'))
            if count == 0:
                raise RuntimeError('変換できる映像フレームがありません。')
            if cancel.is_set():
                raise RuntimeError('変換を中止しました。')
            output.seek(0)
            output.write(header(width, height, fps, count))
        # Exclusive creation preserves existing files even if created during conversion.
        created = False
        try:
            with open(destination, 'xb') as target, open(temporary, 'rb') as source_file:
                created = True
                shutil.copyfileobj(source_file, target)
        except BaseException:
            if created:
                destination.unlink(missing_ok=True)
            raise
        return count
    finally:
        done.set()
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdout.close()
        Path(temporary).unlink(missing_ok=True)


def gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    root = tk.Tk()
    root.title('NUV・MP4変換ツール')
    root.columnconfigure(1, weight=1)
    values = {key: tk.StringVar(value=value) for key, value in
              [('source', ''), ('output', ''), ('ffmpeg', shutil.which('ffmpeg') or 'ffmpeg'),
               ('width', '640'), ('height', '480'), ('fps', '30')]}
    mode = tk.StringVar(value='NUV → MP4')
    labels = ['入力動画', '出力動画', 'FFmpeg', '幅（NUV作成時）', '高さ（NUV作成時）', 'FPS（NUV作成時）']
    for row, (key, value) in enumerate(values.items()):
        ttk.Label(root, text=labels[row]).grid(row=row, column=0, padx=8, pady=5)
        ttk.Entry(root, textvariable=value, width=55).grid(row=row, column=1, sticky='ew', padx=8)

    def browse(key):
        extension = '.mp4' if mode.get() == 'NUV → MP4' else '.nuv'
        path = (filedialog.asksaveasfilename(defaultextension=extension, filetypes=[('動画', '*' + extension)])
                if key == 'output' else filedialog.askopenfilename())
        if path:
            values[key].set(path)
            if key == 'source' and not values['output'].get():
                values['output'].set(str(Path(path).with_name(Path(path).stem + '_converted' + extension)))

    for row, key in enumerate(['source', 'output', 'ffmpeg']):
        ttk.Button(root, text='参照', command=lambda k=key: browse(k)).grid(row=row, column=2, padx=8)
    ttk.Label(root, text='NUV作成：映像のみ・非圧縮。640×480/30fpsで約830 MB/分。\nMP4変換：H.264＋AAC。入力に音声があれば保存します。\n出力と一時ファイル用に、出力容量の約2倍の空き容量が必要です。',
              wraplength=560).grid(row=6, column=0, columnspan=3, padx=10, pady=10)
    status = tk.StringVar(value='入力動画と出力先を選択してください。')
    ttk.Label(root, textvariable=status, wraplength=560).grid(row=7, column=0, columnspan=3, padx=10, pady=8)
    events = queue.Queue()
    stop = threading.Event()
    busy = False

    def start():
        nonlocal busy
        if busy:
            return
        try:
            options = {key: value.get().strip() for key, value in values.items()}
            for key in ['width', 'height', 'fps']:
                options[key] = int(options[key])
            options['destination'] = options.pop('output')
            mp4_mode = mode.get() == 'NUV → MP4'
        except ValueError:
            messagebox.showerror('設定エラー', '幅・高さ・FPSは整数にしてください。')
            return
        busy = True
        stop.clear()
        start_button.config(state='disabled')
        status.set('変換を開始しています…')

        def run():
            try:
                result = (to_mp4 if mp4_mode else convert)(**options, cancel=stop, progress=lambda m: events.put(('progress', m)))
                events.put(('done', f'完了：{result}\n{options["destination"]}'))
            except Exception as error:
                events.put(('error', str(error)))
        threading.Thread(target=run, daemon=True).start()

    def poll():
        nonlocal busy
        try:
            while True:
                kind, message = events.get_nowait()
                status.set(message)
                if kind != 'progress':
                    busy = False
                    start_button.config(state='normal')
                    if kind == 'error':
                        messagebox.showerror('変換エラー', message)
        except queue.Empty:
            pass
        root.after(100, poll)

    def close():
        stop.set()
        if busy:
            status.set('停止処理中…')
            root.after(150, close)
        else:
            root.destroy()

    def change_mode(event=None):
        extension = '.mp4' if mode.get() == 'NUV → MP4' else '.nuv'
        if values['output'].get():
            values['output'].set(str(Path(values['output'].get()).with_suffix(extension)))

    mode_box = ttk.Combobox(root, textvariable=mode, values=['NUV → MP4', '動画 → NUV'], state='readonly')
    mode_box.grid(row=9, column=1, pady=8)
    mode_box.bind('<<ComboboxSelected>>', change_mode)
    start_button = ttk.Button(root, text='変換開始', command=start)
    start_button.grid(row=8, column=1, pady=12)
    ttk.Button(root, text='中止', command=stop.set).grid(row=8, column=2)
    root.protocol('WM_DELETE_WINDOW', close)
    poll()
    root.mainloop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='映像のみの非圧縮NUVを作成。引数なしでGUI起動。')
    parser.add_argument('source', nargs='?')
    parser.add_argument('destination', nargs='?')
    parser.add_argument('--ffmpeg', default='ffmpeg')
    parser.add_argument('--width', type=int, default=640)
    parser.add_argument('--height', type=int, default=480)
    parser.add_argument('--fps', type=int, default=30)
    args = parser.parse_args()
    if args.source:
        if not args.destination:
            parser.error('出力先の .nuv または .mp4 ファイルを指定してください。')
        try:
            action = to_mp4 if Path(args.destination).suffix.lower() == '.mp4' else convert
            print(f'完了: {action(**vars(args), progress=print)}')
        except Exception as error:
            parser.exit(1, f'エラー: {error}\n')
    else:
        gui()
