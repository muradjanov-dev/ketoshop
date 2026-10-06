const fs = require('node:fs');
const assert = require('node:assert/strict');
const vm = require('node:vm');

for (const file of ['webapp/index.html', 'webapp/admin.html']) {
  const html = fs.readFileSync(file, 'utf8');
  assert.doesNotMatch(html, /working_hours|pickupHours|Ish vaqti:|Часы работы/,
    `${file} must not expose pickup working hours`);
  const scripts = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)];
  scripts.forEach((match, index) => new vm.Script(match[1], {filename: `${file}#inline-${index + 1}`}));
  console.log(`${file}: ${scripts.length} inline script(s) parse`);
}
