# Báo cáo Deep Audit #2 — Trading-Alert (snapshot `55885b9`)

> Audit chỉ đọc, ngày 2026-11-17 → 2026-11-18. Toàn bộ đầu vào nằm trong
> `C:\Users\admin\Music\project-audit\2026-11-17_55885b9\` (gọi tắt là AUDIT).
> Mọi finding được dẫn bằng mã `G-xxxx`; chi tiết đầy đủ (evidence, reproduction, why_tests_miss,
> recommendation) nằm trong `AUDIT\findings.json` và file lane tương ứng `AUDIT\lanes\<lane>.md`.
> Bản tóm tắt dễ đọc: `AUDIT\BAO_CAO_TONG_HOP.md`.

---

## 1. Danh tính audit

| Mục | Giá trị |
|---|---|
| Repository | `C:\Users\admin\Music\Trading`, branch `develop` |
| Snapshot | `55885b932ec38048385677d150f92fa7369e196d` (`55885b9`), audit trên cây đã commit (các file dirty `.planning/config.json`, `.planning/state.json`, `.gsd/`, `.planning/milestone.lock` không thuộc phạm vi) |
| Bản sao dùng để đọc | `AUDIT\snapshot` (detached tại SHA, sạch) |
| Audit trước để so sánh | `.planning/audits/2026-09-29-deep-audit/` (snapshot `63ca176`, 152 finding primary, 12 HIGH) |
| Kích thước | 3.890 file tracked; `src` ≈ 135k dòng trong 16 package; 946 file test ≈ 306k dòng; khoảng 2.500 commit kể từ audit trước |
| Người yêu cầu | owner, 2026-11-17, yêu cầu audit **trung lập** vì mọi quyết định, docs và plan đều do AI đề xuất |
| Trạng thái hệ thống khi audit | placement live bị tắt (`LIVE_ORDERS_DISABLED`), chỉ chạy Demo; Demo smoke 21/21 bước đã pass (2026-11-06, 2026-11-15) |
| Hai thang severity | **now** = trạng thái hiện tại (placement tắt, chỉ Demo); **mainnet** = khi bật placement trên mainnet |
| Quy tắc | không sửa repo gốc, không kết nối Binance/Telegram/DB, không chạy `--execute` hay `pytest -m demo`, không đọc `.env` |

---

## 2. Tóm tắt điều hành

**Kết luận ngắn.** So với audit 2026-09-29, dự án đã tiến một bước rất lớn: toàn bộ đường đi của
tiền (signal → plan → approve/confirm → place → fill → protect → reconcile → journal) đã được
nối thành một tiến trình chạy được trên Demo, và các nguyên tắc quan trọng nhất (không bao giờ gửi
lại lệnh, làm tròn khối lượng xuống, không mở entry khi còn vị thế không được bảo vệ, SAFE_MODE,
ràng buộc approval với plan, gate Telegram theo user) đều có trong code **và** có test sẽ đỏ nếu
chúng bị phá (mutation probe, mục 4.3). Ở trạng thái hiện tại không có finding CRITICAL hay HIGH.
Nhưng nếu bật placement trên mainnet với code như ở snapshot này thì có **8 finding HIGH**, tất cả
đã được verifier mù xác nhận, và kết quả nghiên cứu của chính dự án cho thấy chưa có chiến lược
nào vượt qua gate đã đăng ký trước.

**Số liệu (tính lại từ `findings.json`, khớp với số liệu đã cho).**

| | Tổng | CRITICAL | HIGH | MEDIUM | LOW | INFO |
|---|---|---|---|---|---|---|
| Bản ghi thô | 148 | | | | | |
| Primary (bỏ 4 duplicate) | 144 | | | | | |
| Severity **now** (primary) | 144 | 0 | 0 | 22 | 103 | 19 |
| Severity **mainnet** (primary) | 144 | 0 | 8 | 76 | 48 | 12 |

Phân loại primary: DESIGN 46, GAP 45, DRIFT 22, DEFECT 19, IMPROVEMENT 9, AMBIGUITY 3.
Các con số trên đã gồm 6 finding của lane X11 (G-2300..G-2305: 0 HIGH, 2 MEDIUM, 3 LOW, 1 INFO), thêm vào sau khi phần còn lại của báo cáo được viết; các mục khác trích 138 primary là con số trước X11.
Duplicate: G-2101 → G-0901, G-0400 → G-0101, G-2104 → G-0250, G-2201 → G-2100.
Tỷ lệ DESIGN cao (46/144) là hệ quả trực tiếp của yêu cầu trung lập: nhiều vấn đề nằm ở chính
quyết định, code chỉ làm đúng theo quyết định đó.

**Xác minh mù.** 16 claim CRITICAL/HIGH (now hoặc mainnet) được gửi cho verifier chỉ nhận claim
và vị trí: **9 CONFIRMED, 7 DOWNGRADED, 0 REJECTED**. Tám finding còn HIGH trên mainnet đều
CONFIRMED: G-2100, G-0300, G-0301 + G-2203 (một cặp), G-1101, G-0801, G-1302, G-1508.

**Tám rủi ro HIGH trên mainnet, nói gọn.**

1. G-2100 — Entry GTD LIMIT nằm chờ trên sàn mà không có stop; nếu tiến trình chết, host reboot
   hoặc mất mạng đúng lúc entry khớp thì vị thế không có stop, và service live có `restart: "no"`.
   Tổn thất bị chặn bởi margin isolated (khoảng 88 USDT ở equity 1000, ≈17R) thay vì 5 USDT dự kiến.
2. G-0300 — Hai lần đọc position bằng 0 sát nhau ngay sau fill được coi là bằng chứng "đã flat":
   plan chuyển FLAT và tự hủy stop của chính nó trong khi vị thế vẫn mở.
3. G-0301 + G-2203 — Emergency close có kết quả không rõ (hoặc bị sàn từ chối bằng mã chưa có
   trong bảng, ví dụ -4131) bị giữ PENDING_UNKNOWN vĩnh viễn: không gửi close thứ hai, không đặt
   stop, lệnh operator bị từ chối.
4. G-1101 — Không có code production nào ghi bảng `fills`, `orders.local_status` không rời NEW:
   analytics live và mọi gate dựa trên kết quả live sẽ thấy 0 giao dịch.
5. G-0801 — Alert CRITICAL gửi Telegram thất bại bị bỏ trong suốt đời tiến trình, và dedupe 5 phút
   nuốt luôn các lần lặp, kể cả plan khác trên cùng symbol.
6. G-1302 — `evaluate_demo_soak.py` có thể cho PASS một soak không hề diễn ra (hai dòng journal
   cách nhau 22 ngày → PASS).
7. G-1508 — Không có gate tuần tự có PostgreSQL nào được ghi lại kể từ 2026-10-20; từ đó có 572
   commit, +43.096 dòng `src`, gồm toàn bộ `src/live`.

**Kết quả nghiên cứu (G-0901).** Trong 48 candidate của research run 1 (simulator 2.3.0), 45 có
mean R trên tập Validation gộp âm; không candidate nào có thể qua gate G1–G5 của protocol; candidate
đang dùng cho paper/Demo (a01) có mean -0.1019 R trên 613 trade; không file nào ghi lại kết luận này.
Khoảng bootstrap thật không tính lại được vì danh sách trade không còn (chi tiết và giới hạn ở mục 9).

**Quy trình.** Discussion log của mười phase chạy ở chế độ `--auto`; nhiều "quyết định của owner"
thực chất là chấp nhận hàng loạt giá trị mặc định do AI đề xuất (G-1603, G-2103). Điều này không làm
các quyết định tự động sai (mục 8 liệt kê rất nhiều quyết định SOUND), nhưng các con số tiền bạc
chưa từng được trình bày cho owner kèm hậu quả bằng USDT.

**Audit 2026-09-29.** Cả 12 finding HIGH cũ đều đã đóng trong code hoặc docs; không finding cũ nào
bị đóng sai (WRONGLY_CLOSED = 0) (mục 11).

**Việc nên làm trước Phase 25 (Demo campaign):** ghi lại kết quả run 1 và để owner quyết hướng đi
(R-25); sửa G-1101 (fills ledger) để campaign đánh giá được; sửa G-1302 (soak evaluator); chạy và
ghi lại gate tuần tự có PG (G-1508); làm cho alert CRITICAL không bị mất (G-0801). Trước go-live:
G-2100, G-0300, G-0301/G-2203 và các quyết định owner ở mục 15 (thứ tự đầy đủ ở mục 14).

---

## 3. Phạm vi và độ phủ

### 3.1 Phạm vi

Toàn bộ cây đã commit tại `55885b9`: `src/` (16 package), `tests/`, `scripts/`, `deploy/`,
`config/`, `params/`, `docs/` (canonical), `.planning/` (đọc như ý định đã ghi lại, không như sự
thật), CI workflow, Docker/compose, evidence Demo đã commit, và các bản ghi nghiên cứu
`docs/research/experiments/`. Thứ tự ưu tiên chiều sâu theo charter §4: đường đi của lệnh → hiệu
ứng tiền → fail-closed/SAFE_MODE → sự thật của sàn → concurrency/persistence → tính hợp lệ của
nghiên cứu → ops → test → drift.

### 3.2 Độ phủ file (từ `AUDIT\FILE_COVERAGE.md`)

Mức đọc tốt nhất mà một lane ghi cho mỗi file tracked dưới `src/`, `scripts/`, `deploy/`,
`config/`, `docs/` (trừ `docs/research/experiments`):

| Mức | Số file |
|---|---|
| DEEP_READ | 198 |
| NORMAL_READ | 70 |
| METADATA_ONLY | 17 |
| NOT_READ | 4 |
| NOT_RECORDED (không lane nào ghi đúng đường dẫn; có thể nằm trong một dòng nhóm) | 146 |

Riêng `src/*.py`: 173 DEEP, 43 NORMAL, 7 METADATA, 68 chỉ được phủ bởi dòng nhóm hoặc văn bản lane
(không có dòng riêng). Các vùng còn phủ mỏng được các lane ghi rõ: phần lớn `src/analytics`,
`src/persistence/{pending_actions,risk_reservations,day_risk,safe_mode_store,system_state}.py`
(NOT_READ trong lane data_persistence_db, dù các lane khác có đọc một phần), `src/ops/alerts.py`
và `alert_wording.py` theo góc nhìn ops (lane telegram_alerts đã đọc sâu), nhiều file systemd và
docs không có dòng riêng.

### 3.3 Công cụ tĩnh và bộ test (từ `AUDIT\tool-output\`)

| Công cụ | Kết quả tại snapshot |
|---|---|
| `ruff check`, `ruff format --check` | sạch (exit 0) |
| `mypy src` (strict, 291 file) | 0 lỗi |
| `verify_decision_alignment.py all` | exit 0 (nhưng xem G-1300: gate này chỉ kiểm câu chữ) |
| `pytest -m "not docker" -n 4` | exit 0: 17.380 passed, 915 skipped, 3 xfail (strict), 0 failed |

Phần lớn skip là test PostgreSQL (`TEST_DATABASE_URL` cố ý để trống; lane X03 đếm 872 case PG),
cộng test Demo chỉ owner chạy và vài test phụ thuộc nền tảng. Ba xfail đều strict và ghim các lỗi
đã biết 25-12-F1, 25-14-F1, 25-15-F1 (`tests/test_phase25_gate.py:1197-1221`).

---

## 4. Phương pháp

### 4.1 Lane

26 lane, mỗi lane là một agent mới với brief chung (`AUDIT\LANE_BRIEF.md`) và phạm vi riêng
(`AUDIT\LANES.md`); mỗi lane ghi `lanes\<lane>.md` và `lanes\<lane>.findings.json` từng phần.

| Nhóm | Lane (mã ID) |
|---|---|
| Đường đi của tiền | M01 core_strategy_risk (G-01xx), M02 exec_placement (G-02xx), M02b exec_gapfill (G-025x), M03 exec_protection (G-03xx), M04 live_risk_state (G-04xx), M05 reconcile_safemode (G-05xx) |
| Tiến trình live và sàn | M06 live_composition (G-06xx), M07 binance_adapters (G-07xx), M08 telegram_alerts (G-08xx) |
| Nghiên cứu, paper | M09 backtest_research_analytics (G-09xx), M09b backtest_gapfill (G-095x), M10 paper_runtime (G-10xx), M10b paper_gapfill (G-105x) |
| Dữ liệu, ops, công cụ | M11 data_persistence_db (G-11xx), M12 ops_deploy_security (G-12xx), M13 scripts_tooling (G-13xx) |
| Kỹ thuật X (mới trong audit này) | X01 failure_scenarios (G-18xx), X02 mutation_probe (G-19xx), X03 test_effectiveness_ci (G-14xx), X04 evidence_reproducibility (G-15xx), X05 decisions_requirements_process (G-16xx), X06/X07 prior_findings_closure_a/b (G-17xx), X08 operator_golive_gap (G-20xx), X09 decisions_trading_soundness (G-21xx), X10 exchange_facts (G-22xx) |

### 4.2 Các kỹ thuật X

- **X01 FMEA theo kịch bản**: 26 kịch bản lỗi trên vòng đời lệnh, 8 probe trên tiến trình được
  ghép với fake exchange; tái hiện độc lập G-2100, G-0300, G-0301, G-0403.
- **X02 mutation probe**: khoảng 90 mutation có chủ đích lên các guard an toàn, chạy test liên quan,
  kiểm tra tương đương cho mọi mutation sống sót. Chỉ 3 mutation sống thật (G-1901, G-1902, G-1903).
- **X03 hiệu quả test và CI**: so fake exchange với hành vi thật của Binance, phân loại skip/xfail,
  lịch sử test từ 2026-10-01, AST guard.
- **X04 tái lập evidence**: re-hash 73 parameter set, chạy simulator trong ba interpreter với
  `PYTHONHASHSEED` khác nhau, tính lại `experiment_id` của 480 record, đọc từng bước smoke 21/21.
- **X05/X09 xét chính các quyết định**: bảng "Decision review" với thước đo rõ ràng; X09 xét tính
  đúng đắn về trading, X05 xét quy trình ra quyết định.
- **X06/X07 kiểm tra đóng finding cũ** từ code (plan/summary chỉ dùng để định vị).
- **X08 góc nhìn operator**: runbook, alert, heartbeat, khoảng cách Demo → mainnet.
- **X10 sự thật của sàn**: bảng 53 fact đối chiếu tài liệu chính thức developers.binance.com và SDK
  đã cài (core.telegram.org trả 403, nên các fact Telegram ghi UNVERIFIABLE).

### 4.3 Xác minh mù

Mọi finding CRITICAL/HIGH (now hoặc mainnet) được gửi cho verifier độc lập chỉ nhận claim và vị trí
(`AUDIT\VERIFIER_BRIEF.md`), năm batch V1–V5 trong `AUDIT\verification\`:

| Batch | Claim | Kết quả |
|---|---|---|
| V1 protection | G-0250, G-0300, G-0301, G-2203 | G-0300, G-0301, G-2203 CONFIRMED (mainnet HIGH); G-0250 DOWNGRADED (LOW / mainnet MEDIUM: fail closed, chỉ là một lần close không cần thiết) |
| V2 design/risk | G-2100, G-2201, G-0403, G-0700 | G-2100 CONFIRMED; G-2201 DOWNGRADED, duplicate của G-2100; G-0403 DOWNGRADED (mainnet MEDIUM: entry mới vẫn bị chặn, fill muộn vẫn có stop); G-0700 DOWNGRADED (mainnet MEDIUM: "không gì xóa được" là sai, có `rest_gate_cli clear --force` + restart) |
| V3 ops/evidence | G-1101, G-0801, G-1302, G-1501, G-1503, G-1508 | G-1101, G-0801, G-1302, G-1508 CONFIRMED; G-1501, G-1503 DOWNGRADED (mainnet MEDIUM) |
| V4 alerting | G-2003 | DOWNGRADED (LOW / mainnet MEDIUM: Telegram hỏng hoặc verdict RED đã chặn entry mới, stop thiếu thì emergency close chạy) |
| V5 tests | G-1400 | DOWNGRADED (LOW / mainnet MEDIUM: 7 file test có mô phỏng lag bằng wrapper) |

Tổng: 16 claim, 9 CONFIRMED, 7 DOWNGRADED, 0 REJECTED. Không CRITICAL nào nên không cần verifier thứ hai.
G-2101 không gửi đi vì là MEDIUM và đã được M09 tính lại độc lập (G-0901).

### 4.4 Lập trường trung lập (charter §2.7)

Theo yêu cầu của owner ngày 2026-11-17: `docs/DECISIONS.md`, docs canonical, `AGENTS.md` và
`.planning/` là **ý định đã ghi lại, không phải sự thật**, vì đều do AI đề xuất. Thước đo "đúng",
theo thứ tự: (a) hành vi thật của sàn (docs chính thức, SDK đã cài, quan sát Demo được ghi rõ là
Demo); (b) số học và logic (probe có số); (c) thực hành quản trị rủi ro futures và phương pháp
nghiên cứu được chấp nhận rộng rãi; (d) mục tiêu owner đã nêu (vốn nhỏ, làm bán thời gian, không
chuyên trading, fail closed, không bao giờ auto-trade). Mỗi lane vừa so code với ý định, vừa xét
chính ý định. Trung lập theo cả hai chiều: không coi quyết định là đúng vì có số D và lý do, cũng
không coi là sai vì AI viết. Các quyết định đứng vững được ghi lại kèm lý do (mục 8, mục 12).
Các mục đã biết (`*-DEFERRED`, `19-OWNER-GAPS`, `NOT_CONFIGURED`, placement tắt) được dẫn chiếu
`KNOWN:` chứ không báo lại như mới, trừ khi bị mô tả sai, đóng sai, hoặc nặng hơn mức đã ghi.

---

## 5. Finding HIGH trên mainnet

Cả tám đều là LOW hoặc MEDIUM **now** (placement tắt nên không vị thế thật nào có thể tồn tại),
và HIGH **mainnet**. Ví dụ tiền dùng giả định của lane (equity 1000 USDT, risk 0,5 % ⇒ 1R = 5 USDT,
ISOLATED 5x) trừ khi ghi khác.

### 5.1 G-2100 — Entry nằm chờ không có stop; tiến trình chết là vị thế trần (DESIGN)

- **Cái gì.** D042 điều kiện (1) nói "stop bảo vệ luôn nằm trên sàn nên VPS sập không bao giờ để
  vị thế không được bảo vệ". Từ D079, entry là GTD LIMIT **không có stop** cho tới khi tiến trình
  thấy fill rồi mới đặt stop `closePosition`. Hai quyết định mâu thuẫn nhau. Crash, reboot hoặc mất
  mạng khi entry đang chờ ⇒ entry có thể khớp mà không ai đặt stop; service live có
  `restart: "no"` (`docker-compose.yml:232`). Không dùng dead-man switch phía sàn
  (`countdownCancelAll` không có trong `src`; COVERAGE của Phase 25 ghi OPT-OUT). Rủi ro này từng là
  "blocker carried to Phase 24" (`20-DEFERRED.md:134`) rồi biến mất khỏi kế hoạch Phase 24/25;
  R-22 của 24-DEFERRED chỉ phủ trường hợp dừng có chủ ý.
- **Vì sao quan trọng (tiền).** Một lần outage khi entry đang chờ có thể mất tới mức margin
  isolated, khoảng 88 USDT ở equity 1000 (rủi ro dự kiến 5 USDT, daily stop 10 USDT), tức khoảng
  17R. Ví dụ của lane: long 0,004 BTC ở 80.000, stop 1,5 % (rủi ro 4,8 USDT); host offline 20 phút,
  entry khớp, giá giảm 6 % ⇒ lỗ khoảng 19,2 USDT; với stop đặt trước, sàn thoát quanh -4,8 USDT.
  Daily stop, cap và SAFE_MODE không tác dụng vì tiến trình đã chết.
- **Evidence.** `docs/DECISIONS.md:46` (D042), `:83` (D079); `docs/operations/RUNBOOK.md:1182`
  ("a GTD LIMIT entry that is still resting can fill while the process is down ... and stay without
  a stop until the next start protects it"); `docker-compose.yml:218-232`; `20-DEFERRED.md:134`;
  `19-NOTES.md:16` (model (b), stop reduce-only đặt trước, được Demo chấp nhận nhưng không xây).
- **Xác minh.** V2: CONFIRMED (now LOW, mainnet HIGH). Verifier đọc thêm tài liệu chính thức
  `POST /fapi/v1/countdownCancelAll` (đúng là biện pháp phía sàn cho tình huống này) và evidence Demo
  của model (b). Restart có rehydrate và sẽ đặt stop (X01 P1: outage 5 s và 3600 s), nhưng không gì tự
  restart, và một tiến trình còn sống nhưng mất mạng cũng không đặt được stop. Duplicate G-2201
  (DOWNGRADED, mainnet MEDIUM): tiền đề -4509 của D079 chỉ đúng cho biến thể `closePosition`; model (b)
  có trade-off riêng (stop mồ côi khi entry bị hủy, partial fill, trigger theo mark khi còn flat,
  tốn headroom), nên chọn (a) là lựa chọn kỹ thuật có thể bảo vệ được; khuyết điểm là trade-off chưa
  được ghi và chưa so với rủi ro outage. Liên quan: G-1800 (restart bị từ chối khi một bước HOLD lỗi,
  không thử lại), G-2007 (`restart: "no"` được gọi là an toàn).
- **Hướng khắc phục.** Quyết định của owner (R-01): (a) probe và bật `countdownCancelAll` khi có
  entry chờ (cần kiểm tra không hủy algo stop của plan khác); (b) xây stop reduce-only đặt trước;
  (c) chấp nhận bằng văn bản với `restart: unless-stopped` và thời gian sống entry ngắn; (d) chỉ đặt
  entry khi owner có mặt. Dù chọn gì, sửa lại D042 điều kiện (1).

### 5.2 G-0300 — Hai lần đọc position bằng 0 ngay sau fill ⇒ plan FLAT, tự hủy stop (DEFECT)

- **Cái gì.** Ở trạng thái PROTECTED, nếu `positionRisk` trả về 0 thì `_second_read_is_flat` đọc
  lần hai **ngay lập tức** (không giãn cách); hai lần 0 ⇒ PROTECTED → FLAT
  (`REST_FLAT_TWO_READS_ENTRY_TERMINAL`), `_sweep` hủy SL/TP1/TP2, plan không còn chặn entry mới và
  không bao giờ được xem lại (FLAT không có handler). Sau fill, scheduler chạy 3 pass liền nhau
  (`src/live/stream.py:392-408`), nên hai lần đọc có thể rơi vào dưới một giây sau fill. Việc stop
  vừa được đọc ACTIVE trong cùng bước bị bỏ qua. Nhánh thứ hai (đã trace): stop bị từ chối (B5) +
  closer trả "already_flat" ⇒ FLAT cho một vị thế chưa từng có stop.
- **Vì sao quan trọng (tiền).** Một vị thế đã khớp, không stop, không TP, coordinator không theo dõi,
  entry mới không bị chặn, cho tới khi con người can thiệp. Ví dụ của X08: Telegram hỏng 02:00–07:00,
  0,5 ETH ở 3000 USDT bị trần lúc 02:10; giá đi ngược 5 % = 75 USDT trên tài khoản 500–1000 USDT.
- **Evidence.** `src/execution/protection.py:2571-2584`, `2523-2548`, `1794-1796` (comment chính
  code: "positionRisk lags the fill"); quick task 261114-kxu đã sửa lag này cho bước kiểm tra
  liquidation và ghi nhận bước attach cũng đọc `positionRisk`. Probe lane
  `tmp/exec_protection/probe_lag.py`: state FLAT, vị thế thật 0,004, open algo orders `[]`.
- **Xác minh.** V1: CONFIRMED cơ chế (now LOW, mainnet HIGH). Probe verifier: PROTECTED, vị thế thật
  0,010, hai lần đọc rỗng ⇒ FLAT, SL/TP1/TP2 bị hủy, `blocks_new_entries: False`. Reconcile thấy
  POSITION_WITHOUT_STOP và alert UNPROTECTED_POSITION nhưng chỉ đặt `recheck_requested`; plan FLAT
  không làm gì thêm. **Giới hạn:** khả năng Binance thật sự trả hai lần đọc rỗng cho vị thế vừa khớp
  chưa được chứng minh. X03 (G-1400) giải thích vì sao test không bắt được: fake exchange mặc định
  không có lag.
- **Hướng khắc phục.** Hai lần đọc 0 phải ở hai tick khác nhau hoặc cách `first_fill_at` một khoảng
  tối thiểu, và/hoặc khớp với `executedQty` của entry; áp dụng tương tự cho "already_flat" của
  closer. Đo lag `positionRisk` trong Phase 25.

### 5.3 G-0301 + G-2203 — Emergency close không rõ kết quả bị đóng băng vĩnh viễn (DESIGN + GAP)

- **Cái gì.** G-0301: emergency close có POST không rõ kết quả, sau đó REST không tìm thấy lệnh ⇒
  `mark_unknown` ⇒ PENDING_UNKNOWN **mãi mãi**: không gửi close reduce-only thứ hai, không đặt stop
  trong CLOSE_REQUIRED/CLOSE_FAILED, `operator_close` và `operator_protect` đều từ chối. Closer cũng
  không đọc lại position khi còn attempt pending, nên ngay cả khi owner tự đóng tay thì plan vẫn
  CLOSE_FAILED (G-1801). G-2203: nguyên nhân thực tế dẫn tới trạng thái đó; các mã từ chối chắc chắn
  sàn đã công bố (-4131, -4118, -2023, -2025, -4045) và các biến thể 503 "100 % failure" không có
  trong bảng lỗi nên bị coi là kết quả không rõ.
- **Vì sao quan trọng (tiền).** Ví dụ lane: long 0,02 BTC ở 60.000, 5x isolated (margin 240 USDT),
  stop chưa bao giờ được xác nhận; close bị trả -4131 trong thị trường chạy nhanh (đúng lúc emergency
  close hay chạy nhất) ⇒ một lần gửi rồi chờ con người; tổn thất bị chặn bởi 240 USDT margin chứ không
  phải 5–10 USDT rủi ro dự kiến. Một close reduce-only thứ hai không thể mở hay đảo vị thế.
- **Evidence.** `src/execution/emergency_close.py:794-873`, `512-516`, `807-812`, `182-187` (tập
  "definitive" chỉ gồm REJECTED_DEFINITIVE và PRECONDITION_NO_POSITION), `736-819`;
  `protection.py:1953-1957`, `1197-1200`, `1314-1321`; `src/domain/exchange_errors.py:756`,
  `766-786`. Probe lane `tmp/exec_protection/probe_close.py`: sau khoảng 24 h giả lập 1 POST,
  CLOSE_FAILED, vị thế 0,004 BTC, 0 stop.
- **Xác minh.** V1: cả hai CONFIRMED (now LOW, mainnet HIGH). Probe verifier: -4131, -2023, -2025,
  -1008 mỗi mã cho 1 lần gửi rồi PENDING_UNKNOWN ở cả 4 lần gọi; mã đã có trong bảng (-2022) thì được
  thử lại mỗi lần (4 lần gửi). Verifier đọc docs chính thức (2026-11-18): -4131 "counterparty's best
  price does not meet the PERCENT_PRICE filter limit", -2023 "User in liquidation mode now", -2025,
  -4045, -4118; HTTP 503 "Service Unavailable" là thất bại. Lưu ý: -1008 được miễn cho lệnh
  reduce-only/close-position nên dòng probe -1008 chỉ mang tính minh họa. Không phải duplicate: sửa
  riêng một trong hai giảm rủi ro theo cách khác nhau. Đã biết một phần (`19-OWNER-GAPS` WR-03 / D080
  ghi "có thể mở lâu hơn"; thực tế là không có giới hạn thời gian).
- **Hướng khắc phục.** Quyết định owner (R-03): thêm các mã từ chối chắc chắn đã công bố vào bảng;
  cho phép một close reduce-only mới dưới id mới sau một từ chối chắc chắn, hoặc sau N lần "not found"
  (ví dụ 3 lần trong 30 s) kèm một lần đọc position khác 0. Trong lúc chờ: lặp lại alert và có một lệnh
  operator dùng được trong CLOSE_FAILED. Lane exec_protection đánh giá việc áp D080 (không gửi lại)
  cho close reduce-only là WRONG (mục 8).

### 5.4 G-1101 — Không ai ghi bảng `fills`; analytics live thấy 0 giao dịch (GAP)

- **Cái gì.** `record_fill` không có caller production; `stream_persistence.py:258-298` chỉ gọi
  `update_order_exchange_state` (không đụng `local_status`); `transition_order` chỉ chạy khi
  `local_status` là UNKNOWN; row được insert NEW nên mãi là NEW. Fill live chỉ đi vào bộ nhớ của
  coordinator. `normalize_live_outcomes` bỏ qua plan không có fill entry (`live_outcomes.py:270-271`).
  Mục 20D-01 của `24-DEFERRED.md:56` ghi "CLOSED [DESIGN]" cho "fills ledger", tức là **đóng sai**.
- **Vì sao quan trọng (tiền).** Ví dụ lane: campaign Demo 20 trade đã khớp, kết quả ròng -3R ⇒
  báo cáo 0 trade. Trên mainnet: không có bản ghi bền vững theo từng fill của giao dịch tiền thật;
  mọi báo cáo live hay gate dựa trên kết quả live (kill gate) đều mù.
- **Evidence.** `src/persistence/entities.py:550`, `628`, `682`, `692-739`;
  `src/live/stream_persistence.py:283-284`, `428`; `src/live/stream.py:257`;
  `src/execution/protection.py:1422`; `src/adapters/analytics_store.py:210-211`;
  `src/analytics/live_outcomes.py`.
- **Xác minh.** V3: CONFIRMED (now MEDIUM, mainnet HIGH). Grep `record_fill|insert(FillRow|FillRow(`
  chỉ thấy định nghĩa, mapper và một hàm ghi evidence JSON trong `scripts/demo_rehearsal.py`. Việc bảo
  vệ vị thế không phụ thuộc các row này, nên không lên CRITICAL.
- **Hướng khắc phục.** Thêm writer cho `fills` trên đường fill stream/REST, cùng transaction với cập
  nhật order; chuyển `local_status` theo sự kiện stream; mở lại 20D-01 cho tới khi có test end-to-end.
  Quyết định owner trước Phase 25 (R-35, mục 15).

### 5.5 G-0801 — Alert CRITICAL gửi thất bại bị bỏ; dedupe nuốt lần lặp (DESIGN)

- **Cái gì.** `TelegramAlertSender.drain` lấy alert khỏi hàng đợi (`popleft`); nếu gửi thất bại
  (3 lần, tối đa 30 s) chỉ ghi journal `ALERT_SEND_FAILED`, không đưa lại vào hàng đợi; chỉ restart
  mới re-queue. `_accept` dedupe theo `(event, subject, reason)` trong 300 s **dù lần đầu có giao được
  hay không**, và key không có `plan_hash`, nên plan khác trên cùng symbol cũng bị nuốt. Các producer
  CLOSE_REQUIRED, EMERGENCY_CLOSE_FAILED/NOT_SENT, SAFE_MODE on_enter, DAILY_STOP đầu tiên chỉ phát
  một lần.
- **Vì sao quan trọng (tiền).** Chính các sự cố gây ra alert này (mất mạng, sàn/API trục trặc) cũng
  làm gửi Telegram thất bại, nên alert dễ mất nhất lại là alert của sự cố thật. Ví dụ lane: Telegram
  mất 40 s lúc 03:00 đúng khi emergency close thất bại ⇒ 3 lần thử trong 30 s, bỏ, điện thoại im lặng.
  Trên mainnet: vị thế không stop sau emergency close thất bại có thể mở mà owner không biết.
- **Evidence.** `src/ops/alerts.py:733-772` (`drain`), `489-530` (`_accept`);
  `src/paper/notify.py:115-116` (`NOTIFY_MAX_ATTEMPTS = 3`, `NOTIFY_MAX_DELAY_SECONDS = 30`);
  `config/execution/execution-limits-v1.toml:68` (`dedupe_window_ms = 300000`); `src/live/alerts.py:30-31`
  (ghi chú WR-C6 của chính dự án). Probe lane `tmp/telegram_alerts/probe_alert_lost.py`: gửi lúc
  Telegram chết ⇒ delivered 0, queue 0; sau khi phục hồi ⇒ 0; lặp +2 phút ⇒ 0; plan khác +4 phút ⇒ 0;
  lặp +6 phút ⇒ 1.
- **Xác minh.** V3: CONFIRMED (now MEDIUM, mainnet HIGH). Giảm nhẹ: alert đã được journal; SAFE_MODE
  được bật trước alert nên không có entry mới; emergency close vẫn chạy dù alert có đi hay không. Đã
  biết (KNOWN WR-C6, 24-DEFERRED R-02) nhưng bị "đóng" bằng cách chuyển thành mục owner, và
  `docs/integration/TELEGRAM.md` mô tả nhẹ hơn thực tế.
- **Hướng khắc phục.** Giữ alert CRITICAL/HIGH thất bại trong hàng đợi và thử lại ở các lần drain sau
  tới khi giao được (ghi giờ gốc trong nội dung); không suppress lặp khi alert đầu của sự cố chưa
  giao; thêm plan hash vào key dedupe của sự kiện theo plan. Cân nhắc kênh thứ hai (G-2003, R-23).

### 5.6 G-1302 — Soak evaluator có thể PASS một soak không diễn ra (DESIGN)

- **Cái gì.** `compute_window` lấy cửa sổ = dòng journal đầu → dòng cuối, không có tiêu chí mật độ
  hay khoảng trống; `check_order_after_registration` PASS khi không có order; `check_round_trips`
  SKIPPED khi `owner_round_trips_per_week` null mà verdict tổng vẫn PASS; cửa sổ export do operator
  chọn tự do; `image_commit` được parse nhưng không bao giờ được so sánh.
- **Vì sao quan trọng (tiền).** PASS của Demo soak là bằng chứng gate trước mainnet. Theo quy tắc
  95 % kiểu D061 cho soak 21 ngày (504 h) thì chỉ được phép 25,2 h downtime; evaluator hiện tại cho qua
  khoảng 502 h downtime.
- **Evidence.** `scripts/evaluate_demo_soak.py:620-630`, `658-671`, `819-829`, `876`, `880-901`,
  `1039-1067`; `image_commit` chỉ xuất hiện ở dòng 27, 220, 289, 345-358. Probe lane
  `tmp/scripts_tooling/p2_soak_two_rows.py`: hai dòng HEALTH_VERDICT cách 22 ngày ⇒ PASS.
- **Xác minh.** V3: CONFIRMED (now MEDIUM vì soak chưa chạy; mainnet HIGH). Probe verifier: hai dòng
  của một loại sự kiện giả cách nhau 21 ngày + 1 s, không có tick, health, order hay trade nào ⇒
  `PASSED: True`.
- **Hướng khắc phục.** Thêm tiêu chí coverage/khoảng trống tối đa với ngưỡng được owner phê duyệt,
  kiểm tra journal bắt đầu từ lúc đăng ký, so `image_commit`, coi 0 trade là không đạt (R-36).

### 5.7 G-1508 — Không có gate tuần tự có PostgreSQL kể từ 2026-10-20 (GAP)

- **Cái gì.** Gate được ghi gần nhất là `16-66-gate-post-phase19.txt` (2026-10-20, sequential,
  `TEST_DATABASE_URL` set, 11.557 passed, `IMAGE_COMMIT=36dcad8`). Từ `36dcad8` tới `55885b9`:
  572 commit trên tập đường dẫn của gate (306 chạm `src`), `src` thay đổi 139 file, +43.096 / -2.037
  dòng; `src/live` (26 file, +12.539 dòng) hoàn toàn mới. Phases 20–24 không có file gate có
  `IMAGE_COMMIT=`. Chính audit này cũng skip test PG.
- **Vì sao quan trọng (tiền).** Code sẽ đặt lệnh tiền thật không có bằng chứng full-suite nào gắn với
  một commit, kể cả các test database của nó; một image mainnet sẽ không có gate.
- **Evidence.** `.planning/phases/16-paper-runtime-composition/evidence/16-66-gate-post-phase19.txt:1-30`;
  `.planning/STATE.md:46-47`; `23-VERIFICATION:286` (full suite có một lỗi đã biết);
  `261114-mp1-SUMMARY:116,124` (`test_phase20_gate.py` invariant 6 fail).
- **Xác minh.** V3: CONFIRMED (now MEDIUM, mainnet HIGH). Có các lần chạy `-n 4` không được ghi, nên
  code không phải chưa từng được test; nhưng không lần nào gắn với commit, và lỗi invariant 6 đã biết
  nghĩa là một gate tại HEAD sẽ không sạch như quy định. Liên quan G-1401 (CI có thể timeout, kết quả
  CI không được ghi ở đâu).
- **Hướng khắc phục.** Chạy và ghi lại gate tuần tự có PG trên cây hiện tại; gắn lần smoke tiếp theo
  vào `IMAGE_COMMIT` đó (G-1501); owner kiểm tra GitHub Actions (G-1401).

---

## 6. Finding MEDIUM

Mục này gồm 73 finding primary có severity **mainnet MEDIUM**, nhóm theo chủ đề. Cột "now" là
severity hiện tại. Có 16 trong số đó đã là MEDIUM ngay bây giờ (G-0101, G-0500, G-0501, G-0802,
G-0901, G-0902, G-0903, G-1001, G-1002, G-1003, G-1005, G-1052, G-1300, G-1401, G-1501, G-1502);
4 finding MEDIUM now còn lại là HIGH mainnet và đã nêu ở mục 5 (G-0801, G-1101, G-1302, G-1508).
Mỗi dòng một câu; chi tiết trong `findings.json`.

### 6.1 Bảo vệ vị thế, thực thi lệnh, emergency close

| ID | now | Lớp | Vị trí | Vấn đề |
|---|---|---|---|---|
| G-0250 (dup G-2104) | LOW | DESIGN | `src/execution/protection.py:2316-2337` | Một lần đọc by-id "not found" cho stop đã xác nhận ⇒ đóng toàn bộ vị thế bằng MARKET + SAFE_MODE, không đọc lại, bỏ qua cross-check bằng listing; endpoint này đã trả "not found" sai trên Demo (2026-10-22, 11-01, 11-15). Verifier V1 hạ xuống vì vẫn fail closed (một lần close không cần thiết, không mất bảo vệ). |
| G-0251 | LOW | DESIGN | `src/execution/manager.py:2210-2228` | Bước gắn TP chỉ chạy một lần: một lỗi thoáng qua trước khi POST (lag đọc 1,5 s, một lần đọc exchangeInfo lỗi, DB trục trặc) ⇒ vị thế cả đời có stop nhưng không TP, SAFE_MODE. Chính smoke 2026-11-15 dừng ở đúng đường này. |
| G-0252 | LOW | GAP | `src/execution/manager.py:1937-1947` | POST TP1 mơ hồ không được đọc lại: TP1 nằm trên sàn, journal ghi UNKNOWN, TP2 không bao giờ gửi, SAFE_MODE. |
| G-0302 | LOW | DESIGN | `src/execution/protection.py:1549-1561` | Fill đầu tiên (bất kỳ cỡ) hủy phần còn lại của entry; với TP1 = 50 % và quy tắc min-notional, vị thế nhỏ hơn 2 × MIN_NOTIONAL không có TP và hệ thống dừng ở SAFE_MODE. |
| G-1800 | LOW | DESIGN | `src/live/startup.py:182-937` | Restart trên tài khoản có entry đã khớp chưa được bảo vệ bị từ chối khi một bước HOLD lỗi (ví dụ đọc revision DB lỗi một lần): không đặt stop, và với `--hold-on-refusal` thì chờ mãi không thử lại. Restart policy không chặn được cửa sổ outage của G-2100 trong trường hợp này. |
| G-1801 | LOW | DEFECT | `src/execution/emergency_close.py:512-819` | Khi close đang PENDING_UNKNOWN, closer return trước khi đọc position: owner đóng tay xong thì plan vẫn CLOSE_FAILED mãi (31 h và một restart trong probe), reservation giữ RESERVED, entry bị chặn, `/safemode_exit` từ chối; plan 25-32 (`/close` retry) chạy lại đúng bước bị giữ. |
| G-0201 | LOW | GAP | `src/execution/manager.py:823-1349` | Enablement, SAFE_MODE và cờ "vị thế không được bảo vệ" chỉ đọc một lần trước khoảng mười lần await REST, không đọc lại trước khi consume approval và gửi entry. |
| G-0202 | LOW | DESIGN | `src/execution/manager.py:953-960` | Quantity được tính lại lúc CONFIRM từ equity mới; nếu lớn hơn approved một step thì từ chối cả lệnh (QUANTITY_ABOVE_APPROVED) thay vì đặt đúng quantity đã duyệt. |
| G-0203 | LOW | IMPROVEMENT | `src/execution/manager.py:1291-1445` | Giữa POST entry và `register_resting_entry` chỉ bắt `PersistenceError`; exception khác hoặc cancellation bỏ qua bước chuyển cho protection, và tiến trình đang chạy không theo dõi lại row SENT. |
| G-0401 | INFO | GAP | `src/risk/reservations.py:292-307` | `mark_placed`/`mark_open` không có caller (KNOWN R-21) và hậu quả bị ghi nhẹ: khi có bất kỳ vị thế mở nào, mọi placement sau đều UNCERTAIN_ACCOUNT_STATE (hệ thống thực chất chỉ một vị thế). |
| G-0403 | LOW | GAP | `src/execution/daily_stop.py:229-325` | `enforce_daily_state` không có caller trong tiến trình live (KNOWN 25-15-F1): tại DAILY_STOP entry đang chờ không bị hủy, không alert; comment `src/live/risk_inputs.py:557-563` sai; `evaluate()` tiêu thụ dấu alert một lần cho các caller không gửi gì. V2 hạ xuống: entry mới vẫn bị chặn, fill muộn vẫn có stop. |

### 6.2 Sizing, cap và rủi ro danh mục

| ID | now | Lớp | Vị trí | Vấn đề |
|---|---|---|---|---|
| G-0101 (dup G-0400) | MEDIUM | DESIGN | `src/risk/portfolio.py:307-322` | `cluster_cap` = risk một trade (0,005) tính trên equity đầu ngày, còn sizing dùng equity hiện tại: sau bất kỳ khoản lãi trong ngày, candidate gần như dùng hết budget bị từ chối CLUSTER_CAP_REJECT dù sổ trống (ví dụ 600 USDT, +6 ⇒ XRP 3,03 > 3,00). |
| G-0102 | LOW | DESIGN | `src/risk/gating.py:122-200` | Size tính như thể khớp ở mép bất lợi của vùng, nhưng entry là một LIMIT ở giữa vùng nên fill đó không xảy ra: một trade Family A bị stop chỉ mất khoảng 60 % budget đã nêu (3,05 thay vì 5 USDT ở 1000), và R tính theo con số lớn hơn. |
| G-0103 | LOW | GAP | `src/core/strategy.py:680-782` | Core không kiểm tra stream 4h kết thúc ngay trước bar 1h được đánh giá: context cũ 90 ngày hay ở tương lai 8 giờ vẫn cho ra verdict regime. |
| G-0105 | LOW | DESIGN | `params/trend-pullback/research-run-1-a01.toml:65-140` | 48 set của research run mang cùng giá trị seed chưa kiểm chứng như baseline-v6 nhưng gắn nhãn EXPERIMENT thay vì PLACEHOLDER, nên gate từ chối PLACEHOLDER cho paper thấy 0 giá trị. |

### 6.3 Reconcile và SAFE_MODE

| ID | now | Lớp | Vị trí | Vấn đề |
|---|---|---|---|---|
| G-0500 | MEDIUM | DESIGN | `src/reconcile/loop.py:782-788` | Một tick so sánh với một divergence đã khóa SAFE_MODE bền vững, trong khi một trade khỏe vẫn đi qua các snapshot bị coi là divergence (fill trước khi stop được xác nhận, TP1 ack trước COMPLETE, GTD hết hạn...). D097 chỉ phủ một trường hợp. |
| G-0501 | MEDIUM | DESIGN | `src/reconcile/loop.py:597-604` | Một lần đọc thất bại (một trong ba GET mỗi 15 s, không retry) ⇒ SAFE_MODE API_DEGRADATION mà chỉ operator thoát được (khoảng 17.280 GET mỗi ngày). |
| G-0502 | LOW | DEFECT | `src/reconcile/safe_mode.py:525-538` | Khi ghi journal vào SAFE_MODE thất bại thì không lưu state; journal và state cùng một DB, nên SAFE_MODE vào lúc DB sập sẽ mất sau restart. |
| G-0503 | LOW | GAP | `scripts/demo_clear.py:81-126` | Script owner ghi thẳng `in_safe_mode False` vào log system-state, bỏ qua bảy điều kiện thoát; chỉ gắn với Demo bằng một biến môi trường và một câu gõ tay. |

### 6.4 Tiến trình live, scheduler, giám sát

| ID | now | Lớp | Vị trí | Vấn đề |
|---|---|---|---|---|
| G-0600 | LOW | DRIFT | `src/live/health.py:487-527` | Health verdict định kỳ không có consumer sau khi start: RED không chặn entry, không alert, trong khi D102 nói DEGRADED "blocks new entries once enabled". |
| G-0601 | LOW | DEFECT | `src/live/scheduler.py:229-279` | Một `CancelledError` thoát khỏi một task hủy cả 13 vòng scheduler, rồi `shutdown_in_order` re-raise trước bước shutdown nào: không journal, không held marker, không dừng có thứ tự. |
| G-0602 | LOW | GAP | `src/live/health.py:167-190` | Task giám sát lỗi ở mọi lần chạy (hoặc treo, trừ protection_step) chỉ tạo một dòng journal, không alert, heartbeat xanh, các health check reconcile vẫn pass từ báo cáo tốt cuối cùng. |
| G-0603 | LOW | DESIGN | `src/live/startup.py:1043-1049` | Bước BOT lỗi khi start (một lần gọi Telegram lỗi) chỉ là degrade, không thử lại: tiến trình chạy cả đời trong SAFE_MODE không polling, heartbeat xanh. |
| G-0604 | LOW | DESIGN | `src/live/wiring.py:1064-1071` | Tick reconcile bị bỏ qua cho mọi symbol chừng nào còn một placement task sống; không có giới hạn trên dù D097 nói "khoảng hai interval". |
| G-0607 | LOW | DRIFT | `src/live/wiring.py:684-761` | D099 nói mọi lần gọi store trên event loop đi qua StoreExecutor; thực tế protection, emergency close, placement manager, SAFE_MODE controller, operator command và scheduled cancel gọi store đồng bộ ngay trên loop. |
| G-2003 | LOW | DESIGN | `src/live/config.py:395-426` | Telegram là kênh duy nhất tới con người; heartbeat live chỉ kiểm vòng lặp còn sống và held marker, nên SAFE_MODE, vị thế trần hay Telegram hỏng đều giữ check ngoài host màu xanh. V4 hạ xuống vì cần nhiều lỗi cùng lúc mới mất trong im lặng. |

### 6.5 Sàn Binance và adapter

| ID | now | Lớp | Vị trí | Vấn đề |
|---|---|---|---|---|
| G-0700 | LOW | DESIGN | `src/adapters/binance_ratelimit_gate.py:334-393` | Một HTTP 418 không có Retry-After dùng được ⇒ khóa mọi REST 259.200 s (3 ngày), kể cả stop, cancel, emergency close và keepalive, dù body nói ban hết sau 2 phút; code dùng giờ trong body (D083) bị tắt vì `rest_gate.ban_end_clock_margin_ms` là NOT_CONFIGURED. V2 hạ xuống: có `rest_gate_cli clear --force` + restart, xác suất thấp, có alert. |
| G-0701 | LOW | DESIGN | `src/adapters/binance_usdm.py:894-906` | Bất kỳ 429 nào (kể cả từ một lần đọc), hoặc 400 với -1003/-1015, dừng mọi REST 120 s khi không có Retry-After: stop, cancel entry và emergency close bị từ chối trước khi gửi. |
| G-0702 | LOW | GAP | `src/adapters/binance_userdata_supervisor.py:405-411` | `request_resync()`, lối thoát duy nhất khỏi user-data stream bị halt, không có caller: sau 7 lần reconnect lỗi hoặc 120 s stream ở UNKNOWN tới khi restart, tiến trình vào SAFE_MODE chỉ operator thoát được. |
| G-0703 | LOW | GAP | `src/adapters/binance_userdata_events.py:807-819` | Trường tùy chọn gửi chuỗi rỗng (rm, act, V, pm, wt, ot, N, M, er) biến cả ALGO_UPDATE/ORDER_TRADE_UPDATE thành anomaly, nên xác nhận stop hay fill không được route; chỉ `ai` có quy tắc chuỗi rỗng (hình dạng wire chưa quan sát, SUSPICIOUS). |

### 6.6 Telegram, alert và operator

| ID | now | Lớp | Vị trí | Vấn đề |
|---|---|---|---|---|
| G-0802 | MEDIUM | GAP | `src/execution/confirm_flow.py:525-629` | Sau CONFIRM operator không bao giờ được báo trên Telegram lệnh ra sao: card đứng ở "handed to the execution step"; từ chối, ack, fill, stop đặt xong, thoát lệnh đều không có tin nhắn. |
| G-0803 | LOW | DEFECT | `src/execution/approval_desk.py:118-121` | APPROVE bị từ chối vì lý do có thể tự hết (ví dụ UNCERTAIN_ACCOUNT_STATE) làm request thành final và xóa nút trong khi approval vẫn PENDING: plan không thể duyệt, symbol bị chặn tới khi plan hết hạn. |
| G-0804 | LOW | GAP | `src/ops/alert_wording.py:257-420` | 13/23 sự kiện alert không có lời giải thích dễ hiểu, trong đó ba CRITICAL (UNPROTECTED_POSITION, PROTECTIVE_REJECTED, DAILY_STOP); alert chỉ in giờ UTC, không có dòng DEMO/LIVE. |
| G-2001 | LOW | DRIFT | `docs/operations/DEPLOY_GUIDE.vi.md:3-2771` | Hướng dẫn tiếng Việt cho owner là bản chụp 2026-10-09: nói live runtime chưa xây, lời khuyên khẩn cấp trước Phase 20, khẳng định stop luôn nằm trên sàn, không nhắc lệnh live nào. |
| G-2002 | LOW | GAP | `docs/operations/RUNBOOK.md:9-1066` | RUNBOOK không có mục cho phần lớn mã alert CRITICAL/HIGH (UNPROTECTED_POSITION, EMERGENCY_CLOSE_FAILED/NOT_SENT, PROTECTIVE_REJECTED, ENTRY_STATE_UNKNOWN, DAILY_STOP...), không phân loại mức khẩn, không nói gì về ngõ cụt CLOSE_FAILED. |
| G-2004 | LOW | DEFECT | `docs/operations/RUNBOOK.md:1182` | RUNBOOK 22.5 / `update.sh` bảo chỉ dừng live khi `/status` báo "protections: 0 open", nhưng `/status` đếm cả trade đã khớp và được bảo vệ, nên quy tắc chặn mọi lần dừng hay update cho tới khi mọi trade kết thúc. |
| G-2005 | LOW | GAP | `docs/operations/RUNBOOK.md:173-1104` | Quy trình khôi phục ban / REST-gate không chạy được như viết (thiếu dạng container, đường dẫn, phải dừng tiến trình), mâu thuẫn với alert ban, và không bảo owner tự bảo vệ vị thế trên giao diện Binance. |
| G-2006 | LOW | GAP | `deploy/restore.sh:72-97` | Restore và hướng dẫn rollback bỏ qua tiến trình live: không chặn khi live đang chạy, không cảnh báo DB khôi phục cũ hơn trạng thái sàn và volume livestate không được backup. |
| G-2007 | LOW | DESIGN | `docs/operations/RUNBOOK.md:1087` | `restart: "no"` được ghi là mặc định an toàn, nhưng restart không bao giờ đặt entry và chỉ tiến trình đang chạy mới bảo vệ fill (D079), nên host reboot ban đêm để entry khớp không có stop tới khi owner dậy. |
| G-2008 | LOW | GAP | `docs/operations/DEPLOY_GUIDE.vi.md:2243-2262` | Không có quy trình xoay vòng key hay xử lý lộ credential cho key Binance live, bot token live hay mật khẩu PostgreSQL (đổi `POSTGRES_PASSWORD` trong `.env` không đổi mật khẩu trong volume). |

### 6.7 Ops, deploy, bảo mật

| ID | now | Lớp | Vị trí | Vấn đề |
|---|---|---|---|---|
| G-1201 | LOW | GAP | `deploy/systemd/trading-backup.service:1-17` | Backup đêm thất bại chỉ thấy trong `systemctl status`/journalctl: không OnFailure, không alert, không probe tuổi snapshot. |
| G-1202 | LOW | DESIGN | `docker-compose.yml:252-302` | Backup chỉ gồm PostgreSQL và rawdata, mỗi ngày một lần: volume livestate (trạng thái REST gate, spill) và logs không bao giờ được backup; mất host có thể mất tới 24 h journal live; RPO không được ghi. |
| G-1203 | LOW | GAP | `docker-compose.yml:225-238` | Không gì ép "một tiến trình live" (D098): không lease hay advisory lock trong `src/live`; `deploy/compose-soak.sh` nhận `--profile live`, khởi động live thứ hai với cùng key `.env.live` nhưng DB và gate state riêng. |
| G-1752 | LOW | DESIGN | `src/adapters/binance_usdm.py:564-575` | Hạn chế của API key (không rút tiền, IP allowlist) không bao giờ được code kiểm tra: adapter bỏ `canWithdraw` có chủ ý, không đọc apiRestrictions; một key rò rỉ không hạn chế có thể mất cả số dư, trong khi mọi gate rủi ro chỉ giới hạn một trade ở khoảng 5 USDT. |

### 6.8 Nghiên cứu, backtest và paper

| ID | now | Lớp | Vị trí | Vấn đề |
|---|---|---|---|---|
| G-0901 (dup G-2101) | MEDIUM | GAP | `.planning/phases/16-paper-runtime-composition/evidence/16-63-run-output.txt` | Run 1 xong, không candidate nào qua được G1–G5, không file nào ghi kết luận; a01 = -0,1019 R trên 613 trade (mục 9). |
| G-0902 | MEDIUM | GAP | `src/research/run.py:377-383` | 240 record chỉ chứa trades digest; danh sách trade không được giữ; khoảng bootstrap G2 được tính ở mọi grid point rồi bỏ đi trước khi in. |
| G-0903 | MEDIUM | DESIGN | `src/analytics/killgate.py:428-454` | Kill gate chỉ đếm trạng thái family do con người chọn ghi; không ghi gì thì trả WITHIN_BUDGET ở bất kỳ ngày nào, dù ba family đã chạy. |
| G-0950 | LOW | DESIGN | `src/research/authorization.py:110-125` | Holdout "dùng một lần" chỉ được bảo vệ bằng quy trình: không code nào đọc/ghi `holdout_consumed.json`, không kiểm tra manifest sau dùng lại khoảng holdout, `strategy_version` mới là lineage mới được đánh giá lại cùng holdout. |
| G-0953 | LOW | GAP | `src/analytics/live_outcomes.py` | Kết quả live chỉ đóng khi fill của lệnh SL/TP1/TP2; close khẩn cấp, đóng tay hay thanh lý không đóng outcome nên các trade (thường tệ nhất) biến mất khỏi R live. |
| G-1700 | INFO | DESIGN | `src/execution/enablement.py:236-286` | `LiveEnablementController.enable` chấp nhận kill-gate WITHIN_BUDGET ("tiếp tục nghiên cứu"), có test ghim hành vi này; đường LIVE dự kiến không cần bằng chứng có edge. |
| G-2102 | LOW | DESIGN | `docs/research/RESEARCH_PROTOCOL.md:281-291` | Kiểm soát dương tính giả G3 chỉ phủ 48 giả thuyết của run 1; run hai trên cùng Validation (kết quả đã lộ trong evidence) bắt đầu với alpha mới; G5 chỉ cần mean > 0 và 30 trade (candidate không edge qua được khoảng một nửa số lần); v2.5.0 và v2.6.0 sửa sau khi số Validation đã in (2026-10-16). |
| G-1001 | MEDIUM | DEFECT | `src/paper/shadow_runtime.py:1062-1083` | Restore SHADOW replay phút 1m từ vị thế filled sớm nhất của mỗi symbol; poller giới hạn 20 trang × 1500 nên mọi lần start thất bại khi vị thế đó cũ hơn 20,83 ngày. |
| G-1002 | MEDIUM | DEFECT | `src/paper/shadow_ledger.py:1022-1199` | Restore ledger đọc mọi approval SHADOW trong DB, không lọc theo epoch đã pin, nên epoch mới trên cùng DB replay vị thế của epoch trước. |
| G-1003 | MEDIUM | DESIGN | `src/paper/coverage.py:318-711` | Health chỉ được chứng minh bằng bar 1h đóng đầu tiên sau start, nên mọi lần start/restart hơn 15 phút trước giờ đóng bar tạo khoảng không phủ vượt trần 900 s và làm hỏng trial. |
| G-1005 | MEDIUM | GAP | `src/paper/runtime.py:1696-1713` | Pin và RUNTIME_START ghi parameter set và cấu hình nhưng không ghi bản build code; evidence trial có thể đến từ nhiều image mà bundle không cho thấy. |
| G-1050 | LOW | GAP | `scripts/export_soak_evidence.py:391-418` | `analytics_evidence.json` của soak bundle được dựng từ một file JSON đưa tay, không kiểm tra chéo với journal hay parameter set, nhưng được niêm phong trong manifest như file dẫn xuất từ journal. |
| G-1051 | LOW | DESIGN | `src/live/stream_persistence.py:222-400` | Sự kiện user-data ghi DB thất bại bị bỏ hẳn: không retry, không sửa từ snapshot reconnect; `WriterStats.failures` không ai đọc; bảng orders/positions có thể cũ vô thời hạn. |
| G-1052 | MEDIUM | DESIGN | `src/live/signal_source.py:1-12` | Tiến trình live chỉ có nguồn signal của Demo smoke (LIVE không có producer nào); không phase nào (kể cả 25, 26) xây đường strategy → lệnh, nên Demo campaign chỉ chạy plan tổng hợp. |

### 6.9 Evidence, test, CI và công cụ

| ID | now | Lớp | Vị trí | Vấn đề |
|---|---|---|---|---|
| G-1300 | MEDIUM | DESIGN | `scripts/decision_alignment/ops_risk.py:57-398` | Gate decision-alignment là lint câu chữ docs (có/không có cụm từ); chỉ params, protocol hash và reason code chạm tới code; không gate nào phủ D076–D114. |
| G-1401 | MEDIUM | GAP | `.github/workflows/ci.yml:8-73` | CI chạy toàn suite tuần tự có PG với `timeout-minutes: 30`; dự án đo 24 phút cho 10.412 test, nay khoảng 18.300 test (×1,76), không có pytest-timeout, CI chỉ chạy trên master; không ghi kết quả CI ở đâu (SUSPICIOUS; owner phải kiểm GitHub Actions). |
| G-1501 | MEDIUM | GAP | `scripts/demo_rehearsal.py:584-606` | Evidence Demo smoke không có commit, cờ dirty hay hash cấu hình; hai lần 21/21 không gắn được với HEAD (code và limits đổi sau cả hai lần). V3 hạ xuống (lỗ hổng provenance, không ảnh hưởng runtime). |
| G-1502 | MEDIUM | GAP | `scripts/demo_rehearsal.py:2514-2538` | Evidence smoke chỉ giữ order id: không giá, quantity, cờ, filter hay echo từ sàn (`exchange_orders []`, `constraints {}`). |
| G-1503 | LOW | DESIGN | `.planning/phases/24-live-runtime-composition-demo/24-DEFERRED.md:9-78` | Các mục đóng "demo-observed" dựa trên smoke có signal tiêm vào, fill taker tức thì, SAFE_MODE gọi trực tiếp, restart có thứ tự và close bởi operator; stop/TP trigger, fill chờ/partial và emergency close chưa từng chạy. V3 hạ xuống: mỗi dòng chỉ nêu đúng bước đã quan sát. |
| G-1505 | LOW | DRIFT | `24-DEFERRED.md:21` | D056 được đóng là "enabled through the explicit DEGRADED flag" nhưng evidence bỏ step code và chi tiết health; HEALTH=OK cũng bao cả NO_TRADE. |
| G-1507 | LOW | GAP | `docs/DECISIONS.md:117-118` | Con số 886 ms làm cơ sở cho D114 không có trong file đã commit nào; bản sửa reread của D113 chỉ được chứng minh bằng một lần chạy không ghi việc reread; STATE.md bỏ qua lần chạy thất bại 2026-11-15. |
| G-1303 | LOW | DESIGN | `scripts/evaluate_demo_soak.py:740-769` | Id LIVE_PLACEMENT_OUTCOME xác định theo approval và journal insert ON CONFLICT DO NOTHING, nên lần gửi thứ hai cho cùng approval không bao giờ tạo dòng thứ hai: tiêu chí "duplicate entry" của soak không thể thấy lỗi chính nó cần bắt. |
| G-1400 | LOW | GAP | `tests/support/fake_binance_exchange.py:265-819` | Fake exchange mặc định không có lag đọc; lag chỉ được mô phỏng bằng wrapper trong 7 file test; lag position kéo dài hơn một lần đọc không được mô phỏng. V5 hạ xuống. |
| G-1902 | LOW | GAP | `src/backtest/exits.py:350-355` | Biên chạm đúng giá của stop trong backtest (`low <= trigger`) không được test nào ghim (đổi thành `<` vẫn pass 13 file test, kể cả golden). |

### 6.10 Quy trình, docs và trạng thái kế hoạch

| ID | now | Lớp | Vị trí | Vấn đề |
|---|---|---|---|---|
| G-1601 | LOW | DRIFT | `docs/trading/RISK_MANAGEMENT.md:115-125` | Docs nói DAILY_STOP hủy entry đang chờ "exactly as in live" nhưng `enforce_daily_state` không có caller; EXECUTION_SPEC và `config/execution/README` vẫn nói các key NOT_CONFIGURED / chưa ghép. |
| G-1603 | LOW | DESIGN | `.planning/phases/18-user-data-stream-error-taxonomy/decisions/18-DEC-O-18-01.md:8-14` | Mười discussion log chạy `--auto`, không câu hỏi nào tới owner; các lựa chọn tiền bạc (sizing mép bất lợi, slippage, ngưỡng, 418 = 3 ngày) chưa từng được trình bày kèm hậu quả; D072 ghi "DECIDED by the user" dù chỉ là một câu chấp nhận; Phase 25 Q-AB..Q-L trả lời bằng một dòng chung. |
| G-1604 | LOW | GAP | `.planning/ROADMAP.md:880-1292` | Success criteria được đóng "VERIFIED (library level)"; trong 18 tiêu chí kiểm bằng code cho Phases 16–24, 4 (22 %) không đúng trong tiến trình đã ghép; Phase 18 được tick Complete dựa trên một trong số đó. |
| G-1751 | LOW | DRIFT | `.planning/REQUIREMENTS.md:19-21` | DATA-02 (thu OI liên tục) và DATA-04 (diễn tập backup + restore PG) vẫn tick Complete mà không có evidence; các dòng trạng thái ROADMAP/STATE mâu thuẫn với DECISIONS. |
| G-2103 | LOW | DESIGN | `config/execution/execution-limits-v1.toml` | Các con số an toàn mang nhãn DECISION và cụm "the owner's choice" dù owner chấp nhận mặc định của trợ lý hàng loạt (D089: 14 limit trong một câu; D098–D106; D079–D083...) hoặc không được hỏi; không có ví dụ một giá trị sai tốn bao nhiêu USDT. |

---

## 7. Finding LOW và INFO

57 finding primary có severity mainnet LOW (46) hoặc INFO (11). Phần lớn là hygiene, drift của docs
hoặc lỗ hổng test nhỏ; vài mục (G-0108, G-2105, G-2106, G-2107) là đầu vào cho quyết định của owner.

| ID | now / mainnet | Lớp | Vị trí | Vấn đề |
|---|---|---|---|---|
| G-0104 | LOW / LOW | DEFECT | `src/core/strategy.py:81-92` | Gate nến đang hình thành trong core so `close_time` với close trước + duration; kline Binance đang hình thành mang close time dự kiến nên gate không phát hiện được (guard thật nằm ở upstream); test dùng dạng bar sàn không gửi. |
| G-0106 | LOW / LOW | GAP | `src/domain/registry.py:347-565` | Registry không có danh sách key bắt buộc hay kiểm khoảng cho key portfolio, daily-loss, utilisation, RR: set có `cluster_cap = -1` hay daily stop 100 % vẫn load. |
| G-0107 | LOW / LOW | GAP | `tests/test_domain_no_float.py:16-139` | Guard float liệt kê file bằng tay, bỏ sót `cost_rates.py`, `cost_guards.py`, `_decimal.py`, `lot_filters.py`, `transitions.py`, `live_commission.py`; không có guard wall-clock cho `src/core`. |
| G-0205 | LOW / LOW | IMPROVEMENT | `src/execution/manager.py:1390-1406` | Guard clock-drift chỉ chạy trong `place_entry`, sau consume và `mark_sent`, nên một PreSendRefusal làm mất approval dù không gửi gì. |
| G-0253 | LOW / LOW | GAP | `src/execution/manager.py:2758-2798` | Manual close kết luận flat từ hai lần đọc cách nhau vài mili giây; hàm được export như trình tự điều khiển khẩn cấp thủ công nhưng tiến trình không gọi. |
| G-0254 | LOW / LOW | DRIFT | `src/execution/manager.py:974-995` | Hai quy tắc min-notional khác nhau cho TP1 (pre-trade và attach); quy tắc pre-trade yếu hơn. |
| G-0303 | LOW / LOW | DEFECT | `src/execution/protection.py:1497-1511` | Trước lần poll REST đầu, bất kỳ fill nào cùng symbol và side (stop/TP của plan khác, fill mồ côi tới 60 s) bị coi là fill đầu của plan. |
| G-0304 | LOW / LOW | DEFECT | `src/execution/protection.py:2203-2237` | Stop trigger trước lần xác nhận REST đầu đọc NOT_ACTIVE, không "lost" cũng không "absent": plan chặn entry `max_unprotected_ms` rồi vào CLOSE_REQUIRED + SAFE_MODE dù vị thế đã flat. |
| G-0305 | LOW / LOW | DRIFT | `24-LIMITS-CHECKPOINT.md:27-34` | Lý do đưa cho owner cho 900.000 ms ("cho partial fill chậm thời gian hoàn tất") trái với code, vốn hủy phần còn lại ngay fill đầu. |
| G-0402 | LOW / LOW | DRIFT | `src/live/wiring.py:801` | ACCOUNT_UPDATE không làm mất hiệu lực nguồn equity hay day-loss; D084 và hai docstring nói có. |
| G-0605 | LOW / LOW | DEFECT | `src/live/runtime.py:196-229` | Held marker do một hold bị kill để lại không bao giờ bị xóa; lần start thành công sau của cùng container bị báo held mãi. |
| G-0704 | LOW / LOW | GAP | `src/adapters/binance_userdata_supervisor.py:594-598` | Hai đường làm mất một frame stream chỉ với một dòng log mà stream vẫn LIVE (exception trong vòng nhận SDK; except ngoài của `_on_raw_message`). |
| G-0805 | LOW / LOW | AMBIGUITY | `src/execution/approval_desk.py:478-481` | Card in tỷ lệ risk ở chỗ phần trăm ("Risk: 0.005" nghĩa là 0,5 %); nguồn signal live duy nhất luôn truyền exposure 0 và leverage từ cấu hình. |
| G-0806 | LOW / LOW | GAP | `src/live/wiring.py:1117-1122` | Card approval gửi thất bại bị bỏ: không retry, không alert, approval PENDING chặn symbol tới khi plan hết hạn. |
| G-0904 | LOW / LOW | DRIFT | `src/backtest/records.py:148-169` | TP được tính phí như limit chờ (slippage 1 bp) dù live đặt TAKE_PROFIT_MARKET trigger theo mark; stop cùng loại lệnh bị tính 3 bp. |
| G-0905 | LOW / LOW | AMBIGUITY | `src/backtest/report.py:545-558` | G4 (drawdown ≤ 20 % equity nghiên cứu) không có cách tính được định nghĩa: run in drawdown cộng dồn theo R qua bốn fold mỗi fold bắt đầu với equity 600. |
| G-0951 | LOW / LOW | GAP | `src/research/register.py:127-189` | `register.py` báo VALID với bất kỳ grid JSON nào caller đưa, không đối chiếu với run authorization đã commit. |
| G-0952 | LOW / LOW | DRIFT | `src/analytics/inputs.py:49-84` | Core metrics của analytics tính cả exit END_OF_DATA và SETTLEMENT và gộp mọi experiment; dashboard ra mean 0,225 R so với số khác của protocol trên cùng trade. |
| G-0954 | LOW / LOW | DESIGN | `src/analytics/excursion.py:204-232` | Cửa sổ MFE/MAE gồm cả phút vào và phút ra, nên giá trước fill và sau exit lọt vào excursion. |
| G-1004 | LOW / LOW | DEFECT | `src/paper/restart.py:172-174` | Một close giữa lúc pin và bar đầu được xử lý của một cặp không có record processed lẫn gap, nên tiêu chí "không thiếu dòng journal" thất bại. |
| G-1006 | LOW / LOW | DESIGN | `src/paper/market_inputs.py:186-212` | Bar được đánh giá với ledger SHADOW do minute poller ghi, trễ ít nhất 5 s sau close, nên exit ở phút cuối giờ chưa được ghi. |
| G-1007 | LOW / LOW | DEFECT | `src/paper/supervisor.py:337-614` | Bar live đóng bị giữ trong lúc recovery bị bỏ như duplicate khi backfill cùng lần recovery trả lại close đó, nên bar nhận live không bao giờ được đánh giá. |
| G-1008 | LOW / LOW | DESIGN | `src/paper/resync.py:300` | Row REST được coi là đã đóng theo đồng hồ host, độ lệch không có giới hạn: host nhanh lưu row đang hình thành, host chậm bỏ mọi bar live đã đóng. |
| G-1102 | LOW / LOW | DEFECT | `src/data/case_input.py:79-81` | Kiểm tra lỗ funding dùng dung sai 8 h + 60 s cho mọi chuỗi, nên lỡ một tick của chuỗi 4 h (hoặc 1 h) không bị phát hiện, trái docstring. |
| G-1205 | LOW / LOW | IMPROVEMENT | `src/ops/redaction.py:89-117` | Lớp redaction theo hình dạng bỏ sót nhiều dạng credential (18/28 lọt trong probe); việc che dựa vào lớp giá trị env/runtime, vốn bắt được các đường chính. |
| G-1206 | LOW / LOW | GAP | `deploy/bootstrap.sh:547-563` | Chỉ `.env` được kiểm mode 0600; `.env.live` (key Binance có quyền trade, bot token live), `.env.backup`, `.env.paper` không được kiểm. |
| G-1207 | INFO / LOW | IMPROVEMENT | `docker-compose.yml:59-75` | Collector, paper, live, backup, ops đều kết nối bằng superuser `POSTGRES_USER`. |
| G-1304 | LOW / LOW | DESIGN | `scripts/evaluate_trial_soak.py:150-161` | Bundle nguồn fixture (FAKE) đạt tiêu chí vẫn exit 0; proof class chỉ thêm một dòng chú thích. |
| G-1402 | LOW / LOW | GAP | `tests/test_core_tracer.py:378-410` | Guard import của `src/core` kiểm danh sách cố định 5 file và so theo root, để lọt `binance_sdk_*`, `httpx`, `websockets`, `telegram`, `psycopg`, `duckdb`, `socket`...; hôm nay vẫn sạch. |
| G-1504 | LOW / LOW | DEFECT | `scripts/demo_rehearsal.py:2729-2745` | `confirm_entry` ghi "no entry-time stop (D079)" mà không kiểm; mọi lần chạy ghi 1 algo order mở lúc ack. |
| G-1506 | LOW / LOW | DEFECT | `scripts/demo_rehearsal.py:2851-3097` | Poll cancel-lag bắt đầu sau khi plan đã FLAT nên chỉ có thể báo "không lag"; lại được dẫn để đóng 20D-35. |
| G-1600 | LOW / LOW | DRIFT | `.planning/STATE.md:665-680` | Bản ghi trạng thái kế hoạch mâu thuẫn với DECISIONS và với nhau (mục đã quyết vẫn OPEN, phase tick xong với verification human_needed, ROADMAP cũ). |
| G-1602 | LOW / LOW | DRIFT | `.planning/REQUIREMENTS.md:47-183` | BKTS-03 Complete trong khi `src/backtest/report.py:58` nói bootstrap "not computed (BKTS-03 pending)"; ghi chú EXEC-02 có trước Phase 24. |
| G-1701 | LOW / LOW | GAP | `23-VERIFICATION.md` | Báo cáo VERIFICATION của phases 20–23 được commit trước 7, 13, 1 và 9 commit src sau đó của cùng phase; phase 23 "passed" cho code mà quy tắc thời gian CONFIRM đã đổi sau. |
| G-1750 | LOW / LOW | DRIFT | `.github/workflows/research-gate.yml:76-140` | Hai check của research-gate (identity tuple, registry tripwire) vẫn không bao giờ fail được (sai tên file, key camelCase, JSON/YAML thay vì TOML), trong khi DOC_STATUS gọi đây là gate thực thi. |
| G-1901 | LOW / LOW | GAP | `src/execution/manager.py:450-456` | Kiểm `status == APPROVED` ở gate manager và gate confirm có thể bị xóa mà không unit test nào fail; chỉ mệnh đề WHERE của DB được ghim, bởi một test chỉ chạy với PG. |
| G-2000 | LOW / LOW | DEFECT | `24-OWNER-RUNBOOK.md:61-89` | Lệnh trong owner-runbook không chạy được như viết (`python` trần trong container, không có venv; G1 và RUNBOOK 21.3 cần uv/python trên host mà bootstrap không cài). |
| G-2009 | INFO / LOW | DRIFT | `docs/operations/DEMO_VS_MAINNET.md:53-89` | DVM-14 nói `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED` vẫn False, code để True từ D085. |
| G-2010 | INFO / LOW | GAP | `.planning/ROADMAP.md` | Gate go-live có 0 plan và thiếu điều kiện tiên quyết: LIVE không có đường enable, không có signal source ngoài injector Demo, canary cần owner bán thời gian theo dõi với 0 divergence. |
| G-2106 | LOW / LOW | DESIGN | `docs/DECISIONS.md` (D096) | Giới hạn tuổi last price nâng 5 s → 30 s vì sổ lệnh Demo ít biến động; giá trị dùng chung cho LIVE dựa trên khẳng định chưa đo về mainnet. |
| G-2107 | LOW / LOW | DESIGN | `docs/research/experiments/research-run-1-v2-3-0` | Mỗi family được đo qua cap danh mục PLACEHOLDER (tối đa 2 vị thế, tổng 1 %, cluster 0,5 %), nên nhiều signal bị loại trước khi được đánh giá (trend-pullback Development: 47.117 AGGREGATE_CAP_REJECT so với 171–570 trade mỗi điểm). |
| G-2200 | LOW / LOW | DRIFT | `src/domain/exchange_errors.py:265-285` | -1008 được docs ghi là biến thể HTTP 503, không phải mã body 400; SDK bỏ body 5xx nên loại SYSTEM_THROTTLED không bao giờ xảy ra và test mô hình sai transport. |
| G-2202 | LOW / LOW | DRIFT | `src/domain/exchange_errors.py:419-438` | Bảy khẳng định "chưa có tài liệu / chưa kiểm" thực ra đã có câu trả lời trong docs chính thức hiện tại; DVM-23 mâu thuẫn với code về -5040. |
| G-0108 | INFO / LOW | DESIGN | `src/risk/quantization.py:94-136` | Với 500 USDT và risk 0,5 %, BTCUSDT chỉ giao dịch được với stop khoảng 0,8–2,35 % (27/115 điểm grid); ở 1000 USDT là 72/115. |
| G-0404 | INFO / LOW | GAP | `src/risk/daily_loss.py:327-328` | Fill có phí trả bằng BNB làm day loss "unknown" tới hết ngày UTC (hệ thống ngừng trade); không gì kiểm cài đặt fee-burn của tài khoản. |
| G-0606 | INFO / LOW | DEFECT | `src/live/runtime.py:357-377` | Probe và hold khi từ chối admission dùng thư mục state tương đối theo cwd, còn tiến trình chạy neo cùng đường dẫn ở gốc repo. |
| G-0109 | INFO / INFO | IMPROVEMENT | `src/core/planner.py:689-700` | `invalidation_rule_json` mang `break_distance_atr` là khoảng cách giá chứ không phải bội số ATR, không code nào đọc, nhưng nằm trong plan hash. |
| G-0204 | INFO / INFO | DRIFT | `src/approval/confirm_core.py:285-287` | Token confirm/approve không đi theo nút bấm hay được so với lần bấm; hai docstring cũ. |
| G-0255 | INFO / INFO | DRIFT | `src/execution/execution_limits.py:3-9` | Docstring lỗi thời: bất kỳ số nguyên dương nào có nhãn kiểu DECISION đều load. |
| G-0256 | INFO / INFO | IMPROVEMENT | `src/execution/lot_filter_source.py:160-164` | Bảo đảm "không bao giờ dùng row lưu trữ cho entry" chỉ đúng vì không ai gọi nguồn này cho entry. |
| G-0306 | INFO / INFO | IMPROVEMENT | `src/execution/fill_monitor.py:150-290` | `fold_fills` và divergence ENTRY_WITHOUT_PROTECTIVE không có caller trong `src`. |
| G-0705 | INFO / INFO | DRIFT | `src/live/exchange.py:39` | Kiểu SDK `ConfigurationWebSocketStreams` được import ngoài `src/adapters` (`src/live/exchange.py:39`, `src/live/stream.py:47`); không type response SDK nào rời adapter. |
| G-1053 | INFO / INFO | DRIFT | `src/paper/shadow.py:31-33` | Docstring nói chưa có xác thực user-id SHADOW; code đã có. |
| G-1301 | LOW / INFO | GAP | `scripts/demo_clear.py:100-137` | `demo_clear` kiểm intent chưa giải quyết ở một connection riêng, rồi expire plan và tắt SAFE_MODE ở các lần gọi riêng, không kiểm tiến trình live đã dừng. |
| G-1605 | INFO / INFO | DRIFT | `docs/DECISIONS.md:117-118` | D113, D114 và RUNBOOK gọi evidence 2026-11-15 là untracked dù commit `55885b9` đã thêm nó. |
| G-1903 | INFO / INFO | IMPROVEMENT | `tests/test_execution_manager.py:4889-4915` | Phá slot in-flight theo symbol làm test treo thay vì fail (không có pytest-timeout). |
| G-2105 | INFO / INFO | DESIGN | `docs/trading/RISK_MANAGEMENT.md:11-13` | Ở risk 0,5 %, 1R = 2,5–5 USDT; BTC biên, canary 50–100 USDT của D040 không bao giờ trade được BTC; chi phí round-trip 15 % của 1R ở stop hẹp nhất; edge +0,10R trên 250 trade/năm là 62–125 USDT/năm, dưới chi phí host hợp lý (giả định, không từ repo). |

---

## 8. Đánh giá các quyết định

Mỗi lane có một bảng "Decision review"; mục này gộp lại, bỏ trùng. **Thước đo** (charter §2.7):
EX = hành vi thật của sàn (docs chính thức, SDK đã cài, quan sát Demo ghi rõ là Demo); AR = số học
và logic (probe có số); RP = thực hành quản trị rủi ro/nghiên cứu được chấp nhận; OG = mục tiêu của
owner. Một quyết định có thể SOUND về nguyên tắc nhưng DOUBTFUL ở con số hay cách triển khai; khi đó
nó xuất hiện ở cả hai bảng với phần tương ứng. Bảng đầy đủ: mục "Decision review" trong từng
`AUDIT\lanes\<lane>.md`.

### 8.1 SOUND — đứng vững

| Quyết định / quy tắc | Thước đo | Lý do ngắn | Lane |
|---|---|---|---|
| D001 không LLM trong đường ra quyết định | OG, RP | tái lập được; chính quy trình lập kế hoạch là do LLM làm, đó là điều audit này kiểm | X09 |
| D080 / quy tắc owner 2026-10-20: một placement không bao giờ gửi lại; mơ hồ ⇒ probe một lần ⇒ UNKNOWN + SAFE_MODE; `sdk_retries = 0` | EX, RP, OG | client id chỉ duy nhất giữa các lệnh đang mở; gửi lại có thể nhân đôi vị thế; mọi mutation phá quy tắc đều bị test giết (cho **entry**; cho close reduce-only xem 8.3) | M02, M07, X02, X06, X09 |
| Quantization floor → min qty → min notional → min utilisation, NO_TRADE thay vì làm tròn lên (D031) | AR | probe: rủi ro thực tế/cho phép tối đa 0,999997 trên mọi case; mọi bước được ghim bởi test | M01, X02, X09 |
| D046 mục 1: chi phí = quote trên mỗi đơn vị, hai chân entry và stop; D036 phí taker cho entry | AR, RP | đúng đơn vị; bảo thủ (phóng đại chi phí, không bao giờ đánh thấp) | M01, M09, X07 |
| D037 trigger theo MARK_PRICE, backtest dùng cùng chuỗi mark | EX, RP | tránh râu nến last price; stop và liquidation cùng chuỗi tham chiếu | X10, X06, X07, X09 |
| D052 simulator nhân quả (kích hoạt từ bar N+1, trade-through một tick, stop-first) | RP, probe | bảo thủ ở mọi chỗ mơ hồ; probe xác nhận không look-ahead | M09, M09b, X09 |
| D032/D043 ngưỡng đăng ký trước, G1 100/30, Holm một lần trên 48 (D069) | RP, AR | thông thường và chặt; sức mạnh thống kê đủ ở số trade đạt được (140–613) | M09, X09 |
| D013/D030 kill gate (3 family + 6 tháng + không family nào qua) | RP | ngăn tối ưu vô tận (nhưng xem 8.2: chỉ đếm trạng thái được ghi tay) | X09 |
| D039/D049 universe point-in-time có symbol đã delist | RP | loại survivorship bias | M11, X07, X09 |
| D070 settlement symbol delist ở biên bất lợi | AR | biên chứng minh được chứa quy tắc settlement | M09b, X09 |
| D-14 dấu funding, ghi theo fundingTime, cửa sổ nửa mở; D-18 equity chỉ tính realized | EX, probe | dấu và quy thuộc kiểm bằng số; ledger khớp chính xác | M09b |
| D034 SAFE_MODE chỉ chặn entry; không stop ⇒ close | RP, OG | hành động bảo vệ không bao giờ bị chặn vì vắng operator | X09, X07 |
| D035/D085 ISOLATED 5x, liquidation ngoài SL + buffer 300 bps | AR | notional tối đa ≈ 0,54 × equity; liquidation cách ≈ 19,5 %; buffer hiếm khi chặn, phía an toàn | M04, X09 |
| D086 equity = min(wallet, margin balance); từ chối multi-asset và hedge mode | RP | lãi chưa thực hiện không bao giờ làm tăng size | M04, X09 |
| D084/D087 tuổi equity 15 s, tuổi daily-loss 300 s | AR | input cũ ⇒ NO_TRADE; equity được đọc lại ở mọi placement | M04, X09 |
| D041 APPROVE rồi CONFIRM trong 60 s, gắn với user | OG, RP | chống bấm nhầm; card dựng lại từ khối tiền đã lưu | M02, M08, M10b |
| Phase 23 D-01/D-02: chat gate + allow-list user + private chat; callback_data 36 byte không chứa token | EX (từ trí nhớ, core.telegram.org 403), OG | hai gate độc lập, bắt buộc ở mọi điểm vào; mutation bị giết | M08, X02 |
| D072 (5): phân loại lỗi theo (lớp SDK, mã int, loại call), không theo text; mã lạ ⇒ UNKNOWN | EX (SDK) | text có thể đổi; mọi câu trả lời lạ rơi về phía mơ hồ (nhưng bảng thiếu mã, G-2203) | M07, X10 |
| D072 (4): chỉ trạng thái algo NEW mới xác nhận bảo vệ | EX | cách đọc chặt nhất tài liệu ALGO_UPDATE | M07, X10 |
| D072 (1): drift 500 ms/1000 ms, recvWindow 5000 | EX, AR | nằm trong cửa sổ sàn với biên dư | M07, X10 |
| D051/EXECUTION_SPEC §7.1: sàn không dedupe; intent đã lưu là guard | EX | đọc đúng quy tắc "unique among open orders" | X10 |
| GTD với `min_remaining_validity_seconds = 900`, không dựa vào GTD hết hạn | EX | 300 s dư so với sàn 600 s; hết hạn GTD coi là chưa chứng minh | M02, X10 |
| D051(d) consume approval cùng transaction với ENTRY intent; READ COMMITTED + unique index làm trọng tài | RP | ràng buộc DB quyết định, không phải mức isolation | M11, X06 |
| NUMERIC(38,18) + từ chối thay vì làm tròn; DB timeout 3/5/10 s, không retry | AR, fail closed | không làm tròn ngầm; chờ có giới hạn | M11 |
| D-04/D-13 Parquet theo ngày bất biến, chỉ publish ngày UTC đã đóng; CR-02 resume theo store | RP | dữ liệu thô hash được, không đóng băng nến đang hình thành | M11 |
| D-04/D-05 parameter set khóa hash, không sửa tại chỗ | probe | 73/73 set khớp pin; không file nào bị sửa sau audit trước | X04 |
| D094 stream trước tick reconcile đầu; D-08 thứ tự start | logic, probe | restart có vị thế chưa bảo vệ kết thúc được bảo vệ ở tick đầu (X01 P1) | M05, M06, X01 |
| D-02 không hủy/đóng thứ hệ thống không chứng minh được là của mình | RP | hủy nhầm lệnh của người tệ hơn một alert | M05, X01 |
| D104 bộ lệnh operator; lệnh tăng rủi ro cần bước hai, không có lệnh enable | RP | không lệnh nào tăng rủi ro | M06, X09 |
| D092 kill gate Demo = WITHIN_BUDGET, chỉ cho DEMO | logic | `enable_demo` từ chối mọi mode khác | M06, X05, X07 |
| D110 entry không khôi phục được bị hủy một lần; D111/D114 stall watchdog chỉ quan sát | RP | đóng một đường fill trần sau restart; không hủy là đúng với quy tắc không gửi lại | X09, M06 |
| `TRADING_CI_STRICT=1`; xfail twin strict được đăng ký; Demo scenario chỉ owner chạy | RP | chống skip im lặng trong CI; lỗi đã biết luôn hiển thị | X03 |
| Bí mật chỉ trong env file, tách theo service; image ghim digest; container non-root | RP | collector không giữ key trade, bot token hay secret backup | M12 |
| Công cụ Demo: dry run mặc định, `--execute` cần TTY + câu gõ đúng, không tùy chọn host | RP | guard nằm trong code ở điểm dựng client duy nhất | M13 |
| D061 mục D (paper exit) như một trial "plumbing"; D-12/L-12 chỉ Mode.SHADOW trong code paper | logic | chứng minh tái lập; không có đường lệnh từ SHADOW (nhãn "parity" thì DOUBTFUL, xem 8.2) | M10, M10b |

### 8.2 DOUBTFUL — đáng ngờ

| Quyết định / quy tắc | Thước đo | Vấn đề | Finding / lane |
|---|---|---|---|
| D042 điều kiện (1) "SL luôn nằm trên sàn" | AR, logic | sai từ D079 | G-2100 (X09) |
| D055/D079 stop chỉ đặt sau fill; model (b) không xây, lý do từ chối không được ghi | EX, AR | tiền đề -4509 chỉ đúng cho `closePosition`; rủi ro outage chưa được so. Lane M03 xét riêng phần "không đặt stop không reduce-only bên cạnh entry" là SOUND | G-2100, G-2201 (X09, X10) |
| D106 `restart: "no"` cho live, "mặc định an toàn" | AR, logic | kéo cửa sổ outage của G-2100 từ giây thành giờ; điều kiện bật (một lần Demo sạch) đã đạt | G-2007 (X01, X05, X08, X09) |
| D-08/D-03 các lớp HOLD và `--hold-on-refusal` | logic, OG | đúng cho entry; sai cho tài khoản có thể giữ vị thế không stop, vì hold cũng giữ lại việc bảo vệ và không thử lại | G-1800 (X01) |
| D077 như được triển khai: một lần đọc by-id quyết định đóng thị trường; cross-check listing tắt có chủ ý | EX, RP | nguyên tắc "không đặt lại stop đã mất" thì bảo vệ được; quyết định dựa trên một lần đọc của endpoint đã trả sai ba lần thì không | G-0250/G-2104 (M02b, X09) |
| Hai lần đọc position 0 = flat (T-8-30) | EX | hai lần đọc sát nhau, không độc lập | G-0300 (M03) |
| D113 ba lần reread 0,5 s chỉ cho bước TP | EX | con số mượn, không đo; bản sửa đặt ở đường có hậu quả nhẹ | G-0250, G-0251 (M02b, X09) |
| "Attach chạy đúng một lần" và D080 cho TP leg (không probe) | logic | đúng sau POST, sai cho hold trước POST; TP mơ hồ không được đọc lại | G-0251, G-0252 (M02b) |
| O-03: áp MIN_NOTIONAL cho TP1 reduce-only, không có fallback một TP | EX (-4164 "unless you choose reduce only") | chặt hơn không có nghĩa an toàn hơn: sau fill là SAFE_MODE không TP | G-0302, G-0254 (M02b, M03) |
| D079 mục: fill đầu hủy phần còn lại của entry | AR, OG | biến partial fill thành TP_UNAVAILABLE + SAFE_MODE | G-0302 (M03) |
| D089 `max_unprotected_ms` 180 s, `entry_terminal_timeout_ms` 15 phút (lý do ghi lại là sai) | AR | suy từ pause 429 120 s, không từ rủi ro giá; lý do 15 phút mâu thuẫn với code | G-0305, R-04 (M03, X09) |
| D089 như một quy trình (14 limit trong một câu) | AR | giá trị hợp lý nhưng chấp nhận hàng loạt | G-2103 (X09) |
| D072 (1) 418 không Retry-After = 259.200 s; D083 xây nhưng tắt | EX | 3 ngày là ban **tối đa** đã công bố; fallback là đường có khả năng nhất ở 418 thật đầu tiên | G-0700 (M07, X10) |
| D072 (6) + D081 Q4: 429 dừng mọi REST kể cả stop/cancel/close, 120 s | EX, RP | gấp đôi cửa sổ weight một phút, chặn cả lệnh giảm rủi ro | G-0701 (M07) |
| Stream halt chờ `request_resync()` thủ công | OG | mỗi outage hơn 2 phút cần owner | G-0702 (M07) |
| D-03 mọi divergence ⇒ SAFE_MODE ngay; D-15 chỉ operator thoát (cho lý do điều kiện) | logic, OG | trade khỏe tạo divergence vài giây; một lần đọc lỗi khóa hệ thống | G-0500, G-0501 (M05) |
| D097 bỏ tick reconcile khi placement đang chạy | logic | che toàn bộ so sánh, không giới hạn trên | G-0604 (M05, M06) |
| D102 phần LIVE (enable thủ công, health gate sau enable) | logic | đường enable LIVE không tồn tại; health gate sau enable không được xây | G-0600 (M06, X05) |
| D033 daily stop 1 % chỉ tính trade đã đóng | AR, RP | ngày có thể kết thúc gần 2 %; stop lúc 23:55 UTC hết hiệu lực lúc 00:00 UTC | R-15 (M04) |
| D033 hai equity + `cluster_cap` = `risk_rate` | AR | từ chối trade sau ngày lãi | G-0101 (M01, M04: WRONG như một tổ hợp) |
| D046 mục 2: size ở mép bất lợi của vùng ("fill ở bất kỳ đâu trong vùng") | AR | entry là một LIMIT ở giữa; rủi ro thật thấp hơn budget 39–41 % (Family A); D046 tự ghi "quyết định trong lần chạy không giám sát" | G-0102 (M01) |
| `minimum_risk_utilization_after_rounding` 0,6 gắn nhãn STRUCTURAL | AR | là số được chọn, không phải sự thật cấu trúc | M01, X09 |
| `cluster_cap` = risk một trade; cluster cứng BTC/ETH/SOL/XRP | RP | 8/12 symbol nghiên cứu ngoài cluster (KNOWN F-908) | M01 |
| Nhãn EXPERIMENT cho giá trị không có cơ sở (16-DEC-O-02) | logic | nhãn mà gate paper đọc đã đổi, giá trị thì không | G-0105 (M01) |
| D-02 closed-candle bên trong core | EX | core không nhận diện được kline Binance đang hình thành | G-0104 (M01) |
| D046 slippage 1 bp / 3 bps | EX | chưa hiệu chỉnh trên fill thật; TP dùng mức nhỏ hơn | G-0904 (M09, X09) |
| G4 20 % equity nghiên cứu | logic | cách quy đổi từ bốn fold riêng chưa định nghĩa | G-0905 (M09) |
| D013/D030 kill gate cần trạng thái được ghi tay | logic, probe | không ai ghi thì không bao giờ kích hoạt | G-0903 (M09) |
| L-03/L-10 "chỉ báo cáo, không xếp hạng"; record chỉ giữ digest | OG, protocol §4 | giữ run trung lập nhưng cũng giữ kết luận không được nói ra; không tính lại được gì | G-0901, G-0902 (M09) |
| Protocol §4 khóa holdout theo lineage | RP | version mới = lineage mới, dùng lại holdout không giới hạn | G-0950 (M09b) |
| D057/D060 G5 cần 30 trade holdout | RP, AR | là sàn số lượng, không phải phép kiểm định | G-2102 (X09) |
| D082 sở hữu symbol chỉ kiểm ở reconcile | logic | phát hiện sau sự việc | X09 |
| D096 tuổi last price 5 s → 30 s cho cả LIVE | EX | dựa trên khẳng định chưa đo về mainnet | G-2106 (X09) |
| D078 vượt approved thì **từ chối** thay vì clip | AR, OG | không giảm rủi ro, chỉ mất trade | G-0202 (M02) |
| D051(c) plan hash không gồm symbol/side/quantity | logic | đã được bù bằng signal_id, Signal lưu, kiểm hình học, quantity trên approval; không tìm thấy đường vượt | M02 |
| D-23 dedupe 300 s theo (event, subject, reason) bất kể đã giao; ngân sách 3 lần / 30 s cho CRITICAL | RP | key bỏ qua plan và trạng thái giao; ngân sách cho tin nhắn lịch sự, không cho alert an toàn | G-0801 (M08) |
| Danh sách lý do từ chối "chữa được" của APPROVE quá ngắn | logic | xem G-0803 | M08 |
| D106 Q11: heartbeat = tem vòng lặp còn sống; D104 Telegram là kênh duy nhất | OG | xanh khi SAFE_MODE, vị thế trần, Telegram hỏng | G-2003 (X08) |
| D040 / Phase 26 tiêu chí 5: canary "operator theo dõi", 0 divergence | OG | owner bán thời gian không theo dõi trọn trade 4H/1H; 0 divergence có thể không đạt được (G-0500) | G-2010 (X08) |
| D098 một tiến trình live | RP | nêu thành quy tắc, không gì ép | G-1203 (M12) |
| Backup: chỉ trạng thái systemd khi thất bại; một lần/ngày cho journal live | OG, RP | owner không xem console mỗi ngày; RPO 24 h chưa được tính | G-1201, G-1202 (M12) |
| D-05 drill bằng fault giả qua `src/ops/drills.py` | RP | chứng minh đường code, không chứng minh quy trình trên host | M12 |
| D-21 / OPS-02 hạn chế key chỉ bằng cam kết của owner | OG, AR | key không hạn chế là lỗi duy nhất có thể mất toàn bộ số dư | G-1752 (X07) |
| D061 mục D (paper exit không so chi phí/fill thực tế với mô hình) | RP | thu hẹp F-023; bằng chứng edge chỉ còn run 1 | X07 |
| `LiveEnablementController.enable` nhận WITHIN_BUDGET | RP, OG | WITHIN_BUDGET là "tiếp tục nghiên cứu", không phải bằng chứng edge | G-1700 (X06) |
| D-25/F-603 fake exchange có nhãn provenance nhưng mặc định không lag | EX | ngược với Demo đã thấy | G-1400 (X03) |
| CI chỉ trên master, job test 30 phút | AR | suite ×1,76 từ lần đo 24 phút | G-1401 (X03) |
| AGENTS.md "Invariants machine-enforced" | code | đúng cho backtest/analytics/live, chỉ một phần cho core/risk | G-1402, G-0107 (X03, M01) |
| `verify_decision_alignment.py` như gate docs↔code | probe | chỉ là lint câu chữ | G-1300 (M13) |
| Soak Demo đánh giá chỉ từ journal, cửa sổ = dòng đầu..cuối | RP (D061/D063) | không có tiêu chí coverage | G-1302 (M13) |
| Phân tách Demo/LIVE cho database chỉ bằng env | logic | host sàn được code ràng buộc, DB thì không | G-0503, G-1301 (M13) |
| Smoke 21/21 là bằng chứng Phase 24; nhãn "demo-observed"; schema evidence không có code identity | RP | tên bước bị coi như hành vi đã chứng minh | G-1501..G-1506 (X04) |
| D-35 lệch đồng hồ chỉ ghi log; O-07 trần 900 s; 16-DEC-EQUITY-BASE | AR | xem G-1008, G-1003, G-1006 | M10 |
| 16-30 analytics từ file đưa tay; 24-19 stream persistence không retry; 24-01 Q4 chỉ nguồn signal smoke | RP | G-1050, G-1051, G-1052 | M10b |
| D-36 lỗ funding 8 h + 60 s cho mọi chuỗi | EX, probe | che lỡ tick của chuỗi 4 h/1 h | G-1102 (M11) |
| Journal append-only bằng trigger trong khi app kết nối là owner bảng | PG privilege model | owner có thể `DISABLE TRIGGER` (KNOWN tới Phase 26) | M11 |
| D072 "DECIDED by the user"; Phase 25 trả lời một dòng; D113/D114 ghi evidence | record vs source | nhãn không khớp nguồn | G-1603, G-1605 (X05) |
| Fill attribution theo symbol + side khi chưa biết order id | logic | G-0303 | M03 |
| Restart khi lịch sử stop không rõ ⇒ đóng thị trường dù stop ACTIVE | EX | đọc stop theo id sẽ trả lời được | M03 |

### 8.3 WRONG — sai

| Quyết định / quy tắc | Thước đo | Lý do | Finding / lane |
|---|---|---|---|
| D080 áp dụng cho **emergency close** (close reduce-only mơ hồ không bao giờ được gửi lại) | EX, AR | một close reduce-only trùng không thể mở hay đảo vị thế; close thiếu để vị thế không bảo vệ vô thời hạn. Quy tắc chép từ entry sang một lệnh có rủi ro ngược lại (X10 và X01 đánh giá DOUBTFUL cùng ý) | G-0301, G-2203, G-1801 (M03) |
| 24-DEFERRED 20D-01 "CLOSED [DESIGN]" (fills ledger) | trace tĩnh | không có writer production cho `fills` | G-1101 (M11) |
| Quy ước "VERIFIED (library level)" dùng để đóng success criterion của ROADMAP | kết quả trong tiến trình ghép | 4/18 không đúng trong tiến trình chạy | G-1604 (X05) |
| D099 "mọi store call trên loop đi qua StoreExecutor" (như được viết) | code | sai cho protection, close, placement, SAFE_MODE, operator | G-0607 (M06) |
| Sizing theo equity hiện tại + cap theo equity đầu ngày + `cluster_cap` = `risk_rate` (như một tổ hợp) | AR (probe) | từ chối trade trên sổ trống sau ngày lãi | G-0101/G-0400 (M04) |
| Live-minute page cap 20 × 1500 ("ratify current") | AR (probe) | sai cho soak dài hơn 20,8 ngày | G-1001 (M10) |
| Soak `duplicate_entry` từ dòng LIVE_PLACEMENT_OUTCOME | logic | id xác định + ON CONFLICT DO NOTHING: lỗi chính không thể tạo dòng thứ hai | G-1303 (M13) |
| RUNBOOK 22.5 "chờ tới khi protections: 0 open" | code | đếm cả trade đã được bảo vệ | G-2004 (X08) |
| WR-C6 / R-02 để mở như "quyết định owner, plan sau" trước mainnet | OG | một vấn đề an toàn bị đóng bằng cách gắn nhãn owner | G-0801 (M08) |
| "-1008 dưới HTTP 400 là SYSTEM_THROTTLED" (quick task 261020-g1a) | EX (docs + SDK) | -1008 đến dưới HTTP 503; kết quả an toàn không đổi | G-2200 (X10) |
| AGENTS.md "`*_pg.py` (26 file)" | đếm file | 41 file `*_pg.py` + 9 file khác có case PG; vô hại | X03 |

### 8.4 CANNOT_JUDGE (các lane không đủ căn cứ để kết luận)

D005/D006/D011 (4H/1H, entry vùng limit: hợp với owner bán thời gian trên giấy, chưa đo khả năng trả
lời alert); D054 (hình học TP theo cấu trúc, giá trị phụ thuộc kết quả run 1); D107; `reconcile.tick_interval_ms`
15000; `constraint_snapshot_ttl_seconds` 3600; headroom 200 lệnh điều kiện "account-wide" (code tự ghi
"re-verify before wiring"); `max_cost_to_risk` 0,15 (công thức đúng, giá trị là câu hỏi nghiên cứu);
`minimum_rr` 2,0; D-11 stop không đổi sau TP1; chính sách funding `TRADES_WITH_UNVERIFIED_FUNDING`
(M04 CANNOT_JUDGE, X09 SOUND ở quy mô này); các quy tắc TELEGRAM.md (core.telegram.org trả 403);
D113 từ evidence (một mẫu không ghi việc reread).

**Nhận xét chung.** Phần lớn các quyết định về nguyên tắc an toàn (không gửi lại entry, làm tròn
xuống, SAFE_MODE chỉ chặn entry, mark price, simulator nhân quả, ngưỡng nghiên cứu đăng ký trước) đứng
vững theo cả bốn thước đo. Các quyết định đáng ngờ tập trung ở ba chỗ: (1) những con số được nhận
mặc định hàng loạt (D089, D072, D046 slippage) mà không có ví dụ USDT; (2) các quy tắc "một lần đọc
là đủ" hoặc "một sự kiện là khóa hệ thống" (D077, D-03, G-0300); (3) cách đóng mục và gắn nhãn trong
`.planning` (library level, demo-observed, DECIDED by the user).

---

## 9. Kết quả nghiên cứu

### 9.1 Run 1 ở simulator 2.3.0 (G-0901, primary; duplicate G-2101)

Lane X09 nêu vấn đề (G-2101); lane M09 được giao đánh giá **độc lập** và tính lại từ file đã commit
(G-0901 là bản ghi primary). Phương pháp của M09: 240 record trong
`docs/research/experiments/research-run-1-v2-3-0/` chỉ chứa định danh và trades digest, không có
trade, R hay mean nào; danh sách trade từng nằm trong thư mục checkpoint `C:\rerun-v230\ck\<family>`,
nay không còn. Số liệu duy nhất theo từng candidate là các dòng `feasibility` và `plateau point` trong
`.planning/phases/16-paper-runtime-composition/evidence/16-63-run-output.txt` (file text "viết sau từ
log", không gắn hash với record). M09 trace trong code rằng `mean_r` in ra chính là thống kê của vế
một G2: mean net R mỗi trade trên bốn fold Validation gộp, chỉ trade đã đóng, sau chi phí
(`src/research/run.py:762-786`, `src/backtest/report.py:606-676`).

| Gate | Quyết định được từ số đã commit? | Kết quả (48 candidate = 3 family × 16 điểm grid) |
|---|---|---|
| G1 (≥ 100 gộp, ≥ 30 mỗi fold) | Có, chính xác | 45 qua; 3 trượt: b04, b08, b16 |
| G2 vế 1 (mean R gộp > 0) | Có, chính xác | **45 trượt** (mean từ -0,2324 tới -0,0106 R); 3 dương: a05 +0,0027, b12 +0,0007, b16 +0,0137 |
| G2 vế 2 (cận dưới bootstrap khối 95 % > 0) | **Không** (không có danh sách trade) | chỉ chặn được bằng dựng hình: SE iid 0,055 / 0,140 / 0,146; chuỗi hai điểm khớp n, số thắng/thua, mean, std cho cận dưới -0,030 / -0,072 / -0,065 ngay cả ở thứ tự thuận lợi nhất; trượt ở mọi thứ tự đã thử |
| G3 (Holm trên 48, p hiệu chỉnh < 0,05) | Không (không có bộ sinh p-value) | cần p thô nhỏ nhất < 0,00104; p thuận lợi nhất tìm được là 0,38; không candidate nào qua được |
| G4 (drawdown ≤ 20 % equity) | Không chính xác (con số in theo R, gate theo %) | 20 % ≈ 40–67 R; a01 ở 78,3 R nằm trên khoảng; 29 candidate không xác định được |
| G5 (holdout) | Không chạy, đúng quy trình | `holdout_consumed.json` rỗng; holdout (từ 2026-05-10) còn sạch |

**Kết luận của M09 theo phép hội G1 ∧ G2 ∧ G3 ∧ G4 ∧ G5:**

- 45/48: TRƯỢT chắc chắn chỉ vì vế 1 của G2 (mean Validation gộp âm).
- b16: TRƯỢT chắc chắn ở G1 (fold 2 có 23 trade).
- a05 và b12: dương 0,003 R và 0,0007 R; trượt G2 vế 2 và G3 với độ tin cậy rất cao, nhưng "chắc
  chắn" thì cần danh sách trade. Vì vậy finding ghi CONFIRMED cho 46/48, PROBABLE cho a05 và b12.
- **Candidate paper/Demo a01** (`16-DEC-candidate.md`): n = 613, mean **-0,1019 R**, std 1,103, 137
  thắng / 476 thua, drawdown quan sát 78,3 R. Trượt G2 vế 1, chắc chắn. Cùng điểm này ở run trước
  (2.1.0) in -0,1104 R trên 343 trade; bản ghi chỉ định a01 được commit 13 phút sau output đó. Việc
  chọn a01 không dựa trên kết quả (đó là điểm đăng ký đầu tiên với giá trị seed), nên không có
  cherry-picking; vấn đề ngược lại là không ai ghi kết quả.
- Không file nào ghi kết luận: `docs/research/kill_gate_decisions.json` có `"families": []`;
  không code nào tính G2–G4 (`src/analytics/gates.py` vẫn ghi "Numeric acceptance thresholds remain
  TBD"; KNOWN G3-004).

**Các phát biểu bị nói quá mà M09 đã sửa (từ G-2101):**

- "a01 có mean âm có ý nghĩa thống kê (z = -2,29)": **nói quá**. -2,29 là z iid, không hiệu chỉnh
  phụ thuộc hay đa kiểm định; protocol không có gate kiểm định "âm có ý nghĩa"; khoảng bootstrap khối
  của a01 không tính được từ file đã commit. Phát biểu đứng được: mean âm, đủ để trượt G2.
- "Không có verdict kill-gate nào được ghi": đúng về sự kiện, nhưng (1) theo D013/D030 kill gate không
  thể kích hoạt trước 2027-03-19 (sáu tháng sau ngày đóng băng 2026-09-19), nên WITHIN_BUDGET là trạng
  thái quy tắc cho hôm nay; (2) cái thiếu là trạng thái G1–G5 theo family của một run đã xong, đúng như
  protocol yêu cầu ("computed from G1–G5 ... and recorded with a decision reference").
- "Hai trong ba điều kiện D013 đã đạt trên thực tế": **một phần**. "Không family nào có quyết định
  pass được ghi" là đúng; "ba family đã được test" đúng về thực chất, nhưng file mà evaluator đọc không
  liệt kê family nào, nên evaluator sẽ báo 0 family đã test.

**Giới hạn của kết luận.** Đây là kết quả theo quy tắc đăng ký trước của chính dự án, không phải dự báo
lợi nhuận tương lai (charter §6: chỉ xét phương pháp). Khoảng bootstrap thật không tính lại được vì
danh sách trade không còn (tái tạo cần khoảng 25 giờ mô phỏng: 4,7 h + 12,5 h + 7,9 h, trên dữ liệu thô
cũng không được commit). Các số liệu được lấy từ một file text không gắn hash với record. Không có
tiền nào đang chịu rủi ro vì kết quả này ở trạng thái hiện tại.

### 9.2 Các finding nghiên cứu liên quan

- **G-0902** (MEDIUM): record chỉ giữ digest; khoảng bootstrap được tính rồi bỏ đi. Đây là lý do 9.1
  có giới hạn.
- **G-0903** (MEDIUM): kill gate chỉ đếm trạng thái được ghi tay ⇒ WITHIN_BUDGET mãi mãi nếu không ai ghi.
- **G-1700** (INFO / mainnet MEDIUM): enable LIVE dự kiến chấp nhận WITHIN_BUDGET, có test ghim. Ví
  dụ của X06: 100 trade live ở -0,10 R với 1R = 5 USDT mất khoảng 50 USDT trước chi phí chạy, kill gate
  vẫn đọc WITHIN_BUDGET.
- **G-2102** (LOW / mainnet MEDIUM): kiểm soát đa kiểm định chỉ trong run 1; run hai trên cùng
  Validation không được kiểm soát; G5 chỉ là sàn 30 trade; v2.5.0 và v2.6.0 sửa sau khi số Validation
  đã in.
- **G-2107** (LOW): family được đo qua cap danh mục PLACEHOLDER, nhiều signal bị loại trước khi đánh giá.
- **G-0950, G-0951, G-0952, G-0954, G-0904, G-0905**: holdout chỉ được bảo vệ bằng quy trình, register
  không kiểm grid, dashboard dùng tập trade khác protocol, MFE/MAE gồm giá ngoài thời gian giữ lệnh,
  slippage TP 1 bp, G4 chưa định nghĩa.
- **G-2105** (INFO): ở 500–1000 USDT, 1R = 2,5–5 USDT; một edge +0,10 R trên 250 trade/năm là
  62–125 USDT/năm, dưới chi phí host hợp lý (giả định của lane, không từ repo).

Điều vẫn đứng vững (M09, M09b, X04, X09): simulator nhân quả và tất định (byte-identical qua ba
interpreter và ba `PYTHONHASHSEED`), không look-ahead, holdout chưa bị chạm, 480 `experiment_id` tái lập
được, run authorization ràng buộc grid/manifest/semantics, Holm cài đúng, candidate paper không được
chọn theo kết quả, G1 đạt được (sức mạnh đủ cho một edge vừa phải: mean tới hạn khoảng 0,15 R ở n = 600).

---

## 9a. Khả năng sống của strategy và có nên đi tiếp

Nguồn: lane X11 `strategy_viability` (`AUDIT\lanes\strategy_viability.md`, finding G-2300..G-2305). Lane này
được owner yêu cầu thêm ngày 2026-11-18 và được nới phạm vi: được đánh giá "có nên đi tiếp" dựa trên bằng chứng
đã có, nhưng **không dự đoán lợi nhuận tương lai**. Mọi con số dưới đây được tính lại bằng code của chính dự án
(cost model `src/risk/cost_rates.py`, `cost_guards.py`, `quantize()`), probe ở `AUDIT\tmp\strategy_viability\`.
Các nhận định về thị trường không lấy từ repo hay nguồn chính thức được ghi rõ là **ý kiến**.

### 9a.1 Khuyến nghị

**Không đi tiếp theo kế hoạch hiện tại. Phương án (b):** tạm dừng phần kỹ thuật thực thi (không bắt đầu soak Demo
21 ngày, không làm phase nguồn tín hiệu, không làm Phase 26), giữ `LIVE_ORDERS_DISABLED`, ghi lại kết luận của
research run 1, và dùng thời gian tới mốc kill gate của chính dự án (**2027-03-19**, khoảng 4 tháng) cho **một**
research run 2 được đăng ký trước và có đủ sức mạnh thống kê. Trong khoảng đó được phép đổi family/khung thời
gian/thị trường (phương án c). Nếu tới 2027-03-19 không có ứng viên nào đạt: dừng mục tiêu kiếm tiền (phương án d,
đúng như D013 đã quy định) và giữ code làm nền tảng nghiên cứu. Nếu có ứng viên đạt: quay lại (a) — phần đã xây
không bị phí, nó đang chờ.

### 9a.2 Lý do, bằng số

| Câu hỏi | Kết quả | Finding |
|---|---|---|
| Có bằng chứng lợi thế không? | 0/48 biến thể có thể qua cổng của dự án. Trung bình mỗi lệnh theo family: trend-pullback -0,070 R, breakout-retest -0,094 R, range-mr -0,102 R. Ứng viên paper/Demo a01: -0,102 R (cận trên khoảng tin cậy 95 % iid: -0,015 R). Điểm tốt nhất (a05, +0,0027 R) chỉ cao hơn 0 khoảng 0,05 sai số chuẩn, và chọn nó bây giờ là chọn theo kết quả. | G-0901, G-2300 |
| Trước chi phí thì sao? | Gần hòa vốn (khoảng -0,05 tới +0,05 R, tùy phân bố khoảng cách stop chưa đo được). Phí + slippage chiếm 6,5–15 % của 1R mỗi lệnh ở các khoảng stop mà cost guard cho phép (0,8–2 %). Chi phí biến "không có lợi thế" thành "lỗ"; nó không che một lợi thế lớn. Đặt lệnh maker chỉ tiết kiệm 0,02–0,04 R. | G-2303 |
| Cơ sở của các strategy? | Cả ba là ý tưởng phân tích kỹ thuật phổ biến được viết thành luật chính xác. Không family nào có nguồn trích dẫn về lợi thế ở khung 1H/4H trên crypto perpetual; tài liệu của chính dự án ghi rằng nghiên cứu momentum được trích "không tự động áp dụng cho crypto perpetual". Tham số là giá trị khởi đầu được chọn, không suy ra. Run 1 trông đúng như khi không có lợi thế: lỗ xấp xỉ bằng chi phí. | G-2303, G-2305 |
| Tăng vốn có giúp không? | **Không đổi dấu, chỉ phóng to kết quả.** Mọi chi phí trong mô hình là tỷ lệ của notional, nên chi phí mỗi lệnh tính bằng R như nhau ở mọi mức vốn. Vốn lớn hơn chỉ làm BTC giao dịch được ở stop rộng hơn (tỷ lệ sử dụng ngân sách rủi ro của BTC từ 63–91 % lên 97–99 %). Với -0,08 R/lệnh và khoảng 200 lệnh/năm: 500 USDT lỗ khoảng 40 USDT/năm, 20.000 USDT lỗ khoảng 1.600 USDT/năm. Ý kiến: bậc giảm phí đầu tiên của Binance cần khối lượng 30 ngày cỡ 15 triệu USD, xa mức của tài khoản 20.000 USDT. | G-2304 |
| Có thể chứng minh lợi thế không? | Run 1 chỉ đủ sức phát hiện lợi thế lớn (+0,13 tới +0,57 R). Một lợi thế thực tế +0,1 R ở family A cần khoảng 790 lệnh cho một phép thử đăng ký trước (1.964 lệnh theo ngưỡng Holm của run 1), tức 19–47 tháng dữ liệu 12 symbol. 3–6 tháng paper hay canary chỉ cho 50–105 lệnh, sai số chuẩn 0,11–0,16 R: không phân biệt được +0,1 R với -0,1 R. Các giai đoạn đó kiểm tra đường ống, không kiểm tra lợi thế. | G-2301, G-2302 |
| Lộ trình còn lại dẫn tới đâu? | Không phase nào trên roadmap tạo ra ứng viên đạt, trong khi Phase 26 yêu cầu `enable()` phải có ứng viên đạt. Còn phải làm: phần còn lại của Phase 25 (gồm soak Demo ≥ 21 ngày), một phase chưa đặt tên cho nguồn tín hiệu strategy (G-1052), Phase 26 (0 plan), rồi 3–6 tháng paper. Ước tính của lane: lệnh tiền thật sớm nhất khoảng giữa 2027 **nếu** hôm nay đã có family đạt; không có family đạt thì theo đúng kế hoạch là không bao giờ. | G-2300, G-1052 |

### 9a.3 Bốn phương án cho owner

| Phương án | Chi phí | Chứng minh được gì | Tiêu chí quyết định |
|---|---|---|---|
| (a) Đi tiếp như kế hoạch | 4–8 tuần Phase 25 (kèm soak 21 ngày), một phase nguồn tín hiệu, 6–12 tuần Phase 26; owner tham gia xuyên suốt | Đường ống thực thi chạy được trên Demo và trên canary 50–100 USD. **Không chứng minh gì về lợi thế.** | Không có tiêu chí về lợi thế cho tới `enable()`, mà `enable()` sẽ từ chối; kill gate có thể kích hoạt 2027-03-19 trong lúc đó |
| **(b) Tạm dừng kỹ thuật, ghi kết luận run 1, làm research run 2 đăng ký trước (khuyến nghị)** | 1–2 tuần ghi kết luận và viết luật cho run 2 (chia alpha giữa các run — G-2102; giữ danh sách lệnh — G-0902; báo cáo R theo tín hiệu không bị trần danh mục — G-2107; định nghĩa G4 — G-0905); bổ sung dữ liệu lịch sử hoặc chờ dữ liệu mới; khoảng 25 giờ máy mỗi run | Có ứng viên nào với giả thuyết viết rõ vượt được một phép thử đủ mạnh để thấy +0,1 tới +0,2 R hay không | Trước khi chạy: chốt grid, alpha của run 2 và cửa sổ dữ liệu. Sau: đạt G1–G3 → quay lại (a), làm nguồn tín hiệu trước; trượt → (d) hoặc (c) |
| (c) Đổi family, khung thời gian hoặc thị trường | Một family sheet mới, code strategy mới trong `src/core` (simulator, risk, cost và execution dùng lại được); vài tuần | Như (b), cho một giả thuyết có nguồn bên ngoài ủng hộ. Ý kiến: ý tưởng ít giao dịch hơn (momentum ngày/tuần trên rổ symbol) giảm chi phí xuống 1–3 % của R nhưng ít lệnh hơn, nên sức mạnh thống kê vẫn là nút thắt | Như (b), cộng quy tắc D013: family mới cần một câu hỏi có bằng chứng được duyệt |
| (d) Dừng | Không tốn thêm; giữ repo làm nền tảng nghiên cứu/journal (đúng như D013 quy định khi không family nào đạt) | Không có gì mới; giữ giá trị của phần thực thi đã xây cho sau này | Mục tiêu của owner: nếu là thu nhập, bằng chứng hiện có không ủng hộ đầu tư thêm vào phần thực thi; nếu là học hỏi, (b) hoặc (c) rẻ hơn (a) |

### 9a.4 Điều gì sẽ làm khuyến nghị thay đổi

1. Mục tiêu của owner là chính phần kỹ thuật (một dự án học hỏi): khi đó (a) là một sở thích hợp lý, miễn là không
   ai coi kết quả Demo/paper là bằng chứng có lời.
2. Mô phỏng lại run 1 (khi đã giữ danh sách lệnh) cho thấy R theo tín hiệu, không bị trần danh mục, dương rõ ràng mà
   các trần PLACEHOLDER đã che (G-2107): đó là lý do để kiểm lại family đó với đủ sức mạnh.
3. Một ứng viên của run 2 đạt G1–G3 với alpha đăng ký trước.
4. Có một nguồn bên ngoài, có tài liệu, cho một trong ba setup ở khung này trên crypto perpetual: khi đó kiểm lại
   family đó có giá trị hơn (c).

### 9a.5 Giới hạn của phần này

Phân bố khoảng cách stop của run 1 không còn (danh sách lệnh đã bị xóa), nên kết quả trước chi phí là một khoảng
chứ không phải một con số. Trung bình trên cửa sổ Development không được in ra. Nguyên nhân ba trong bốn trục grid
của range-mr gần như không có tác dụng (G-2305) chưa được truy. Không trang web nào được tải; nhận định về thị
trường là ý kiến. Các con số sức mạnh dùng xấp xỉ iid, nên là cận dưới (bootstrap với lệnh phụ thuộc cần nhiều hơn).

Các việc chờ owner quyết của phần này: R-52..R-55 (mục 15.4).

---

## 10. Drift giữa docs/plan và code

22 finding primary có phân loại DRIFT; cộng thêm các DESIGN/GAP mà nguyên nhân là văn bản nói khác
code. Nhóm chính:

| Loại drift | Finding | Tóm tắt |
|---|---|---|
| Quyết định mô tả hành vi không có trong code | G-0600 (D102 health gate sau enable), G-0607 (D099 StoreExecutor), G-0402 (D084 ACCOUNT_UPDATE), G-0604 (D097 "khoảng hai interval"), G-2100 (D042 điều kiện 1) | văn bản DECISIONS khẳng định một bảo đảm mà tiến trình chạy không có |
| Docs canonical lỗi thời hoặc sai | G-1601 (RISK_MANAGEMENT "exactly as in live"; EXECUTION_SPEC, config README còn NOT_CONFIGURED), G-2001 (DEPLOY_GUIDE.vi.md bản 2026-10-09), G-2009 (DVM-14), G-2202 (bảy mục "chưa có tài liệu" đã có), G-2200 (-1008), G-0801 (TELEGRAM.md mô tả nhẹ) | owner đọc docs sẽ hiểu sai hành vi hiện tại |
| Runbook không khớp code | G-2004 (quy tắc "0 open"), G-2005 (quy trình REST-gate), G-2000 (lệnh `python` trần), G-2002 (thiếu mục cho alert CRITICAL), G-2006 (restore bỏ qua live) | thủ tục owner không chạy được hoặc chặn sai |
| Trạng thái kế hoạch đóng sai hoặc lệch | G-1101 (20D-01 CLOSED), G-1604 (library level), G-1600 (STATE/ROADMAP/19-OWNER-GAPS), G-1602 (BKTS-03), G-1751 (DATA-02/04 Complete), G-1701 (VERIFICATION trước review-fix), G-1750 (research-gate "executable"), G-1505 (D056 đóng) | các ô tick "Complete/CLOSED" không phản ánh code |
| Evidence và nhãn | G-1503 (demo-observed), G-1504, G-1506, G-1507, G-1605 (D113/D114 "untracked"), G-0305 (lý do 15 phút), G-1603/G-2103 (nhãn "DECIDED by the user", "the owner's choice") | nhãn mạnh hơn bằng chứng |
| Docstring/comment | G-0403 (comment `risk_inputs.py:557-563` sai), G-0204, G-0255, G-1053, G-0254, G-0705, G-0904, G-0952 | nhỏ, nhưng comment sai ở G-0403 che một lỗ hổng an toàn |
| AGENTS.md | G-1402/G-0107 ("machine-enforced" chỉ đúng một phần), số file `*_pg.py` (26 vs 41, X03) | |

Gate `verify_decision_alignment.py` (exit 0) không bắt được các drift này vì chỉ kiểm câu chữ (G-1300).

---

## 11. Tình trạng các finding của audit 2026-09-29

Hai lane X06 (F-2xx..F-8xx) và X07 (F-0xx/1xx/9xx) kiểm từng ID cũ từ code và test của `55885b9`;
plan, SUMMARY và VERIFICATION chỉ dùng để định vị.

| Lane | Phạm vi | FIXED | PARTIAL | SUPERSEDED | OPEN | WRONGLY_CLOSED |
|---|---|---|---|---|---|---|
| X06 | 45 ID HIGH/MEDIUM (42 primary + 3 duplicate) | 37 | 3 (F-203, F-604, F-806) | 3 | 2 (F-807 → G-1701, F-809 → G-2103) | 0 |
| X07 | 61 HIGH/MEDIUM primary | 42 | 11 | 5 | 3 (F-953 kill gate WITHIN_BUDGET, thuộc Phase 26; F-107 bằng chứng thu OI; F-121 không có restore PG thật) | 0 |
| X07 | kiểm điểm 15/22 LOW | 9 | 2 (F-019, F-027) | 0 | 4 (F-003 = G-2105, F-025, F-028, F-114) | 0 |

**Cả 12 HIGH cũ đã đóng trong code hoặc docs:** F-301, F-302, F-401, F-501, F-701, F-702 (X06:
geometry validator, plan binding, miễn trừ resting-entry + D079, not-found theo taxonomy, divergence
kinds, giảm rủi ro act-first) và F-007, F-022, F-902, F-104, F-120, F-126 (X07: kiểm giá mark/last
trước placement, gate số và một Holm, khớp trade-through và kích hoạt N+1, user-data stream, ENTRY intent
đúng một lần). **Không finding cũ nào bị đóng sai.**

Mẫu hình (X07): các mục kế hoạch được trả lời bởi D031–D046 và Phases 11–24 thật sự đóng trong cả docs
và code. Cái còn mở là bằng chứng chỉ host hoặc owner tạo được (thu OI, restore PostgreSQL, CI trên
remote, hạn chế key), và các ô trạng thái vẫn báo những mục đó là Complete (G-1751). Finding mới từ hai
lane: G-1700, G-1701, G-1750, G-1751, G-1752.

So với audit trước: khi đó 152 primary với 0 CRITICAL / 12 HIGH / 91 MEDIUM, hệ thống chưa được nối
dây và simulator nhìn trước tương lai. Nay 138 primary với 0 HIGH now; các HIGH mainnet là vấn đề của
một hệ thống đã chạy được end-to-end (cửa sổ outage, đọc lag, close mơ hồ, alert, evidence), không còn
là vấn đề nền móng.

---

## 12. Những phần đã kiểm và đứng vững

Tổng hợp từ mục "Verified Safe Areas" của 26 lane (mỗi mục có file:line và thường có probe trong lane).

**Đường đặt lệnh**
- Một POST cho mỗi approval, không retry ở tầng nào: một call site `place_entry` (`manager.py:376`),
  adapter một `_sdk_call`, SDK chỉ retry GET/DELETE và `sdk_retries = 0`; probe: mọi case lỗi `posts=1` (M02, M07, X10).
- Mơ hồ ⇒ một probe ⇒ UNKNOWN + SAFE_MODE; thứ tự write-ahead (consume → snapshot → `mark_sent` → POST
  → kết quả → chuyển cho protection) đúng khi crash ở mọi điểm (M02).
- Approval consume đúng một lần, do DB phân xử (ON CONFLICT + UPDATE có điều kiện + unique index), giữ
  được ở READ COMMITTED; một quyết định mỗi plan (M02, M11).
- Plan binding D078: symbol và side gửi sàn lấy từ Signal đã lưu; hash tính lại; quantity không bao giờ
  lớn hơn approved (M02, X02).
- `LIVE_ORDERS_DISABLED` là khẳng định: mặc định disabled, mỗi lần start tạo controller disabled mới,
  `enable()` duy nhất ở `enable_demo` vốn từ chối mọi mode khác DEMO; LIVE cần sửa code (M02, M06, X07).
- Làm tròn giá không bao giờ tăng rủi ro; số thập phân ra wire là chuỗi fixed-point, không float (M02, M07).

**Bảo vệ vị thế**
- Stop `closePosition` phủ đúng vị thế sau mọi kiểu fill; fill trùng không tạo stop thứ hai; fill bị
  stream bỏ lỡ được REST poll tìm thấy (tối đa thêm 15 s) (M03).
- Chỉ trả lời REST ACTIVE mới tính là bảo vệ; stop bị từ chối không bao giờ gửi lại mà đi CLOSE_REQUIRED;
  không stop mới trong CLOSE_REQUIRED/CLOSE_FAILED/FLAT (M03).
- Restart bảo vệ một vị thế đã khớp trong lúc tiến trình chết, dù outage dài (probe 5 s và 3600 s);
  start không sạch vẫn chạy protection; stop không chờ DB (86 method store lỗi, stop vẫn được đặt) (X01).
- TP chỉ có thể giảm vị thế, floor không bao giờ vượt vị thế, không bao giờ POST hai lần (M02b).
- Liquidation: công thức isolated khớp FAQ chính thức tới số thập phân; unknown ⇒ CLOSE (M03, M04).

**Rủi ro và tài khoản**
- Sized loss không bao giờ vượt budget (probe 4 symbol × 3 equity × ~150 stop × 2 side; tối đa 0,999997);
  cost guard chạy trước làm tròn và không tắt được (M01, X09).
- Equity fail closed (mọi nhánh không đủ dữ liệu ⇒ UNCERTAIN_ACCOUNT_STATE), được đọc lại ở mỗi
  placement; daily loss fold đúng, latch bền qua restart (M04).
- Approval tuần tự hóa bằng advisory lock + `FOR UPDATE`; margin claim không thể bị khai thấp (M04, M11).

**Reconcile, SAFE_MODE, khởi động**
- Reconcile không đặt gì và chỉ hủy ORPHAN_PROTECTIVE; sweeper không thể hủy chân của vị thế đang sống;
  mọi loại divergence có policy; nguồn thiếu không bao giờ được đọc là rỗng (M05).
- Không đường tự động nào thoát SAFE_MODE trong tiến trình; lệnh operator thoát kiểm bảy điều kiện với dữ
  liệu Binance mới; SAFE_MODE không bao giờ chặn hành động bảo vệ (M05, X07).
- Mode tường minh; LIVE không start được (hai guard độc lập); credential mode kia từ chối start; wiring
  gate so sánh danh tính (M06).

**Sàn và Telegram**
- Phân loại lỗi không bao giờ gán "definitive" cho câu trả lời mơ hồ; "absent" không bao giờ suy từ text;
  sự kiện user-data chỉ dùng từ vựng đã công bố; khoảng trống stream không bao giờ được lấp im lặng (M07, X10).
- Hầu hết fact sàn mà code dựa vào khớp docs chính thức từng chữ (timestamp/recvWindow, GTD, cửa sổ
  not-found 3 ngày, vòng đời listenKey, ALGO_UPDATE); quan sát Demo luôn được ghi là Demo (X10).
- Telegram: xác thực user-id cho mọi callback và lệnh; callback_data 36 byte không chứa token; replay
  ghi cùng row; lỗi gửi thông báo không bao giờ dẫn tới approve; chỉ tin nhắn được retry; card hiển thị
  đúng cái sẽ thực hiện (M08, X02).

**Nghiên cứu, paper, dữ liệu**
- Simulator nhân quả, tất định qua process và hash seed; ledger khớp tay tới số thập phân; funding đúng
  dấu và thời điểm; không look-ahead khi dựng case; holdout chưa chạm (M09, M09b, X04).
- 73/73 parameter set khớp pin; 480 `experiment_id` tái lập; hai gate đã ghi đúng là cây chúng nói (X04).
- Paper: không có đường tới endpoint đặt lệnh; từ chối mọi biến `BINANCE_*`; chỉ nến đóng vào pipeline;
  backfill không bao giờ sinh signal (M10, M10b).
- Dữ liệu: Parquet bất biến, ghi an toàn khi bị cắt; chỉ publish ngày UTC đã đóng; ORM == migration ==
  enum domain (69 CHECK, 0 khác biệt); không float trong migration (M11).

**Ops và kiểm thử**
- Mật khẩu DB không vào argv; lớp redaction theo giá trị che mọi dạng thử; URL heartbeat giữ bí mật;
  container non-root, image ghim digest; update.sh từ chối khi live đang chạy (M12).
- Công cụ Demo không thể chạm REST mainnet; `--execute` cần TTY + câu gõ đúng (M13).
- **Mutation probe (X02):** khoảng 90 mutation lên guard an toàn; chỉ 3 sống sót sau kiểm tra tương đương
  (G-1901, G-1902, G-1903). Bị giết: không gửi lại placement (D01, D03/D04, D05, D17, E18), làm tròn
  xuống (A02b/c, A04, A20, A21, C05), không entry khi chưa bảo vệ (B15, E08–E11), SAFE_MODE (D11, D17,
  E14–E16), approval binding (B07–B09, D07, D08, D14, E03, E04/E06, E07), xác thực Telegram (E01, E02,
  F05b), daily loss/margin/liquidation (A05–A16), emergency close (E12, E13), reconcile/sweeper, stop-first,
  live orders disabled (B04, B20, D12). Nghĩa là các guard then chốt đều có test sẽ đỏ khi bị phá.
- CI: `TRADING_CI_STRICT=1` biến skip PG thành lỗi; xfail strict và được đăng ký; không có tolerance nới
  rộng hay skip im lặng nào được thêm từ 2026-10-01 (X03).

---

## 13. Khoảng cách Demo → mainnet

Từ lane X08 (mục "Demo -> mainnet delta"), X04 (smoke từng bước) và `docs/operations/DEMO_VS_MAINNET.md`.

### 13.1 Cờ và cấu hình phải đổi hoặc phải quyết trước lệnh tiền thật đầu tiên

- `LIVE_ORDERS_DISABLED` / enablement: mode LIVE **không có đường enable nào** (`src/live/startup.py:1078-1081`);
  các điều kiện `enable()` của Phase 26 (candidate pass, paper exit gate, Demo campaign, vốn tối thiểu,
  registry WR) chưa được xây; enable hiện chấp nhận WITHIN_BUDGET (G-1700).
- `LIVE_NET_PNL_SEMANTICS_VERIFIED=False` (`src/analytics/live_outcomes.py:80`), `FUNDING_SOURCE_VERIFIED=False`
  (`src/risk/daily_loss.py:72`), `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED=True` chỉ dựa trên Demo (G-2009).
- Key `NOT_CONFIGURED`: `rest_gate.ban_end_clock_margin_ms`, `scheduler.duration_summary_interval_ms`.
- `restart: "no"` của service live (G-2007); tách role DB owner / application (G4-033, G-1207);
  `.env.live` với `BINANCE_LIVE_*` và `LIVE_RUNTIME_MODE=LIVE`, key IP-restricted không quyền rút (G-1752, G-1206).
- Nguồn signal cho LIVE: không có (D101, G-1052, G-2010).
- Daily stop: `enforce_daily_state` không có caller (G-0403), alert DAILY_STOP mà docs liệt kê không bao giờ phát.
- Ghi `fills` và vòng đời order (G-1101) để có kết quả live.

### 13.2 Lần đầu được chạy bằng tiền thật (chưa có quan sát Demo)

Partial fill (DVM-03, P3), slippage/độ sâu sổ (DVM-02), trạng thái kết thúc GTD (DVM-22, A2: trên Demo
vẫn NEW 840 s sau goodTillDate), phí funding (DVM-12), một 418/429 thật và thứ tự hàng đợi sau đó
(DVM-28..31), emergency close và các timeout của bậc thang tự động, stop bị từ chối sau khi đã nhận
(DVM-33), SAFE_MODE do stale feed, cắt user-data 24 h (DVM-27), giá liquidation short/tier cao (DVM-15),
lag `-2013` trên mainnet sau placement (DVM-19), heartbeat và service compose trên host
(24-OWNER-RUNBOOK B–E đều NOT_OBSERVED), `/status`, `/disable_entries`, `/close` gõ tay. Smoke 21/21 dùng
signal tiêm vào, fill taker tức thì, SAFE_MODE gọi trực tiếp, restart có thứ tự và close bởi operator;
stop/TP trigger, fill chờ, partial fill và emergency close chưa chạy trên Demo (G-1503). Smoke không gắn
với commit (G-1501) và chỉ giữ order id (G-1502).

### 13.3 Những việc hệ thống không làm được nếu thiếu owner

Duyệt và xác nhận mọi entry; thoát SAFE_MODE (mọi lý do, kể cả lý do một tick vô hại: G-0500, G-0501);
xóa REST gate (ssh); kết thúc CLOSE_FAILED sau khi đóng tay (cần sửa DB: G-1801); đóng vị thế hệ thống đã
"mất" (G-0300) hoặc có close PENDING_UNKNOWN (G-0301); restart tiến trình live sau khi host reboot
(G-2007); sửa row plan không khôi phục được (RUNBOOK 21.6, sửa DB tay). Khi owner ngủ hoặc đi xa, vị thế
chỉ dựa vào stop trên sàn nếu đã được đặt; entry khớp lúc tiến trình chết thì không có stop (G-2100).
Mọi thông báo cho owner đi qua một kênh duy nhất là Telegram (G-2003), và alert gửi lỗi bị bỏ (G-0801).

---

## 14. Đề xuất khắc phục theo thứ tự ưu tiên

Đây là hướng, không phải bản vá; các mục có "owner" cần quyết định ở mục 15 trước khi làm.

### 14.1 Trước Phase 25 (Demo campaign)

1. **Ghi lại kết quả run 1** theo từng family với decision reference và để owner chọn hướng đi (R-25):
   campaign Demo có còn là bước tới go-live hay chỉ là kỹ thuật (G-0901, G-0903, G-1700). Giữ danh sách
   trade cho mọi run sau (G-0902).
2. **Fills ledger và vòng đời order** (G-1101; R-35), nếu không campaign báo 0 trade. Kèm G-0953 (close
   khẩn cấp/tay/thanh lý phải đóng outcome) và G-1051 (ghi stream lỗi không được mất hẳn).
3. **Soak evaluator** (G-1302; R-36): tiêu chí coverage/khoảng trống, journal bắt đầu từ lúc đăng ký, so
   `image_commit`, 0 trade không đạt; sửa tiêu chí duplicate (G-1303).
4. **Gate tuần tự có PG được ghi lại** trên cây hiện tại (G-1508); owner kiểm GitHub Actions và quyết cách
   CI chứng minh test DB đã chạy (G-1401; R-50).
5. **Evidence có danh tính**: commit, cờ dirty, hash limits và câu trả lời gốc của sàn trong evidence smoke
   (G-1501, G-1502); định nghĩa "Demo-proven" (R-38).
6. **Alert CRITICAL không được mất** (G-0801; R-23) và một đường báo ngoài Telegram cho trạng thái nguy
   hiểm (G-2003; R-43). Thêm tin nhắn kết quả sau CONFIRM (G-0802).
7. **Nguồn signal chiến lược trong tiến trình live ở DEMO** nếu campaign phải kiểm đường strategy → lệnh
   (G-1052; R-45).
8. **Fake exchange có lag**, đặc biệt lag position nhiều lần đọc, để campaign không phải là nơi đầu tiên
   bắt G-0300/G-0250 (G-1400; R-51).
9. Chạy các plan Phase 25 đã có cho daily stop (25-28: G-0403), reservation (25-23: G-0401), resync
   (25-29: G-0702), và kiểm lại 25-32 vì nó không giải được trường hợp PENDING_UNKNOWN (G-1801).

### 14.2 Trước go-live (bất kỳ placement mainnet nào)

1. **G-2100** (R-01): biện pháp phía sàn cho entry đang chờ, hoặc chấp nhận bằng văn bản với restart tự
   động; sửa D042; xem lại G-1800 và G-2007 cùng lúc.
2. **G-0300**: hai lần đọc flat phải độc lập về thời gian và khớp `executedQty`; tương tự cho closer.
3. **G-0301 + G-2203 + G-1801** (R-03): bổ sung mã từ chối chắc chắn; close reduce-only có giới hạn được
   gửi lại; lệnh operator dùng được trong CLOSE_FAILED; plan kết thúc được sau khi owner đóng tay.
4. **G-0250 / G-2104** (R-02): xác nhận "stop mất" bằng nhiều hơn một lần đọc trước khi đóng thị trường.
5. Lỗi giảm rủi ro bị chặn: 418 ba ngày (G-0700; R-07), 429 chặn stop/close (G-0701; R-08), stream halt
   (G-0702; R-09).
6. Giám sát tiến trình: health RED sau enable (G-0600; R-20), CancelledError giết scheduler (G-0601),
   task lỗi im lặng (G-0602), bot không retry (G-0603), skip reconcile không giới hạn (G-0604), store đồng
   bộ trên loop (G-0607).
7. Reconcile/SAFE_MODE: một lần thấy hay một lần đọc lỗi không nên khóa hệ thống (G-0500, G-0501; R-22);
   lưu SAFE_MODE khi journal lỗi (G-0502); `demo_clear` không được chạm DB live (G-0503, G-1301; R-37).
8. Đường enable LIVE với kill-gate producer và điều kiện edge (G-1700, R-24); hạn chế key được code kiểm
   (G-1752; R-48); một tiến trình live được ép (G-1203); quyền DB tách (G-1207).
9. Rủi ro tài khoản: cluster cap sau ngày lãi (G-0101; R-13), rủi ro thật mỗi trade (G-0102; R-14), daily
   stop (R-15), reservation (G-0401; R-16), re-check lúc CONFIRM (G-0201, G-0202; R-17, R-18), phí BNB
   (G-0404; R-12), tuổi last price LIVE (G-2106; R-10).
10. Runbook và docs cho owner: DEPLOY_GUIDE.vi.md (G-2001), mục cho mọi alert CRITICAL và CLOSE_FAILED
    (G-2002), quy tắc dừng (G-2004; R-44), quy trình REST gate (G-2005), restore với live (G-2006), xoay
    key (G-2008), lệnh chạy được (G-2000), wording alert (G-0804).
11. Backup cho journal live: RPO (G-1202; R-39), báo backup lỗi (G-1201; R-40), gate S3 thật và diễn tập
    restore (R-42).
12. Trình lại cho owner các con số tiền đã được nhận mặc định, mỗi số một ví dụ USDT (G-1603, G-2103; R-30).

### 14.3 Sau (hygiene, không chặn)

Guard tĩnh (G-0107, G-1402), registry kiểm khoảng (G-0106), các DEFECT nhỏ của protection (G-0303,
G-0304), paper (G-1004, G-1006, G-1007, G-1008), dữ liệu (G-1102), redaction (G-1205), mode env file
(G-1206), test biên (G-1901, G-1902, G-1903), drift docs/plan (G-1600, G-1602, G-1605, G-1701, G-1750,
G-1751, G-2009, G-2200, G-2202, G-0204, G-0255, G-1053), các vấn đề nghiên cứu cho run sau (G-0904,
G-0905, G-0950, G-0951, G-0952, G-0954, G-2102, G-2107), và gate decision-alignment phủ cả code (G-1300).

---

## 15. Sổ việc chờ owner quyết

Nền là sổ hợp nhất R-01..R-34 của lane X05 (`lanes\decisions_requirements_process.md`, dựng từ 14 lane
đầu cộng các mục còn mở của `19-OWNER-GAPS.md`, `25-OWNER-DECISIONS.md`, D058, D092 và file cấu hình).
Mục 15.2 bổ sung R-35..R-51 từ các lane hoàn thành sau (data_persistence_db, evidence_reproducibility,
ops_deploy_security, scripts_tooling, mutation_probe, prior_findings_closure_a/b, operator_golive_gap,
paper_gapfill, backtest_gapfill, test_effectiveness_ci), đã bỏ trùng: mục nào đã có trong R-01..R-34 thì
được gộp vào dòng cũ (ghi ở 15.3). Các phương án là của lane; **audit không chọn hộ**. Ví dụ dùng equity
1000 USDT, risk 0,5 % (1R = 5 USDT) trừ khi ghi khác.

### 15.1 R-01..R-34 (từ X05)

**A. Bảo vệ vị thế đang mở (ảnh hưởng tiền lớn nhất trên mainnet)**

| ID | Quyết định | Nguồn | Phương án, ví dụ số | Nếu để nguyên |
|---|---|---|---|---|
| R-01 | Bảo vệ phía sàn khi tiến trình không chạy (stop chỉ đặt sau fill; `restart: "no"`) | G-2100, G-2201, G-1800, G-2007; D106 | Long 0,004 BTC ở 80.000, stop 1,5 % (rủi ro 4,8 USDT); host offline 20 phút, entry khớp, giá -6 % ⇒ lỗ ≈ 19,2 USDT, chỉ bị chặn bởi margin isolated (≈ 88 USDT). (a) đặt stop reduce-only cùng entry (Demo chấp nhận, mainnet chưa thấy); (b) probe và dùng `countdownCancelAll`; (c) `restart: unless-stopped` + entry sống ngắn, chấp nhận bằng văn bản; (d) chỉ đặt entry khi owner có mặt. Khi DB chưa lên lúc start: thử lại N phút / thoát để restart trễ thử lại / giữ hold | entry khớp không có stop chừng nào tiến trình còn chết; điều kiện bật restart (một lần Demo sạch) đã đạt mà policy vẫn "no" |
| R-02 | Một lần đọc by-id âm cho stop đã xác nhận ⇒ đóng thị trường + SAFE_MODE | G-0250/G-2104 | Long 0,010 BTC từ 60.000, stop 59.000, giá 59.600; một lần "not found" sai (đã thấy trên Demo 2026-10-22, 11-01, 11-15) ⇒ bán thị trường ≈ -4 USDT + phí, SAFE_MODE. (a) giữ một lần đọc; (b) 2–3 lần âm liên tiếp + listing (stop mất thật được xử lý chậm 15–45 s). Restart với lịch sử stop không rõ: đóng (hiện tại) hay đọc stop trước | mỗi lần âm sai đóng một trade khỏe và dừng giao dịch tới khi thoát tay |
| R-03 | Emergency close sau câu trả lời mất hoặc bị từ chối: có được gửi close reduce-only thứ hai? | G-0301, G-2203, G-1801 | 0,02 BTC ở 60.000, 5x (margin 240 USDT), không stop; close bị -4131 hoặc mất trả lời. A: một close, chờ người (tệ nhất mất 240 USDT margin); B: close mới dưới id mới sau từ chối chắc chắn; C: B + sau N (vd 3 trong 30 s) lần "not found". Thêm: cho phép kết thúc plan FLAT sau khi owner đóng tay (hai lần đọc 0)? Bao lâu giữa alert đầu và hành động của owner là chấp nhận được? | vị thế mở không stop tới khi owner hành động; đóng tay xong vẫn cần sửa DB |
| R-04 | `protection.max_unprotected_ms` 180000 và các limit D089 khác (entry timeout 15 phút, UNKNOWN grace 30 phút, tick reconcile 15 s) | G-2103, G-0305 | Giá đi ngược 1,5 % trong 3 phút trên vị thế 1.200 USDT = 18 USDT so với rủi ro dự kiến 5–10 USDT. Ngắn hơn đóng sớm hơn nhưng cũng đóng vị thế khỏe trong pause 429 120 s | các con số suy từ pause rate-limit, không từ rủi ro giá, vẫn mang nhãn "của owner" |
| R-05 | TP dưới min notional; retry bước TP; fallback một TP (O-03); phần còn lại khi partial fill (N1); B1 | G-0251, G-0252, G-0254, G-0302, G-0305 | Min notional 100, TP1 0,003 BTC ở 62.000 bị từ chối, 0,004 là nhỏ nhất qua. (a) giữ quy tắc chặt (plan nhỏ không bao giờ giao dịch, partial fill kết thúc ở SAFE_MODE); (b) vẫn gửi TP1 reduce-only, coi -4164 là hold; (c) một TP closePosition khi TP1 không size được (cần cùng quy tắc trong backtest). Retry đọc ở bước TP (không có rủi ro trùng). Partial fill: hủy phần còn lại (hiện tại) hay để tới GTD. B1: có đóng thị trường vị thế đã có stop khi entry không hủy được 15 phút không | vị thế quá nhỏ cho TP1 không có TP và đẩy hệ thống vào SAFE_MODE |
| R-06 | Tỷ lệ chia TP1 là hằng số code, không phải tham số | 19-OWNER-GAPS O-02 | giữ `TP1_QUANTITY_FRACTION` trong code, hoặc đưa vào parameter set khóa hash (set mới + strategy_version mới) | tỷ lệ không đổi được qua quy trình registry |

**B. Giới hạn sàn và kết nối**

| ID | Quyết định | Nguồn | Phương án, ví dụ số | Nếu để nguyên |
|---|---|---|---|---|
| R-07 | Ban 418 không Retry-After = 259.200 s (3 ngày) không REST; `rest_gate.ban_end_clock_margin_ms` NOT_CONFIGURED | G-0700; D072 | Ban lúc 12:00, body nói hết 12:02; hiện tại stop/close kế tiếp gửi được ngày thứ 4 lúc 12:00; với margin 60000 là 12:03. Đặt margin; giảm fallback với kiểm tra leo thang; "clear" có audit sau khi owner kiểm Binance (CLI `rest_gate_cli clear` đã có) | ban 2 phút có thể chặn reconcile và close 3 ngày nếu owner không can thiệp |
| R-08 | Lệnh giảm rủi ro trong pause 429 | G-0701; D081 | 0,01 BTC khớp 5 s sau một 429; stop chờ tới 115 s; giá đi 1 % ≈ 8,4 USDT không có stop. Cho phép một lần gửi stop/close reduce-only trong pause 429 (không bao giờ trong 418), rủi ro biến 429 thành ban | stop và close chờ tới 120 s sau mọi 429 |
| R-09 | User-data stream halt vĩnh viễn sau 7 reconnect / 120 s | G-0702; 25 Q-K | resync tự động có giới hạn mỗi N phút, hay lệnh `/resync_stream` thủ công (đã chọn cho Phase 25) | mỗi lần halt tốn thời gian tới khi owner thấy alert |
| R-10 | Tuổi last price 30 s dùng chung Demo và LIVE | G-2106; D096 | 30 s cho cả hai, hay 5 s cho LIVE sau một lần đo read-only trên mainnet | last price cũ 30 s có thể qua kiểm tra marketability trên mainnet |
| R-11 | Đọc lại fact của sàn từ nguồn chính xác từng ký tự trước Phase 25/26 | G-2202 | bắt buộc đọc lại `llms-full.txt` + OpenAPI như một gate, hay không | bảy mục register vẫn "unknown" dù đã có tài liệu; DVM-23 mô tả sai -5040 |
| R-12 | Phí trả bằng BNB trên mainnet | G-0404 | tắt BNB fee burn trên tài khoản, hay để hệ thống kiểm lúc start | hệ thống ngừng giao dịch sau fill đầu mỗi ngày |

**C. Sizing, cap và daily stop**

| ID | Quyết định | Nguồn | Phương án, ví dụ số | Nếu để nguyên |
|---|---|---|---|---|
| R-13 | Cluster cap sau ngày lãi | G-0101 (G-0400) | Ngày bắt đầu 1000, thắng +10; plan XRP kế tiếp size trên 1010 có risk 5,045 > cap 5,000 ⇒ từ chối dù không gì mở (ở 600: 3,03 > 3,00). (a) giữ; (b) cap và size trên cùng một equity; (c) cap hơi cao hơn một đơn vị risk. (b)/(c) đổi tập trade và record nghiên cứu | ít trade hơn sau ngày thắng, cả live lẫn backtest |
| R-14 | Rủi ro thật mỗi trade (size cho fill ở mép xa của vùng) | G-0102; G-1603 | Ở 1000 USDT "risk 0,5 %": stop-out mất ≈ 3,05 (Family A), 4,65 (B), 4,47 (C) thay vì 5. (a) giữ và hiện số thật trên card và báo cáo; (b) size theo giá limit thật | rủi ro được nêu không phải rủi ro được nhận |
| R-15 | Ngữ nghĩa và wiring của daily stop | G-0403, G-1601; 25 Q-J | Hai trade đóng -9,90 (chưa stop), rồi hai trade mở mỗi cái risk 5: ngày có thể kết thúc ≈ -19,90 (2 %), không phải -10; stop lúc 23:55 UTC hết lúc 00:00 UTC. Chỉ trade đóng (hiện tại); tính cả risk mở; cửa sổ 24 h trượt. Wiring: tới khi plan 25-28 chạy, entry chờ không bị hủy ở DAILY_STOP | giới hạn ngày 1 % thực tế ≈ 2 % và entry chờ sống sót qua nó |
| R-16 | Reservation không tiến hoặc không kết thúc (R-21) | G-0401; 25 Q-F | Có một vị thế mở thì plan thứ hai bị từ chối (margin đếm hai lần: cần 882,2 so với 600 có). Row của entry UNKNOWN chặn chiều đó tới khi sửa DB; phương án: lệnh operator giải phóng có audit | hệ thống thực tế chỉ một vị thế; entry UNKNOWN chặn một chiều vô thời hạn |
| R-17 | Quantity đã duyệt so với quantity tính lại lớn hơn lúc CONFIRM | G-0202 | Card 181,9 XRP ở equity 1000,00; lúc CONFIRM equity 1000,55 ⇒ 182,0 ⇒ từ chối, card chết. Phương án: đặt 181,9 (quantity đã duyệt, risk hơi dưới budget) | biến động equity nhỏ giết approval |
| R-18 | Kiểm lại disable / SAFE_MODE ở khoảnh khắc cuối của CONFIRM | G-0201 | CONFIRM ETHUSDT, 1 s sau kill gate disable hoặc SAFE_MODE bật; hiện entry vẫn được gửi | một CONFIRM đang bay vượt qua lệnh disable mới |
| R-19 | Khả năng sống của tài khoản nhỏ: BTC ở 500–600 USDT, canary 50–100 USDT | G-2105, G-0108; D040 | Ở 500 USDT, BTC chỉ trade được với stop ≈ 0,8–2,35 %; canary không trade được BTC; 1R = 2,5–5 USDT; edge +0,10R × 250 trade = 62–125 USDT/năm trước chi phí host. Chấp nhận như công cụ nghiên cứu; bỏ BTC khỏi universe tài khoản nhỏ; xem lại sàn utilisation 60 % (đọc lại min notional BTCUSDT mainnet trước) | kỳ vọng không được ghi; tập trade BTC live khác backtest |

**D. Giám sát runtime và alert**

| ID | Quyết định | Nguồn | Phương án, ví dụ số | Nếu để nguyên |
|---|---|---|---|---|
| R-20 | Health chuyển RED sau enable (chính sách (1) của D056 chưa làm) | G-0600 | A: N tick NO_TRADE liên tiếp thì disable entry (N = 2 = 30 s); B: chỉ journal và sửa D102. Ví dụ 4/10 REST call cuối lỗi lúc 10:00:15; với A một CONFIRM lúc 10:00:50 bị từ chối | tiến trình suy giảm vẫn đặt lệnh nếu kiểm tra riêng của manager qua |
| R-21 | Telegram không với tới lúc start; task lỗi im lặng; pause reconcile khi placement | G-0603, G-0602, G-0604 | hold hay tiếp tục trong SAFE_MODE và retry bot; alert sau 3 lần lỗi (45 s) hay 20 (5 phút); giới hạn skip reconcile ở 2 tick (30 s) hay không (placement 70 s bỏ 5 tick) | vị thế khôi phục chỉ dựa vào stop trên sàn; lỗi im lặng không ai thấy |
| R-22 | Reconcile: một lần thấy khóa hệ thống; một lần đọc lỗi ⇒ SAFE_MODE; tự xóa API_DEGRADATION/STALE_FEED; `scripts/demo_clear.py` | G-0500, G-0501, G-0503 | Entry khớp 14:00:07,0, stop ACTIVE 14:00:09,0, tick lúc 14:00:08 ⇒ SAFE_MODE POSITION_WITHOUT_STOP tới `/safemode_exit`. Hai tick liên tiếp, so sánh biết chuyển tiếp, chỉ khóa loại không thoáng qua; N = 4 tick lỗi (60 s) trước SAFE_MODE; demo_clear gắn Demo hoặc bỏ trước mainnet | SAFE_MODE giả thường xuyên, cần owner |
| R-23 | Telegram: giao lại alert an toàn thất bại, tin kết quả sau CONFIRM, nút sau từ chối chữa được, báo card bị lỡ | G-0801, G-0802, G-0803, G-0806 | Telegram mất 40 s lúc 03:00 khi emergency close lỗi ⇒ 3 lần thử trong 30 s, bỏ, điện thoại im. Retry mỗi lần drain tới khi giao; trong N phút; như hiện tại. Một tin mỗi trạng thái (đặt, từ chối + lý do, khớp, stop đặt, đóng + PnL) | owner có thể lỡ đúng alert quan trọng |
| R-24 | Kill-gate producer cho LIVE; điều kiện để enable LIVE/CANARY (gộp G-1700 từ X06) | D092; G-1604; G-1700 | Xây producer trước mọi enable LIVE, hay giữ LIVE bị từ chối. Điều kiện: (a) cần PASSING_CANDIDATE + decision reference; (b) cho CANARY ở WITHIN_BUDGET chỉ với waiver viết tay nêu family và trần lỗ; (c) giữ như hiện tại. Ví dụ: a01 -0,10 R × 100 trade × 5 USDT ≈ -50 USDT trước chi phí, kill gate vẫn WITHIN_BUDGET | LIVE bị từ chối `KILL_GATE_UNEVALUATED` (an toàn) cho tới khi có đường enable; khi có thì không cần bằng chứng edge |

**E. Nghiên cứu và evidence**

| ID | Quyết định | Nguồn | Phương án, ví dụ số | Nếu để nguyên |
|---|---|---|---|---|
| R-25 | Ghi kết quả research run 1 | G-0901 (G-2101), G-0903 | 48 candidate: 45 mean Validation âm (-0,23R tới -0,011R), một dưới sàn trade, hai dương 0,003R và 0,0007R với độ bất định 0,055R và 0,14R. (a) ghi "không candidate nào pass" (kill gate có thể kích hoạt 2027-03-19) và dừng công việc thực thi tới khi có câu hỏi nghiên cứu mới được duyệt; (b) để không ghi (trạng thái mãi WITHIN_BUDGET); (c) tiếp tục Demo như công việc kỹ thuật, nói rõ như vậy, không có ngày go-live; bắt đầu run 2 chỉ sau R-26 | công việc thực thi tiếp tục hướng tới live mà không có chiến lược nào đã pass |
| R-26 | Quy tắc cho research run hai; R theo signal không cap; slippage theo loại exit; giữ danh sách trade | G-2102, G-2107, G-0902, G-0904 | alpha qua các run, khoảng Validation mới, kiểm định thật trên holdout; báo R không cap bên cạnh R có gate (trend-pullback Development: 47.117 aggregate-cap reject so với 171–570 trade mỗi điểm); một mức 3 bps cho mọi exit thị trường hay 1 bp cho TP (phiên bản simulator mới); giữ danh sách trade (đĩa, tái chạy ≈ 25 h) | run hai trên cùng dữ liệu không được kiểm soát |
| R-27 | Giá trị nhãn EXPERIMENT không có cơ sở trong SHADOW/go-live; thành viên cluster (8/12 symbol nghiên cứu ngoài cluster cứng) | G-0105; KNOWN F-908 | cho phép chỉ trong SHADOW và từ chối ở gate go-live, hay không; định nghĩa thành viên cluster | một giá trị không có cơ sở có thể tới live |
| R-28 | Quy tắc paper soak: trần thời gian không phủ, pin mới trên cùng DB, giới hạn 21 ngày, danh tính build, giới hạn lệch đồng hồ | G-1001, G-1002, G-1003, G-1005, G-1008 | Restart 60 s lúc 12:20 tính 2400 s không phủ, vượt trần 900 s; lúc 12:50 thì qua. Giữ 900 s; ghi bằng chứng feed lúc start; trần = một bar + thời gian start. Lệch đồng hồ ví dụ 500 ms | trial hỏng vì restart vô hại; soak dài không restart được sau ≈ ngày 21 |
| R-29 | OQ-1: trade backtest giữ qua lỗ dữ liệu mark price | D058 | chỉ chú thích / tính vào coverage / loại khỏi R gộp / hủy | mở từ 2026-10-07 |

**F. Quy trình**

| ID | Quyết định | Nguồn | Phương án | Nếu để nguyên |
|---|---|---|---|---|
| R-30 | Trình lại các con số tiền owner chưa thật sự chọn, kèm hậu quả | G-1603, G-2103 | một ví dụ USDT cho mỗi số: `max_unprotected_ms`, `entry_terminal_timeout_ms`, slippage 1/3 bps, `cluster_cap`, sàn utilisation 60 %, 418 = 3 ngày, 429 = 120 s, N = 3 lượt/tuần, sizing mép bất lợi; thêm giá trị provenance như `ASSISTANT_DEFAULT_ACCEPTED` | mặc định của trợ lý giữ nhãn DECISION và không bị chất vấn |
| R-31 | Quy tắc đóng success criteria | G-1604 | "library level" = PARTIAL cho tới khi có test tiến trình ghép hoặc evidence Demo; hay giữ | tiêu chí tiếp tục được đóng bằng chứng minh ở mức thư viện |
| R-32 | Một sổ duy nhất cho mục mở (gộp G-1751 từ X07) | G-1600, G-1751 | dùng bảng này làm sổ, bỏ "Open user decisions" của STATE và mục 1 của 19-OWNER-GAPS; DATA-02/DATA-04 đánh dấu Partial ngay hay giữ tick tới Phase 26 (mỗi ngày OI không thu là mất hẳn sau cửa sổ API 30 ngày) | ba sổ lỗi thời; trạng thái Complete sai |
| R-33 | Key tùy chọn `NOT_CONFIGURED` | `config/execution/execution-limits-v1.toml:80,84` | `rest_gate.ban_end_clock_margin_ms` (không đặt: fallback 418 của R-07); `scheduler.duration_summary_interval_ms` (không đặt: chỉ ghi dòng khi có max mới) | như mô tả; không key nào chặn start |
| R-34 | Kiểm tra Demo chưa làm và điều Demo không thể cho thấy | 19-OWNER-GAPS 2a; 25 Q-G | Partial fill (P3/A5) và race fill/cancel (P7) không tạo được trên Demo; GTD (A2) vẫn NEW 840 s sau goodTillDate. Chấp nhận là thấy lần đầu ở canary với fallback viết sẵn, hay thiết kế một quan sát read-only / kích thước tối thiểu trên mainnet | các đường này lần đầu chạy bằng tiền thật |

### 15.2 R-35..R-51 (bổ sung từ các lane hoàn thành sau)

| ID | Quyết định | Nguồn | Phương án, ví dụ số | Nếu để nguyên |
|---|---|---|---|---|
| R-35 | Fills ledger trước Demo campaign Phase 25? | G-1101 (data_persistence_db) | Hiện một trade Demo khớp, chạm stop, đóng chỉ để lại một row `orders` NEW và 0 row `fills`; campaign 20 trade -3R báo 0 trade. (a) xây writer fills và vòng đời trước campaign; (b) đánh giá campaign từ lịch sử trade xuất tay từ Binance (sàn chỉ giữ trong một cửa sổ thời gian); (c) chấp nhận và ghi lại | campaign không đánh giá được từ DB; analytics live mù |
| R-36 | Quy tắc khoảng trống của Demo soak; `owner_round_trips_per_week` có được null? | G-1302, G-1303 (scripts_tooling) | Như trial paper (D061: ≥ 95 % của 14 ngày = 319,2 h/336 h). Với 21 ngày (504 h), 95 % cho phép 25,2 h downtime; evaluator hiện cho qua ≈ 502 h | PASS không chứng minh vận hành liên tục; 0 trade vẫn PASS |
| R-37 | Đánh dấu DEMO/LIVE trong chính DB vận hành | G-0503, G-1301 (scripts_tooling) | DB mang marker mode mà mọi script owner và tiến trình live so với `LIVE_RUNTIME_MODE`, thay vì tin biến shell | một script Demo có thể ghi vào DB live nếu env sai |
| R-38 | Thế nào là "Demo-proven" trước Phase 26; evidence phải ghi commit | G-1503, G-1501 (evidence_reproducibility) | Hiện một fill taker tức thì đóng tay đại diện cho cả mô hình bảo vệ. Ví dụ: LONG limit thấp hơn giá 1 % khớp sau 3 giờ được 40 %, rồi stop trigger: không bước nào đã chạy trên Demo. (a) chấp nhận smoke ghép như hiện tại; (b) cần mỗi thứ một lần trên Demo: fill chờ, partial fill, stop trigger, TP1 rồi resize stop; (c) (b) + N lần lặp (vd 5) chuỗi cơ bản để bắt lag đọc thất thường như lần lỗi 08:32Z. Run không có commit hash có được đóng mục không | các mục "demo-observed" bị đọc rộng hơn bằng chứng |
| R-39 | RPO của journal live | G-1202 (ops_deploy_security) | Hiện một dump/ngày lúc 03:15 UTC. Host chết lúc 02:00 UTC sau một ngày 3 approval, 3 entry và stop: DB khôi phục không biết gì, hệ thống phải tìm lại 3 vị thế từ Binance (dự kiến SAFE_MODE tới khi reconcile tay). Giữ daily; dump mỗi giờ (24× dung lượng); WAL archiving | tới 24 h journal mất khi mất host |
| R-40 | Backup lỗi báo cho owner bằng cách nào | G-1201 (ops_deploy_security) | alert Telegram từ job backup; check heartbeat ngoài thứ tư chỉ ping khi thành công (monitor báo khi im ví dụ 26 h); hoặc cả hai | backup lỗi chỉ thấy khi tự vào `systemctl status` |
| R-41 | Quyền của credential backup | ops_deploy_security | Key S3 của job có thể xóa snapshot (retention cần). Chọn thời hạn object-lock (vd 35 ngày phủ tầng 4 tuần) và lifecycle cho noncurrent version | key bị đánh cắp có thể xóa backup nếu versioning/object-lock chưa bật |
| R-42 | Chạy gate S3 thật và diễn tập restore thật trước Phase 26 (KNOWN, gộp F-121) | ops_deploy_security; X07 F-121 | chạy trước Phase 26, hay chấp nhận rủi ro | chưa backup nào được chứng minh với provider thật |
| R-43 | Kênh alert thứ hai | G-2003 (operator_golive_gap) | Telegram mất 02:00–07:00, 0,5 ETH ở 3000 bị trần lúc 02:10 (trường hợp G-0300). A: chỉ Telegram (owner biết lúc 07:00; giá ngược 5 % = 75 USDT). B: cho liveness probe fail khi có plan UNPROTECTED / CLOSE_REQUIRED / CLOSE_FAILED hoặc alert CRITICAL chưa giao, để healthchecks.io (email/SMS) báo trong ≈ 3 phút | mọi trạng thái nguy hiểm chỉ đi qua một kênh |
| R-44 | Quy tắc dừng khi update | G-2004 (operator_golive_gap) | Vị thế đã được bảo vệ có được để mở qua một lần dừng có kế hoạch (stop vẫn trên sàn), hay owner muốn mọi trade đóng trước | quy tắc hiện tại chặn mọi lần dừng/update tới khi mọi trade kết thúc |
| R-45 | Signal chiến lược trong tiến trình live | G-1052 (paper_gapfill) | Hiện chỉ có plan smoke (một LONG cỡ tối thiểu BTCUSDT). (a) đặt tên một phase trước soak Phase 25 đưa plan của detector SHADOW vào sender live ở DEMO, và lấy "plan chiến lược được đặt trên Demo" làm tiêu chí Phase 25; (b) giữ nguồn smoke và chấp nhận lệnh chiến lược đầu tiên xảy ra ở canary Phase 26 bằng tiền thật (sub-account 50–100 USD); (c) khác. (b) để lại chưa chứng minh: bar 1h đóng 10:00:00, plan phải tới Telegram, được duyệt, xác nhận và còn 900 s hiệu lực lúc đặt | đường strategy → lệnh chưa từng chạy với plan thật trước tiền thật |
| R-46 | File attribution của soak; mất mát của stream persistence | G-1050, G-1051 (paper_gapfill) | chấp nhận file analytics đưa tay (manifest phải ghi rõ) hay bắt buộc dựng từ journal; chấp nhận "analytics có thể cũ sau DB outage" hay bắt buộc replay ghi lỗi trước khi dùng báo cáo live làm evidence | evidence soak có phần không dẫn xuất từ journal |
| R-47 | Holdout "dùng một lần" chặt tới đâu | G-0950 (backtest_gapfill) | Holdout run 1: 2026-05-10..2026-10-03 (146 ngày). Hiện v5.0.0 đánh giá một lần, v5.1.0 (đổi một tham số sau khi thấy v5.0.0 trượt) thêm một lần... (a) một lần đánh giá mỗi cửa sổ holdout, sau đó cần cửa sổ mới; (b) số lineage nhỏ cố định mỗi cửa sổ, ép bằng code; (c) giữ (chỉ đếm). Có từ chối manifest có Development/Validation trùng holdout đã dùng không | mỗi lần nhìn tăng xác suất chấp nhận một lần pass may mắn |
| R-48 | Code kiểm hạn chế API key | G-1752 (prior_findings_closure_b) | A: tiến trình live kiểm khi start và từ chối key có quyền rút hoặc không giới hạn IP (thêm một GET ký mỗi lần start). B: giữ cam kết của owner và lặp lại mỗi lần xoay key. Với 1.000 USDT, key rò rỉ không hạn chế có thể chuyển toàn bộ 1.000 USDT; mọi gate rủi ro chỉ giới hạn một trade ≈ 5 USDT | lỗi duy nhất có thể mất cả số dư chỉ được chặn bằng lời hứa |
| R-49 | Phạm vi gate paper exit (F-023 / D061 mục D) | prior_findings_closure_b | giai đoạn forward có so tỷ lệ fill, slippage và độ trễ approval thực tế với mô hình trước CANARY không, hay để việc hiệu chỉnh chi phí cho Demo campaign và canary | bằng chứng edge chỉ dựa vào run 1 |
| R-50 | CI chứng minh test DB đã chạy như thế nào | G-1401 (test_effectiveness_ci) | Merge PR #3 ngày 2026-11-15 mang Phases 20–25 (≈ 18.300 test, 872 PG). (a) giữ job tuần tự 30 phút và ghi thời lượng/kết quả mỗi lần; (b) CI chạy `-n 4` (dự án đo cùng số pass/skip), giữ chạy tuần tự cho gate có ghi; (c) (b) + CI trên mọi push `develop`. Mỗi cách tốn phút runner; (a) có thể đơn giản là timeout | không biết test PG có chạy trên commit nào kể từ 2026-10-20 |
| R-51 | Fake exchange có lag mặc định không | G-1400 (test_effectiveness_ci) | Bật lag mặc định sẽ làm đỏ một số test hiện có (giả định nhất quán tức thì); giữ opt-in thì bắt lỗi lag chỉ do may mắn | lỗi kiểu G-0300/G-0250 tiếp tục lọt qua test |

### 15.3 Gộp trùng khi mở rộng

- operator_golive_gap O-2 (restart policy, G-2007) → gộp vào R-01; O-1 → R-43; O-3 → R-44.
- prior_findings_closure_a (G-1700) → gộp vào R-24.
- prior_findings_closure_b mục 2 (DATA-02/04, G-1751) → gộp vào R-32.
- backtest_research_analytics O-1..O-3 đã ở R-25, R-26; failure_scenarios O-1..O-3 đã ở R-01, R-03.
- mutation_probe: không có mục owner.


### 15.4 R-52..R-55 (lane X11, khả năng sống của strategy — xem mục 9a)

| R | Việc cần quyết | Nguồn | Phương án và ví dụ bằng số | Nếu để nguyên |
|---|---|---|---|---|
| R-52 | Đi tiếp, tạm dừng để làm research run 2, đổi hướng, hay dừng | G-2300 (strategy_viability OD-1) | (a) đi tiếp: khoảng 3–6 tháng owner tham gia, kết thúc ở một cổng sẽ từ chối nếu không có ứng viên; (b) 1–2 tuần viết luật + bổ sung dữ liệu + khoảng 25 giờ máy, trả lời được có lợi thế +0,1–0,2 R hay không; (c) đổi family/khung/thị trường, vài tuần; (d) không tốn thêm | Kỹ thuật tiếp tục xây trên một strategy chưa có bằng chứng; kill gate có thể kích hoạt 2027-03-19 |
| R-53 | Lợi thế tối thiểu run 2 muốn phát hiện, và lượng dữ liệu tương ứng | G-2301 (OD-2) | +0,1 R ở family A với một phép thử đăng ký trước, sức mạnh 80 %: khoảng 790 lệnh ≈ 19 tháng dữ liệu 12 symbol; +0,2 R: khoảng 200 lệnh | Run 2 lặp lại điểm yếu của run 1: chỉ thấy được lợi thế lớn |
| R-54 | Bắt buộc mọi family vào run 2 phải có nguồn hoặc cơ chế được viết ra | G-2303 (OD-3) | Có: ít giả thuyết hơn, mỗi cái có lý do; Không: grid rộng hơn nhưng tốn alpha cho ý tưởng không có cơ sở | Run 2 có thể lại thử những setup không có cơ sở |
| R-55 | Tuyên bố trước khi soak Phase 25 và PAPER-03 bắt đầu rằng kết quả của chúng chỉ là bằng chứng về đường ống | G-2302 (OD-4) | 100 lệnh paper cho sai số chuẩn 0,11 R: không phân biệt được +0,1 R với -0,1 R | Kết quả paper/Demo có thể bị đọc nhầm là bằng chứng có lời |

---

## 16. Giới hạn của audit

- **PostgreSQL**: test `*_pg.py` (X03 đếm 872 case) bị skip trong lần chạy của audit (`TEST_DATABASE_URL`
  cố ý để trống). Các khẳng định về SQL (consume approval, advisory lock, race APPROVE/expiry, system-state
  version) được lập luận từ văn bản SQL, không chạy trên PostgreSQL.
- **Không Docker, không Demo, không host**: suite docker, script Demo, `pytest -m demo`, heartbeat, systemd,
  compose và backup S3 thật không được chạy. Evidence Demo được đọc, không tái tạo. Không có quan sát
  mainnet nào: mọi severity mainnet là suy luận từ code, docs chính thức và quan sát Demo đã ghi.
- **CI không biết**: không có kết quả GitHub Actions nào được ghi trong repo; owner phải tự kiểm (G-1401).
- **Độ phủ**: 135k dòng `src` không thể đọc sâu hết; 68 file `src/*.py` chỉ được phủ bởi dòng nhóm hoặc văn
  bản lane, và 146 file trong `src/`, `scripts/`, `deploy/`, `config/`, `docs/` không có dòng riêng trong
  `FILE_COVERAGE.md`. Vùng mỏng nhất: phần lớn `src/analytics`, một số module `src/persistence`, nhiều file
  systemd và docs.
- **Khả năng xảy ra chưa chứng minh**: một số HIGH là cơ chế đã xác nhận nhưng tần suất trên mainnet chưa
  biết (G-0300 cần `positionRisk` trả rỗng hai lần; G-0700 cần 418 không Retry-After; G-0703 hình dạng wire
  chưa quan sát).
- **Nghiên cứu**: khoảng bootstrap thật của run 1 không tính lại được (danh sách trade không còn); số liệu
  lấy từ file text không gắn hash (mục 9.1). Charter chỉ cho phép xét phương pháp, không đánh giá lợi nhuận.
- **Telegram**: core.telegram.org trả 403, nên các fact Telegram (giới hạn 64 byte, một consumer mỗi token)
  dựa trên trí nhớ của lane và được ghi UNVERIFIABLE.
- **Lane X11** (`strategy_viability`) chạy sau khi báo cáo này được viết; finding G-2300.. của nó không có
  trong `findings.json` và không được tính trong bất kỳ con số nào ở đây (mục 9a).
- **Tác nhân**: audit do các agent AI thực hiện (một phần lane chạy trên Fable rồi được Opus tiếp tục từ file
  dở dang sau giới hạn sử dụng). Mọi CRITICAL/HIGH đã qua verifier mù, nhưng các MEDIUM/LOW chỉ có một lane
  đứng sau (trừ các mục được hai lane độc lập cùng thấy, như G-0901/G-2101, G-2100/G-2201, G-0250/G-2104).
- **Severity hai thang**: "now" thấp vì placement tắt; nó không có nghĩa là vấn đề nhỏ khi bật placement.
