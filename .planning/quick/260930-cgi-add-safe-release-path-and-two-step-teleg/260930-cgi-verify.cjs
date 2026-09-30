'use strict';
// Quick task 260930-cgi verification gates (D040/D041 in DECISIONS.md, ROADMAP Phase 25 insert + 25→26→27 renumber).
//
// Run from the repository root:
//   node .planning/quick/<this-dir>/260930-cgi-verify.cjs <decisions|roadmap|dirs|git|all>
//
// Read-only: never writes to the repository. Prints one PASS/FAIL line per gate and ends with
// "ALL_PASS <mode>" (exit 0) only when every gate passed; otherwise "FAILED n gate(s)" (exit 1).
// INPUT.md is located next to this script, so a rename of the quick directory does not break it.

const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');
const cp = require('child_process');

const INPUT = path.join(__dirname, '260930-cgi-INPUT.md');
const TASK_ID = '260930-cgi';
const BASE = '6a0d4aa'; // HEAD when this task was planned; ROADMAP.md and DECISIONS.md are unchanged since then
const DECISIONS = 'docs/DECISIONS.md';
const ROADMAP = '.planning/ROADMAP.md';
// CR-stripped SHA-256 digests of the expected results (computed at planning time in a throwaway-worktree rehearsal).
const DECISIONS_SHA256_LF = '01e6868107de34f177141b858304d10dff5b7edcf187572f47c5ed0c062094b4';
const ROADMAP_SHA256_LF = '93b187ae4b1b1023ecaf8f913e906da067b803c4d1cd68f0326f5186d64688e7';
const EXPECTED_PHASES = 28; // 1-10, 07.1, 11-27
const NEW_DIRS = {
  25: '25-demo-integration-test-campaign',
  26: '26-go-live-readiness-gate',
  27: '27-configurable-quote-asset',
};
const OLD_DIRS = ['25-go-live-readiness-gate', '26-configurable-quote-asset'];
const COMMIT_SUBJECTS = [
  'docs(quick-260930-cgi): record D040 safe release path and D041 two-step Telegram confirm',
  'docs(quick-260930-cgi): insert Phase 25 demo campaign and renumber phases 26-27 in ROADMAP',
  'docs(quick-260930-cgi): map phase directories 25-27 to the renumbered roadmap',
];
const ALLOWED_IN_COMMITS = [
  /^docs\/DECISIONS\.md$/,
  /^\.planning\/ROADMAP\.md$/,
  /^\.planning\/phases\/(25|26|27)-[a-z0-9-]+\/\.gitkeep$/,
  /^\.planning\/quick\/260930-cgi-[^/]+\/260930-cgi-(apply|verify)\.cjs$/,
];
const TRAILER = 'Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>';
const GSD_TOOLS = path.join(os.homedir(), '.claude', 'gsd-core', 'bin', 'gsd-tools.cjs');

const failures = [];
function check(ok, label, detail) {
  if (ok) {
    console.log('PASS ' + label);
  } else {
    failures.push(label);
    console.log('FAIL ' + label + (detail ? ' :: ' + detail : ''));
  }
}
const lf = (s) => s.replace(/\r/g, '');
const sha256 = (s) => crypto.createHash('sha256').update(s, 'utf8').digest('hex');
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
function fences() {
  const out = {};
  let section = null;
  let open = -1;
  const lines = lf(fs.readFileSync(INPUT, 'utf8')).split('\n');
  lines.forEach((l, i) => {
    if (open < 0) {
      if (l.startsWith('## Part A')) section = 'A';
      const m = /^### (B\d)\./.exec(l);
      if (m) section = m[1];
    }
    if (l === '```') {
      if (open < 0) open = i;
      else {
        out[section] = lines.slice(open + 1, i);
        open = -1;
      }
    }
  });
  return out;
}
function containsRun(hay, run) {
  outer: for (let i = 0; i + run.length <= hay.length; i++) {
    for (let k = 0; k < run.length; k++) if (hay[i + k] !== run[k]) continue outer;
    return true;
  }
  return false;
}

