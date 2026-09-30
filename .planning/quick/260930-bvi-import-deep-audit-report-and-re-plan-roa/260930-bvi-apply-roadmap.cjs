'use strict';
// Quick task 260930-bvi: apply BLOCK 1, 2, 3, 4a and 4b of 260930-bvi-ROADMAP-SECTIONS.md to .planning/ROADMAP.md.
//
// Run from the repository root:
//   node .planning/quick/<this-dir>/260930-bvi-apply-roadmap.cjs            (writes .planning/ROADMAP.md)
//   node .planning/quick/<this-dir>/260930-bvi-apply-roadmap.cjs --dry-run  (validates anchors, writes nothing)
//
// Block text is copied verbatim: every line strictly between "<<<BLOCK n" and "BLOCK n>>>" in the SECTIONS file.
// Every anchor must match exactly one line, so a second run fails loudly instead of applying the blocks twice.
// The file's existing line ending (CRLF in a core.autocrlf=true checkout) is preserved for every line.
// The SECTIONS file is located next to this script, so a rename of the quick directory does not break it.

const fs = require('fs');
const path = require('path');

const ROADMAP = '.planning/ROADMAP.md';
const SECTIONS = path.join(__dirname, '260930-bvi-ROADMAP-SECTIONS.md');
const dryRun = process.argv.includes('--dry-run');

function fail(msg) {
  console.error('APPLY_FAILED ' + msg);
  process.exit(1);
}

if (!fs.existsSync(ROADMAP)) fail('run from the repository root (' + ROADMAP + ' not found)');
if (!fs.existsSync(SECTIONS)) fail('sections file not found: ' + SECTIONS);

const raw = fs.readFileSync(ROADMAP, 'utf8');
const eol = raw.includes('\r\n') ? '\r\n' : '\n';
const lines = raw.replace(/\r\n/g, '\n').split('\n');
const sec = fs.readFileSync(SECTIONS, 'utf8').replace(/\r\n/g, '\n').split('\n');

function block(id) {
  const open = sec.filter((l) => l === '<<<BLOCK ' + id).length;
  const close = sec.filter((l) => l === 'BLOCK ' + id + '>>>').length;
  if (open !== 1 || close !== 1) fail('BLOCK ' + id + ' delimiters found ' + open + '/' + close + ' times (expected 1/1)');
  const s = sec.indexOf('<<<BLOCK ' + id);
  const e = sec.indexOf('BLOCK ' + id + '>>>');
  if (e <= s + 1) fail('BLOCK ' + id + ' is empty or inverted');
  return sec.slice(s + 1, e);
}

function one(pred, what) {
  const hits = [];
  lines.forEach((l, i) => {
    if (pred(l)) hits.push(i);
  });
  if (hits.length !== 1) fail('anchor "' + what + '" matched ' + hits.length + ' lines (expected exactly 1; already applied?)');
  return hits[0];
}

const iPhases = one((l) => l === '## Phases', '## Phases');
const iList11 = one((l) => l.startsWith('- [ ] **Phase 11: Fix fee units in sizing'), 'old phase-list line 11');
const iList17 = one((l) => l.startsWith('- [ ] **Phase 17: Configurable quote asset'), 'old phase-list line 17');
const iDet11 = one((l) => l.startsWith('### Phase 11: Fix fee units in sizing'), 'old Phase 11 details heading');
const iProgress = one((l) => l === '## Progress', '## Progress');
const iExec = one((l) => l.startsWith('Phases execute in numeric order: 1 → 2 → '), 'execution-order sentence');
const iRow11 = one((l) => l.startsWith('| 11. Fix fee units'), 'old progress row 11');
const iRow17 = one((l) => l.startsWith('| 17. Configurable quote asset'), 'old progress row 17');

if (iList17 - iList11 !== 6) fail('old phase-list lines 11..17 are not 7 consecutive lines');
if (iRow17 - iRow11 !== 6) fail('old progress rows 11..17 are not 7 consecutive lines');
if (!(iPhases < iList11 && iList17 < iDet11 && iDet11 < iProgress && iProgress < iExec && iExec < iRow11)) {
  fail('anchors are not in the expected document order');
}
if (lines[iPhases - 1] !== '') fail('expected one blank line before "## Phases"');
if (lines[iPhases - 2] === '') fail('expected the Overview paragraph directly above the blank line before "## Phases"');

const b1 = block('1');
const b2 = block('2');
const b3 = block('3');
const b4a = block('4a');
const b4b = block('4b');
if (b4a.length !== 1) fail('BLOCK 4a must be exactly one line');
if (b4b.length !== 16) fail('BLOCK 4b must be exactly 16 progress rows');
if (b2.length !== 16) fail('BLOCK 2 must be exactly 16 phase-list lines');

// Splice bottom-up so earlier indices stay valid.
lines.splice(iRow11, 7, ...b4b); // BLOCK 4b: progress rows 11..17 -> 11..26
lines.splice(iExec, 1, ...b4a); // BLOCK 4a: execution-order sentence
lines.splice(iDet11, iProgress - iDet11, ...b3); // BLOCK 3: details from old Phase 11 up to (not incl.) ## Progress
lines.splice(iList11, 7, ...b2); // BLOCK 2: phase-list lines 11..17 -> 11..26
lines.splice(iPhases - 1, 0, '', ...b1); // BLOCK 1: blank line + paragraph, before the existing blank line + ## Phases

const out = lines.join(eol);
if (dryRun) {
  console.log('DRY_RUN_OK lines=' + lines.length + ' eol=' + (eol === '\r\n' ? 'CRLF' : 'LF') + ' (nothing written)');
} else {
  fs.writeFileSync(ROADMAP, out, 'utf8');
  console.log('APPLIED lines=' + lines.length + ' eol=' + (eol === '\r\n' ? 'CRLF' : 'LF'));
}
