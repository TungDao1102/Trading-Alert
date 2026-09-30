'use strict';
// Quick task 260930-d0b: apply INPUT Part A (docs/DECISIONS.md) and Part B (.planning/ROADMAP.md), then verify.
//
// Run from the repository root:
//   node .planning/quick/<this-dir>/260930-d0b-apply.cjs decisions [--dry-run]
//   node .planning/quick/<this-dir>/260930-d0b-apply.cjs roadmap   [--dry-run]
//   node .planning/quick/<this-dir>/260930-d0b-apply.cjs verify <decisions|roadmap|git|all>
//
// All inserted text is read verbatim from 260930-d0b-INPUT.md (next to this script): the Part A fence and the
// OLD/NEW fence pair of every section B1-B14. Nothing is re-typed here. Every OLD must occur exactly once and no
// NEW may exist yet, so a second run fails loudly (APPLY_FAILED) and writes nothing. The existing line ending
// (CRLF in this core.autocrlf=true checkout) is preserved. The verify modes are read-only.

const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const cp = require('child_process');

const INPUT = path.join(__dirname, '260930-d0b-INPUT.md');
const SCRIPT_REL = '.planning/quick/260930-d0b-record-single-vps-deployment-decision-d0/260930-d0b-apply.cjs';
const DECISIONS = 'docs/DECISIONS.md';
const ROADMAP = '.planning/ROADMAP.md';
const BASE = '6cc2f56caaef2671c5dfcb31f3cb6841b0acb832';
const PIN = {
  [DECISIONS]: '141a1cfc6695e4cf974258884d460fe863ed12c99a198954b37beec3be30036a',
  [ROADMAP]: 'dbc919fc0a3505b7bf8c6fbdedd8ad041c0339e9db3ef7bf34781205ec5da0eb',
};
const NUMSTAT = { [DECISIONS]: '1\t0', [ROADMAP]: '23\t12' };
const TRAILER = 'Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>';
const COMMITS = [
  ['docs(quick-260930-d0b): record D042 single-VPS deployment topology', [DECISIONS, SCRIPT_REL]],
  ['docs(quick-260930-d0b): pull VPS hardening and collector deployment into Phase 13', [ROADMAP]],
];
const PHASE13_DIR = '.planning/phases/13-research-data-foundation-fixes';
const PHASE13_NAME = 'Research Data Foundation Fixes + VPS Collector Deployment';
// roadmap.analyze depends_on per phase at BASE; this task must not change any of them.
const BASE_DEPENDS = {
  1: 'Nothing (first phase)', 2: 'Phase 1', 3: 'Phase 2', 4: 'Phase 3', 5: 'Phase 4', 6: 'Phase 5', 7: 'Phase 6',
  '07.1': 'Phase 6',
  8: 'Phase 7 (construction may run parallel to the paper soak; enablement gates on paper evidence)',
  9: 'Phase 8', 10: 'Phase 9', 11: 'Phase 10', 12: 'Phase 11', 13: 'Phase 11', 14: 'Phase 12, Phase 13',
  15: 'Phase 14', 16: 'Phase 12, Phase 15', 17: 'Phase 11', 18: 'Phase 17', 19: 'Phase 17, Phase 18',
  20: 'Phase 17, Phase 18', 21: 'Phase 18', 22: 'Phase 21', 23: 'Phase 12, Phase 21, Phase 22',
  24: 'Phase 16, Phase 19, Phase 20, Phase 21, Phase 22, Phase 23', 25: 'Phase 24', 26: 'Phase 25', 27: 'Phase 26',
};

const argv = process.argv.slice(2);
const dryRun = argv.includes('--dry-run');

function fail(msg) {
  console.error('APPLY_FAILED ' + msg);
  process.exit(1);
}