// ---------------------------------------------------------------- decisions (Task 1)
function decisions() {
  const F = fences();
  const cur = lf(fs.readFileSync(DECISIONS, 'utf8'));
  const base = lf(git(['show', BASE + ':' + DECISIONS]));
  const digest = sha256(cur);
  check(digest === DECISIONS_SHA256_LF, 'decisions: CR-stripped SHA-256 equals the pinned digest', 'got ' + digest);
  const ns = git(['diff', '--numstat', BASE, '--', DECISIONS]).trim();
  check(ns === '2\t0\t' + DECISIONS, 'decisions: exactly 2 added and 0 deleted lines versus ' + BASE, JSON.stringify(ns));
  const bl = base.split('\n');
  const i39 = bl.findIndex((l) => l.startsWith('| D039 | '));
  const expected = [...bl.slice(0, i39 + 1), ...F.A, ...bl.slice(i39 + 1)].join('\n');
  check(cur === expected, 'decisions: file = ' + BASE + ' content with the INPUT Part A rows inserted directly after D039 (verbatim)');
  const rows = cur.split('\n').filter((l) => /^\| D04[01] \| /.test(l));
  check(rows.length === 2 && rows[0].startsWith('| D040 | ') && rows[1].startsWith('| D041 | '), 'decisions: one D040 row then one D041 row', rows.map((r) => r.slice(0, 8)).join(','));
  check(rows.every((r) => (r.match(/\|/g) || []).length === 5), 'decisions: each new row is 4 cells with no "|" inside a cell');
  check(rows.every((r) => r.includes('| Accepted (2026-09-30, user) |')), 'decisions: both rows carry status "Accepted (2026-09-30, user)"');
}

