const fs = require('node:fs');
fs.mkdirSync('dist/vendor', {recursive: true});
for (const name of ['index.html', 'app.js', 'nuv.js', 'style.css', 'nuv_creator.py', 'sample.nuv']) {
  fs.copyFileSync(name, `dist/${name}`);
}
for (const pkg of ['ffmpeg', 'core']) {
  fs.cpSync(`node_modules/@ffmpeg/${pkg}/dist/umd`, `dist/vendor/${pkg}`, {recursive: true});
}
fs.writeFileSync('dist/.nojekyll', '');