// ---------------------------------------------------------------- INPUT fences
if (!fs.existsSync(INPUT)) fail('INPUT file not found: ' + INPUT);
const inputLines = fs.readFileSync(INPUT, 'utf8').replace(/\r\n/g, '\n').split('\n');
const F = (() => {
  const out = {};
  let sec = null;
  let kind = null;
  let open = -1;
  inputLines.forEach((l, i) => {
    if (open < 0) {
      if (l.startsWith('## Part A')) { sec = 'A'; kind = 'ROW'; }
      const m = /^### (B\d+) /.exec(l);
      if (m) { sec = m[1]; kind = null; }
      if (l === 'OLD:') kind = 'OLD';
      if (l === 'NEW:') kind = 'NEW';
    }
    if (l !== '```') return;
    if (open < 0) { open = i; return; }
    if (!sec || !kind) fail('fence at INPUT line ' + (open + 1) + ' has no Part A / Bn OLD|NEW label');
    const key = sec + ':' + kind;
    if (key in out) fail('duplicate INPUT fence ' + key);
    out[key] = inputLines.slice(open + 1, i).join('\n');
    if (out[key] === '') fail('empty INPUT fence ' + key);
    open = -1;
    if (kind !== 'ROW') kind = null;
  });
  if (open >= 0) fail('unterminated fence in INPUT at line ' + (open + 1));
  const want = ['A:ROW'];
  for (let b = 1; b <= 14; b++) want.push('B' + b + ':OLD', 'B' + b + ':NEW');
  const got = Object.keys(out);
  if (got.length !== want.length || want.some((k) => !(k in out))) fail('INPUT fences [' + got.join(',') + '] != expected A:ROW + B1-B14 OLD/NEW');
  return out;
})();
const ROW = F['A:ROW'];
const PAIRS = [];
for (let b = 1; b <= 14; b++) PAIRS.push({ id: 'B' + b, old: F['B' + b + ':OLD'], neu: F['B' + b + ':NEW'] });

// ---------------------------------------------------------------- helpers
const count = (hay, needle) => hay.split(needle).length - 1;
const sha = (s) => crypto.createHash('sha256').update(s, 'utf8').digest('hex');
function load(file) {
  if (!fs.existsSync(file)) fail('run from the repository root (' + file + ' not found)');
  const raw = fs.readFileSync(file, 'utf8');
  return { raw, eol: raw.includes('\r\n') ? '\r\n' : '\n', text: raw.replace(/\r\n/g, '\n') };
}
function save(file, doc, text, label) {
  const lines = text.split('\n');
  const tag = 'lines=' + (lines.length - 1) + ' eol=' + (doc.eol === '\r\n' ? 'CRLF' : 'LF');
  if (dryRun) return console.log('DRY_RUN_OK ' + label + ' ' + tag + ' (nothing written)');
  fs.writeFileSync(file, lines.join(doc.eol), 'utf8');
  console.log('APPLIED ' + label + ' ' + tag);
}
function git(args) {
  return cp.execFileSync('git', args, { encoding: 'utf8', maxBuffer: 64 << 20 });
}

// ---------------------------------------------------------------- Part A: docs/DECISIONS.md
function applyDecisions() {
  if (ROW.includes('\n') || !ROW.startsWith('| D042 | ')) fail('Part A fence must be one line starting "| D042 | "');
  if (count(ROW, '|') !== 5) fail('Part A row has ' + count(ROW, '|') + ' "|" (expected 5: four cells, no pipe inside a cell)');
  const doc = load(DECISIONS);
  const L = doc.text.split('\n');
  if (L.some((l) => l.startsWith('| D042 |'))) fail('D042 already present (already applied?)');
  const hits = L.map((l, i) => (l.startsWith('| D041 | ') ? i : -1)).filter((i) => i >= 0);
  if (hits.length !== 1) fail('D041 row matched ' + hits.length + ' lines (expected 1)');
  if (L.slice(hits[0] + 1).some((l) => l !== '')) fail('D041 is not the last row of docs/DECISIONS.md');
  L.splice(hits[0] + 1, 0, ROW);
  save(DECISIONS, doc, L.join('\n'), 'decisions');
}

