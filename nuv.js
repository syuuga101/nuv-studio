export const LIMIT = 256 * 1024 * 1024;
const ascii = (data, start, length) => new TextDecoder().decode(data.subarray(start, start + length));
export function unpackNUV(bytes) {
  if (bytes.length < 596 || ascii(bytes, 0, 17) !== 'NuppelVideo\x000.05\x00') return null;
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (view.getInt32(60, true) || view.getInt32(64, true)) return null;
  if (ascii(bytes, 72, 2) !== 'DR' || view.getUint32(80, true) !== 512) return null;
  for (let i = 84; i < 596; i += 4) if (view.getUint32(i, true) !== 1) return null;
  const width = view.getUint32(20, true), height = view.getUint32(24, true);
  const fps = view.getFloat64(48, true), frames = view.getInt32(56, true);
  const size = width * height * 1.5;
  if (width < 16 || height < 16 || width % 2 || height % 2 || size > 0xffffff || !(fps >= 1 && fps <= 120) || frames <= 0)
    throw Error('NUVの映像情報が不正です。');
  if (596 + frames * (size + 12) !== bytes.length) throw Error('NUVのサイズが一致しません。ファイルが途中で切れている可能性があります。');
  const raw = new Uint8Array(frames * size);
  for (let i = 0; i < frames; i++) {
    const offset = 596 + i * (size + 12);
    if (ascii(bytes, offset, 2) !== 'V0' || view.getUint16(offset + 2, true) !== 0 ||
        view.getUint32(offset + 4, true) !== Math.round(i * 1000 / fps) || view.getUint32(offset + 8, true) !== size)
      throw Error(`フレーム${i + 1}の情報が不正です。`);
    raw.set(bytes.subarray(offset + 12, offset + 12 + size), i * size);
  }
  return {raw, width, height, fps, frames};
}
export function packNUV(raw, width, height, fps) {
  const size = width * height * 1.5, frames = raw.length / size;
  if (!Number.isInteger(frames) || frames < 1) throw Error('映像データが不足しています。');
  const length = 596 + frames * (size + 12);
  if (length > LIMIT) throw Error('出力が256 MBを超えます。解像度やFPSを下げるか、Python版をお使いください。');
  const bytes = new Uint8Array(length), v = new DataView(bytes.buffer);
  const write = (offset, text) => bytes.set(new TextEncoder().encode(text), offset);
  write(0, 'NuppelVideo\0'); write(12, '0.05\0');
  for (const offset of [20, 28]) v.setUint32(offset, width, true);
  for (const offset of [24, 32]) v.setUint32(offset, height, true);
  write(36, 'P'); v.setFloat64(40, width / height, true); v.setFloat64(48, fps, true);
  v.setInt32(56, frames, true); v.setInt32(68, 1, true);
  write(72, 'DR'); v.setUint32(80, 512, true);
  for (let i = 84; i < 596; i += 4) v.setUint32(i, 1, true);
  for (let i = 0; i < frames; i++) {
    const offset = 596 + i * (size + 12);
    write(offset, 'V0'); v.setUint32(offset + 4, Math.round(i * 1000 / fps), true);
    v.setUint32(offset + 8, size, true); bytes.set(raw.subarray(i * size, (i + 1) * size), offset + 12);
  }
  return bytes;
}
