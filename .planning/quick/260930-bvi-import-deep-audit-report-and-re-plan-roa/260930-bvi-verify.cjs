'use strict';
// Quick task 260930-bvi verification gates (deep-audit import + ROADMAP re-plan of phases 11-26).
//
// Run from the repository root:
//   node .planning/quick/<this-dir>/260930-bvi-verify.cjs <audit|roadmap|dirs|git|all>
//
// Read-only: never writes to the repository. Prints one PASS/FAIL line per gate and ends with
// "ALL_PASS <mode>" (exit 0) only when every gate passed; otherwise "FAILED n gate(s)" (exit 1).
// The SECTIONS file is located next to this script, so a rename of the quick directory does not break it.

const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');
const cp = require('child_process');

const SECTIONS = path.join(__dirname, '260930-bvi-ROADMAP-SECTIONS.md');
const SRC = 'C:/Users/admin/Music/project-audit/2026-09-29_63ca176';
const DEST = '.planning/audits/2026-09-29-deep-audit';
const TOP_FILES = [
  'BAO_CAO_TONG_HOP.md',
  'DEEP_AUDIT_REPORT.md',
  'findings.json',
  'INVARIANTS.md',
  'FILE_COVERAGE.md',
  'MANIFEST.md',
  'AUDIT_CHARTER.md',
  'LANE_BRIEF.md',
  'LANES.md',
  'VERIFIER_BRIEF.md',
  'TODO.md',
  'OUTPUT_HASHES.txt',
];
const TOP_DIRS = ['lanes', 'verification', 'tool-output'];
const NOT_IMPORTED = ['snapshot', 'tmp', 'baseline'];
const AUDIT_FILE_COUNT = 51; // 12 top-level + 24 lanes/ + 10 verification/ + 5 tool-output/ (counted 2026-09-30)
const README_MAX_LINES = 60;
const ROADMAP = '.planning/ROADMAP.md';
const ROADMAP_BASE = '63ca176'; // last commit that touched ROADMAP.md before this task (== HEAD 929f88e content)
const TASK_BASE = '929f88e'; // HEAD when this task was planned
const TASK_ID = '260930-bvi';
// SHA-256 of .planning/ROADMAP.md after the re-plan, all CR bytes removed (computed at planning time by a dry run).
const ROADMAP_SHA256_LF = '1af9525ed5a72dc0bbe8fa92fcaa21cba40398354bb6c2be0a682b3345d85373';
const EXPECTED_PHASE_HEADINGS = 27; // 1-10, 07.1, 11-26
const TRAILER = 'Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>';
const GSD_TOOLS = path.join(os.homedir(), '.claude', 'gsd-core', 'bin', 'gsd-tools.cjs');
const FORBIDDEN_IN_COMMITS = [
  /^\.planning\/state\.json$/,
  /^\.gsd\//,
  /^docs\//,
  /^src\//,
  /^tests\//,
  /^params\//,
  /^\.planning\/REQUIREMENTS\.md$/,
];
const SECRET_PATTERNS = [
  /\b\d{8,10}:[A-Za-z0-9_-]{35}\b/, // Telegram bot token shape
  /-----BEGIN [A-Z ]*PRIVATE KEY-----/,
  /(API_SECRET|SECRET_KEY|BOT_TOKEN|API_KEY)[A-Z_]*\s*[=:]\s*["']?[A-Za-z0-9]{20,}/,
];

const failures = [];
function check(ok, label, detail) {
  if (ok) {
    console.log('PASS ' + label);
  } else {
    failures.push(label);
    console.log('FAIL ' + label + (detail ? ' :: ' + detail : ''));
  }
}
const stripCR = (buf) => Buffer.from(buf.filter((b) => b !== 13));
const sha256 = (s) => crypto.createHash('sha256').update(s, 'utf8').digest('hex');
function walk(root, rel) {
  const out = [];
  const here = rel ? path.join(root, rel) : root;
  for (const e of fs.readdirSync(here, { withFileTypes: true })) {
    const r = rel ? rel + '/' + e.name : e.name;
    if (e.isDirectory()) out.push(...walk(root, r));
    else if (e.isFile()) out.push(r);
  }
  return out;
}
function git(args) {
  return cp.execFileSync('git', args, { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
}
function gsd(args) {
  let out = cp
    .execFileSync(process.execPath, [GSD_TOOLS, 'query', ...args], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })
    .trim();
  if (out.startsWith('@file:')) out = fs.readFileSync(out.slice('@file:'.length), 'utf8');
  return JSON.parse(out);
}
function sectionLines() {
  return fs.readFileSync(SECTIONS, 'utf8').replace(/\r\n/g, '\n').split('\n');
}
function block(id) {
  const sl = sectionLines();
  const s = sl.indexOf('<<<BLOCK ' + id);
  const e = sl.indexOf('BLOCK ' + id + '>>>');
  if (s < 0 || e <= s) throw new Error('BLOCK ' + id + ' delimiters not found in ' + SECTIONS);
  return sl.slice(s + 1, e);
}
function phaseNamesFromBlock2() {
  const names = {};
  for (const l of block('2')) {
    const m = /^- \[ \] \*\*Phase (\d+): (.+?)\*\* - /.exec(l);
    if (m) names[Number(m[1])] = m[2];
  }
  return names;
}
function dirMapping() {
  const sl = sectionLines();
  const start = sl.indexOf('## Phase directory mapping');
  if (start < 0) throw new Error('"## Phase directory mapping" not found in ' + SECTIONS);
  const byNumber = {};
  const old = [];
  for (const l of sl.slice(start)) {
    if (!/^\| .+ \| .+ \|$/.test(l)) continue;
    const [a, b] = l.split('|').slice(1, -1).map((c) => c.trim());
    if (/^\d\d-/.test(a)) old.push(a);
    const m = /^(\d\d)-/.exec(b);
    if (m) byNumber[Number(m[1])] = b;
  }
  return { byNumber, old };
}

// ---------------------------------------------------------------- audit (Task 1)
function audit() {
  const srcOk = fs.existsSync(SRC);
  check(srcOk, 'audit: source directory exists at ' + SRC);
  if (!srcOk) return;
  const expected = [...TOP_FILES];
  for (const d of TOP_DIRS) expected.push(...walk(SRC, d));
  check(expected.length === AUDIT_FILE_COUNT, 'audit: source list has ' + AUDIT_FILE_COUNT + ' files', 'found ' + expected.length);

  const bad = [];
  for (const rel of expected) {
    const d = path.join(DEST, rel);
    if (!fs.existsSync(d)) {
      bad.push('missing ' + rel);
      continue;
    }
    if (!stripCR(fs.readFileSync(path.join(SRC, rel))).equals(stripCR(fs.readFileSync(d)))) bad.push('differs ' + rel);
  }
  check(bad.length === 0, 'audit: every source file is copied with identical content (CR-insensitive)', bad.slice(0, 10).join('; '));

  const present = fs.existsSync(DEST) ? walk(DEST, '') : [];
  const allowed = new Set([...expected, 'README.md']);
  const extras = present.filter((r) => !allowed.has(r));
  check(extras.length === 0, 'audit: destination holds only the ' + AUDIT_FILE_COUNT + ' audit files plus README.md', extras.slice(0, 10).join('; '));
  for (const x of NOT_IMPORTED) check(!fs.existsSync(path.join(DEST, x)), 'audit: ' + x + '/ was not imported');

  const leaks = [];
  for (const rel of present) {
    const text = fs.readFileSync(path.join(DEST, rel), 'utf8');
    for (const re of SECRET_PATTERNS) if (re.test(text)) leaks.push(rel + ' ~ ' + re.source.slice(0, 30));
  }
  check(leaks.length === 0, 'audit: no secret-shaped strings in imported files', leaks.slice(0, 5).join('; '));

  const rp = path.join(DEST, 'README.md');
  const hasReadme = fs.existsSync(rp);
  check(hasReadme, 'readme: ' + rp + ' exists');
  if (!hasReadme) return;
  const t = fs.readFileSync(rp, 'utf8');
  const required = [
    ['snapshot id 63ca176', /63ca176/],
    ['audit date 2026-09-29', /2026-09-29/],
    ['read-only', /read-only/i],
    ['section 19 remediation', /§19/],
    ['section 20 decisions', /§20/],
    ['decision D031', /D031/],
    ['decision D039', /D039/],
    ['docs/DECISIONS.md', /docs\/DECISIONS\.md/],
    ['phases 11-26', /11\s*(–|-|to)\s*26/],
    ['re-plan date 2026-09-30', /2026-09-30/],
    ['ROADMAP.md', /ROADMAP\.md/],
    ['OUTPUT_HASHES.txt', /OUTPUT_HASHES\.txt/],
    ['line-ending normalization note', /line[- ]ending/i],
    ['snapshot/ not imported', /snapshot\//],
    ['tmp/ not imported', /tmp\//],
    ['original out-of-repo path', /project-audit[\\/]2026-09-29_63ca176/],
  ];
  for (const [label, re] of required) check(re.test(t), 'readme: mentions ' + label);
  const a = t.indexOf('BAO_CAO_TONG_HOP.md');
  const b = t.indexOf('DEEP_AUDIT_REPORT.md');
  const c = t.indexOf('findings.json');
  check(a >= 0 && b > a && c > b, 'readme: first mentions follow the reading order BAO_CAO_TONG_HOP.md -> DEEP_AUDIT_REPORT.md -> findings.json');
  const n = t.replace(/\r/g, '').trimEnd().split('\n').length;
  check(n <= README_MAX_LINES, 'readme: short (<= ' + README_MAX_LINES + ' lines)', 'lines ' + n);
}

// ---------------------------------------------------------------- roadmap (Task 2)
function roadmap() {
  const cur = fs.readFileSync(ROADMAP, 'utf8').replace(/\r/g, '');
  const digest = sha256(cur);
  check(digest === ROADMAP_SHA256_LF, 'roadmap: CR-stripped SHA-256 equals the pinned post-re-plan digest', 'got ' + digest);

  const bl = git(['show', ROADMAP_BASE + ':' + ROADMAP]).replace(/\r/g, '').split('\n');
  const cl = cur.split('\n');
  const idx = (pred, what) => {
    const hits = [];
    bl.forEach((l, i) => {
      if (pred(l)) hits.push(i);
    });
    if (hits.length !== 1) throw new Error('base anchor "' + what + '" matched ' + hits.length);
    return hits[0];
  };
  const iPhases = idx((l) => l === '## Phases', '## Phases');
  const iList11 = idx((l) => l.startsWith('- [ ] **Phase 11: Fix fee units'), 'list 11');
  const iList17 = idx((l) => l.startsWith('- [ ] **Phase 17: Configurable quote asset'), 'list 17');
  const iDet11 = idx((l) => l.startsWith('### Phase 11: Fix fee units'), 'details 11');
  const iProgress = idx((l) => l === '## Progress', '## Progress');
  const iExec = idx((l) => l.startsWith('Phases execute in numeric order:'), 'execution order');
  const iRow11 = idx((l) => l.startsWith('| 11. Fix fee units'), 'row 11');
  const iRow17 = idx((l) => l.startsWith('| 17. Configurable quote asset'), 'row 17');
  const segments = [
    ['preserved: title + Overview paragraph', bl.slice(0, iPhases - 1)],
    ['BLOCK 1 (with its leading blank line)', ['', ...block('1')]],
    ['preserved: "## Phases" through the Phase 10 list line', bl.slice(iPhases - 1, iList11)],
    ['BLOCK 2', block('2')],
    ['preserved: "## Phase Details" for phases 1-10 and 07.1', bl.slice(iList17 + 1, iDet11)],
    ['BLOCK 3', block('3')],
    ['preserved: "## Progress" heading lines', bl.slice(iProgress, iExec)],
    ['BLOCK 4a', block('4a')],
    ['preserved: progress table header + rows 1-10 and 07.1', bl.slice(iExec + 1, iRow11)],
    ['BLOCK 4b', block('4b')],
    ['preserved: end of file', bl.slice(iRow17 + 1)],
  ];
  let off = 0;
  for (const [label, seg] of segments) {
    let bad = -1;
    for (let k = 0; k < seg.length; k++) {
      if (cl[off + k] !== seg[k]) {
        bad = k;
        break;
      }
    }
    const where = bad < 0 ? '' : 'line ' + (off + bad + 1) + ' expected ' + JSON.stringify(String(seg[bad]).slice(0, 80)) + ' got ' + JSON.stringify(String(cl[off + bad]).slice(0, 80));
    check(bad < 0, 'roadmap: ' + label + ' is verbatim (vs ' + ROADMAP_BASE + ' / SECTIONS file)', where);
    off += seg.length;
  }
  check(off === cl.length, 'roadmap: no extra lines after the last segment', 'expected ' + off + ' lines, file has ' + cl.length);

  const stale = cl.filter((l) => /Fix fee units in sizing|Promoted from|promoted from backlog 999/.test(l));
  check(stale.length === 0, 'roadmap: old backlog-promoted phase 11-17 text is gone', stale.slice(0, 3).join(' | '));
  const headings = cl.filter((l) => l.startsWith('### Phase ')).length;
  check(headings === EXPECTED_PHASE_HEADINGS, 'roadmap: ' + EXPECTED_PHASE_HEADINGS + ' "### Phase" headings', 'found ' + headings);

  const an = gsd(['roadmap.analyze']);
  const byNum = {};
  for (const p of an.phases || []) byNum[String(p.number)] = p;
  const names = phaseNamesFromBlock2();
  for (let n = 11; n <= 26; n++) {
    const p = byNum[String(n)];
    const ok = !!p && p.name === names[n] && typeof p.goal === 'string' && p.goal.trim().length > 0 && !!p.depends_on;
    check(ok, 'analyze: phase ' + n + ' "' + names[n] + '" has a goal and depends_on', p ? JSON.stringify({ name: p.name, goal: String(p.goal).slice(0, 40), depends_on: p.depends_on }) : 'missing');
  }
  const kept = ['1', '2', '3', '4', '5', '6', '7', '07.1', '8', '9', '10'];
  const lost = kept.filter((k) => !byNum[k] || !byNum[k].goal);
  check(lost.length === 0, 'analyze: phases 1-10 and 07.1 still present with goals', lost.join(','));
  check((an.phases || []).length === EXPECTED_PHASE_HEADINGS, 'analyze: reports ' + EXPECTED_PHASE_HEADINGS + ' phases', 'got ' + (an.phases || []).length);
}

// ---------------------------------------------------------------- dirs (Task 3)
function dirs() {
  const { byNumber, old } = dirMapping();
  check(Object.keys(byNumber).length === 16, 'dirs: SECTIONS mapping names 16 target directories', 'got ' + Object.keys(byNumber).length);
  check(old.length === 7, 'dirs: SECTIONS mapping names 7 old directories', 'got ' + old.length);
  const entries = fs
    .readdirSync('.planning/phases', { withFileTypes: true })
    .filter((e) => e.isDirectory())
    .map((e) => e.name);
  for (let n = 11; n <= 26; n++) {
    const d = byNumber[n];
    const keep = path.join('.planning/phases', String(d), '.gitkeep');
    check(!!d && fs.existsSync(keep) && fs.statSync(keep).size === 0, 'dirs: phase ' + n + ' directory ' + d + ' exists with an empty .gitkeep');
    const same = entries.filter((e) => {
      const m = /^(\d+)-/.exec(e);
      return m && Number(m[1]) === n;
    });
    check(same.length === 1 && same[0] === d, 'dirs: exactly one directory carries number ' + n, same.join(', '));
    const r = gsd(['find-phase', String(n)]);
    const got = String(r.directory || '').replace(/\\/g, '/');
    check(r.found === true && got === '.planning/phases/' + d, 'dirs: find-phase ' + n + ' resolves to ' + d, JSON.stringify({ found: r.found, directory: got }));
  }
  for (const o of old) check(!fs.existsSync(path.join('.planning/phases', o)), 'dirs: old directory ' + o + ' is gone');
}

// ---------------------------------------------------------------- git (after the task commits)
function gitChecks() {
  const tracked = git(['ls-files', '--', DEST])
    .split('\n')
    .filter(Boolean)
    .map((p) => p.slice(DEST.length + 1));
  check(tracked.length === AUDIT_FILE_COUNT + 1, 'git: ' + (AUDIT_FILE_COUNT + 1) + ' files tracked under ' + DEST, 'tracked ' + tracked.length);
  const onDisk = fs.existsSync(DEST) ? walk(DEST, '') : [];
  const untracked = onDisk.filter((r) => !tracked.includes(r));
  check(untracked.length === 0, 'git: every file under the audit directory is tracked', untracked.slice(0, 5).join('; '));

  const dirty = git(['status', '--porcelain', '--', DEST, ROADMAP, '.planning/phases']).trim();
  check(dirty === '', 'git: audit dir, ROADMAP.md and .planning/phases have no uncommitted changes', dirty.split('\n').slice(0, 5).join('; '));
  const headDigest = sha256(git(['show', 'HEAD:' + ROADMAP]).replace(/\r/g, ''));
  check(headDigest === ROADMAP_SHA256_LF, 'git: committed ROADMAP.md matches the pinned digest', 'got ' + headDigest);

  const { byNumber, old } = dirMapping();
  for (let n = 11; n <= 26; n++) {
    const f = '.planning/phases/' + byNumber[n] + '/.gitkeep';
    check(git(['ls-files', '--', f]).trim() === f, 'git: ' + f + ' is tracked');
  }
  for (const o of old) check(git(['ls-files', '--', '.planning/phases/' + o]).trim() === '', 'git: nothing tracked under old directory ' + o);

  const hashes = git(['log', TASK_BASE + '..HEAD', '--grep=' + TASK_ID, '--format=%H']).split('\n').filter(Boolean);
  check(hashes.length >= 3, 'git: at least 3 commits mention ' + TASK_ID + ' since ' + TASK_BASE, 'found ' + hashes.length);
  const touched = git(['log', TASK_BASE + '..HEAD', '--grep=' + TASK_ID, '--name-only', '--format=']).split('\n').filter(Boolean);
  const forbidden = [...new Set(touched.filter((f) => FORBIDDEN_IN_COMMITS.some((re) => re.test(f))))];
  check(forbidden.length === 0, 'git: no ' + TASK_ID + ' commit touches .planning/state.json, .gsd/, docs/, src/, tests/, params/ or REQUIREMENTS.md', forbidden.join('; '));
  const noTrailer = hashes.filter((h) => !git(['log', '-1', '--format=%B', h]).trimEnd().endsWith(TRAILER));
  check(noTrailer.length === 0, 'git: every ' + TASK_ID + ' commit message ends with the Co-Authored-By trailer', noTrailer.join(', '));
}

// ---------------------------------------------------------------- main
const modes = { audit, roadmap, dirs, git: gitChecks };
const mode = process.argv[2] || 'all';
if (!fs.existsSync(ROADMAP)) {
  console.log('FAIL run this script from the repository root (' + ROADMAP + ' not found)');
  process.exit(2);
}
const run = mode === 'all' ? Object.keys(modes) : [mode];
for (const m of run) {
  if (!modes[m]) {
    console.log('usage: node 260930-bvi-verify.cjs <audit|roadmap|dirs|git|all>');
    process.exit(2);
  }
  try {
    modes[m]();
  } catch (e) {
    check(false, m + ': gate crashed', e && e.message);
  }
}
if (failures.length) {
  console.log('FAILED ' + failures.length + ' gate(s) in mode ' + mode);
  process.exit(1);
}
console.log('ALL_PASS ' + mode);