// ---------------------------------------------------------------- Part B: .planning/ROADMAP.md
function applyRoadmap() {
  const doc = load(ROADMAP);
  let t = doc.text;
  const edits = PAIRS.map((p) => {
    const n = count(t, p.old);
    if (n !== 1) fail(p.id + ' OLD matched ' + n + ' times (expected exactly 1; already applied?)');
    if (count(t, p.neu) !== 0) fail(p.id + ' NEW already present (already applied?)');
    const at = t.indexOf(p.old);
    if (at > 0 && t[at - 1] !== '\n') fail(p.id + ' OLD does not start at a line start');
    const endsLine = t[at + p.old.length] === '\n';
    // B12 OLD is, per INPUT, a prefix of a longer line (the rest of the line is kept); all others are whole lines.
    if (p.id === 'B12' ? endsLine : !endsLine) fail(p.id + ' OLD line-boundary shape unexpected');
    return { ...p, at };
  });
  edits.sort((a, b) => b.at - a.at);
  for (let k = 1; k < edits.length; k++) {
    if (edits[k].at + edits[k].old.length > edits[k - 1].at) fail('OLD texts ' + edits[k].id + ' and ' + edits[k - 1].id + ' overlap');
  }
  for (const e of edits) t = t.slice(0, e.at) + e.neu + t.slice(e.at + e.old.length);
  save(ROADMAP, doc, t, 'roadmap');
}

// ---------------------------------------------------------------- verify (read-only)
let failures = 0;
function gate(name, ok, detail) {
  if (ok) console.log('PASS ' + name);
  else { failures++; console.log('FAIL ' + name + (detail ? ': ' + detail : '')); }
}
function crlfKept(raw) {
  return count(raw, '\n') === count(raw, '\r\n');
}
function numstat(file) {
  return git(['diff', '--numstat', BASE, '--', file]).trim().split('\t').slice(0, 2).join('\t');
}

function verifyDecisions() {
  const doc = load(DECISIONS);
  gate('decisions: CRLF line endings kept', doc.eol === '\r\n' && crlfKept(doc.raw));
  gate('decisions: CR-stripped SHA-256 pinned', sha(doc.text) === PIN[DECISIONS], sha(doc.text));
  const ns = numstat(DECISIONS);
  gate('decisions: numstat vs BASE is 1 added / 0 deleted', ns === NUMSTAT[DECISIONS], ns);
  const base = git(['show', BASE + ':' + DECISIONS]).replace(/\r\n/g, '\n').split('\n');
  const i41 = base.findIndex((l) => l.startsWith('| D041 | '));
  const expected = base.slice();
  expected.splice(i41 + 1, 0, ROW);
  gate('decisions: file == BASE + INPUT Part A row directly after D041', i41 >= 0 && expected.join('\n') === doc.text);
  const rows = doc.text.split('\n').filter((l) => l.startsWith('| D042 |'));
  gate('decisions: exactly one D042 row, 4 cells, no pipe in a cell', rows.length === 1 && count(rows[0], '|') === 5);
  gate('decisions: D042 row is Accepted (2026-09-30, user)', rows.length === 1 && rows[0].includes('| Accepted (2026-09-30, user) |'));
}

function sectionBounds(lines, headingPrefix) {
  const h = lines.findIndex((l) => l.startsWith(headingPrefix));
  if (h < 0) return null;
  let end = h + 1;
  while (end < lines.length && !lines[end].startsWith('### ') && !lines[end].startsWith('## ')) end++;
  return [h + 1, end]; // 1-based inclusive start, 1-based inclusive end (= 0-based exclusive end)
}

