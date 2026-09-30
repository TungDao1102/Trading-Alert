'use strict';
// Quick task 260930-cgi: apply INPUT Part A (docs/DECISIONS.md) or Part B (.planning/ROADMAP.md).
//
// Run from the repository root:
//   node .planning/quick/<this-dir>/260930-cgi-apply.cjs decisions [--dry-run]
//   node .planning/quick/<this-dir>/260930-cgi-apply.cjs roadmap   [--dry-run]
//
// Fenced text is read verbatim from 260930-cgi-INPUT.md (located next to this script): every line strictly
// between the "```" fence lines of the section it belongs to (Part A, B2, B3, B4, B6, B7). Nothing is re-typed.
// The short inline replacements below are asserted at runtime to occur verbatim, between backticks, in INPUT.md.
// Every anchor must match exactly one line, so a second run fails loudly (APPLY_FAILED) instead of applying twice.
// The file's existing line ending (CRLF in a core.autocrlf=true checkout) is preserved for every line.

const fs = require('fs');
const path = require('path');

const INPUT = path.join(__dirname, '260930-cgi-INPUT.md');
const DECISIONS = 'docs/DECISIONS.md';
const ROADMAP = '.planning/ROADMAP.md';
const mode = process.argv[2];
const dryRun = process.argv.includes('--dry-run');

function fail(msg) {
  console.error('APPLY_FAILED ' + msg);
  process.exit(1);
}

if (!fs.existsSync(INPUT)) fail('INPUT file not found: ' + INPUT);
const inputRaw = fs.readFileSync(INPUT, 'utf8').replace(/\r\n/g, '\n');

// ---------------------------------------------------------------- INPUT fences, keyed by section
function fences() {
  const out = {};
  let section = null;
  let open = -1;
  const lines = inputRaw.split('\n');
  lines.forEach((l, i) => {
    if (open < 0) {
      if (l.startsWith('## Part A')) section = 'A';
      const m = /^### (B\d)\./.exec(l);
      if (m) section = m[1];
    }
    if (l === '```') {
      if (open < 0) {
        open = i;
      } else {
        if (!section) fail('fence at INPUT line ' + (open + 1) + ' has no Part A / Bn section');
        if (out[section]) fail('section ' + section + ' has more than one fence in INPUT');
        out[section] = lines.slice(open + 1, i);
        open = -1;
      }
    }
  });
  if (open >= 0) fail('unterminated fence in INPUT at line ' + (open + 1));
  const keys = Object.keys(out).sort().join(',');
  if (keys !== 'A,B2,B3,B4,B6,B7') fail('INPUT fences found for [' + keys + '], expected [A,B2,B3,B4,B6,B7]');
  return out;
}
const F = fences();