// ---------------------------------------------------------------- roadmap (Task 2)
function phaseKey(s) {
  return /^\d+$/.test(s) ? String(Number(s)) : s;
}
function isProtected(p) {
  if (p === '07.1') return true;
  if (!/^\d+$/.test(p)) return false;
  const n = Number(p);
  return (n >= 1 && n <= 15) || (n >= 17 && n <= 22);
}
function owners(lines) {
  // owner[i] = phase key that line i (0-based) belongs to, or null for non-phase text.
  const own = new Array(lines.length).fill(null);
  let cur = null;
  lines.forEach((l, i) => {
    const h = /^### Phase (\d+(?:\.\d+)?): /.exec(l);
    if (h) cur = h[1] === '07.1' ? '07.1' : phaseKey(h[1]);
    else if (l.startsWith('### ') || l.startsWith('## ')) cur = null;
    let o = cur;
    const li = /^- \[[ x]\] \*\*Phase (\d+(?:\.\d+)?): /.exec(l);
    if (li) o = li[1] === '07.1' ? '07.1' : phaseKey(li[1]);
    const row = /^\| (\d+(?:\.\d+)?)\. /.exec(l);
    if (row) o = row[1] === '7.1' || row[1] === '07.1' ? '07.1' : phaseKey(row[1]);
    own[i] = o;
  });
  return own;
}
function roadmap() {
  const F = fences();
  const cur = lf(fs.readFileSync(ROADMAP, 'utf8'));
  const cl = cur.split('\n');
  const digest = sha256(cur);
  check(digest === ROADMAP_SHA256_LF, 'roadmap: CR-stripped SHA-256 equals the pinned digest', 'got ' + digest);

  // No changed line belongs to Phases 1-15, 17-22 or 07.1 (git diff -U0 hunks mapped onto the base file).
  const bl = lf(git(['show', BASE + ':' + ROADMAP])).split('\n');
  const own = owners(bl);
  const diff = git(['diff', '--no-color', '--no-ext-diff', '-U0', BASE, '--', ROADMAP]);
  const bad = [];
  let hunks = 0;
  for (const m of diff.matchAll(/^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@/gm)) {
    hunks++;
    const start = Number(m[1]);
    const count = m[2] === undefined ? 1 : Number(m[2]);
    const touched = count === 0 ? [start - 1, start] : Array.from({ length: count }, (_, k) => start - 1 + k);
    for (const i of touched) {
      if (i < 0 || i >= bl.length) continue;
      const o = own[i];
      if (o !== null && isProtected(o)) bad.push('base line ' + (i + 1) + ' (phase ' + o + ')');
    }
  }
  check(hunks > 0, 'roadmap: git diff vs ' + BASE + ' has hunks to inspect', 'no diff');
  check(bad.length === 0, 'roadmap: no diff hunk touches a line of Phases 1-15, 17-22 or 07.1', bad.slice(0, 5).join('; '));

  // New text is present verbatim.
  for (const k of ['B2', 'B3', 'B4', 'B6', 'B7']) check(containsRun(cl, F[k]), 'roadmap: INPUT fence ' + k + ' appears verbatim as consecutive lines');
  const want = [
    '- old 17 → 27',
    '- Live enablement (26) requires 11–25 complete, and follows the D040 release path SHADOW → DEMO → CANARY → LIVE.',
    '### Phase 16: Paper Runtime Composition + SHADOW Approval Mode',
    '### Phase 23: Telegram Approval Hardening + Two-Step Confirm + Money Amounts',
    '**Audit refs**: F-201, F-125, F-607, F-961, F-023, D040, D041',
    '**Audit refs**: F-508, F-707, F-405, F-509, F-127, F-015, F-016, D041',
    '   - Telegram bot runner (APPROVE → CONFIRM → `execute_approved_plan`, D041);',
    '   - signal → approve → confirm → entry → SL/TP;',
    '| 16. Paper Runtime Composition + SHADOW Approval Mode | 0/TBD | Not started | - |',
    '| 23. Telegram Approval Hardening + Two-Step Confirm + Money Amounts | 0/TBD | Not started | - |',
  ];
  for (const w of want) check(cl.filter((l) => l === w).length === 1, 'roadmap: exactly one line "' + w.slice(0, 70) + '"');
  check(cl.some((l) => l.includes('Phases 11–27 below replace the earlier backlog-promoted phases 11–17')), 'roadmap: overview sentence says Phases 11–27');
  const exec = cl.filter((l) => l.startsWith('Phases execute in numeric order: '));
  check(exec.length === 1 && exec[0].includes('→ 27.') && exec[0].includes('No real-money order before Phase 26 is complete (D040: SHADOW → DEMO → CANARY → LIVE).') && !exec[0].includes('→ 26.') && !exec[0].includes('No live order before Phase 25'), 'roadmap: execution-order line says → 27 and "No real-money order before Phase 26 ..."');

  // Old text is gone.
  const stale = [
    '- old 17 → 26',
    'Live enablement (25)',
    '### Phase 25: Go-Live Readiness Gate',
    '### Phase 26: Configurable Quote Asset',
    '- [ ] **Phase 25: Go-Live Readiness Gate**',
    '- [ ] **Phase 26: Configurable Quote Asset',
    '| 25. Go-Live Readiness Gate |',
    '| 26. Configurable Quote Asset',
    'Telegram bot runner (APPROVE → `execute_approved_plan`);',
  ];
  for (const s of stale) check(!cl.some((l) => l.includes(s)), 'roadmap: stale text gone: "' + s.slice(0, 60) + '"');

  const c40 = cl.filter((l) => l.includes('D040')).length;
  const c41 = cl.filter((l) => l.includes('D041')).length;
  check(c41 >= 4, 'roadmap: lines containing D041 >= 4', 'got ' + c41);
  check(c40 >= 5, 'roadmap: lines containing D040 >= 5', 'got ' + c40);
  const headings = cl.filter((l) => l.startsWith('### Phase ')).length;
  check(headings === EXPECTED_PHASES, 'roadmap: ' + EXPECTED_PHASES + ' "### Phase" headings', 'found ' + headings);

  // gsd-tools view of the result.
  const an = gsd(['roadmap.analyze']);
  const ph = an.phases || [];
  check(ph.length === EXPECTED_PHASES, 'analyze: reports ' + EXPECTED_PHASES + ' phases', 'got ' + ph.length);
  const byNum = {};
  for (const p of ph) byNum[String(p.number)] = p;
  const goalOf = (heading) => {
    const i = F.B6.indexOf(heading);
    const g = F.B6.slice(i).find((l) => l.startsWith('**Goal**: '));
    return g ? g.slice('**Goal**: '.length) : null;
  };
  const expect = {
    25: ['Binance Demo Integration Test Campaign', 'Phase 24'],
    26: ['Go-Live Readiness Gate', 'Phase 25'],
    27: ['Configurable Quote Asset (USDC readiness)', 'Phase 26'],
  };
  for (const n of Object.keys(expect)) {
    const [name, dep] = expect[n];
    const p = byNum[n];
    const goal = goalOf('### Phase ' + n + ': ' + name);
    const ok = !!p && p.name === name && p.goal === goal && p.depends_on === dep;
    check(ok, 'analyze: phase ' + n + ' is "' + name + '" with the INPUT goal and depends_on ' + dep, p ? JSON.stringify({ name: p.name, goal: String(p.goal).slice(0, 50), depends_on: p.depends_on }) : 'missing');
  }
  check(!!byNum['16'] && byNum['16'].name === 'Paper Runtime Composition + SHADOW Approval Mode', 'analyze: phase 16 renamed', byNum['16'] && byNum['16'].name);
  check(!!byNum['23'] && byNum['23'].name === 'Telegram Approval Hardening + Two-Step Confirm + Money Amounts', 'analyze: phase 23 renamed', byNum['23'] && byNum['23'].name);
  const kept = ['1', '2', '3', '4', '5', '6', '7', '07.1', '8', '9', '10', '11', '12', '13', '14', '15', '16', '17', '18', '19', '20', '21', '22', '23', '24'];
  const lost = kept.filter((k) => !byNum[k] || !byNum[k].goal);
  check(lost.length === 0, 'analyze: phases 1-24 and 07.1 still present with goals', lost.join(','));
}

