import {packNUV, unpackNUV, LIMIT} from './nuv.js';
const $ = id => document.getElementById(id);
let selected, mode = 'mp4', engine, busy = false, resultURL, logs = [];
function status(message) { $('status').textContent = message; }
function choose(file) {
  if (busy || !file) return;
  if (file.size > 128 * 1024 * 1024) { status('入力は128 MBまでです。大きな動画はPython版をご利用ください。'); return; }
  selected = file; $('filename').textContent = `${file.name} · ${(file.size / 1048576).toFixed(2)} MB`;
  $('convert').disabled = false; $('result').hidden = true; status('準備できました。変換を開始できます。');
}
function setMode(value) {
  if (busy) return;
  mode = value; for (const id of ['mp4', 'nuv']) { $(id).classList.toggle('active', id === value); $(id).setAttribute('aria-pressed', String(id === value)); }
  $('settings').hidden = value !== 'nuv'; $('convert').innerHTML = (value === 'mp4' ? 'MP4' : 'NUV') + 'に変換する <span>→</span>';
  $('result').hidden = true;
}
$('mp4').onclick = () => setMode('mp4'); $('nuv').onclick = () => setMode('nuv');
$('file').onchange = event => choose(event.target.files[0]);
$('drop').ondragover = event => { event.preventDefault(); $('drop').classList.add('drag'); };
$('drop').ondragleave = () => $('drop').classList.remove('drag');
$('drop').ondrop = event => { event.preventDefault(); $('drop').classList.remove('drag'); choose(event.dataTransfer.files[0]); };
$('sample').onclick = async () => {
  try { const response = await fetch('sample.nuv'); if (!response.ok) throw Error('サンプルを読み込めませんでした。'); setMode('mp4'); choose(new File([await response.blob()], 'sample.nuv')); }
  catch (error) { status(error.message); }
};
function resetEngine() { if (engine) { engine.terminate(); engine = null; } }
$('cancel').onclick = () => { resetEngine(); status('変換を中止しました。'); };
async function loadEngine() {
  if (engine) return engine;
  const instance = new window.FFmpegWASM.FFmpeg(); engine = instance;
  instance.on('log', ({message}) => { logs.push(message); if (logs.length > 100) logs.shift(); $('logs').textContent = logs.join('\n'); });
  instance.on('progress', ({progress}) => { if (progress > 0 && progress <= 1) $('progress').value = progress; });
  status('変換エンジンを読み込み中…（初回は約32 MB）');
  await instance.load({coreURL: new URL('vendor/core/ffmpeg-core.js', location.href).href, wasmURL: new URL('vendor/core/ffmpeg-core.wasm', location.href).href});
  return instance;
}
async function exec(ff, args) { const code = await ff.exec(args); if (code !== 0) throw Error('変換に失敗しました。変換ログを確認してください。'); }
$('convert').onclick = async () => {
  if (!selected || busy) return;
  busy = true; logs = []; $('logs').textContent = ''; $('details').hidden = false;
  for (const id of ['convert', 'file', 'mp4', 'nuv', 'sample', 'width', 'height', 'fps']) $(id).disabled = true;
  $('progress').hidden = false; $('progress').removeAttribute('value'); $('cancel').hidden = false; $('result').hidden = true;
  let ff;
  try {
    ff = await loadEngine(); status('変換中… このタブを開いたままお待ちください。');
    let bytes = new Uint8Array(await selected.arrayBuffer()), output;
    if (mode === 'mp4') {
      const raw = unpackNUV(bytes);
      let input;
      if (raw) {
        await ff.writeFile('input.raw', raw.raw);
        input = ['-f','rawvideo','-pixel_format','yuv420p','-video_size',`${raw.width}x${raw.height}`,'-framerate',String(raw.fps),'-i','input.raw'];
      } else { await ff.writeFile('input.nuv', bytes); input = ['-i','input.nuv']; }
      await exec(ff, [...input,'-map','0:v:0','-map','0:a:0?','-c:v','libx264','-preset','ultrafast','-crf','20','-vf','pad=ceil(iw/2)*2:ceil(ih/2)*2','-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart','output.mp4']);
      output = await ff.readFile('output.mp4');
    } else {
      const width = Number($('width').value), height = Number($('height').value), fps = Number($('fps').value);
      if (![width,height,fps].every(Number.isInteger) || width < 16 || height < 16 || width > 1920 || height > 1080 || width % 2 || height % 2 || fps < 1 || fps > 60) throw Error('幅・高さは範囲内の偶数、FPSは1〜60の整数にしてください。');
      await ff.writeFile('input.video', bytes);
      const maxFrames = Math.floor((LIMIT - 596) / (width * height * 1.5 + 12));
      await exec(ff, ['-i','input.video','-map','0:v:0','-an','-vf',`scale=${width}:${height}:force_original_aspect_ratio=decrease,pad=${width}:${height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=${fps}`,'-frames:v',String(maxFrames + 1),'-pix_fmt','yuv420p','-c:v','rawvideo','-f','rawvideo','output.raw']);
      output = packNUV(await ff.readFile('output.raw'), width, height, fps);
    }
    if (resultURL) URL.revokeObjectURL(resultURL);
    resultURL = URL.createObjectURL(new Blob([output], {type: mode === 'mp4' ? 'video/mp4' : 'application/octet-stream'}));
    $('download').href = resultURL; $('download').download = selected.name.replace(/\.[^.]+$/, '') + '_converted.' + mode;
    $('preview').hidden = mode !== 'mp4'; if (mode === 'mp4') $('preview').src = resultURL;
    $('result').hidden = false; $('progress').value = 1;
    const warnings = logs.some(line => /error|invalid|corrupt/i.test(line));
    status(warnings ? '変換が終了しました。ログに警告・エラーがあります。保存前に動画を確認してください。' : `変換完了 · ${(output.length/1048576).toFixed(2)} MB。下のボタンから保存できます。`);
  } catch (error) {
    status(engine ? `エラー：${error.message}` : '変換を中止しました。再度変換できます。');
  } finally {
    if (ff && engine === ff) { for (const name of ['input.raw','input.nuv','input.video','output.mp4','output.raw']) { try { await ff.deleteFile(name); } catch {} } }
    resetEngine(); busy = false; $('cancel').hidden = true;
    for (const id of ['convert','file','mp4','nuv','sample','width','height','fps']) $(id).disabled = false;
  }
};
