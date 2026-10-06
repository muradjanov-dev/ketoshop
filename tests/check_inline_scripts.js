const fs = require('node:fs');
const vm = require('node:vm');

for (const file of ['webapp/index.html', 'webapp/admin.html']) {
  const html = fs.readFileSync(file, 'utf8');
  const scripts = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)];
  scripts.forEach((match, index) => new vm.Script(match[1], {filename: `${file}#inline-${index + 1}`}));
  console.log(`${file}: ${scripts.length} inline script(s) parse`);
}