// ---------------------------------------------------------------- dirs (Task 3)
function dirs() {
  const entries = fs
    .readdirSync('.planning/phases', { withFileTypes: true })
    .filter((e) => e.isDirectory())
    .map((e) => e.name);
  for (const n of Object.keys(NEW_DIRS)) {
    const d = NEW_DIRS[n];
    const keep = path.join('.planning/phases', d, '.gitkeep');
    check(fs.existsSync(keep) && fs.statSync(keep).size === 0, 'dirs: phase ' + n + ' directory ' + d + ' exists with an empty .gitkeep');
    const same = entries.filter((e) => {
      const m = /^(\d+)-/.exec(e);
      return m && Number(m[1]) === Number(n);
    });
    check(same.length === 1 && same[0] === d, 'dirs: exactly one directory carries number ' + n, same.join(', '));
    const r = gsd(['find-phase', n]);
    const got = String(r.directory || '').replace(/\\/g, '/');
    check(r.found === true && got === '.planning/phases/' + d, 'dirs: find-phase ' + n + ' resolves to ' + d, JSON.stringify({ found: r.found, directory: got }));
  }
  for (const o of OLD_DIRS) check(!fs.existsSync(path.join('.planning/phases', o)), 'dirs: old directory ' + o + ' is gone');
}

// ---------------------------------------------------------------- git (after the task commits)
function gitChecks() {
  const dirty = git(['status', '--porcelain', '--', DECISIONS, ROADMAP, '.planning/phases']).trim();
  check(dirty === '', 'git: DECISIONS.md, ROADMAP.md and .planning/phases have no uncommitted changes', dirty.split('\n').slice(0, 5).join('; '));
  check(sha256(lf(git(['show', 'HEAD:' + DECISIONS]))) === DECISIONS_SHA256_LF, 'git: committed DECISIONS.md matches the pinned digest');
  check(sha256(lf(git(['show', 'HEAD:' + ROADMAP]))) === ROADMAP_SHA256_LF, 'git: committed ROADMAP.md matches the pinned digest');
  for (const d of Object.values(NEW_DIRS)) {
    const f = '.planning/phases/' + d + '/.gitkeep';
    check(git(['ls-files', '--', f]).trim() === f, 'git: ' + f + ' is tracked');
  }
  for (const o of OLD_DIRS) check(git(['ls-files', '--', '.planning/phases/' + o]).trim() === '', 'git: nothing tracked under old directory ' + o);

  const log = git(['log', BASE + '..HEAD', '--format=%H%x09%s']).split('\n').filter(Boolean).map((l) => l.split('\t'));
  for (const subj of COMMIT_SUBJECTS) {
    const hits = log.filter(([, s]) => s === subj);
    check(hits.length === 1, 'git: exactly one commit "' + subj + '" since ' + BASE, 'found ' + hits.length);
    if (hits.length !== 1) continue;
    const h = hits[0][0];
    const files = git(['show', '--name-only', '--format=', h]).split('\n').filter(Boolean);
    const outside = files.filter((f) => !ALLOWED_IN_COMMITS.some((re) => re.test(f)));
    check(outside.length === 0, 'git: commit ' + h.slice(0, 7) + ' touches only DECISIONS.md, ROADMAP.md, phase 25-27 .gitkeep files or the ' + TASK_ID + ' helper scripts', outside.join('; '));
    check(git(['log', '-1', '--format=%B', h]).trimEnd().endsWith(TRAILER), 'git: commit ' + h.slice(0, 7) + ' ends with the Co-Authored-By trailer');
  }
}

// ---------------------------------------------------------------- main
const modes = { decisions, roadmap, dirs, git: gitChecks };
const mode = process.argv[2] || 'all';
if (!fs.existsSync(ROADMAP) || !fs.existsSync(DECISIONS)) {
  console.log('FAIL run this script from the repository root (' + ROADMAP + ' / ' + DECISIONS + ' not found)');
  process.exit(2);
}
if (!fs.existsSync(INPUT)) {
  console.log('FAIL INPUT file not found: ' + INPUT);
  process.exit(2);
}
const run = mode === 'all' ? Object.keys(modes) : [mode];
for (const m of run) {
  if (!modes[m]) {
    console.log('usage: node 260930-cgi-verify.cjs <decisions|roadmap|dirs|git|all>');
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