function analyze() {
  const tools = path.join(os.homedir(), '.claude', 'gsd-core', 'bin', 'gsd-tools.cjs');
  let out = cp.execFileSync('node', [tools, 'query', 'roadmap.analyze', '--cwd', process.cwd()], { encoding: 'utf8', maxBuffer: 64 << 20 });
  if (out.startsWith('@file:')) out = fs.readFileSync(out.slice(6).trim(), 'utf8');
  return JSON.parse(out);
}

function verifyRoadmap() {
  const doc = load(ROADMAP);
  const t = doc.text;
  gate('roadmap: CRLF line endings kept', doc.eol === '\r\n' && crlfKept(doc.raw));
  gate('roadmap: CR-stripped SHA-256 pinned', sha(t) === PIN[ROADMAP], sha(t));
  const ns = numstat(ROADMAP);
  gate('roadmap: numstat vs BASE pinned', ns === NUMSTAT[ROADMAP], ns);
  for (const p of PAIRS) {
    gate(p.id + ': NEW present exactly once', count(t, p.neu) === 1, 'count=' + count(t, p.neu));
    const want = count(p.neu, p.old);
    gate(p.id + ': OLD gone (or only inside its own NEW)', count(t, p.old) === want, 'count=' + count(t, p.old) + ' want=' + want);
  }
  const baseText = git(['show', BASE + ':' + ROADMAP]).replace(/\r\n/g, '\n');
  const base = baseText.split('\n');
  const b12 = PAIRS[11];
  const b12Base = base.find((l) => l.startsWith(b12.old));
  const b12Line = b12Base && b12.neu + b12Base.slice(b12.old.length);
  gate('B12: rest of the CANARY line unchanged', !!b12Line && t.split('\n').filter((l) => l === b12Line).length === 1);
  // Hunk ownership: every git diff -U0 hunk touches only the Phase 13 list line, the Phase 13 / 24 / 26 sections or
  // the Phase 13 progress row (line numbers taken from the BASE file).
  const regions = {
    'list line 13': (() => { const i = base.findIndex((l) => l.startsWith('- [ ] **Phase 13: ')); return i < 0 ? null : [i + 1, i + 1]; })(),
    'Phase 13 section': sectionBounds(base, '### Phase 13: '),
    'Phase 24 section': sectionBounds(base, '### Phase 24: '),
    'Phase 26 section': sectionBounds(base, '### Phase 26: '),
    'progress row 13': (() => { const i = base.findIndex((l) => l.startsWith('| 13. ')); return i < 0 ? null : [i + 1, i + 1]; })(),
  };
  const touched = new Set();
  const stray = [];
  const hunks = git(['diff', '-U0', BASE, '--', ROADMAP]).split('\n').filter((l) => l.startsWith('@@ '));
  for (const h of hunks) {
    const m = /^@@ -(\d+)(?:,(\d+))? \+/.exec(h);
    const a = Number(m[1]);
    const n = m[2] === undefined ? 1 : Number(m[2]);
    const lo = a;
    const hi = n === 0 ? a : a + n - 1; // n=0: pure insertion after base line a
    const owner = Object.keys(regions).find((k) => regions[k] && lo >= regions[k][0] && hi <= regions[k][1]);
    if (owner) touched.add(owner);
    else stray.push(h);
  }
  gate('roadmap: every diff hunk is inside an allowed region', hunks.length > 0 && stray.length === 0, stray.join(' ; '));
  gate('roadmap: all five allowed regions were edited', touched.size === 5, [...touched].join(', '));
  let j = null;
  try { j = analyze(); } catch (e) { gate('analyze: roadmap.analyze runs', false, e.message.split('\n')[0]); return; }
  const phases = j.phases || [];
  gate('analyze: 28 phases', j.phase_count === 28 && phases.length === 28, 'phase_count=' + j.phase_count);
  const p13 = phases.find((p) => String(p.number) === '13');
  gate('analyze: Phase 13 name includes "VPS Collector Deployment"', !!p13 && p13.name === PHASE13_NAME, p13 && p13.name);
  const goal = PAIRS[2].neu.replace(/^\*\*Goal\*\*: /, '');
  gate('analyze: Phase 13 goal is the INPUT B3 goal', !!p13 && p13.goal === goal, p13 && p13.goal);
  const numbers = phases.map((p) => String(p.number)).sort().join(',');
  const baseNumbers = Object.keys(BASE_DEPENDS).map(String).sort().join(',');
  gate('analyze: phase numbers unchanged', numbers === baseNumbers, numbers);
  const changed = phases.filter((p) => BASE_DEPENDS[String(p.number)] !== p.depends_on).map((p) => p.number + '=' + p.depends_on);
  gate('analyze: depends_on of every phase unchanged', changed.length === 0, changed.join(' ; '));
  const dirs = fs.readdirSync('.planning/phases').filter((d) => /^13-/.test(d));
  gate('dirs: phase 13 directory unchanged (13-research-data-foundation-fixes only)', dirs.length === 1 && '.planning/phases/' + dirs[0] === PHASE13_DIR, dirs.join(','));
}