// An inline replacement must appear in INPUT between backticks (INPUT writes a literal backtick as \`).
function inl(s) {
  const plain = '`' + s + '`';
  const escaped = '`' + s.replace(/`/g, '\\`') + '`';
  if (!inputRaw.includes(plain) && !inputRaw.includes(escaped)) fail('inline text not found verbatim in INPUT: ' + s);
  return s;
}

function load(file) {
  if (!fs.existsSync(file)) fail('run from the repository root (' + file + ' not found)');
  const raw = fs.readFileSync(file, 'utf8');
  const eol = raw.includes('\r\n') ? '\r\n' : '\n';
  return { eol, lines: raw.replace(/\r\n/g, '\n').split('\n') };
}

function save(file, doc, label) {
  const out = doc.lines.join(doc.eol);
  const tag = 'lines=' + doc.lines.length + ' eol=' + (doc.eol === '\r\n' ? 'CRLF' : 'LF');
  if (dryRun) {
    console.log('DRY_RUN_OK ' + label + ' ' + tag + ' (nothing written)');
  } else {
    fs.writeFileSync(file, out, 'utf8');
    console.log('APPLIED ' + label + ' ' + tag);
  }
}

function oneIn(lines, pred, what) {
  const hits = [];
  lines.forEach((l, i) => {
    if (pred(l)) hits.push(i);
  });
  if (hits.length !== 1) fail('anchor "' + what + '" matched ' + hits.length + ' lines (expected exactly 1; already applied?)');
  return hits[0];
}

// ---------------------------------------------------------------- Part A: docs/DECISIONS.md
function decisions() {
  const rows = F.A;
  if (rows.length !== 2) fail('Part A fence must hold exactly 2 rows, found ' + rows.length);
  if (!rows[0].startsWith('| D040 | ') || !rows[1].startsWith('| D041 | ')) fail('Part A rows must be D040 then D041');
  for (const r of rows) {
    const pipes = (r.match(/\|/g) || []).length;
    if (pipes !== 5) fail('row ' + r.slice(0, 8) + ' has ' + pipes + ' "|" characters (expected 5: four cells, no pipe inside a cell)');
  }
  const doc = load(DECISIONS);
  const L = doc.lines;
  if (L.some((l) => l.startsWith('| D040 |') || l.startsWith('| D041 |'))) fail('D040/D041 already present (already applied?)');
  const i39 = oneIn(L, (l) => l.startsWith('| D039 | '), 'D039 row');
  if (L.slice(i39 + 1).some((l) => l !== '')) fail('D039 is not the last row of docs/DECISIONS.md');
  L.splice(i39 + 1, 0, ...rows);
  save(DECISIONS, doc, 'decisions');
}

// ---------------------------------------------------------------- Part B: .planning/ROADMAP.md
function roadmap() {
  const doc = load(ROADMAP);
  const L = doc.lines;
  const one = (pred, what) => oneIn(L, pred, what);
  const eq = (s) => (l) => l === s;

  // Section bounds of a "### Phase N:" detail block (heading .. next "### " or "## " heading, exclusive).
  function section(headingIdx) {
    let end = headingIdx + 1;
    while (end < L.length && !L[end].startsWith('### ') && !L[end].startsWith('## ')) end++;
    return [headingIdx, end];
  }
  function within(idx, bounds, what) {
    if (!(idx > bounds[0] && idx < bounds[1])) fail('anchor "' + what + '" is not inside its phase section');
    return idx;
  }

  // ---- B1 Overview (line-level replacements)
  const iOld17 = one(eq('- old 17 → 26'), 'B1 "- old 17 → 26"');
  const iLiveEn = one(eq('- Live enablement (25) requires 11–24 complete.'), 'B1 live-enablement line');
  const sentence = inl('Phases 11–26 below replace the earlier backlog-promoted phases 11–17 and carry their scope forward:');
  const iSentence = one((l) => l.includes(sentence), 'B1 "Phases 11–26 below replace" sentence');
  if (L[iSentence].split(sentence).length !== 2) fail('B1 sentence occurs more than once in its line');

  // ---- B2 Phase list
  const iList25 = one((l) => l.startsWith(inl('- [ ] **Phase 25: Go-Live Readiness Gate**')), 'B2 phase-list line 25');
  const iList26 = one((l) => l.startsWith(inl('- [ ] **Phase 26: Configurable Quote Asset (USDC readiness)**')), 'B2 phase-list line 26');
  if (iList26 !== iList25 + 1) fail('B2 phase-list lines 25 and 26 are not consecutive');
  const list16Old = inl('- [ ] **Phase 16: Paper Runtime Composition** - Runnable paper process (M3), fixed WS await, simulated fills, measured approval delay; soak can start');
  const list23Old = inl('- [ ] **Phase 23: Telegram Approval Hardening + Money Amounts** - User-id auth, working SKIP, keyboard removal, $ amounts in messages (was Phase 16)');
  const iList16 = one(eq(list16Old), 'B2 phase-list line 16');
  const iList23 = one(eq(list23Old), 'B2 phase-list line 23');

  // ---- B3 Phase 16 details
  const iH16 = one(eq(inl('### Phase 16: Paper Runtime Composition')), 'B3 Phase 16 heading');
  const s16 = section(iH16);
  const iG16 = within(one(eq('**Goal**: A runnable paper process observes the corrected families forward, so the wall-clock-bound soak can finally start.'), 'B3 Phase 16 goal'), s16, 'B3 Phase 16 goal');
  const iC16 = within(one(eq('4. The paper exit criteria are quantitative and pre-registered (F-023).'), 'B3 Phase 16 criterion 4'), s16, 'B3 Phase 16 criterion 4');
  const iA16 = within(one(eq('**Audit refs**: F-201, F-125, F-607, F-961, F-023'), 'B3 Phase 16 audit refs'), s16, 'B3 Phase 16 audit refs');
  if (!(iC16 < iA16)) fail('B3 criterion 4 must precede the Audit refs line');
  if (!/^### Phase 17: /.test(L[s16[1]])) fail('B3 Phase 16 section is not followed by the Phase 17 heading');

  // ---- B4 Phase 23 details
  const iH23 = one(eq(inl('### Phase 23: Telegram Approval Hardening + Money Amounts')), 'B4 Phase 23 heading');
  const s23 = section(iH23);
  const iG23 = within(one(eq('**Goal**: Only the authorized user in a private chat can approve. SKIP works. Decided messages cannot be tapped again. Every SIMULATE/APPROVE message shows the money at stake.'), 'B4 Phase 23 goal'), s23, 'B4 Phase 23 goal');
  const iC23 = within(one(eq('3. The expiry window shown and the remaining-validity rule match Phase 19 (F-016).'), 'B4 Phase 23 criterion 3'), s23, 'B4 Phase 23 criterion 3');
  const iA23 = within(one(eq('**Audit refs**: F-508, F-707, F-405, F-509, F-127, F-015, F-016'), 'B4 Phase 23 audit refs'), s23, 'B4 Phase 23 audit refs');
  if (!(iC23 < iA23)) fail('B4 criterion 3 must precede the Audit refs line');
  if (!/^### Phase 24: /.test(L[s23[1]])) fail('B4 Phase 23 section is not followed by the Phase 24 heading');

  // ---- B5 Phase 24 details
  const iH24 = one((l) => l.startsWith('### Phase 24: '), 'B5 Phase 24 heading');
  const s24 = section(iH24);
  const runnerOld = inl('   - Telegram bot runner (APPROVE → `execute_approved_plan`);');
  const smokeOld = inl('   - signal → approve → entry → SL/TP;');
  const iRunner = within(one(eq(runnerOld), 'B5 bot-runner line'), s24, 'B5 bot-runner line');
  const iSmoke = within(one(eq(smokeOld), 'B5 smoke-path line'), s24, 'B5 smoke-path line');

  // ---- B6 old Phase 25 + 26 detail sections
  const iDet25 = one(eq(inl('### Phase 25: Go-Live Readiness Gate')), 'B6 old Phase 25 heading');
  const iProgress = one(eq('## Progress'), '## Progress');
  if (iDet25 !== s24[1]) fail('B6 old Phase 25 heading does not directly follow the Phase 24 section');
  if (!(iDet25 < iProgress)) fail('B6 "## Progress" must follow the old Phase 25 heading');
  const between = L.slice(iDet25, iProgress).filter((l) => l.startsWith('### ')).join(' | ');
  if (between !== '### Phase 25: Go-Live Readiness Gate | ### Phase 26: Configurable Quote Asset (USDC readiness)') {
    fail('B6 region must hold exactly the old Phase 25 and 26 sections, found: ' + between);
  }

  // ---- B7 Progress section
  const iExec = one((l) => l.startsWith('Phases execute in numeric order: '), 'B7 execution-order line');
  const arrowOld = inl('→ 26.');
  const noLiveOld = inl('No live order before Phase 25 is complete.');
  if (L[iExec].split(arrowOld).length !== 2) fail('B7 "→ 26." must occur exactly once in the execution-order line');
  if (L[iExec].split(noLiveOld).length !== 2) fail('B7 "No live order before Phase 25 is complete." must occur exactly once');
  const iRow16 = one(eq(inl('| 16. Paper Runtime Composition | 0/TBD | Not started | - |')), 'B7 progress row 16');
  const iRow23 = one(eq(inl('| 23. Telegram Approval Hardening + Money Amounts | 0/TBD | Not started | - |')), 'B7 progress row 23');
  const iRow25 = one((l) => l.startsWith('| 25. Go-Live Readiness Gate |'), 'B7 progress row 25');
  const iRow26 = one((l) => l.startsWith('| 26. Configurable Quote Asset (USDC readiness) |'), 'B7 progress row 26');
  if (iRow26 !== iRow25 + 1) fail('B7 progress rows 25 and 26 are not consecutive');
  if (!(iProgress < iExec && iExec < iRow16 && iRow16 < iRow23 && iRow23 < iRow25)) fail('B7 anchors are not in document order');

  // ---- fence shape checks
  if (F.B2.length !== 3 || !F.B2[0].startsWith('- [ ] **Phase 25: Binance Demo Integration Test Campaign**')) fail('B2 fence must be the 3 new phase-list lines 25/26/27');
  if (F.B3.length !== 2 || !F.B3[0].startsWith('5. ') || !F.B3[1].startsWith('6. ')) fail('B3 fence must be success criteria 5 and 6');
  if (F.B4.length !== 1 || !F.B4[0].startsWith('4. ')) fail('B4 fence must be success criterion 4');
  const b6h = F.B6.filter((l) => l.startsWith('### ')).join(' | ');
  if (b6h !== '### Phase 25: Binance Demo Integration Test Campaign | ### Phase 26: Go-Live Readiness Gate | ### Phase 27: Configurable Quote Asset (USDC readiness)') {
    fail('B6 fence headings unexpected: ' + b6h);
  }
  if (F.B6[F.B6.length - 1] !== '') fail('B6 fence must end with one blank line (section separator before ## Progress)');
  if (F.B7.length !== 3 || !F.B7.every((l) => /^\| 2[567]\. .+ \| 0\/TBD \| Not started \| - \|$/.test(l))) fail('B7 fence must be the 3 new progress rows 25/26/27');

  // ---- line-level replacements (indices do not shift)
  L[iOld17] = inl('- old 17 → 27');
  L[iLiveEn] = inl('- Live enablement (26) requires 11–25 complete, and follows the D040 release path SHADOW → DEMO → CANARY → LIVE.');
  L[iSentence] = L[iSentence].replace(sentence, sentence.replace('Phases 11–26', 'Phases 11–27'));
  L[iList16] = inl('- [ ] **Phase 16: Paper Runtime Composition + SHADOW Approval Mode** - Runnable paper process (M3), fixed WS await, simulated fills, SHADOW APPROVE/SKIP journaled with no order path (D040); soak can start');
  L[iList23] = inl('- [ ] **Phase 23: Telegram Approval Hardening + Two-Step Confirm + Money Amounts** - User-id auth, working SKIP, APPROVE→CONFIRM card (D041), keyboard removal, $ amounts (was Phase 16)');
  L[iH16] = inl('### Phase 16: Paper Runtime Composition + SHADOW Approval Mode');
  L[iG16] = inl('**Goal**: A runnable paper process observes the corrected families forward, so the wall-clock-bound soak can finally start. The operator can already APPROVE/SKIP (with the D041 confirm step) in SHADOW mode to build a decision history, with no possible path to a real order (D040).');
  L[iA16] = L[iA16] + inl(', D040, D041');
  L[iH23] = inl('### Phase 23: Telegram Approval Hardening + Two-Step Confirm + Money Amounts');
  L[iG23] = inl('**Goal**: Only the authorized user in a private chat can approve. SKIP works. An APPROVE tap alone never places an order: a second CONFIRM step on a confirmation card is required (D041). Decided messages cannot be tapped again. Every SIMULATE/APPROVE message shows the money at stake.');
  L[iA23] = L[iA23] + inl(', D041');
  L[iRunner] = inl('   - Telegram bot runner (APPROVE → CONFIRM → `execute_approved_plan`, D041);');
  L[iSmoke] = inl('   - signal → approve → confirm → entry → SL/TP;');
  L[iExec] = L[iExec].replace(arrowOld, inl('→ 27.')).replace(noLiveOld, inl('No real-money order before Phase 26 is complete (D040: SHADOW → DEMO → CANARY → LIVE).'));
  L[iRow16] = inl('| 16. Paper Runtime Composition + SHADOW Approval Mode | 0/TBD | Not started | - |');
  L[iRow23] = inl('| 23. Telegram Approval Hardening + Two-Step Confirm + Money Amounts | 0/TBD | Not started | - |');

  // ---- splices, bottom-up so earlier indices stay valid
  const splices = [
    [iRow25, 2, F.B7], // B7: progress rows 25, 26 -> 25, 26, 27
    [iDet25, iProgress - iDet25, F.B6], // B6: old Phase 25 + 26 details (up to, not incl., ## Progress)
    [iC23 + 1, 0, F.B4], // B4: new criterion 4 after Phase 23 criterion 3
    [iC16 + 1, 0, F.B3], // B3: new criteria 5, 6 after Phase 16 criterion 4
    [iList25, 2, F.B2], // B2: phase-list lines 25, 26 -> 25, 26, 27
  ];
  for (let k = 1; k < splices.length; k++) if (!(splices[k][0] < splices[k - 1][0])) fail('internal: splices are not bottom-up');
  for (const [at, del, ins] of splices) L.splice(at, del, ...ins);

  save(ROADMAP, doc, 'roadmap');
}

if (mode === 'decisions') decisions();
else if (mode === 'roadmap') roadmap();
else {
  console.error('usage: node 260930-cgi-apply.cjs <decisions|roadmap> [--dry-run]');
  process.exit(2);
}