function verifyGit() {
  const dirty = git(['status', '--porcelain', '--', DECISIONS, ROADMAP, SCRIPT_REL]).trim();
  gate('git: DECISIONS, ROADMAP and the script have no uncommitted changes', dirty === '', dirty);
  for (const f of [DECISIONS, ROADMAP]) {
    let blob = '';
    try { blob = git(['show', 'HEAD:' + f]).replace(/\r\n/g, '\n'); } catch (e) { /* fall through */ }
    gate('git: committed ' + f + ' matches the pinned digest', sha(blob) === PIN[f]);
  }
  let tracked = null;
  try { tracked = git(['show', 'HEAD:' + SCRIPT_REL]).replace(/\r\n/g, '\n'); } catch (e) { /* not tracked */ }
  gate('git: this script is committed as run', tracked !== null && tracked === fs.readFileSync(__filename, 'utf8').replace(/\r\n/g, '\n'));
  const log = git(['log', '--format=%H%x09%s', BASE + '..HEAD']).trim().split('\n').filter(Boolean).map((l) => l.split('\t'));
  for (const [subject, allowed] of COMMITS) {
    const hits = log.filter(([, s]) => s === subject);
    gate('git: one commit "' + subject + '"', hits.length === 1, 'found ' + hits.length);
    if (hits.length !== 1) continue;
    const h = hits[0][0];
    const files = git(['diff-tree', '--no-commit-id', '--name-only', '-r', h]).trim().split('\n').filter(Boolean).sort();
    gate('git: ' + h.slice(0, 7) + ' touches exactly ' + allowed.join(' + '), files.join(',') === allowed.slice().sort().join(','), files.join(','));
    const body = git(['log', '-1', '--format=%B', h]).trim().split('\n');
    gate('git: ' + h.slice(0, 7) + ' ends with the Co-Authored-By trailer', body[body.length - 1] === TRAILER);
  }
}

function verify(mode) {
  const modes = { decisions: [verifyDecisions], roadmap: [verifyRoadmap], git: [verifyGit], all: [verifyDecisions, verifyRoadmap, verifyGit] };
  if (!modes[mode]) {
    console.error('usage: verify <decisions|roadmap|git|all>');
    process.exit(2);
  }
  for (const fn of modes[mode]) fn();
  if (failures) {
    console.log('GATES_FAILED ' + failures + ' (' + mode + ')');
    process.exit(1);
  }
  console.log('ALL_PASS ' + mode);
}

const mode = argv[0];
if (mode === 'decisions') applyDecisions();
else if (mode === 'roadmap') applyRoadmap();
else if (mode === 'verify') verify(argv[1]);
else {
  console.error('usage: node 260930-d0b-apply.cjs <decisions|roadmap> [--dry-run] | verify <decisions|roadmap|git|all>');
  process.exit(2);
}
