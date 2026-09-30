# BÁO CÁO KIỂM TOÁN SÂU (DEEP AUDIT REPORT): Hệ thống nghiên cứu & bán tự động Binance Futures

> Snapshot `63ca176` · Ngày 2026-09-29 · Kiểm toán forensic, **chỉ đọc**. Không sửa, không test mới, không đụng repo gốc.
> Ngôn ngữ: tiếng Việt. Định danh kỹ thuật (đường dẫn, tên hàm, ID, thuật ngữ Binance như STOP_MARKET, clientOrderId) giữ tiếng Anh.
> Nguồn sự thật: `findings.json` (đã merge, có severity cuối sau verification), `verification/V1..V5_*_result.md`, `lanes/*.md`, `INVARIANTS.md`, `FILE_COVERAGE.md`, `tool-output/*`.

---

> ## ĐỌC NHANH (1 phút)
>
> - **Có an toàn để giao dịch tiền thật hôm nay không? KHÔNG.** Hiện tại hệ thống **không thể** đặt lệnh thật. Chưa có process nào nối APPROVE với đặt lệnh, chưa có tầng lưu trữ (persistence), chưa có user-data stream (F-201, F-202, F-104). Nếu nối dây ngay bây giờ, audit đã xác nhận (verifier độc lập) một chuỗi lỗi có thể để **vị thế không có stop-loss** hoặc **vào lệnh trùng**: F-401, F-701, F-702, F-126, F-007, F-302, cùng F-501 (cần testnet để chốt).
> - **Có tin được kết quả backtest không? KHÔNG.** Simulator lấy kết quả khớp lệnh và thoát lệnh từ **chính cây nến đã sinh tín hiệu**. Probe cho thấy thời điểm thoát còn *sớm hơn* thời điểm vào lệnh 59 phút (F-120/F-901). Simulator còn tính "chạm vùng" là "khớp ở giá giữa vùng" (F-902). Mọi bằng chứng backtest tới nay phải coi là **vô hiệu**.
> - **Tài liệu và kế hoạch do AI sinh có lỗi thiết kế thật**, không chỉ lệch với code. Ví dụ:
>   - Protocol nghiên cứu **đảo ngược** nguyên tắc pre-registration: ngưỡng pass được đặt *sau* khi xem kết quả, và không hiệu chỉnh cho việc thử nhiều biến thể (F-022/F-903).
>   - Kế hoạch Phase 8 tin rằng "sàn tự chống trùng clientOrderId". Sai: Binance chỉ chống trùng giữa các lệnh **đang mở** (F-951 → F-126).
>   - `partial_fill_fraction = 0.5` được chọn vì tiện cho việc hash, không có lý do giao dịch (F-006/F-957).
>   - Cấu hình SL MARK_PRICE không khớp với backtest (F-958).
>   - ROADMAP xếp các sửa lỗi an toàn tiền **sau** phase go-live (F-954).
> - **Số liệu:** 164 finding thô → **152 finding chính** (11 trùng, 1 bị bác bỏ: F-008). Phân bố: **0 CRITICAL · 12 HIGH · 91 MEDIUM · 45 LOW · 4 INFO**. 50 finding chính chưa ở mức CONFIRMED (36 PROBABLE, 13 SUSPICIOUS, 1 UNVERIFIED).
> - **Điểm tốt thật sự:**
>   - Lõi thuần (`src/core`, `src/domain`, `src/risk`) tách lớp sạch và dùng Decimal ở mọi giá trị tiền.
>   - Lượng tử hoá luôn làm tròn xuống, NO_TRADE được ưu tiên hơn làm tròn lên.
>   - Không bao giờ retry mù lệnh POST. SL `closePosition` được đặt trước khi entry khớp.
>   - Không có secret nào bị commit.
>   - 1268 test pass và chạy tất định (deterministic).
> - **Việc cần làm trước tiên (P0):** thêm một phase "runtime composition + persistence" có ràng buộc symbol/side (F-302) và tiêu thụ approval bền vững (F-126). Làm cứng reconcile (F-401, F-701, F-711, F-702). Đưa P11–P15 lên **trước** mọi lệnh live. Gọi testnet để xác minh mã lỗi (F-501). Viết lại simulator theo quan hệ nhân quả **trước khi** tin bất kỳ bằng chứng nào (F-120, F-902).

---

## Mục lục

1. [Định danh audit](#1-định-danh-audit)
2. [Tóm tắt điều hành](#2-tóm-tắt-điều-hành)
3. [Phạm vi bao phủ](#3-phạm-vi-bao-phủ)
4. [Phương pháp](#4-phương-pháp)
5. [Finding CRITICAL](#5-finding-critical)
6. [Finding HIGH](#6-finding-high)
7. [Finding MEDIUM](#7-finding-medium)
8. [Finding LOW / INFO, trùng lặp, bị bác bỏ](#8-finding-low--info-trùng-lặp-bị-bác-bỏ)
9. [Kết quả kiểm tra bất biến nghiệp vụ](#9-kết-quả-kiểm-tra-bất-biến-nghiệp-vụ)
10. [Lệch tài liệu / kế hoạch](#10-lệch-tài-liệu--kế-hoạch)
11. [Hồi quy xuyên phase](#11-hồi-quy-xuyên-phase)
12. [Rủi ro kiến trúc](#12-rủi-ro-kiến-trúc)
13. [Rủi ro dữ liệu / đồng thời](#13-rủi-ro-dữ-liệu--đồng-thời)
14. [Rủi ro tích hợp](#14-rủi-ro-tích-hợp)
15. [Rủi ro bảo mật / độ tin cậy](#15-rủi-ro-bảo-mật--độ-tin-cậy)
16. [Khoảng trống kiểm thử](#16-khoảng-trống-kiểm-thử)
17. [Vùng đã xác minh là an toàn](#17-vùng-đã-xác-minh-là-an-toàn)
18. [Vùng chưa xác minh / đáng ngờ](#18-vùng-chưa-xác-minh--đáng-ngờ)
19. [Khuyến nghị khắc phục](#19-khuyến-nghị-khắc-phục)
20. [Hạng mục cần quyết định nghiệp vụ của con người](#20-hạng-mục-cần-quyết-định-nghiệp-vụ-của-con-người)
21. [Giới hạn của audit](#21-giới-hạn-của-audit)

---

## 1. Định danh audit

| Mục | Giá trị |
|---|---|
| Repository | `C:\Users\admin\Music\Trading` (branch `master`) |
| Commit được audit | `63ca17686137d037ec7d8d9283f99259c3a4d27e` (`63ca176`, không có tag) |
| Trạng thái bẩn lúc snapshot | `M .planning/state.json` (thay đổi cục bộ có sẵn từ trước, không phải của audit) và `?? Trading.7z` (file nén chưa track, không được audit). Audit chỉ xét **cây đã commit**. |
| Bản snapshot (đầu vào chỉ đọc) | `C:\Users\admin\Music\project-audit\2026-09-29_63ca176\snapshot`: `git clone --no-hardlinks`, detached tại SHA. Dùng clone thay cho `git worktree` vì worktree ghi vào `.git` của repo gốc. |
| Thư mục kết quả | `C:\Users\admin\Music\project-audit\2026-09-29_63ca176\` |
| Baseline repo gốc | `baseline/` (status, diff, hash các file bẩn, stash, worktrees) |
| Thời điểm bắt đầu | 2026-09-29T11:02:07Z |
| Hệ điều hành | Windows 10 Enterprise 10.0.19045, Git Bash + PowerShell 7 |
| Công cụ | Python 3.13.15 (`.venv` của repo), uv 0.12.20, git 2.49.0, node 24.18.0, ruff 0.16.8, mypy 2.3.1, pytest 9.1.1, CodeGraph CLI (chỉ đọc). Không có semgrep/CodeQL. |
| Kết quả công cụ (`tool-output/`) | pytest: **1268 passed, 7 skipped** (5 skip PG mapper, 1 skip PG analytics store, 1 skip symlink trên Windows), 180 s. mypy `--strict src`: **5 lỗi / 4 file**; lane L6 đã kiểm từng lỗi, cả 5 đều là nhiễu kiểu, không phải bug runtime. ruff check: **36 lỗi** (23 tự sửa được). ruff format `--check`: **98 file** cần format. Snapshot vẫn sạch sau khi chạy tool. |
| Mô hình kiểm toán | 13 lane (subagent context mới), 5 lô verifier mù (V1–V5). Chỉ có một mô hình AI thực hiện, không có mô hình thứ hai để kiểm chéo (xem §21). |

---

## 2. Tóm tắt điều hành

### 2.1 Kết luận thẳng thắn

**Hệ thống có an toàn để giao dịch tiền thật hôm nay không? KHÔNG, và hiện cũng chưa thể.**

Mọi đường đi của lệnh live mới chỉ là **thư viện**, chưa có ai gọi:
- `execute_approved_plan`, `enable()`, reconciler, sweeper và Telegram app builder không có caller nào trong `src/` (F-201, xác nhận M1–M4 của v0.3-MILESTONE-AUDIT, thêm M5–M8).
- Không có cài đặt PostgreSQL cho journal/approval (F-202).
- Không có user-data stream (F-104).

Vì vậy nhiều lỗi dưới đây đang **tiềm ẩn**: chúng sẽ bộc lộ ngay khi có người "nối dây" theo đúng thiết kế hiện tại. Các verifier độc lập giữ mức HIGH vì chính thiết kế này là đường đi duy nhất dự kiến cho giai đoạn live (V2, V3, V5).

**Kết quả backtest có đáng tin không? KHÔNG.**
- Simulator dùng dữ liệu trước thời điểm quyết định để quyết định khớp và thoát lệnh (F-120/F-901, V1 CONFIRMED).
- Simulator khớp ở giá mà nến chưa từng giao dịch (F-902, V1 CONFIRMED).
- Simulator giữ lệnh tối đa một nến và thoát 100% tại TP1, trong khi live có TP1/TP2 (F-102).
- Simulator trừ slippage sai đơn vị (F-306), bỏ qua funding (F-905), và đóng băng trạng thái danh mục trong suốt lượt chạy (F-305).
- Cộng thêm: ngưỡng pass được đặt sau khi xem kết quả (F-022). Hiện **không có bằng chứng nghiên cứu nào hợp lệ** để chọn chiến lược hay bật live.

### 2.2 Tám rủi ro hàng đầu (ngôn ngữ đời thường)

1. **Backtest "nhìn trước tương lai".** Simulator lấy chính cây nến sinh tín hiệu để quyết định lệnh khớp và chạm SL/TP. Probe: vào lệnh 09:59:59, thoát tại SL lúc 09:00:59, tức là thoát trước khi vào (F-120, V1). Kết hợp với "chạm mép vùng là khớp ở giữa vùng" (F-902), mọi con số expectancy hay kill gate đều vô nghĩa.
2. **Quy trình chọn chiến lược dễ tự lừa mình.**
   - Ngưỡng pass là TBD cho tới khi đã thấy kết quả Validation. "Pass" là quyết định của người, và không hiệu chỉnh cho việc thử khoảng 25 biến thể trở lên (F-022, V4).
   - `enable()` cho phép bật live ở trạng thái WITHIN_BUDGET, tức là chưa family nào pass (F-953).
   - Với người dùng không chuyên, đây là con đường ngắn nhất để đưa một chiến lược "may mắn trên dữ liệu" vào tiền thật.
3. **Vào lệnh trùng.**
   - Nếu Telegram gửi lại callback (at-least-once) hoặc process restart sau khi lệnh đầu đã khớp hoặc đã huỷ, `execute_approved_plan` đặt lại entry mới (F-126, V2 probe: 2 lần `place_entry`).
   - Khi lệnh đầu đã khớp, lệnh trùng dùng chung SL `closePosition`. Lỗ khi chạm SL vì vậy gấp đôi rủi ro dự kiến: với equity $1.000 và rủi ro 0,5%, lỗ là khoảng $10 thay vì $5 (L3; số $5 là ngân sách trong probe V5).
   - Reconcile vẫn báo "khớp" (agreement=True) cho vị thế bị nhân đôi (F-701).
4. **Stop-loss có thể biến mất.**
   - Sweeper coi SL đặt sẵn của một entry đang chờ là "mồ côi" và huỷ nó. Entry khớp sau đó sẽ không có stop (F-401, V3).
   - Không có kiểm tra giá sau APPROVE: nếu giá đã xuyên SL trong 4 giờ chờ, LIMIT khớp ngay còn SL bị sàn từ chối (F-007, V4).
   - Hệ thống cố ý không đặt lại stop ("no rescue", F-952).
   - Nếu mã lỗi "không tìm thấy algo order" của Binance khác -2011 (chưa có tài liệu, cần testnet), SL **không bao giờ** được đặt và mọi lệnh đều rơi vào SAFE_MODE (F-501, INSUFFICIENT_EVIDENCE).
5. **Mất DB = mất phanh.** Journal được ghi trước hành động. Khi PostgreSQL/journal lỗi, lệnh huỷ entry, tắt live (kill switch) và đóng khẩn cấp đều không được gửi tới sàn (F-702, V2 probe).
6. **Lệnh không bị ràng buộc với plan đã duyệt.**
   - Symbol và chiều (LONG/SHORT) lấy từ tham số do caller truyền vào, không lấy từ plan đã hash. Probe: đảo side thì đặt SELL với stop nằm sai phía, vẫn trả `OK` (F-302, V5; sẽ thành CRITICAL khi nối dây).
   - Số lượng cũng được tính lại lúc đặt lệnh, không so với plan (F-203: golden đặt 3,311 so với 0,500 trong plan).
7. **Kinh tế học của lệnh trend-pullback sai.**
   - SL nằm *bên trong* vùng entry, chỉ cách 0,2 ATR (khoảng 0,133% trên BTC). Chi phí bằng khoảng 60% rủi ro. "Pullback" kích hoạt ngay trên nến vừa tạo đáy mới (F-301, V5).
   - Cộng với lỗi đơn vị phí (F-001/F-801, KNOWN P11), lỗ tại SL có thể lên tới khoảng 1,4–3,2 lần ngân sách (F-301 impact).
8. **Chưa có gì chạy thật.**
   - Collector OI chưa từng được deploy. Dữ liệu OI quá 30 ngày mất vĩnh viễn mỗi ngày (F-107).
   - Paper soak không khởi động được vì thiếu một `await` (F-125).
   - Backup không off-host và không restore thật (F-108, F-121).
   - Không có cảnh báo vận hành nào (F-106).

### 2.3 Những gì thật sự tốt (đã được lane xác minh, §17)

- **Lõi thuần (pure core):** `src/core`, `src/domain`, `src/risk` không import SDK, ORM hay I/O. SDK Binance chỉ nằm trong adapter (L2).
- **Decimal ở mọi giá trị nhạy cảm với sàn:** `_decimal_to_wire` dùng `format(value, "f")`, không float và không dạng số mũ (L2, L5). DB dùng `Numeric(38,18)` (L4).
- **Lượng tử hoá đúng:** làm tròn xuống theo stepSize, rồi kiểm minQty, rồi minNotional, rồi 60% realized-risk. Không làm tròn lên. Test là oracle thật, không phải bản sao code (L3, L6).
- **Không retry mù:** không retry mù lệnh POST, luôn probe theo client id trước. Không rõ position mode thì không đặt lệnh (L5, L7).
- **SL đặt trước khi khớp:** SL `closePosition=true` được đặt ngay sau khi entry được ACK, trước khi khớp. Điều này tốt hơn cả docs. F-008 bị bác bỏ vì lý do này (V4).
- **Primitive duyệt lệnh đúng:** token 256-bit, `hmac.compare_digest`, hết hạn tính bao gồm biên, không tự duyệt khi Telegram lỗi. Live mặc định ở trạng thái `LIVE_ORDERS_DISABLED` (L7, L3).
- **Hygiene:** không có secret nào bị commit. Dependency được ghim qua `uv.lock`, không dùng connector Binance đã archive (L7).
- **Test:** 1268 test pass và tất định (L6). Kill gate D030 có quy tắc kích hoạt đúng (B2).

### 2.4 Phát hiện chính: bản thân docs/plan (AI sinh, tự chọn mặc định) có lỗi thiết kế

User đã nói rõ `docs/` do AI sinh, và phần lớn quyết định trong `.planning/` là phương án "recommended" mà AI tự chọn. Audit xác nhận nhiều lỗi nằm ngay ở tầng thiết kế, trước khi viết code:

| Tầng | Lỗi thiết kế tiêu biểu | ID |
|---|---|---|
| docs (stage A) | Protocol đặt ngưỡng pass sau khi xem kết quả, không hiệu chỉnh đa kiểm định | F-022 (HIGH) |
| docs | Không yêu cầu kiểm tra giá sau APPROVE, không có phương án dự phòng khi SL bị từ chối sau khi khớp | F-007 (HIGH) |
| docs | Công thức sizing không có đơn vị cho chi phí | F-001 |
| docs | SAFE_MODE mâu thuẫn với RUNBOOK (cấm cả lệnh bảo vệ) | F-009 |
| docs | Giới hạn 200 algo order ghi "theo symbol" (thực tế là toàn tài khoản); "TradingView HMAC" là bất khả thi | F-051, F-052 |
| plan (stage B) | 01-RESEARCH gọi pre-registration là "overfitting" | F-903 → F-022 |
| plan | 06-01-PLAN quy định khớp và thoát trên cùng nến tín hiệu | F-901 → F-120 |
| plan | 08 D-04: "sàn chống trùng clientOrderId", nên từ chối lưu trạng thái cục bộ | F-951 → F-126 |
| plan | 07.1: `partial_fill_fraction = 0.5` vì tiện cho hash | F-957 → F-006 |
| plan | 09: `workingType=MARK_PRICE` không có quyết định ghi nhận | F-958 |
| plan | ROADMAP: sửa lỗi an toàn tiền nằm sau go-live | F-954 |
| plan | Checkpoint một chiều do auto-executor tự xoá | F-124, F-809 |

Sổ quyết định của lane B1/B2 (§10.2) đánh giá khoảng 105 quyết định. Phần lớn là SOUND, nhưng có **7 WRONG, 19 QUESTIONABLE, 13 RISKY-DEFERRAL** (đếm theo nhãn đứng đầu mỗi dòng).

---

## 3. Phạm vi bao phủ

Nguồn: `FILE_COVERAGE.md`, tổng hợp bằng `tmp/merge.py` từ bảng Coverage của từng lane. Mức của mỗi file là **mức cao nhất** mà bất kỳ lane nào ghi nhận. Tổng cộng 639 file được track (`MANIFEST.md`).

| Mức | Số file |
|---|---|
| DEEP_READ | 120 |
| NORMAL_READ | 218 |
| METADATA_ONLY | 254 |
| EXCLUDED | 47 |

| Loại | DEEP_READ | NORMAL_READ | METADATA_ONLY | EXCLUDED |
|---|---|---|---|---|
| ci | 3 | 0 | 0 | 0 |
| config | 3 | 2 | 0 | 1 |
| config-params | 10 | 0 | 0 | 0 |
| doc | 24 | 5 | 2 | 2 |
| infra | 2 | 0 | 0 | 0 |
| migration | 4 | 0 | 2 | 0 |
| planning | 32 | 103 | 43 | 44 |
| script | 3 | 3 | 7 | 0 |
| source | 36 | 27 | 37 | 0 |
| test | 2 | 25 | 66 | 0 |
| test-fixture | 1 | 53 | 97 | 0 |

**Ý nghĩa của EXCLUDED:** đây là file **không lane nào ghi vào bảng coverage**. Audit không dựa vào nội dung của chúng, nhưng cũng không khẳng định chúng an toàn. 47 file EXCLUDED gồm:
- 44 file planning: các `*-PATTERNS.md`, `*-VALIDATION.md`, `COVERAGE.md`, một số `*-PLAN.md` của phase 03/04/07, `.planning/research/*`, `.gitkeep` của phase 12–17, `.planning/state.json`.
- 2 file doc: `docs/README.md` và `docs/implementation/AGENT_INSTRUCTIONS.md`.
- 1 file config: `.gitattributes`.

**Lưu ý bao phủ quan trọng:** 37 file source chỉ ở mức METADATA_ONLY, gồm gần như toàn bộ `src/analytics/*` (kể cả `killgate.py`, `family.py`, `stats.py`), `src/backtest/binding.py`, `src/paper/freeze.py`, `src/domain/order.py|fill.py|position.py`. Kết luận về kill gate trong báo cáo này dựa trên planning, lane B2 và `enablement.py`, **không** dựa trên việc đọc sâu `src/analytics/killgate.py` (L3 open question 3: "only skimmed killgate.evaluate").

---

## 4. Phương pháp

### 4.1 Luồng ba giai đoạn (charter §11)

Theo yêu cầu của user, audit chạy **tuần tự docs → plan → code**. Code được đánh giá theo **quy tắc đã hiệu chỉnh**, không theo docs một cách mù quáng.

| Giai đoạn | Lane | Dải ID | Kết quả |
|---|---|---|---|
| **A: tính đúng đắn của docs** | A1 `docs_trading_soundness` | F-001…F-049 | 31 finding. Sinh ra 37 "Corrected Rules for Code Audit". |
| | A2 `docs_exchange_facts` | F-051…F-099 | 8 finding. Bảng "Exchange Facts for Code Audit" đối chiếu developers.binance.com, SDK 17.4.0 và Bot API. |
| **B: quyết định kế hoạch** | B1 `planning_decisions_01_06` | F-901…F-949 | 10 finding + sổ quyết định phase 01–06 |
| | B2 `planning_decisions_07_17` | F-951…F-999 | 17 finding + sổ quyết định phase 07–17 |
| | L1 `requirements_docs_plan` | F-101…F-199 | 28 finding + ma trận truy vết 30 REQ |
| **C: code** | L2 `architecture_code` | F-201… | 9 |
| | L3 `business_invariants` | F-301… | 7 |
| | L4 `data_database_concurrency` | F-401… | 13 |
| | L5 `integrations_external_apis` | F-501… | 9 |
| | L6 `testing_verification` (chạy tool an toàn) | F-601… | 9 |
| | L7 `security_reliability` | F-701… | 11 |
| | L8 `historical_regression` (git history, plan→commit) | F-801… | 12 |

**Lưu ý về "Corrected Rules":** các quy tắc như "Rule 14" hay "Rule 24" là **quy tắc do lane A1 của audit đề xuất**, dựa trên thực hành giao dịch và tài liệu Binance công khai. Chúng **không** có trong `docs/` của snapshot. Verifier V3 và V5 đã chỉ ra điểm này. Vì vậy khi finding viện dẫn chúng, đó là *khuyến nghị* chứ không phải yêu cầu sẵn có của dự án. Mức tin cậy của các ngưỡng số trong đó (2/5 bps, trần chi phí 0,15, trần leverage 5x, 60 s/90 s) do chính A1 ghi là **Medium**.

### 4.2 Verification mù (charter §6)

- **Mọi** finding HIGH ở cấp lane (25 finding) đều được gửi cho verifier với context mới. Verifier chỉ nhận đường dẫn snapshot, phát biểu của finding và vị trí bằng chứng, **không** nhận lập luận của lane. Verifier tự lần lại code và chạy probe riêng (`tmp/verify_*`).
- Có 5 lô: V1 backtest, V2 execution, V3 reconcile, V4 docs/plan, V5 invariants.
- Kết quả: **13 CONFIRMED, 10 DOWNGRADED, 1 REJECTED (F-008), 1 INSUFFICIENT_EVIDENCE (F-501)**.
- Không có CRITICAL nào sau verification, nên không cần verifier thứ hai (TODO T10: N/A).

### 4.3 Quy tắc gộp trùng (dedupe)

Charter §4 quy định "giữ ID nhỏ hơn". Khi merge, audit **lệch khỏi quy tắc này có chủ đích**: finding chính là finding **cụ thể nhất hoặc đã được verify**. Danh sách:

| Finding chính | Trùng | Lý do chọn |
|---|---|---|
| F-120 | F-901 | Cùng gốc lookahead. V1 ghi F-120 là dup của F-901, nhưng merge chọn F-120 vì bằng chứng code chi tiết hơn (dòng, fixture key). Cả hai đều CONFIRMED HIGH. |
| F-022 | F-903 | Lỗi nằm ở protocol đã đóng băng. F-903 là nguồn gốc ở tầng planning (V4). |
| F-126 | F-951, F-603 | Lỗi runtime. F-951 là gốc thiết kế (08 D-04), F-603 là khoảng trống test (V2). |
| F-501 | F-710 | Cùng cơ chế probe algo -2011 |
| F-503 | F-205 | Taxonomy lỗi entry. F-503 cụ thể hơn. |
| F-953 | F-105 | Cổng `enable()` chỉ phủ định |
| F-005 | F-055 | Phí entry giả định maker |
| F-006 | F-957 | `partial_fill_fraction = 0.5` |
| F-108 | F-910 | Backup không off-host / không mã hoá |
| F-508 | F-707 | Duyệt lệnh chỉ theo chat id |

### 4.4 Chuẩn hoá độ tin cậy

Các lane stage A/B dùng thang HIGH/MEDIUM thay cho thang chuẩn của charter. Khi merge đã quy đổi:
- HIGH → **PROBABLE**, MEDIUM → **SUSPICIOUS**.
- Nếu verifier xác nhận → **CONFIRMED** (ví dụ F-001, F-007, F-009, F-022, F-951…F-954).
- F-501 (lane: PROBABLE) thành **UNVERIFIED** vì verifier kết luận INSUFFICIENT_EVIDENCE.
- F-126 và F-502 (lane: PROBABLE) thành CONFIRMED sau verify.
- Trường `lane_severity` và `lane_confidence` trong `findings.json` giữ giá trị trước verification.

### 4.5 Nguyên tắc diễn giải

- "Lỗi xác nhận" (DEFECT, CONFIRMED) khác "khuyến nghị cải tiến" (IMPROVEMENT). Ưa thích kiến trúc không được tính là bug.
- Quy tắc nghiệp vụ mơ hồ được ghi thành `AMB-xxx` (39 mục trong `INVARIANTS.md`) và **không** được audit tự giải quyết (§20).
- Không chấm điểm lợi nhuận chiến lược. User chỉ yêu cầu xét phương pháp: lookahead, overfit, chi phí, thống kê, kill gate (charter §11c).

---

## 5. Finding CRITICAL

**Không có finding CRITICAL sau verification.** Không lane nào đề xuất mức CRITICAL. Verifier V5 cũng xác định rõ F-301 và F-302 "không đạt CRITICAL hôm nay".

**Cần theo dõi leo thang: F-302.** V5 ghi: *"CRITICAL-class (wrong-direction or wrong-symbol live order) the moment a runtime composition calls it … Once M1-M4 composition lands, re-rate this as CRITICAL if the check is still missing."* Nếu phase runtime composition được làm mà chưa có kiểm tra symbol/side (§19 P0-1), F-302 phải được nâng lên **CRITICAL**.

Lý do chung khiến không có CRITICAL: các lỗi nghiêm trọng nhất (F-126, F-302, F-401, F-701, F-702, F-007) nằm trên đường lệnh live mà **chưa có caller production**. Simulator (F-120) cũng chưa chạy trên dữ liệu thật (M4). Mức độ sẽ khác ngay khi các đường này được nối dây.

---

## 6. Finding HIGH

12 finding chính, sắp theo luồng nghiệp vụ: nghiên cứu → plan → duyệt → đặt lệnh → bảo vệ → đối soát → an toàn. Tất cả đã qua verifier mù. Cách đọc nhãn "Phân loại":
- **Lỗi xác nhận** = DEFECT + CONFIRMED.
- **Thiếu hụt xác nhận** = GAP + CONFIRMED.
- **Chưa xác nhận** = độ tin cậy dưới CONFIRMED.

### 6.1 F-120: Backtest khớp và thoát lệnh trên chính nến sinh tín hiệu (lookahead)

| Trường | Giá trị |
|---|---|
| Độ tin cậy / Verification | CONFIRMED / **V1 CONFIRMED HIGH** (probe `tmp/verify_V1_backtest/probe_run.py`) |
| Phân loại | Lỗi xác nhận (DEFECT) |
| Vị trí | `src/backtest/simulator.py:752-870` (`run()`, `_resolve_entry`, `intrabar_key`) |
| Trùng / liên quan | Trùng: **F-901** (B1). Liên quan: F-102, F-305, F-602, F-804, F-805 |
| Known-prior | Một phần: 06-REVIEW CR-04 (đồng hồ hết hạn) bị skip, 06-VERIFICATION G3. Phần **lookahead cùng nến là MỚI**. Không có trong ROADMAP 11–17 (V1). |

**Sai ở đâu:**
- Strategy và planner được đánh giá trên nến `bar` đã đóng, tức là thời điểm quyết định là `bar.close_time_utc`.
- Sau đó `_resolve_entry(bar=bar)` dùng *chính* high/low/open/close của nến đó để quyết định chạm vùng, khớp lệnh và vô hiệu hoá.
- Lệnh thoát được giải bằng các nến 1m có key là close của **chính nến tín hiệu**. Với quyết định lúc 09:59:59, đó là các nến 09:00–09:59.
- Plan không bao giờ được mang sang nến sau. Nếu không chạm SL/TP thì lệnh thoát "EOD" ở nến 1m cuối, nên thời gian giữ lệnh tối đa là 1 nến.

**Kịch bản cụ thể:** Probe của V1 trên fixture `intrabar_both_touched`: `entry 121.5 lúc 2026-09-11T09:59:59, exit SL 121.42 lúc 09:00:59`. Lệnh thoát xảy ra **59 phút trước** lệnh vào. Kết quả không hẳn luôn lạc quan, nhưng *vô nghĩa về nhân quả*. Mọi expectancy, R hay kill-gate evidence do engine này sinh ra đều không dùng được để chọn chiến lược hay quyết định bỏ tiền.

**Vì sao test không bắt được (F-602, F-805):**
- `scripts/gen_phase6_fixtures.py` cố ý đặt dữ liệu 1m *bên trong* nến tín hiệu, nên fixture mã hoá luôn cả lỗi.
- 7/9 case phase 6 không có `expected.json`, và `_load_expected` là code chết.
- `test_no_lookahead.py` và `test_prefix_invariance.py` chỉ test `strategy.evaluate`.
- Không test nào assert `exit_time_utc >= entry_time_utc`.
- **Đính chính:** câu "golden fixtures pin semantics byte-for-byte" trong F-901 là **sai**. Fixture chỉ ghim nhãn thô (L6 F-602, L8 F-805, V1). Muốn sửa lỗi này phải viết **assert mới**, không phải regenerate fixture.
- Về tuyên bố sai: V1 ghi nhận 06-VERIFICATION đã đánh dấu BKTS-01 là PARTIAL và milestone audit ghi "unsatisfied". Tuyên bố sai rõ ràng chỉ là checkbox "[x] No-lookahead test" trong 06-01-SUMMARY.

**Nguồn gốc (L8):** commit `77a0659` (06-01) làm đúng theo **plan**: 06-01-PLAN:97/:109 quy định "1m map keyed by … strategy-bar close_time_utc" và khớp "when a strategy-bar range touches the zone". Plan đã bỏ Pitfall 2 của 06-RESEARCH ("1m candles strictly inside `(entry_bar.open, exit_bar.close]`"). Đây là **lỗi của tầng plan**, không chỉ của code.

**Cách sửa:**
- Viết lại vòng đời plan xuyên nhiều nến: chỉ cho khớp ở các nến *sau* khi nến tín hiệu đóng, trong thời hạn expiry.
- Giải lệnh thoát bằng dữ liệu 1m *từ thời điểm khớp trở đi*, và cho giữ lệnh qua nhiều nến.
- Thêm test "range của nến tín hiệu chạm SL/TP thì không được khớp trên nến đó".
- Verify lại BKTS-01 và **huỷ mọi bằng chứng backtest đã có**.

**Vì sao chưa CRITICAL:** simulator chưa chạy trên dữ liệu thật (M4) và không nằm trên đường lệnh (V1).

### 6.2 F-902: Backtest coi "chạm vùng" là "khớp ở giá giữa vùng"

| Trường | Giá trị |
|---|---|
| Độ tin cậy / Verification | CONFIRMED / **V1 CONFIRMED HIGH** (probe `probe902.py`) |
| Phân loại | Lỗi xác nhận (DEFECT) |
| Vị trí | `src/backtest/simulator.py:448-518` |
| Liên quan | F-301 (khuếch đại), F-004, Corrected Rule 18 |
| Known-prior | Mức docs: F-004 của stage A. Nguồn gốc: checkpoint 04-03 "option A" (auto-selected) cộng với cách diễn đạt trong 06-01-PLAN:109 (L8). |

**Sai ở đâu:** `zone_touched = bar.high >= entry_min and bar.low <= entry_max`, sau đó ghi ENTRY_FILLED tại `entry_ref = (entry_min+entry_max)/2`. Trong khi đó live đặt LIMIT đúng tại giá giữa vùng (`placement.py:143`).

**Kịch bản:** Probe V1 dùng plan LONG, vùng 99–101, nến O 101.5 / H 103 / **L 100.9** / C 102. Kết quả là `ENTRY_FILLED 100`. Nến chưa từng giao dịch tới 100, nên một lệnh BUY LIMIT thật tại 100 **sẽ không khớp**. Hệ quả: backtest thổi phồng cả tỷ lệ khớp lẫn chất lượng giá vào. Đây là adverse selection bị che giấu, và vẫn còn nguyên sau khi đã sửa F-120.

**Vì sao test không bắt được:** fixture sinh ra từ chính implementation (F-608). Không test nào nối quy tắc khớp của backtest với giá lệnh live.

**Cách sửa:** chỉ ghi khớp khi giá đi xuyên qua giá LIMIT live (giữa vùng) ít nhất 1 tick, và giá khớp là giá limit. Trường hợp chỉ chạm mép vùng ghi `TOUCH_NO_FILL`. Giữ option A cho live.

### 6.3 F-022: Protocol nghiên cứu đặt ngưỡng pass sau khi xem kết quả, không hiệu chỉnh đa kiểm định

| Trường | Giá trị |
|---|---|
| Độ tin cậy / Verification | CONFIRMED / **V4 CONFIRMED HIGH** |
| Phân loại | Lỗi xác nhận (DEFECT) ở **tầng thiết kế docs** |
| Vị trí | `docs/research/RESEARCH_PROTOCOL.md:205-236` (cùng dòng 24) |
| Trùng / liên quan | Trùng: **F-903** (gốc ở planning: 01-RESEARCH:226 gọi ngưỡng số đặt trước dữ liệu là "overfitting commitments"). Liên quan: F-960, F-953, F-904, F-025 |
| Known-prior | Không có |

**Sai ở đâu:**
- Ngưỡng số giữ ở TBD "until the methodology is exercised on real data". Chúng chỉ được đề xuất *sau khi* ít nhất 3 family đã có bằng chứng Validation.
- "Passing status is a recorded human decision … never computed".
- Grep toàn bộ docs/src không thấy multiple-testing, deflated Sharpe, Bonferroni, reality check hay trial count (V4).
- Holdout được giữ riêng, nhưng không có gì bắt buộc đóng băng ngưỡng trước khi đọc holdout.

**Kịch bản:** thử khoảng 25 biến thể trở lên cộng với quét tham số. Theo xác suất, một biến thể sẽ trông "tốt" dù chỉ là nhiễu. Ngưỡng lại được đặt sau khi đã thấy nó, và người dùng tự nhận ít kinh nghiệm giao dịch. Đây là con đường điển hình để một lợi thế giả đi vào tiền thật, đúng thứ mà kill gate được thiết kế để ngăn (V4).

**Vì sao test không bắt được:** đây là vấn đề governance, không phải code.

**Cách sửa (khuyến nghị, Corrected Rule 31):**
- Ra protocol v1.1.0 đóng băng ngưỡng số **trước lần chạy Validation đầu tiên**: cận dưới CI block-bootstrap của net expectancy > 0 ở 1× chi phí và ≥ 0 ở 2× chi phí, số giao dịch tối thiểu, trần drawdown và chuỗi thua.
- Ghi số lần thử và áp dụng hiệu chỉnh đa kiểm định.
- Holdout chỉ dùng một lần, cho một ứng viên.
- Con người được **bác** một ứng viên đã pass, nhưng không được **cho pass** một ứng viên trượt.

### 6.4 F-301: Hình học lệnh trend-pullback: SL nằm trong vùng entry, stop quá hẹp, "pullback" trên đáy mới

| Trường | Giá trị |
|---|---|
| Độ tin cậy / Verification | CONFIRMED / **V5 CONFIRMED HIGH (không phải CRITICAL)** (probe `probe_f301.py`) |
| Phân loại | Lỗi xác nhận (DEFECT) |
| Vị trí | `src/core/planner.py:105-409` (LONG 105-114, SHORT 160-169, entry_min/max 378-379), `src/core/features.py:187`, `src/core/strategy.py:157-158` |
| Liên quan | Gốc: F-909 (giá trị tracer thành baseline), F-113. Cộng dồn với F-001/P11, P13. Khuếch đại F-902. |
| Known-prior | Các sự thật trong code là MỚI |

**Sai ở đâu (baseline-v3):**
- Vùng entry LONG = swing_low ± 0.6 ATR, còn SL = swing_low − 0.2 ATR. Như vậy **1/3 vùng entry nằm bên kia SL**.
- Stop cách giá LIMIT (giữa vùng) chỉ 0.2 ATR.
- Cửa sổ swing (`features.py:187`, `candles[i-lookback+1 : i+1]`) **bao gồm cả nến đang xét**. Vì vậy "pullback về hỗ trợ" kích hoạt ngay trên nến tạo đáy 20 nến mới, trái family sheet ("decision-making uses confirmed swings only").

**Kịch bản bằng số (V5):**
- Với S=60.000, ATR=400: entry_min=59.760 < SL=59.920. Stop = 80 USDT = **0,133%** giá, RR=25, nên cổng minimum_rr=2 gần như không bao giờ chặn.
- Chi phí mô hình/đơn vị = 48, tức **chi phí ≈ 60% rủi ro**.
- **Equity $1.000:** ngân sách $5,00, qty 0,0391 BTC, notional $2.344 (2,34× equity). Nếu SL trượt thêm 0,2% / 0,5% thì lỗ **$9,69 / $16,72**.
- **Equity $500:** lỗ $4,84 / $8,36 so với ngân sách $2,50.
- Lane L3 (p9, chạy toàn bộ evaluate → plan → evaluate_risk): tín hiệu LONG xuất hiện trên nến thấp hơn mọi đáy của 19 nến trước. qty = **16,1× equity**. Cộng với lỗi phí P11, lỗ SL thực khoảng **3,2R**.

**Phản biện của verifier:** live chỉ đặt LIMIT ở giữa vùng, nên không bao giờ có lệnh live đặt dưới SL. Phần "33% vùng nằm sau SL" là lỗi ngữ nghĩa của plan/vùng. Tuy nhiên nó đi thẳng vào backtest qua F-902: LONG được khớp tại S dù low vẫn cao hơn S tới 0,6 ATR.

**Vì sao test không bắt được:** golden planner được regenerate từ src (F-608). Không test nào assert "SL nằm ngoài vùng", "swing loại trừ nến hiện tại", hay giới hạn khoảng stop / notional.

**Cách sửa:**
- Thêm bất biến cho planner: LONG thì SL < entry_min, SHORT thì SL > entry_max, nếu không thì NO_TRADE.
- Chỉ dùng pivot đã xác nhận, loại trừ nến hiện tại.
- Thêm trần chi phí/rủi ro và khoảng stop tối thiểu (Corrected Rule 3).
- Tạo parameter set/version mới và **nghiên cứu lại**.

### 6.5 F-302: Lệnh đặt ra không bị ràng buộc symbol/chiều với plan đã duyệt

| Trường | Giá trị |
|---|---|
| Độ tin cậy / Verification | CONFIRMED / **V5 CONFIRMED HIGH, sẽ thành CRITICAL khi nối dây** (probe `probe_f302.py`) |
| Phân loại | Thiếu hụt xác nhận (GAP) |
| Vị trí | `src/execution/manager.py:212-560` (444-445, 470, 497-498, 512, 547), `src/domain/trade_plan.py:59-78` |
| Liên quan | F-203 (qty tính lại), F-127(d), `attach_protectives_to_fill` cùng gốc |
| Known-prior | MỚI |

**Sai ở đâu:**
- `TradePlan` không có trường `symbol` hay `direction`.
- `execute_approved_plan` lấy symbol từ `risk_kwargs["constraint_snapshot"].symbol` và lấy chiều từ `risk_kwargs["candidate_position_side"]`. Cả hai đều do caller truyền vào.
- `_check_approval_authorizes_plan` chỉ so plan_hash, trade_plan_id và expiry.
- Sizing dùng `abs(entry_ref − SL)`, nên đảo chiều vẫn ra đúng cùng một size.

**Kịch bản (V5, dùng golden phase-9: BTCUSDT LONG, vùng 100–102, SL 98, equity 1.000):**
- Đảo side thành `"SHORT"` thì kết quả là **SELL 3,311 @101** kèm stop **BUY tại 98**. Stop nằm dưới entry của một lệnh short, nên sẽ kích hoạt ngay hoặc bị từ chối, để lại vị thế trần. Vẫn trả `OK`.
- Đổi symbol thành XRPUSDT thì đặt lệnh trên XRPUSDT với giá của BTC. Vẫn trả `OK`.
- Chỉ cần **một lỗi nối dây** trong tương lai là có một lệnh chưa được duyệt đi kèm một approval hợp lệ.

**Vì sao test không bắt được:** test dựng `risk_kwargs` từ cùng fixture với plan, không có test đột biến symbol/side.

**Cách sửa (chi phí thấp, vì `plan_hash` đã bao gồm `signal_id`, mà `signal_id` đã chứa symbol và direction):**
- Thêm symbol và direction vào TradePlan (hoặc load Signal theo `signal_id`).
- Assert `snapshot.symbol == plan.symbol`, `side == plan.direction`, và thứ tự SL/entry/TP đúng chiều **trước** mọi lời gọi adapter.

### 6.6 F-007: Không kiểm tra giá sau APPROVE; không có phương án khi SL bị từ chối sau khi khớp

| Trường | Giá trị |
|---|---|
| Độ tin cậy / Verification | CONFIRMED / **V4 CONFIRMED HIGH** |
| Phân loại | Thiếu hụt xác nhận (GAP) ở tầng docs, đã xác minh trong code |
| Vị trí | `docs/trading/EXECUTION_SPEC.md:1-25`. Code: `src/execution/manager.py` (`execute_approved_plan` ~466-565) |
| Liên quan | F-952 (no rescue), F-502, F-016, F-959 |
| Known-prior | Một phần: ROADMAP **Phase 15** (cổng giá so với SL). Phương án dự phòng khi SL bị từ chối sau khi khớp **không** có trong ROADMAP. |

**Sai ở đâu:**
- Các cổng của `execute_approved_plan` gồm: binding, approval, enablement, SAFE_MODE, `evaluate_risk`, `decide_placement`. **Không cổng nào đọc giá mark hay last hiện tại** (grep trong `src/execution` không thấy).
- Nếu SL không được xác nhận, code vào SAFE_MODE rồi *huỷ* entry. Nhưng lệnh huỷ không đảo được một lệnh đã khớp.
- `sweeper.py:5` và `fill_monitor.py:24` ghi rõ: hệ thống không bao giờ đặt lệnh bảo vệ cứu vãn.

**Kịch bản (LONG):**
1. Người dùng duyệt lệnh lúc đang làm việc. Trong khoảng hiệu lực 4 giờ, giá đã rơi xuống dưới SL.
2. BUY LIMIT ở giữa vùng lúc này là marketable nên khớp ngay như taker.
3. SELL STOP_MARKET có trigger cao hơn mark bị Binance từ chối ("would immediately trigger").
4. Kết quả: vị thế **đã vượt qua điểm vô hiệu mà không có stop**, và nằm yên cho tới khi người dùng tự xử lý.

Theo thiết kế, lỗ mỗi lệnh bị chặn ở 0,5% × equity, tức $2,50–$5,00 với $500–1.000. Trong kịch bản này, lỗ **không còn bị chặn bởi plan** mà chỉ còn bị chặn bởi margin và thanh lý. Trường hợp ngược lại, giá rời vùng đi lên, chỉ để lệnh nằm chờ và vô hại (V4).

**Vì sao test không bắt được:** test dùng giá tĩnh, không có kịch bản giá thay đổi giữa lúc duyệt và lúc đặt lệnh.

**Cách sửa:**
- (a) P15: lúc đặt lệnh, đọc cả mark và last. LONG: từ chối nếu giá thấp nhất kể từ tín hiệu ≤ SL, hoặc giá hiện tại > entry_max + buffer (SHORT làm đối xứng). Từ chối nếu lệnh limit sẽ marketable.
- (b) **Mục mới:** sau bất kỳ lần khớp nào, nếu SL bị từ chối (ví dụ -2021) hoặc không được ACK trong N giây, đóng vị thế bằng MARKET reduce-only, gửi cảnh báo, vào SAFE_MODE (Corrected Rule 14). Hướng này mâu thuẫn chính sách "no rescue" hiện tại, nên cần quyết định (§20).

### 6.7 F-501: Việc đặt SL phụ thuộc mã lỗi "không tìm thấy algo order" chưa được xác minh

| Trường | Giá trị |
|---|---|
| Độ tin cậy / Verification | **UNVERIFIED** / **V2 INSUFFICIENT_EVIDENCE**, HIGH **tạm thời** |
| Phân loại | Lỗi (DEFECT), **chưa xác nhận** |
| Vị trí | `src/adapters/binance_usdm.py:858-877` (`query_algo_order_by_client`), `src/execution/manager.py:733-750` (`_place_protective_leg`) |
| Trùng / liên quan | Trùng: **F-710**. Liên quan: F-503/F-205, F-502, F-054 |
| Known-prior | Một phần: 09-REVIEW-FIX.md:42 đã yêu cầu kiểm lại mapping -2011 nhưng chưa bao giờ làm, và chưa ai nhận ra tác động tới mọi SL |

**Sai ở đâu:**
- Trước **mọi** lần đặt SL/TP, manager probe `GET /fapi/v1/algoOrder` theo clientAlgoId. Adapter chỉ map lỗi chứa `"-2011"` hoặc `"UNKNOWN_ORDER"` thành "không tìm thấy". Mọi lỗi khác đều raise, và manager coi leg đó là "chưa xác nhận" nên **không bao giờ đặt SL**.
- Sự thật đã có tài liệu (V2, developers.binance.com): -2011 = CANCEL_REJECTED (mã của đường *huỷ*). -2013 = NO_SUCH_ORDER. Binance không bao giờ gửi chuỗi "UNKNOWN_ORDER", nên nhánh đó là code chết.
- SDK `binance_common` 4.4.0 truyền nguyên mã của sàn. Docstring của adapter nói SDK "chuẩn hoá not-found thành -2011", điều này **sai**.
- **Chưa có tài liệu:** mã mà Binance trả về cho một algo order không tồn tại.

**Kịch bản:** probe V2 với manager và `-2013` cho ra `ENTRY_WITHOUT_PROTECTIVE`, SAFE_MODE, và chuỗi lời gọi `[get_position_mode, place_entry, query_algo_order_by_client, cancel_normal_order]`. SL **không bao giờ** được đặt.
- Nếu testnet trả mã khác -2011: **mọi** lệnh live đều bị huỷ và hệ thống vào SAFE_MODE, tức live không dùng được.
- Nếu entry khớp trong khoảng giữa ACK và lệnh huỷ: vị thế không có stop (xem F-502).

**Điều sẽ quyết định kết quả:** gọi testnet `GET /fapi/v1/algoOrder?clientAlgoId=<xa- id chưa từng đặt>`, ghi lại HTTP status cùng `code`/`msg`, cho cả id mới và id đã quá hạn lưu 3 ngày.
- Khác -2011: **CONFIRMED HIGH**.
- Đúng là -2011: hạ xuống LOW ("mapping chưa verify").

**Vì sao test không bắt được:** mọi fake đều trả `found=False` trực tiếp, không test nào dùng object lỗi thật của SDK. Buổi diễn tập testnet 09-04 đang **BLOCKED**.

**Cách sửa:** xác minh trên testnet, map theo `exc.status_code` thay vì so chuỗi, và thêm test dùng lỗi SDK thật.

### 6.8 F-104: Không có Binance user-data stream và không có truy vấn fill/trade

| Trường | Giá trị |
|---|---|
| Độ tin cậy / Verification | CONFIRMED / **V2 CONFIRMED HIGH** |
| Phân loại | Thiếu hụt xác nhận (GAP): requirement bị mất |
| Vị trí | `src/adapters/binance_usdm.py:526-1256` (danh sách method), `src/execution/manager.py:802-812` (`fill_events` do caller cấp) |
| Liên quan | F-201, F-955, F-963 (P12 phụ thuộc stream không tồn tại), F-053, F-054 |
| Known-prior | MỚI. v0.3 audit chỉ ghi M1–M4. P12 nhắc user-data stream **chỉ** như nguồn equity. |

**Sai ở đâu:**
- Không có listenKey, không WS user-data, không parse ORDER_TRADE_UPDATE/ALGO_UPDATE/ACCOUNT_UPDATE, không có userTrades.
- `attach_protectives_to_fill(fill_events=...)` và `fold_fills` vì vậy không có nguồn fill nào trong production.
- AGENTS, PROJECT, EXECUTION_SPEC §1/§6, PRODUCT_SCOPE §4 và 08-CONTEXT D-03 đều yêu cầu "user-data WS preferred realtime", nhưng yêu cầu này chưa bao giờ trở thành REQ-ID.

**Kịch bản khi live được nối dây:**
- Chỉ có SL close-all đặt lúc vào lệnh (đây là điểm giảm nhẹ mà V2 ghi nhận).
- TP1/TP2 **không bao giờ được gắn**, và SL không được resize theo lượng thực khớp.
- Khớp một phần, TP bị từ chối lúc trigger (`ALGO_UPDATE.o.rm`), hay thanh lý chỉ được thấy qua reconcile REST định kỳ, mà reconcile đó cũng chưa được lập lịch.

**Vì sao test không bắt được:** mọi test execution đều bơm fill giả vào hàm thuần.

**Cách sửa:** tạo REQ-ID và phase mới cho USD-M user-data stream: vòng đời listenKey (keepalive, `listenKeyExpired` thì reconnect và reconcile), ORDER_TRADE_UPDATE, ALGO_UPDATE (gồm `o.rm`), ACCOUNT_UPDATE, URL `/private` sau đợt tách URL 2026-04 (F-053). Stream này cấp dữ liệu cho `fold_fills`, reconciler và P12.

### 6.9 F-126: Retry / restart / replay có thể đặt entry lần hai (approval không được "tiêu thụ")

| Trường | Giá trị |
|---|---|
| Độ tin cậy / Verification | CONFIRMED / **V2 CONFIRMED HIGH** (probe `tmp/verify_V2_execution/probe.py`) |
| Phân loại | Thiếu hụt xác nhận (GAP): EXEC-03 / Phase 8 SC4 được tuyên bố đã đạt nhưng cơ chế không có |
| Vị trí | `src/execution/manager.py:162-240` (docstring 231-239: *"consuming the approval … needs persisted execution state and is NOT handled here"*) |
| Trùng / liên quan | Trùng: **F-951** (gốc thiết kế 08-RESEARCH D-04: "exchange dedups"), **F-603** (khoảng trống test). Liên quan: F-202, F-404, F-703, F-701, F-808 |
| Known-prior | Có NOTE trong code. 09-REVIEW CR-08 đã nêu, nhưng disposition làm phẳng thành "fixed" (F-808). Không có trong ROADMAP 11–17. |

**Sai ở đâu:**
- Binance ghi `newClientOrderId` là *"A unique id among open orders"*. Khi lệnh đầu đã FILLED hoặc CANCELED (kể cả do `expire_pending_entry` huỷ khi hết hạn), cùng một id sẽ được chấp nhận lại.
- `check_binding_full` không có trạng thái "đã dùng".
- Replay trả về dòng APPROVED hiện có, nên bất kỳ cách nối dây nào gọi execute khi nhận callback APPROVED đều sẽ chạy lại lần nữa.

**Kịch bản:**
- Telegram gửi lại callback, hoặc process restart, sau khi entry đầu đã khớp. Kết quả là entry thứ hai, cùng id `x-…EN`.
- Theo L3: entry trùng "nhận nuôi" cùng SL `closePosition` nên không trần trụi, nhưng lỗ tại SL = **2× R dự kiến** (với $1.000 và 0,5%: khoảng $10 thay vì $5).
- Nếu entry đầu chưa khớp và đã bị huỷ, không có gì chặn lệnh thứ hai. Cửa sổ replay chỉ bị giới hạn bởi `expiry_utc` của plan.
- Reconcile báo `agreement=True` cho vị thế 0,010 local so với 0,020 trên sàn (F-701).
- Khi lệnh đầu *còn mở*, sàn từ chối lệnh trùng (-4116) và manager nhận ra ENTRY_EXISTS. Trường hợp này an toàn (V2).

**Vì sao test không bắt được (F-603):**
- Validation 8-0X-04 chỉ chạy `tests/test_order_ids.py` (21 test về tính tất định của ID). Chính tính tất định đó là tiền đề cho lỗi này.
- `FakeExecutionAdapter.place_entry` chấp nhận vô hạn lần nộp cùng id.
- Không test nào gọi `execute_approved_plan` hai lần.

**Cách sửa:** lưu bền trạng thái thực thi theo `approval_id`/`plan_hash` với ràng buộc unique (F-404). Chỉ thực thi ở lần chuyển trạng thái đầu tiên. Các lần replay sau trả về kết quả đã lưu. Sửa luôn 08-CONTEXT D-04 và EXECUTION_SPEC.

### 6.10 F-401: Sweeper huỷ SL đặt sẵn của một entry LIMIT chưa khớp

| Trường | Giá trị |
|---|---|
| Độ tin cậy / Verification | CONFIRMED / **V3 CONFIRMED HIGH** (probe `tmp/verify_V3_reconcile/probe.py`). Đang tiềm ẩn. |
| Phân loại | Lỗi xác nhận (DEFECT): race trong reconcile |
| Vị trí | `src/reconcile/compare.py:293-339` (Pass 1), `src/reconcile/sweeper.py:190-199, 262`, `src/execution/manager.py:741-750` |
| Liên quan | F-952, F-009, 09-REVIEW WR-07 (chiều ngược lại). Mâu thuẫn tài liệu: STATE.md:190 (08-04 D-02) và 08-CONTEXT.md:24 D-03. |
| Known-prior | Liên quan WR-07, không trùng |

**Sai ở đâu:**
- Pass 1 coi một protective *không có vị thế* là `ORPHAN_PROTECTIVE`, mà không xem có ENTRY nào của cùng plan đang chờ khớp hay không.
- Sweeper chỉ cần 2 lần đọc vị thế bằng 0. Một entry đang chờ khớp **luôn** thoả điều kiện này.
- STATE.md:190 ghi quy tắc này một cách cố ý, trong khi 08-CONTEXT D-03 định nghĩa orphan là "protective **without a live entry**". Hai tài liệu mâu thuẫn nhau.

**Kịch bản (luồng bình thường, không cần sự cố gì):**
1. Đặt LIMIT GTC.
2. Đặt SL close-all ngay sau đó (thiết kế tốt).
3. Tick reconcile thấy SL mà không có vị thế, gắn nhãn ORPHAN.
4. Sweeper huỷ SL.
5. Vài giờ sau entry khớp. `_place_protective_leg` probe cùng id, thấy leg ở trạng thái CANCELED và **không đặt lại** (D-02 "no rescue").
6. Kết quả: vị thế thật **không có stop**, còn SAFE_MODE chỉ chặn entry mới.

L3 bổ sung: mọi lần đặt lệnh bình thường vì vậy đều đẩy hệ thống vào SAFE_MODE.

**Vì sao test không bắt được:** test sweeper dùng diff orphan dựng tay. Không test compare nào kết hợp ENTRY đang chờ, SL đặt sẵn và vị thế bằng 0.

**Cách sửa:** miễn trừ các protective có ENTRY của cùng plan hoặc symbol đang mở (local hoặc trên sàn). Sửa định nghĩa orphan trong INV-094. Thêm test hồi quy.

### 6.11 F-701: Reconcile compare không thấy vị thế nhân đôi, vị thế đảo dấu, lệnh lạ, hay vị thế chỉ có TP

| Trường | Giá trị |
|---|---|
| Độ tin cậy / Verification | CONFIRMED / **V3 CONFIRMED HIGH** |
| Phân loại | Lỗi xác nhận (DEFECT): fail-closed bị thủng |
| Vị trí | `src/reconcile/compare.py:228-468` (index 228-233, Pass 1b 383-392, Pass 3 453-470), `src/reconcile/safe_mode.py:291-310` |
| Liên quan | F-711 (tự thoát SAFE_MODE), F-126, F-703. Không trùng F-401 (đường code khác, lỗi theo chiều ngược lại). |
| Known-prior | Liên quan 08-REVIEW CR-03 / WR-13 |

**Sai ở đâu:**
- Lệnh trên sàn chỉ được tra từ phía local, không có pass nào quét lệnh chỉ có trên sàn.
- Vị thế được khớp theo khoá `(symbol, position_side)`. `position_amt` không bao giờ được so, và ở one-way mode `position_side` luôn là "BOTH".
- Pass 1b chấp nhận bất kỳ leg bảo vệ nào (SL, TP1, TP2), không bắt buộc phải có STOP_LOSS.

**Kịch bản (probe V3):** vị thế local 1 so với sàn 2, local 1 so với sàn −1, lệnh thường hoặc algo lạ, vị thế chỉ có TP1: **tất cả đều trả `agreement=True`**. Compare "sạch" này lại là **cổng duy nhất để thoát SAFE_MODE** (`exit_safe_mode` mặc định local intent = `[]`, F-711). Vì vậy lệnh trùng (F-126), lệnh tay, ADL/thanh lý, hay SL bị mất mà TP còn đều được coi là bình thường, và SAFE_MODE có thể tự thoát. V3 ghi nhận một điểm giảm nhẹ: SL local mà không có trên sàn *vẫn* bị bắt (UNSYNCED_ALGO).

**Vì sao test không bắt được:** fixture chỉ mô hình các loại lệch đã lên kế hoạch, không bơm lệnh chỉ-có-trên-sàn hay lệch qty/dấu.

**Cách sửa:** thêm pass ngược quét lệnh trên sàn (UNKNOWN_EXCHANGE_ORDER), so `position_amt` có dấu theo từng (symbol, side), và bắt buộc có STOP_LOSS trên sàn cho mọi vị thế khác 0.

### 6.12 F-702: Ghi journal trước hành động, nên sự cố DB chặn mọi hành động giảm rủi ro

| Trường | Giá trị |
|---|---|
| Độ tin cậy / Verification | CONFIRMED / **V2 CONFIRMED HIGH** (probe với journal luôn raise) |
| Phân loại | Lỗi xác nhận (DEFECT) |
| Vị trí | `src/execution/manager.py:561-1330` (`expire_pending_entry` ~1012-1022, vòng SL/TP ~1083-1094, `emergency_manual_close` ~1230+), `src/execution/enablement.py:235-242`, `src/reconcile/safe_mode.py:205-212` |
| Liên quan | F-127(a) (SAFE_MODE chỉ trong bộ nhớ). Sweeper cũng raise trong nhánh except (L7 open question 6). |
| Known-prior | Không có |

**Sai ở đâu và kịch bản (probe V2 với `journal.record` raise RuntimeError):**
- `expire_pending_entry` và `cancel_untriggered_protectives` raise mà **không gửi lệnh huỷ nào**.
- `LiveEnablementController.disable` raise **trước** khi bật cờ, nên `guard_placement` vẫn PASS. Kill switch không có tác dụng.
- `emergency_manual_close` ném ExceptionGroup 4 lỗi, không gửi lệnh huỷ nào, và live vẫn bật.
- `execute_approved_plan` với SL bị REJECTED: `enter_safe_mode` raise (cờ SAFE_MODE trong bộ nhớ *đã* được đặt), nhưng exception làm bỏ qua bước huỷ. Entry đã ACK mà không có SL **vẫn sống** trên sàn và có thể khớp trần.
- Mất DB lại chính là một trigger của SAFE_MODE, nên đúng lúc cần phanh nhất thì phanh không hoạt động.

**Vì sao test không bắt được:** mọi journal trong test đều là fake chạy trong bộ nhớ và không bao giờ raise.

**Cách sửa:** gửi lệnh huỷ/tắt trước rồi mới ghi journal, có fallback append-only cục bộ. Không bao giờ để việc ghi journal làm hỏng một chuyển trạng thái an toàn. Bọc `enter_safe_mode` trong `execute_approved_plan` để lệnh huỷ entry luôn được chạy.

### 6.13 Các finding HIGH ở cấp lane đã bị hạ mức hoặc bác bỏ

| ID | Lane | Kết quả verifier | Lý do rút gọn |
|---|---|---|---|
| F-001 | A1 | DOWNGRADED → MEDIUM (V4) | Cơ chế đúng, nhưng tác động bị chặn theo tỷ lệ chi phí/khoảng SL: +8% ở SL 1%, +16% ở SL 0,5%, tức rủi ro 0,5% thành khoảng 0,54–0,58% ($0,32–0,64 trên $800). **Xung đột với L6/V1:** trên golden `intrabar_both_touched` (SL rất hẹp), lỗ SL là −103,59 so với rủi ro 49,99, tức **2,07×**. L3 đo được 1,77–1,80R ở stop 0,1%, và **XRP giá 0,5 bị size nhỏ đi** (0,69R ở stop 0,1%). Kết luận: mức độ phụ thuộc khoảng SL. Với hình học F-301 (stop khoảng 0,13%), tác động rất lớn. V4 cũng ghi rằng docs nghiên cứu *không* hoàn toàn bỏ chi phí. |
| F-008 | A1 | **REJECTED** (V4) | Xem §8.4 |
| F-009 | A1 | DOWNGRADED → MEDIUM (V3) | Code đã hiểu SAFE_MODE chỉ chặn entry. Đây là mâu thuẫn trong tài liệu. |
| F-502 | L5 | DOWNGRADED → MEDIUM (V2) | SAFE_MODE đã vào trước. Lỗi thật là bản ghi `post_cancel` sai cộng với việc không kiểm tra fill. |
| F-601, F-602 | L6 | DOWNGRADED → MEDIUM (V1) | Khoảng trống test của F-001 và F-120 |
| F-603 | L6 | DOWNGRADED → MEDIUM, dup F-126 (V2) | Khoảng trống test |
| F-903 | B1 | DOWNGRADED → MEDIUM, dup F-022 (V4) | Gốc ở planning |
| F-952 | B2 | DOWNGRADED → MEDIUM (V3) | "Rule 14/24" không có trong docs của dự án. Cửa sổ rủi ro bị giới hạn bởi operator. |
| F-953, F-954 | B2 | DOWNGRADED → MEDIUM (V4) | Hiện chưa có đường live. Cần trở thành blocker trước khi nối M2. |

---

## 7. Finding MEDIUM

**91 finding chính** mức MEDIUM, nhóm theo chủ đề. Nhãn "Trùng: …" liệt kê finding đã gộp vào. "Verify: …" là kết quả của verifier nếu finding từng là HIGH ở cấp lane. Tóm tắt dịch từ trường `summary` trong `findings.json`; chi tiết (evidence, reproduction, remediation) xem trong `findings.json` và `lanes/*.md`.

Phân bố: GAP 49 · DEFECT 23 · DRIFT 13 · AMBIGUITY 6. Theo độ tin cậy: 60 CONFIRMED · 23 PROBABLE · 8 SUSPICIOUS.

#### Thiết kế tài liệu (docs, stage A) (21)

| ID | Tóm tắt | Loại | Độ tin cậy | Vị trí |
|---|---|---|---|---|
| F-001 | Công thức sizing cộng `modeled_costs` (tỷ lệ, không đơn vị) vào khoảng cách giá tới SL → lỗ khi chạm SL vượt ngân sách rủi ro (verifier: +8–16% ở SL 0,5–1%; 2,07× trên golden fixture SL rất hẹp; XRP giá thấp lại bị size nhỏ hơn). KNOWN P11. Verify: DOWNGRADED. | Lỗi (DEFECT) | CONFIRMED | `docs/trading/RISK_MANAGEMENT.md:19-23` |
| F-002 | Không có khoảng cách SL tối thiểu hay trần chi phí/rủi ro: SL quá hẹp để phí + trượt giá ăn hết lợi thế. | Thiếu hụt (GAP) | PROBABLE | `docs/strategy/TRADING_STRATEGY_SPEC.md:65-69` |
| F-004 | Slippage định nghĩa sai chỗ (áp lên entry LIMIT, không áp cho lệnh thoát STOP_MARKET), cố định 1 bp; không có quy tắc chạm-giá ≠ khớp. | Lỗi (DEFECT) | SUSPICIOUS | `docs/research/RESEARCH_PROTOCOL.md:97-111` |
| F-005 | Phí entry giả định maker (2 bps) dù entry đặt vài giờ sau tín hiệu và có thể khớp ngay như taker (5 bps); không có quy tắc GTX/post-only. Trùng: F-055. | Lỗi (DEFECT) | PROBABLE | `params/trend-pullback/baseline-v3.toml:43-44` |
| F-006 | Bộ chi phí chuẩn mô phỏng mọi lệnh khớp 50% (`partial_fill_fraction = 0.5`) chỉ để né lỗi chuẩn hoá hash; mâu thuẫn nhãn FULL_FILL và baseline dùng 1.0. Trùng: F-957. | Lỗi (DEFECT) | PROBABLE | `params/trend-pullback/baseline-v3.toml:51-57` |
| F-009 | SECURITY_AND_OPERATIONS cấm "mọi lệnh mới" trong SAFE_MODE, kể cả lệnh bảo vệ, trong khi RUNBOOK yêu cầu đặt lại SL. Verifier: code đã hiểu đúng (chỉ chặn entry) → lỗi tài liệu. Verify: DOWNGRADED. | Lỗi (DEFECT) | CONFIRMED | `docs/operations/SECURITY_AND_OPERATIONS.md:76-82` |
| F-010 | `workingType`/`priceProtect` không được chọn trong docs; chuỗi giá kích hoạt SL phải khớp với chuỗi giá dùng trong backtest. | Thiếu hụt (GAP) | SUSPICIOUS | `docs/integration/BINANCE.md:50` |
| F-011 | Docs coi đòn bẩy là chỉ-đọc, không chọn margin type, không yêu cầu giá thanh lý nằm xa hơn SL. KNOWN P13/P14. | Thiếu hụt (GAP) | PROBABLE | `docs/trading/RISK_MANAGEMENT.md:87-91` |
| F-012 | "Account equity" không được định nghĩa (wallet / margin / available) và thời điểm lấy (signal / approval / placement). KNOWN P12. | Mơ hồ (AMBIGUITY) | PROBABLE | `docs/trading/RISK_MANAGEMENT.md:7-23` |
| F-013 | Daily loss stop không có ranh giới ngày, cơ sở PnL, equity gốc, toán tử so sánh, quy tắc reset; docs ghi TBD trong khi params cố định 1%. | Mơ hồ (AMBIGUITY) | PROBABLE | `docs/trading/RISK_MANAGEMENT.md:44-85` |
| F-014 | Thành viên cluster tương quan và cách xử lý chiều lệnh không định nghĩa; "open" có tính lệnh đang chờ / đã duyệt hay không cũng không rõ → 2 approval có thể vượt cap. | Mơ hồ (AMBIGUITY) | SUSPICIOUS | `docs/trading/RISK_MANAGEMENT.md:44-59` |
| F-015 | Tin nhắn duyệt lệnh thiếu số lượng, notional, số $ lỗ tại SL (sau phí), margin, leverage, giá thanh lý, equity dùng để tính. KNOWN P16. | Thiếu hụt (GAP) | PROBABLE | `docs/integration/TELEGRAM.md:34-49` |
| F-016 | Một hạn 4 giờ dùng chung cho signal/approval/entry; không có thời gian hiệu lực tối thiểu còn lại khi duyệt, không có hạn phía sàn (GTD); không xét lịch làm việc của người dùng. | Thiếu hụt (GAP) | SUSPICIOUS | `params/trend-pullback/baseline-v3.toml:31` |
| F-017 | "Revalidate trước khi thực thi" không nói rõ có được đổi qty/giá hay không → có thể thực thi thứ khác với thứ người dùng đã duyệt. | Mơ hồ (AMBIGUITY) | PROBABLE | `docs/trading/RISK_MANAGEMENT.md:143` |
| F-018 | Mẫu TP1/TP2 thiếu quy tắc làm tròn qty, không nói SL sau TP1 xử lý thế nào, không có quy trình thay SL không để hở. | Thiếu hụt (GAP) | PROBABLE | `docs/trading/EXECUTION_SPEC.md:77-85` |
| F-021 | Quy ước dấu funding không được ghi ở đâu, "ADDITIVE" không định nghĩa, giả định chu kỳ funding đồng nhất. | Mơ hồ (AMBIGUITY) | SUSPICIOUS | `docs/research/RESEARCH_PROTOCOL.md:113-115` |
| F-023 | 3–6 tháng paper không đủ để xác nhận thống kê lợi thế; tiêu chí thoát paper ("minimum forward evidence…") không định nghĩa. | Thiếu hụt (GAP) | PROBABLE | `docs/implementation/IMPLEMENTATION_PLAN.md:79-101` |
| F-024 | Research universe chọn "10–15 mã đủ thanh khoản" theo hiện tại, không có quy tắc point-in-time → thiên lệch sống sót/chọn lọc. | Thiếu hụt (GAP) | SUSPICIOUS | `docs/backtest/BACKTEST_SPEC.md:111-119` |
| F-026 | "Định kỳ" và "ngưỡng freshness cấu hình" không có giá trị; ngưỡng bỏ trống sẽ vô hiệu hoá fail-closed. | Mơ hồ (AMBIGUITY) | SUSPICIOUS | `docs/trading/EXECUTION_SPEC.md:114-132` |
| F-051 | Giới hạn 200 lệnh conditional là toàn tài khoản ("across all symbols"), không phải theo symbol như docs và `gates.py`; filter MAX_NUM_ALGO_ORDERS đã bị gỡ nên không thể "đọc động". | Lệch docs/plan↔code (DRIFT) | CONFIRMED | `docs/trading/EXECUTION_SPEC.md:153-155` |
| F-054 | Docs bỏ sót ngữ nghĩa algo order: không kiểm margin trước trigger, có thể REJECTED/EXPIRED lúc trigger, FINISHED không chứng minh đã thoát lệnh. | Thiếu hụt (GAP) | CONFIRMED | `docs/trading/EXECUTION_SPEC.md:87-98` |

#### Quyết định lập kế hoạch / ROADMAP (stage B) (16)

| ID | Tóm tắt | Loại | Độ tin cậy | Vị trí |
|---|---|---|---|---|
| F-904 | Phase-6 D-05 đã quyết định chia tập dữ liệu / walk-forward / holdout dùng một lần nhưng chưa bao giờ được lập kế hoạch hay cài đặt. | Thiếu hụt (GAP) | CONFIRMED | `.planning/phases/06-backtest-simulator-experiment-registry/06-CONTEXT.md` |
| F-906 | Độ sâu lịch sử trôi: code mặc định 1m 7 ngày, 1H/4H 30 ngày thay vì 6–12 tháng / 2 năm; 180 nến 4H không đủ warm-up EMA200-4H. | Lệch docs/plan↔code (DRIFT) | CONFIRMED | `src/data/backfill.py:549-581` |
| F-907 | Việc mở rộng research universe (10–15 mã) bị hoãn với lời hứa "có phase riêng" nhưng không có phase/requirement nào sở hữu. | Thiếu hụt (GAP) | CONFIRMED | `.planning/phases/02-data-foundation/02-CONTEXT.md:14-94` |
| F-908 | Cluster tương quan hard-code {BTC, ETH, SOL, XRP}, loại BNB, trái với khuyến nghị "tham số registry"; cap chỉ đếm vị thế đã khớp. | Lỗi (DEFECT) | CONFIRMED | `src/risk/portfolio.py:26-31` |
| F-952 | Kế hoạch chọn reconciler chỉ-huỷ, không bao giờ đặt lại SL; 09 WR-07 (emergency close huỷ SL trước khi phẳng vị thế; entry hết hạn để lại SL close-all) bị bỏ qua, không phase nào nhận. Verifier hạ MEDIUM. Verify: DOWNGRADED. | Thiếu hụt (GAP) | CONFIRMED | `src/execution/manager.py:627-832` |
| F-953 | Cổng bật live chỉ "phủ định": `enable()` chấp nhận KillGateState.WITHIN_BUDGET (chưa family nào pass), không cần paper exit gate. Verifier hạ MEDIUM vì chưa có đường live. Trùng: F-105. Verify: DOWNGRADED. | Thiếu hụt (GAP) | CONFIRMED | `src/execution/enablement.py:147-208` |
| F-954 | ROADMAP xếp các sửa lỗi an toàn tiền (P11–P15) sau phase live-rollout 9, không có quy tắc "cấm live đến khi P11–P15 xong"; P11 không đứng trước paper soak. Verifier hạ MEDIUM. Verify: DOWNGRADED. | Thiếu hụt (GAP) | CONFIRMED | `.planning/ROADMAP.md:286-435` |
| F-955 | P11–P17 bỏ sót nhiều mục an toàn: thời gian hiệu lực tối thiểu khi duyệt, GTD, cap tính cả lệnh chờ + đã duyệt dưới khoá, trần chi phí/rủi ro, cap algo toàn tài khoản, user-data stream, nhịp reconcile. | Thiếu hụt (GAP) | PROBABLE | `.planning/ROADMAP.md:355-430` |
| F-956 | Không có phase cho runtime composition (M1–M4) hay verification phase 06–10; Phase 8 đánh dấu Complete dù thiếu VERIFICATION; P11–P17 sửa các hàm chưa có caller production. | Thiếu hụt (GAP) | PROBABLE | `.planning/v0.3-MILESTONE-AUDIT.md` |
| F-958 | Phase 9 hard-code `workingType=MARK_PRICE` cho SL/TP live mà không có quyết định ghi nhận và không có backtest theo mark price (backtest dùng nến 1m last price). | Lệch docs/plan↔code (DRIFT) | PROBABLE | `src/execution/manager.py:554` |
| F-959 | Phase 9 không dùng GTD; entry là GTC tại giữa vùng và chỉ hết hạn nhờ lệnh huỷ cục bộ vốn chưa có caller runtime. | Thiếu hụt (GAP) | PROBABLE | `.planning/phases/09-live-execution-rollout/COVERAGE.md:27` |
| F-960 | "Pass" của kill gate là quyết định người ghi tay với ngưỡng TBD (D030); các review finding có thể làm giả/lật kill gate (WR-01/06/10/12/13) bị bỏ qua chờ một người dùng không chuyên quyết định. | Thiếu hụt (GAP) | PROBABLE | `docs/DECISIONS.md:35` |
| F-961 | Paper gán độ trễ duyệt cố định 30 s và nút SIMULATE không hoạt động → tác động của việc người dùng bận/không có mặt chỉ được đo lần đầu bằng tiền thật. | Thiếu hụt (GAP) | PROBABLE | `src/paper/attribution.py:47-51` |
| F-962 | Mục tiêu P11 thiếu: trượt giá lúc thoát, khoảng cách theo mép bất lợi, quy tắc max(phí param, phí tài khoản), xử lý entry taker/GTX, trần chi phí/rủi ro, test "lỗ tại SL ≤ ngân sách". | Thiếu hụt (GAP) | PROBABLE | `.planning/ROADMAP.md:355-364` |
| F-963 | Mục tiêu P12 để ngỏ trường equity, định nghĩa daily loss (ngày UTC, realized + phí + funding, gốc, lưu bền) và phụ thuộc user-data stream chưa tồn tại. | Thiếu hụt (GAP) | PROBABLE | `.planning/ROADMAP.md:366-375` |
| F-964 | Mục tiêu P13 chấp nhận giá thanh lý "strictly beyond" SL (không có đệm), để ngỏ isolated vs cross, không có trần leverage hay kiểm tra Multi-Assets. | Thiếu hụt (GAP) | SUSPICIOUS | `.planning/ROADMAP.md:377-386` |

#### Backtest / paper / phương pháp nghiên cứu (8)

| ID | Tóm tắt | Loại | Độ tin cậy | Vị trí |
|---|---|---|---|---|
| F-102 | Backtest thoát toàn bộ tại TP1 trong khi live chia TP1 (một phần) + TP2; lời biện minh "conservative" là sai (trường hợp TP1 rồi SL bị lạc quan). | Lệch docs/plan↔code (DRIFT) | CONFIRMED | `src/backtest/simulator.py:116-126` |
| F-125 | Paper WS adapter gọi hàm async `kline_candlestick_streams(...)` thiếu `await` → paper soak (PAPER-01/03, chặng dài 3–6 tháng) không thể khởi động; supervisor bỏ kết quả resync; không có producer fill mô phỏng. | Lỗi (DEFECT) | CONFIRMED | `src/adapters/paper_ws.py:155-211` |
| F-204 | Mẫu số R khác nhau: backtest dùng realized_risk sau làm tròn, live dùng `plan.risk_budget` trước làm tròn → \|R\| live nhỏ hơn hệ thống 0–40%+. | Lỗi (DEFECT) | CONFIRMED | `src/analytics/live_outcomes.py:238-241` |
| F-305 | Simulator kiểm mọi nến lịch sử với MỘT constraint snapshot TTL 1 giờ (nến ngoài cửa sổ → STALE_CONSTRAINTS); open_positions, daily_loss, equity bị đóng băng cả run nên cap/DAILY_STOP không bao giờ có hiệu lực. | Lỗi (DEFECT) | CONFIRMED | `src/backtest/simulator.py:713-821` |
| F-306 | `_apply_costs` trừ slippage = qty × tỷ lệ (thiếu nhân giá): nhỏ hơn 60.000× trên BTC giá 60k, lớn gấp 2× trên XRP giá 0,5. 06-REVIEW WR-13 bị bỏ qua, không nằm trong P11. | Lỗi (DEFECT) | CONFIRMED | `src/backtest/simulator.py:650-661` |
| F-801 | Hồi quy Phase 5→6: Phase 6 (77a0659) âm thầm đổi hợp đồng `modeled_costs_per_unit` từ quote/đơn vị sang tỷ lệ không thứ nguyên; paper và live dùng lại hàm này. Gốc của F-001. | Lỗi (DEFECT) | CONFIRMED | `src/backtest/costs.py:184-203` |
| F-804 | Fix 06 WR-12 đóng dấu thời điểm thoát bằng phút 1m của chính nến tín hiệu → `exit_time_utc` < `entry_time_utc`; Phase 10 đánh dấu mọi giao dịch đó INCOMPLETE NEGATIVE_INTERVAL. Không có test. | Lỗi (DEFECT) | CONFIRMED | `src/backtest/simulator.py:862-878` |
| F-905 | Funding không bao giờ được mô hình: backfill funding chỉ 8 giờ, backtest hard-code funding = 0, WR-03 bị bỏ qua không ai sở hữu. | Thiếu hụt (GAP) | CONFIRMED | `src/backtest/simulator.py:655-656` |

#### Thực thi lệnh & tích hợp Binance/Telegram (8)

| ID | Tóm tắt | Loại | Độ tin cậy | Vị trí |
|---|---|---|---|---|
| F-103 | Tỷ lệ chia TP1, quy tắc TP2 (2× chặng TP1) và time-in-force GTC ảnh hưởng kết quả nhưng không phải tham số đã đăng ký; tỷ lệ TP1 chỉ được test đặt (0.5). | Thiếu hụt (GAP) | CONFIRMED | `src/execution/placement.py:49-76` |
| F-203 | `execute_approved_plan` tính lại size với trạng thái do caller cấp và đặt `sized.quantity`, không so với plan đã duyệt/hash (golden phase9: đặt 3,311 so với 0,500 trong plan = 6,6×). | Lỗi (DEFECT) | CONFIRMED | `src/execution/manager.py:418-487` |
| F-303 | Không có quy tắc theo symbol: plan thứ hai trên symbol đang có vị thế vẫn qua cổng; ở one-way mode entry ngược chiều sẽ triệt tiêu vị thế hiện có. | Thiếu hụt (GAP) | CONFIRMED | `src/risk/portfolio.py:317-358` |
| F-304 | Live không bao giờ đọc `TradePlan.status` hay đánh giá `invalidation_rule_json`; backtest lại huỷ theo màu nến – một quy tắc khác. | Thiếu hụt (GAP) | CONFIRMED | `src/execution/manager.py:212-452` |
| F-502 | Lỗi huỷ chứa -2011 bị coi là "đã huỷ" dù -2011 cũng xảy ra khi lệnh đã FILLED → journal ghi `post_cancel` sai cho entry đã khớp. Verifier hạ MEDIUM (SAFE_MODE đã vào trước). Verify: DOWNGRADED. | Lỗi (DEFECT) | CONFIRMED | `src/adapters/binance_usdm.py:933-943` |
| F-503 | Không có phân loại mã lỗi khi đặt entry: -2013 không được map → mọi từ chối rõ ràng (-2019, -4164, -1021…) đều thành "mơ hồ" → SAFE_MODE; nhánh ENTRY_ABSENT không bao giờ tới. Trùng: F-205. | Lỗi (DEFECT) | CONFIRMED | `src/execution/manager.py:184-204` |
| F-504 | Adapter dựng client SDK với mặc định: timeout REST 1000 ms, 3 retry, không API key, URL production, không có công tắc testnet → lệnh POST dễ timeout → probe → SAFE_MODE. | Thiếu hụt (GAP) | CONFIRMED | `src/adapters/binance_usdm.py:526-527` |
| F-507 | Mọi chặng SL/TP live hard-code `workingType=MARK_PRICE` và không lưu trên plan, trái Corrected Rule 15 (CONTRACT_PRICE khớp backtest). Gốc: F-958/F-010. | Lỗi (DEFECT) | CONFIRMED | `src/execution/placement.py:325-450` |

#### Đối soát (reconcile) / SAFE_MODE / phục hồi (3)

| ID | Tóm tắt | Loại | Độ tin cậy | Vị trí |
|---|---|---|---|---|
| F-127 | Nhiều tuyên bố an toàn phase 8–9 mạnh hơn code: (a) SAFE_MODE chỉ trong bộ nhớ, restart là mất; (b) 8 drill chạy trên fake, tự kích SAFE_MODE; (c) "revalidate exchangeInfo" chỉ kiểm snapshot do caller cấp; (d) token một lần không đi trong callback nên cổng token so server với chính nó. | Lệch docs/plan↔code (DRIFT) | CONFIRMED | `src/reconcile/safe_mode.py:150-160` |
| F-703 | Không có ghi trước ý định lệnh (write-ahead): crash giữa ACK entry và ACK SL để lại entry không SL và không có bản ghi cục bộ; F-701 khiến reconcile không thấy. | Thiếu hụt (GAP) | PROBABLE | `src/execution/manager.py:459-584` |
| F-711 | Thoát SAFE_MODE tự động khi compare "sạch", không cần operator, local intent mặc định [] → có thể thoát SAFE_MODE khi còn rủi ro chưa biết (kế thừa điểm mù F-701). | Lỗi (DEFECT) | CONFIRMED | `src/reconcile/safe_mode.py:241-310` |

#### Dữ liệu / DB / đồng thời (6)

| ID | Tóm tắt | Loại | Độ tin cậy | Vị trí |
|---|---|---|---|---|
| F-402 | Backfill ghi ngày UTC hiện tại (chưa hết ngày) thành part.parquet "bất biến"; lần chạy sau cho ngày đó lỗi FileExistsError → ngày bị cụt vĩnh viễn, ingest bị chặn. | Lỗi (DEFECT) | CONFIRMED | `src/data/backfill.py:476-512` |
| F-403 | Hai cột VARCHAR(16) quá hẹp: `positions.status` không chứa được LIQUIDATION_REPORTED (20 ký tự), `symbol_metadata.contract_type` không chứa TRADIFI_PERPETUAL → insert PostgreSQL thất bại. | Lỗi (DEFECT) | CONFIRMED | `src/db/models.py:369` |
| F-404 | Schema không có FK, CHECK, unique (trừ fills): thiếu unique token hash, "tối đa một approval quyết định/plan", unique client_order_id, append-only journal; idempotency chỉ dựa vào khoá trong tiến trình. | Thiếu hụt (GAP) | CONFIRMED | `src/db/models.py:176-398` |
| F-405 | Nút APPROVE và SKIP dùng chung short_id → cùng một token và dòng approval có action định sẵn; SKIP trên yêu cầu APPROVE luôn INVALIDATED, lựa chọn bỏ qua không bao giờ được ghi. | Lỗi (DEFECT) | PROBABLE | `src/approval/replay.py:215-219` |
| F-406 | psycopg3 trả TIMESTAMPTZ theo TimeZone của session; engine không ghim UTC → trên PostgreSQL không đặt UTC mọi dòng đọc bị từ chối (MALFORMED_ROW). | Lỗi (DEFECT) | PROBABLE | `src/db/models.py:439-457` |
| F-407 | Cap danh mục/cluster kiểm trên snapshot do caller cấp, không khoá, không giữ chỗ rủi ro → các coroutine duyệt đồng thời đều qua và vượt cap. | Thiếu hụt (GAP) | CONFIRMED | `src/execution/manager.py:418-520` |

#### Kiến trúc / runtime composition (2)

| ID | Tóm tắt | Loại | Độ tin cậy | Vị trí |
|---|---|---|---|---|
| F-201 | Chỉ collector và các CLI offline chạy được. Ngoài M1–M4 còn thiếu M5 (gửi yêu cầu duyệt), M6 (lập lịch reconcile/health), M7 (đầu vào rủi ro lấy từ sàn), M8 (persistence). | Thiếu hụt (GAP) | CONFIRMED | `src/data/collector.py:908-942` |
| F-202 | Không có tầng persistence vận hành: mọi mapper `*_to_row` không có caller; approval lookup/save và `JournalLike.record` chỉ là Protocol, không có cài đặt PostgreSQL. | Thiếu hụt (GAP) | CONFIRMED | `src/db/mappers.py:47-374` |

#### Yêu cầu & truy vết (requirements) (8)

| ID | Tóm tắt | Loại | Độ tin cậy | Vị trí |
|---|---|---|---|---|
| F-106 | Không có cảnh báo vận hành nào (vị thế không bảo vệ, lệch local/Binance, lệnh lạ, dữ liệu cũ, DAILY_STOP…); chỉ có tin SIMULATE/APPROVE và probe health. | Thiếu hụt (GAP) | CONFIRMED | `src/adapters/telegram_notify.py:58-211` |
| F-107 | Mục tiêu "OI tích luỹ từ ngày đầu" chưa đạt: collector chưa bao giờ được deploy, trong khi cửa sổ API OI 30 ngày liên tục làm mất dữ liệu không thể lấy lại. | Thiếu hụt (GAP) | PROBABLE | `.planning/phases/02-data-foundation/02-VERIFICATION.md:22-34` |
| F-111 | Không có kiểm tra chuyển trạng thái (state machine) nào trong src/, dù DATA_MODEL §5 bắt buộc; ví dụ trong TESTING_STRATEGY §8 còn dùng trạng thái không tồn tại. | Thiếu hụt (GAP) | CONFIRMED | `docs/data/DATA_MODEL.md:355-362` |
| F-112 | DATA_MODEL định nghĩa 12 thực thể, DOMN-01 thu hẹp còn 7; `trades`, `feature_snapshots`, `experiment_runs`, registry trong DB chưa bao giờ được cài đặt, không có DECISIONS ghi nhận. | Thiếu hụt (GAP) | CONFIRMED | `docs/data/DATA_MODEL.md:1-353` |
| F-113 | Hình học family trong code khác "Stage baseline" bắt buộc trong family sheet (TP1, vị trí SL Family B), không có DECISIONS; sheet vẫn ghi "implemented: NO". | Lệch docs/plan↔code (DRIFT) | CONFIRMED | `src/core/planner.py:97-135` |
| F-115 | Các lỗi an toàn/tiền "chờ quyết định thiết kế" (09 WR-07, 09 CR-04, 10 WR-01/06/10/12/13) không có mục ROADMAP/backlog. | Thiếu hụt (GAP) | CONFIRMED | `.planning/phases/09-live-execution-rollout/09-REVIEW-FIX.md:268-280` |
| F-116 | Nhiều MUST trong docs không thành REQ-ID và chưa làm: cấm nới SL, cấm "gỡ gạc", lưu constraint snapshot, trình tự restart, version trong health, mã hoá secrets, điều khiển khẩn cấp. | Thiếu hụt (GAP) | CONFIRMED | `.planning/REQUIREMENTS.md:9-62` |
| F-128 | OPS-02 chưa có gì ngoài test tĩnh: không nạp credential, không chọn testnet/live, không kiểm quyền key; daily loss và equity do caller cấp. | Thiếu hụt (GAP) | CONFIRMED | `src/adapters/binance_usdm.py:526-530` |

#### Bảo mật / vận hành (4)

| ID | Tóm tắt | Loại | Độ tin cậy | Vị trí |
|---|---|---|---|---|
| F-108 | Backup không off-host, không mã hoá, không lịch, không retention; biến `BACKUP_TARGET` không được CLI đọc; checkpoint "off-host" do orchestrator đóng. Trùng: F-910. | Lệch docs/plan↔code (DRIFT) | CONFIRMED | `src/ops/backup.py:28-59` |
| F-121 | "Restore drill" DATA-04 không hề restore PostgreSQL, chỉ copy file dump và so sha256; bằng chứng cũ tạo khi CLI còn dump SQLite. | Lệch docs/plan↔code (DRIFT) | CONFIRMED | `src/ops/backup.py:17-392` |
| F-704 | Runner backup đưa `DATABASE_URL` dạng `postgresql+psycopg://` cho pg_dump (libpq không hiểu) → backup thất bại với cấu hình tài liệu; mật khẩu lộ trên argv; image không có pg_dump. | Lỗi (DEFECT) | PROBABLE | `src/ops/backup.py:455-477` |
| F-706 | Không kiểm đồng hồ ở đâu cả: không truy vấn server time; ký request, hết hạn approval và độ cũ feed đều tin đồng hồ máy local; freshness chấp nhận độ cũ âm. | Thiếu hụt (GAP) | CONFIRMED | `src/adapters/binance_usdm.py:526-527` |

#### Kiểm thử (5)

| ID | Tóm tắt | Loại | Độ tin cậy | Vị trí |
|---|---|---|---|---|
| F-601 | Đường nối đơn vị chi phí không có oracle; test duy nhất nối hai phía tự tính lại đúng công thức sai; golden cho lỗ SL 103,59 so với rủi ro 50 mà không assert. Verifier hạ MEDIUM (P11 đã lên lịch). Verify: DOWNGRADED. | Thiếu hụt (GAP) | CONFIRMED | `tests/test_backtest_simulator.py:326-358` |
| F-602 | Test simulator không có oracle nhân quả/cấu trúc thoát: generator đặt dữ liệu 1m trong chính nến tín hiệu; 7/9 case không có expected.json; `_load_expected` là code chết; TP2 không được so. Đính chính "golden pin byte-for-byte". Verify: DOWNGRADED. | Thiếu hụt (GAP) | CONFIRMED | `scripts/gen_phase6_fixtures.py:211-358` |
| F-604 | Bộ test khẳng định các quy tắc an toàn SAI (cấm đặt lại SL, zero rescue sau khi SL bị từ chối, `enable()` cho phép ở WITHIN_BUDGET) → sửa theo quy tắc đúng sẽ làm test đỏ. | Lỗi (DEFECT) | CONFIRMED | `tests/test_execution_enablement.py:352-364` |
| F-606 | Test PG bị skip và dùng `create_all` (migration chưa từng chạy trên DB); parity migration chỉ so tên cột; không có test restart/rehydrate SAFE_MODE/enablement/kill gate. | Thiếu hụt (GAP) | CONFIRMED | `tests/test_domain_mappers_pg.py:26-44` |
| F-607 | Fake WS của paper là sync trong khi SDK là async và không bị ràng buộc chữ ký → lọt lỗi thiếu `await` (F-125). | Thiếu hụt (GAP) | CONFIRMED | `tests/test_paper_ws_connect.py:43-69` |

#### Quy trình (review / verification / checkpoint) (10)

| ID | Tóm tắt | Loại | Độ tin cậy | Vị trí |
|---|---|---|---|---|
| F-101 | Ba CI gate được trích là "enforced by gate" chưa từng chạy (origin là đường dẫn local, không GitHub); registry-gate đỏ tại HEAD; tripwire của research-gate vô nghĩa vì registry là TOML dưới params/. | Thiếu hụt (GAP) | CONFIRMED | `.github/workflows/registry-gate.yml:31-80` |
| F-109 | 05-VERIFICATION đánh dấu SC1/RISK-01 "VERIFIED … gồm chi phí" dựa trên fixture tự tạo; lỗi đơn vị chi phí cho thấy verification chỉ kiểm tự-nhất-quán. | Lệch docs/plan↔code (DRIFT) | CONFIRMED | `.planning/phases/05-risk-engine/05-VERIFICATION.md:44-128` |
| F-124 | Plan bị kẹt ở checkpoint cần người (09-04 blocked, 08-02 halted) vẫn hiển thị hoàn thành; checkpoint một chiều (one-way door) được auto-executor tự xoá. | Lệch docs/plan↔code (DRIFT) | CONFIRMED | `.planning/phases/09-live-execution-rollout/09-04-SUMMARY.md:107-266` |
| F-802 | 06-REVIEW-FIX đóng WR-03/WR-13 là "đã mở cross-phase item" và CR-04 là "cần design call" nhưng không có mục nào được tạo; lỗi đơn vị phí vô hình 3 ngày trong khi paper/live dùng lại. | Thiếu hụt (GAP) | CONFIRMED | `.planning/phases/06-backtest-simulator-experiment-registry/06-REVIEW-FIX.md:283-325` |
| F-803 | Hai đợt REVIEW-FIX 06 (23 fix) và 08 (34 fix) được commit khi test bị ảnh hưởng không import được (thiếu structlog/tenacity/SDK, Python 3.14) → tuyên bố "không hồi quy" vô nghĩa. | Thiếu hụt (GAP) | CONFIRMED | `.planning/phases/06-backtest-simulator-experiment-registry/06-REVIEW-FIX.md:23-37` |
| F-805 | Commit 06-01 không khớp plan: không có golden `expected.json`/sha256 pinning (mitigation T-06-02), implementation commit trước test, thiếu fixture parity chi phí khác 0; verification vẫn ghi "Pinned … VERIFIED". | Lệch docs/plan↔code (DRIFT) | CONFIRMED | `tests/test_backtest_simulator.py:1-40` |
| F-806 | Review fix Phase-4 CR-03 thay quyết định checkpoint một chiều 04-03 (quy tắc TP) và regenerate golden sau khi 04-VERIFICATION đã pass; STATE.md vẫn ghi quy tắc cũ, không có người xác nhận. | Lệch docs/plan↔code (DRIFT) | CONFIRMED | `.planning/STATE.md:124` |
| F-807 | VERIFICATION phase 02, 04, 05, 07.1 được commit TRƯỚC các đợt review-fix (36/12/13/3 commit) nhưng milestone audit vẫn tính là đã pass. | Lệch docs/plan↔code (DRIFT) | CONFIRMED | `.planning/v0.3-MILESTONE-AUDIT.md:214-234` |
| F-808 | Bảng disposition làm phẳng fix một phần thành "fixed" (09 CR-04, CR-08, WR-06); ~30 fix "cần người xác nhận" chưa bao giờ được xác nhận. | Thiếu hụt (GAP) | CONFIRMED | `.planning/phases/09-live-execution-rollout/09-REVIEW-DISPOSITION.md:130-152` |
| F-809 | Thêm 7 checkpoint (03-04, 05-01, 02-05, 03-01, 03-02, 07.1-01, 04-03) được xoá mà không có quyết định của người được ghi lại. | Thiếu hụt (GAP) | CONFIRMED | `.planning/phases/03-domain-registry-fixtures/03-04-SUMMARY.md:207-216` |

---

## 8. Finding LOW / INFO, trùng lặp, bị bác bỏ

### 8.1 LOW (45) và INFO (4)

#### Thiết kế tài liệu (docs, stage A) (14)

| ID | Mức | Tóm tắt | Loại | Độ tin cậy | Vị trí |
|---|---|---|---|---|---|
| F-031 | INFO | Bậc phí, giảm giá BNB, cặp USDC-margined không được đề cập; phí thực có thể khác phí trong params. KNOWN P11/P17. | Khuyến nghị cải tiến | SUSPICIOUS | `docs/trading/RISK_MANAGEMENT.md:34-42` |
| F-057 | INFO | SOURCES.md trỏ trang WebSocket COIN-M cho USD-M; EXEC_SPEC trích trang New-Order cho quy tắc đổi position mode. | Lệch docs/plan↔code (DRIFT) | CONFIRMED | `docs/SOURCES.md:134` |
| F-003 | LOW | Ở $500, BTCUSDT từ chối phần lớn SL swing (minNotional/60%); tỷ lệ NO_TRADE không được ghi; quy tắc 60% tạo dải từ chối không đơn điệu. | Thiếu hụt (GAP) | SUSPICIOUS | `docs/trading/RISK_MANAGEMENT.md:113-124` |
| F-019 | LOW | Thanh lý và ADL (đóng/giảm vị thế không do lệnh của ta) không được mô tả ngoài trạng thái LIQUIDATION_REPORTED. | Thiếu hụt (GAP) | SUSPICIOUS | `docs/GLOSSARY.md:103-111` |
| F-020 | LOW | "Hỗ trợ position mode đã chọn" vs "hỗ trợ cả hai" mâu thuẫn; ảnh hưởng Multi-Assets mode tới margin không được đề cập. | Mơ hồ (AMBIGUITY) | PROBABLE | `docs/trading/EXECUTION_SPEC.md:106-112` |
| F-025 | LOW | Family sheet diễn đạt lại kill gate sai ("3 family × 6 tháng forward evidence", "cả 3 family phải qua"), mâu thuẫn D030. | Lệch docs/plan↔code (DRIFT) | PROBABLE | `docs/research/families/trend-pullback.md:199-209` |
| F-027 | LOW | IP allowlist chỉ là "ưu tiên"; các quyền khác (universal transfer, spot/margin) không bị giới hạn. | Thiếu hụt (GAP) | PROBABLE | `docs/operations/SECURITY_AND_OPERATIONS.md:3-10` |
| F-028 | LOW | Protocol định nghĩa phí theo basis point/chiều, params lưu dạng phân số (0.0002). | Lỗi (DEFECT) | PROBABLE | `docs/research/RESEARCH_PROTOCOL.md:91-92` |
| F-029 | LOW | Có tickSize nhưng không có chiều làm tròn cho entry/SL/TP và thứ tự làm tròn so với sizing. | Thiếu hụt (GAP) | SUSPICIOUS | `docs/trading/RISK_MANAGEMENT.md:25-32` |
| F-030 | LOW | "Range bị vô hiệu và thoát tại SL" khi nến 1H đóng phá vỡ là một lệnh thoát theo nến đóng, không phải lệnh phía sàn. | Mơ hồ (AMBIGUITY) | SUSPICIOUS | `docs/research/families/range-mr.md:47` |
| F-052 | LOW | "TradingView webhooks (HMAC-checked)" không thể làm: TradingView không ký request, không đặt header tuỳ ý. | Lệch docs/plan↔code (DRIFT) | CONFIRMED | `AGENTS.md:77` |
| F-053 | LOW | Docs không nhắc việc tách base-URL WebSocket USD-M ngày 2026-04-23 (/public, /market, /private); URL cũ sẽ im lặng ngừng dữ liệu (SDK đã xử lý). | Thiếu hụt (GAP) | CONFIRMED | `docs/integration/BINANCE.md:23-42` |
| F-056 | LOW | Docs quantization bỏ qua MARKET_LOT_SIZE (áp cho TP1 *_MARKET có quantity) và PERCENT_PRICE (dải giá LIMIT). | Thiếu hụt (GAP) | CONFIRMED | `docs/trading/RISK_MANAGEMENT.md:257-296` |
| F-058 | LOW | SDK khai báo quantity/price là float; docs không định nghĩa chuyển Decimal→wire. (Lane L5: code đã đóng rủi ro bằng `_decimal_to_wire`.) | Thiếu hụt (GAP) | CONFIRMED | `binance_sdk_derivatives_trading_usds_futures/rest_api/api/trade_api.py:1343-1345` |

#### Quyết định lập kế hoạch / ROADMAP (stage B) (4)

| ID | Mức | Tóm tắt | Loại | Độ tin cậy | Vị trí |
|---|---|---|---|---|---|
| F-909 | LOW | Giá trị tham số seed/tracer (signal_expiry_hours 4, sl_buffer_atr 0.2, minimum_rr 2, zone_tolerance_atr 0.5) trở thành baseline nghiên cứu/paper mà không có lý do. | Khuyến nghị cải tiến | PROBABLE | `params/trend-pullback/baseline-v1.toml:19-27` |
| F-965 | LOW | Phase 9 cam kết hỗ trợ cả hai position mode; quy tắc đã hiệu chỉnh là chỉ one-way single-asset, mode khác → không vào lệnh mới. | Khuyến nghị cải tiến | PROBABLE | `.planning/ROADMAP.md:296` |
| F-966 | LOW | P14 chỉ kiểm margin cho lệnh mới (bỏ qua entry đang chờ / plan đã duyệt); P16 thiếu giá thanh lý, giá hiện tại, thời gian còn lại. | Thiếu hụt (GAP) | PROBABLE | `.planning/ROADMAP.md:388-419` |
| F-967 | LOW | Lệch sổ sách: 10-REVIEW-DISPOSITION còn "open" các mục đã fix; Phase 8 Complete dù 08-05 chưa tick; requirement P11–P17 là TBD; các mục "chờ người dùng xác nhận" chưa thu thập. | Lệch docs/plan↔code (DRIFT) | PROBABLE | `.planning/phases/10-journal-depth-kill-gate-operations/10-REVIEW-DISPOSITION.md` |

#### Backtest / paper / phương pháp nghiên cứu (4)

| ID | Mức | Tóm tắt | Loại | Độ tin cậy | Vị trí |
|---|---|---|---|---|---|
| F-118 | LOW | ExperimentRecord thiếu trường protocol bắt buộc (số NO_TRADE và lý do, tie-break, timeframe, tham số/chi phí đầy đủ); `code_version` là chuỗi caller không kiểm. | Thiếu hụt (GAP) | CONFIRMED | `src/backtest/experiment.py:90-121` |
| F-123 | LOW | Report cắt theo regime đọc `trade["regime"]` mà simulator không phát ra → mọi backtest thật đều regime = UNKNOWN; không có producer cho phân tích plateau. | Thiếu hụt (GAP) | CONFIRMED | `src/backtest/report.py:612-620` |
| F-810 | LOW | Review fix bd12652 thêm khoá vào bộ tham số baseline-v1 đã được tham chiếu → đổi hash; tripwire bị "thoả mãn" bằng cách regenerate hash; không có hash lock commit. | Lỗi (DEFECT) | CONFIRMED | `params/range-mr/baseline-v1.toml:44-49` |
| F-812 | LOW | Việc migrate test 07.1 ghi đè trong bộ nhớ các cost dict phase-6 "grandfathered" từ 1.0 sang 0.5 → mọi test assemble() mô phỏng khớp nửa lệnh. | Lệch docs/plan↔code (DRIFT) | CONFIRMED | `tests/test_backtest_experiment.py:48-65` |

#### Thực thi lệnh & tích hợp Binance/Telegram (8)

| ID | Mức | Tóm tắt | Loại | Độ tin cậy | Vị trí |
|---|---|---|---|---|---|
| F-206 | LOW | Protocol `ExecutionAdapter` khai báo `**kwargs: Any` → adapter thật không gán được dưới mypy strict, dict lệnh không được kiểm tĩnh. | Lỗi (DEFECT) | CONFIRMED | `src/execution/manager.py:69-89` |
| F-207 | LOW | Làm tròn tick chỉ có ở đường live và sau sizing; backtest/paper khớp ở giá giữa vùng chưa làm tròn; live làm tròn SL về phía entry (an toàn nhưng khác Corrected Rule 6). | Lệch docs/plan↔code (DRIFT) | CONFIRMED | `src/execution/manager.py:471-484` |
| F-208 | LOW | Logic/hằng số trùng lặp: `quantize_protective_qty` áp MIN_NOTIONAL cho TP reduce-only (Binance miễn) và dùng LOT_SIZE thay MARKET_LOT_SIZE; danh sách live-5 lặp 4 nơi. | Khuyến nghị cải tiến | CONFIRMED | `src/execution/placement.py:221-275` |
| F-307 | LOW | Lệnh đã qua sizing có thể trượt sizing TP1 (floor(filled×0,5) < minQty hoặc MIN_NOTIONAL sai trên reduce-only) → chỉ đặt SL và buộc ENTRY_WITHOUT_PROTECTIVE + SAFE_MODE. | Lỗi (DEFECT) | CONFIRMED | `src/execution/placement.py:221-410` |
| F-505 | LOW | Không truyền recvWindow, không kiểm lệch giờ với server (`check_server_time` không dùng) → lệch đồng hồ gây -1021 trên mọi request ký, qua F-503 thành SAFE_MODE không chẩn đoán được. | Thiếu hụt (GAP) | CONFIRMED | `src/adapters/binance_usdm.py:761-1249` |
| F-506 | LOW | Backfill retry cả 429 và 418 (IP ban) với backoff ngắn, bỏ qua retry_after; không đọc header X-MBX-USED-WEIGHT. | Lỗi (DEFECT) | CONFIRMED | `src/data/backfill.py:184-223` |
| F-508 | LOW | Duyệt lệnh qua Telegram chỉ kiểm `chat.id`, không kiểm `from_user.id` → thành viên nhóm chat có thể APPROVE; APPROVE/SKIP là hai keyboard riêng. Trùng: F-707. | Thiếu hụt (GAP) | CONFIRMED | `src/adapters/telegram_callbacks.py:184-197` |
| F-509 | LOW | Sau khi quyết định, tin nhắn không được sửa và nút vẫn bấm được; dispatch đồng bộ + I/O DB trong handler async; notify retry TimedOut (có thể đã gửi), bỏ qua RetryAfter. | Khuyến nghị cải tiến | CONFIRMED | `src/adapters/telegram_callbacks.py:657-699` |

#### Dữ liệu / DB / đồng thời (6)

| ID | Mức | Tóm tắt | Loại | Độ tin cậy | Vị trí |
|---|---|---|---|---|---|
| F-408 | LOW | File Parquet ghi thẳng vào đường dẫn cuối, không tmp + `os.replace` → file ghi dở trở thành dữ liệu "bất biến" vĩnh viễn. | Lỗi (DEFECT) | PROBABLE | `src/data/store.py:83-89` |
| F-409 | LOW | Quality gate coi nến có trade_count ≤ 0 là hỏng → một nến không giao dịch làm hỏng cả trang; sau 5 lần backfill dừng vĩnh viễn tại đó. | Lỗi (DEFECT) | PROBABLE | `src/data/quality.py:170-203` |
| F-410 | LOW | Planner hash Decimal độ chính xác 28 chưa lượng tử hoá; NUMERIC(38,18) làm tròn → không tái tạo được plan_hash từ dòng đã lưu. | Lỗi (DEFECT) | CONFIRMED | `src/db/models.py:223-234` |
| F-411 | LOW | ORM metadata không khai báo 14 index của migration, kể cả unique index chống rebinding duy nhất; test dùng create_all nên migration không bao giờ được chạy. | Lệch docs/plan↔code (DRIFT) | CONFIRMED | `src/db/alembic/versions/0003_callback_mapping.py:33-38` |
| F-412 | LOW | Fix WR-09 chưa trọn: id journal SAFE_MODE/sweeper/drill vẫn từ (tên, mili-giây) → nhiều sự kiện trong một tick trùng khoá chính; callback outcome dùng uuid4 nên không replay-safe. | Lỗi (DEFECT) | PROBABLE | `src/reconcile/safe_mode.py:327` |
| F-413 | LOW | Supervisor subscribe lại WS trước khi chờ backfill REST → nến live vượt lên trước nến backfill cũ hơn và bị trùng. | Lỗi (DEFECT) | PROBABLE | `src/paper/supervisor.py:230-315` |

#### Kiến trúc / runtime composition (1)

| ID | Mức | Tóm tắt | Loại | Độ tin cậy | Vị trí |
|---|---|---|---|---|---|
| F-209 | INFO | `src/domain/registry.py` đọc file theo đường dẫn nguồn; Dockerfile không copy params/ → backtest trong container sẽ fail-closed; image uv không ghim phiên bản. | Khuyến nghị cải tiến | CONFIRMED | `src/domain/registry.py:36-387` |

#### Yêu cầu & truy vết (requirements) (5)

| ID | Mức | Tóm tắt | Loại | Độ tin cậy | Vị trí |
|---|---|---|---|---|---|
| F-119 | INFO | Dòng trống ở DECISIONS.md:22 tách bảng; ví dụ alert trong SIGNAL_AND_ALERTS có R:R 1.8 (< minimum_rr 2.0) và giờ UTC thay vì Asia/Ho_Chi_Minh. | Lệch docs/plan↔code (DRIFT) | CONFIRMED | `docs/DECISIONS.md:21-23` |
| F-110 | LOW | GLOSSARY §9 vi phạm quy tắc "không đồng nghĩa" (nhiều cặp mã lý do trùng); code phát mã không có trong GLOSSARY; enum ApprovalResult không có trong GLOSSARY. | Lệch docs/plan↔code (DRIFT) | CONFIRMED | `docs/GLOSSARY.md:150-179` |
| F-114 | LOW | Các artifact trạng thái mâu thuẫn nhau (ROADMAP bảng tiến độ, checkbox, STATE total_phases 11 vs 17, PROJECT "Greenfield: no src/", 25/30 Pending). | Lệch docs/plan↔code (DRIFT) | CONFIRMED | `.planning/ROADMAP.md:436-455` |
| F-117 | LOW | Stack thực tế lệch AGENTS: không có FastAPI/uvicorn/NumPy/SciPy/VectorBT, không có HTTP health; không workflow nào chạy pytest/ruff/mypy; HEAD đỏ cả ba linter. | Lệch docs/plan↔code (DRIFT) | CONFIRMED | `pyproject.toml:9-41` |
| F-122 | LOW | `backfill_universe` (bootstrap DATA-01) và `refresh_symbol_metadata` (DATA-03) không có caller hay CLI; SUMMARY tuyên bố có test nhưng không có. | Lệch docs/plan↔code (DRIFT) | CONFIRMED | `src/data/backfill.py:564-600` |

#### Bảo mật / vận hành (3)

| ID | Mức | Tóm tắt | Loại | Độ tin cậy | Vị trí |
|---|---|---|---|---|---|
| F-705 | LOW | HEALTHCHECK Docker chạy interpreter hệ thống thay vì venv của uv → import polars/sqlalchemy thất bại, container luôn unhealthy (PROBABLE, chưa chạy Docker). | Lỗi (DEFECT) | PROBABLE | `Dockerfile:8-34` |
| F-708 | LOW | `make_engine` in toàn bộ DB URL kèm mật khẩu trong ValueError; sweeper journal nguyên văn lỗi SDK, có thể chứa URL có chữ ký. | Lỗi (DEFECT) | CONFIRMED | `src/db/models.py:450-454` |
| F-709 | LOW | Postgres mở trên mọi interface với mật khẩu placeholder; app nhận toàn bộ .env; image uv:latest/python không ghim digest; .gitignore hẹp. | Khuyến nghị cải tiến | CONFIRMED | `docker-compose.yml:21-34` |

#### Kiểm thử (3)

| ID | Mức | Tóm tắt | Loại | Độ tin cậy | Vị trí |
|---|---|---|---|---|---|
| F-605 | LOW | Không CI/test nào bắt buộc ruff, mypy hay full pytest; các tuyên bố "mypy clean" đã cũ (hiện 5 lỗi mypy, 36 lỗi ruff); 5 lỗi mypy đều là nhiễu kiểu. | Thiếu hụt (GAP) | CONFIRMED | `.github/workflows/registry-gate.yml:1-100` |
| F-608 | LOW | Golden expectation được tính bởi chính src (script regen import evaluate/plan) → chỉ phát hiện thay đổi, không phải oracle. | Thiếu hụt (GAP) | CONFIRMED | `scripts/_regen_phase4_expectations.py:1-45` |
| F-609 | LOW | ~33 test "coverage" review-fix là grep văn bản nguồn; 10-VALIDATION nyquist_compliant dựa vào test PG luôn bị skip. | Lệch docs/plan↔code (DRIFT) | CONFIRMED | `tests/test_phase8_audit_reviewfix.py:1243-1425` |

#### Quy trình (review / verification / checkpoint) (1)

| ID | Mức | Tóm tắt | Loại | Độ tin cậy | Vị trí |
|---|---|---|---|---|---|
| F-811 | LOW | Fix Phase-10 WR-05/WR-09 đổi hợp đồng CLI nhưng UI-SPEC không cập nhật; WR-08 thu hẹp bucket độ trễ duyệt, bỏ chiều OPPORTUNITY mà không ghi quyết định. | Lệch docs/plan↔code (DRIFT) | CONFIRMED | `.planning/phases/10-journal-depth-kill-gate-operations/10-UI-SPEC.md:370-377` |

### 8.2 Finding trùng lặp (liệt kê dưới finding chính)

| Finding chính (mức cuối) | Finding trùng (mức lane → cuối) | Ghi chú |
|---|---|---|
| F-120 (HIGH) | F-901 (HIGH → HIGH, V1 CONFIRMED) | Cùng gốc lookahead. F-901 là góc nhìn planning (06-01-PLAN). |
| F-022 (HIGH) | F-903 (HIGH → MEDIUM, V4) | Gốc ở planning: 01-RESEARCH:226 |
| F-126 (HIGH) | F-951 (HIGH → HIGH, V2 CONFIRMED); F-603 (HIGH → MEDIUM, V2) | Gốc thiết kế 08 D-04 và khoảng trống test |
| F-501 (HIGH, UNVERIFIED) | F-710 (MEDIUM, UNVERIFIED) | Cùng cơ chế probe algo |
| F-503 (MEDIUM) | F-205 (MEDIUM, PROBABLE) | Taxonomy lỗi entry, -2013 không được map |
| F-953 (MEDIUM) | F-105 (MEDIUM) | `enable()` chấp nhận WITHIN_BUDGET, điều kiện tiên quyết cho live không phải REQ |
| F-005 (MEDIUM) | F-055 (LOW) | Phí entry maker và GTC có thể khớp như taker |
| F-006 (MEDIUM) | F-957 (MEDIUM) | `partial_fill_fraction = 0.5` (07.1-01-PLAN) |
| F-108 (MEDIUM) | F-910 (LOW) | Backup OneDrive không mã hoá được coi là "off-host" |
| F-508 (LOW) | F-707 (LOW) | Duyệt lệnh chỉ theo chat id |

Tổng: 11 finding trùng + 1 bị bác bỏ + 152 finding chính = 164 finding thô.

### 8.3 Finding bị bác bỏ

**F-008 (A1, lane HIGH/UNVERIFIED): REJECTED bởi V4.**
- Phát biểu của lane: "Lệnh bảo vệ chỉ được đặt sau khi thấy entry khớp. LIMIT nằm chờ tới 4 giờ, nên nếu process/host/user-data stream chết đúng lúc khớp thì vị thế không có bảo vệ."
- Lý do bác bỏ: `execute_approved_plan` đặt SL (CONDITIONAL STOP_MARKET, `closePosition=true`) **ngay sau khi entry được ACK, trước khi khớp**. Comment trong code gọi đây là "the pre-fill safety net". Chỉ TP1/TP2 chờ tới khi khớp. EXECUTION_SPEC §6 là bước *kiểm tra* sau khi khớp, không phải quy tắc "chỉ được đặt sau khi khớp". Nếu bot chết trong lúc LIMIT đang chờ, SL vẫn còn trên sàn. Rủi ro thật là SL mồ côi, không phải vị thế trần.
- Rủi ro còn sót: SL đặt sẵn này lại chính là thứ F-401 huỷ nhầm. Việc Binance chấp nhận một lệnh `closePosition` CONDITIONAL khi chưa có vị thế là hành vi chuẩn; testnet sẽ khẳng định dứt khoát nhưng không làm đổi kết luận (V4).
- Câu chữ trong docs chỉ là DRIFT nhỏ.

---

## 9. Kết quả kiểm tra bất biến nghiệp vụ

`INVARIANTS.md` có 120 bất biến (INV-001…INV-120) và 39 điểm mơ hồ (AMB-001…AMB-039). Trong đó 108 INV được đánh dấu OK về domain, 10 QUESTIONABLE, 2 UNKNOWN (INV-066, INV-090). Bảng dưới gom theo nhóm. Trạng thái được đánh giá theo **quy tắc đã hiệu chỉnh** (§4.1), không theo docs gốc.

Chú thích trạng thái:
- **ENFORCED:** code thực thi đúng và có bằng chứng từ lane.
- **VIOLATED:** code vi phạm.
- **PARTIAL:** một phần đúng, một phần sai hoặc thiếu.
- **NOT IMPLEMENTED:** chưa có code.
- **UNVERIFIABLE:** không kiểm được trong phạm vi audit.

| Nhóm bất biến | INV chính | Trạng thái | Bằng chứng / finding |
|---|---|---|---|
| Tất định, nến đã đóng, không lookahead (strategy core) | INV-001, INV-003…INV-006 | **ENFORCED** (core) | Feature dùng cửa sổ trượt về phía sau, có cổng nến đang hình thành, không có pivot nhìn phải (L3 safe area). Suite prefix/no-lookahead cho `strategy.evaluate` (L6). |
| Không lookahead / mô phỏng khớp (backtest) | INV-003, INV-004, INV-103, INV-104 | **VIOLATED** | F-120/F-901 (khớp và thoát trên cùng nến), F-902 (chạm vùng = khớp ở giữa vùng), F-305 (snapshot TTL và trạng thái bị đóng băng), F-804 (thoát trước khi vào), F-102 (thoát một lần so với bậc TP1/TP2 của live) |
| Sizing theo rủi ro, lượng tử hoá | INV-053…INV-057 | **PARTIAL** | Làm tròn xuống, minQty, minNotional, 60% realized-risk: ENFORCED (L3, test oracle thật ở L6). Đơn vị chi phí: VIOLATED (F-001, F-801, F-601, KNOWN P11). qty đặt lệnh không bằng qty trong plan (F-203). |
| Phí / chi phí / tính nhất quán backtest-live | INV-058, INV-105 | **VIOLATED** | Phí maker so với GTC (F-005). Slippage thiếu nhân giá (F-306). Funding = 0 (F-905). Mẫu số R khác nhau (F-204). Làm tròn tick chỉ ở live (F-207). Trigger MARK so với last (F-507/F-958). |
| Cap danh mục, cluster, daily loss | INV-063…INV-067 | **PARTIAL / NOT IMPLEMENTED** | Cổng và biên ≥ đã có, cluster cap chặn một lệnh BNB đơn lẻ (L3). Nhưng: không có quy tắc theo symbol (F-303), không có khoá (F-407), cluster hard-code (F-908), cap bỏ qua lệnh đang chờ và plan đã duyệt (F-014, F-955). **Daily loss không có nguồn sinh giá trị** (L3, L6; KNOWN P12, F-963), equity do caller cấp (F-128). |
| Đòn bẩy / margin / thanh lý | INV-068…INV-070 | **NOT IMPLEMENTED** | F-011, F-964, F-966 (KNOWN P13/P14) |
| An toàn duyệt lệnh | INV-043…INV-052 | **PARTIAL** | Ràng buộc plan_hash, hết hạn tính biên, token 256-bit, không tự duyệt: ENFORCED trong process (L3, L7). Nhưng: approval không được tiêu thụ (F-126), không ràng buộc symbol/side (F-302), cổng token so server với chính nó (F-127(d)), chỉ kiểm chat id (F-508), SKIP không bao giờ thành công (F-405), không có thời gian hiệu lực tối thiểu (F-016, F-955), replay chỉ trong process (F-404). |
| Thực thi và bảo vệ lệnh | INV-080…INV-089 | **PARTIAL** | Algo CONDITIONAL, không kết hợp `closePosition` với qty/reduceOnly, không retry mù, SL đặt trước khi khớp: ENFORCED (L3, L5, L7). Nhưng: không có cổng giá (F-007), thiếu user-data/fill (F-104), taxonomy lỗi (F-503), -2011 trên lệnh huỷ đã FILLED (F-502), GTC không có GTD (F-959), sizing TP (F-307). F-501 là **UNVERIFIABLE** khi chưa có testnet. |
| Đối soát, SAFE_MODE, fail-closed | INV-074, INV-075, INV-091…INV-096 | **VIOLATED** | Sweeper huỷ SL của entry đang chờ (F-401). Compare không thấy qty/dấu/lệnh lạ/thiếu SL (F-701). SAFE_MODE tự thoát (F-711). SAFE_MODE chỉ trong bộ nhớ, mất khi restart (F-127(a)). Journal-first chặn hành động an toàn (F-702). Không có WAL (F-703). Reconciler chưa được lập lịch (F-201 M6). Fill replay idempotent qua `uq_fills_order_trade`: ENFORCED (L4). |
| Idempotency và trùng lệnh | INV-087 | **VIOLATED** | F-126 (F-951, F-603), F-404 (không có unique constraint) |
| Kill gate / nghiên cứu / bật live | INV-098…INV-102, INV-120 | **PARTIAL (quy tắc kích hoạt) / VIOLATED (định nghĩa pass và cổng bật live)** | Quy tắc kích hoạt D030 và đồng hồ: ENFORCED (B2, L1, test boundary ở L6). Nhưng: ngưỡng đặt sau khi xem kết quả, không hiệu chỉnh đa kiểm định (F-022, F-960), `enable()` chấp nhận WITHIN_BUDGET (F-953), không có chia tập / walk-forward (F-904), universe không point-in-time (F-024, F-907). |
| Dữ liệu (Decimal, UTC, bất biến, gap) | INV-011, INV-015, INV-107…INV-110 | **PARTIAL** | Numeric(38,18), Parquet Decimal, UTC, gap không bịa dữ liệu, cursor backfill atomic: ENFORCED (L4). Nhưng: ghi ngày dở dang thành file bất biến (F-402), ghi không atomic (F-408), cổng quality chặn nến 0 giao dịch (F-409), độ sâu lịch sử (F-906), collector chưa deploy nên OI mất vĩnh viễn (F-107), TIMESTAMPTZ khác UTC (F-406), plan_hash không tái tạo được (F-410). |
| Bảo mật / vận hành | INV-111…INV-117 | **PARTIAL** | Không có secret bị commit, container non-root, khoá dependency: ENFORCED (L7). Nhưng: backup (F-108, F-121, F-704), healthcheck (F-705, PROBABLE), lộ secret qua thông báo lỗi (F-708), compose (F-709), không kiểm quyền key (F-128), không có cảnh báo (F-106), đồng hồ (F-706, F-505). |
| Không có AI trong đường quyết định | Nhóm B (INV-0xx) | **Không có vi phạm được báo** | Không lane nào báo vi phạm. Không có kiểm tra chuyên biệt ngoài ranh giới import của lõi thuần (L2). |

---

## 10. Lệch tài liệu / kế hoạch

### 10.1 Lỗi thiết kế trong docs (stage A)

Lane A1 và A2 đánh giá docs như "ý định đã ghi lại", không phải sự thật. 39 finding (31 A1, 8 A2), trong đó 1 bị bác bỏ (F-008) và 1 là trùng (F-055). Các lỗi thiết kế quan trọng:

| Chủ đề | Lỗi | ID | Mức |
|---|---|---|---|
| Quản trị nghiên cứu | Ngưỡng đặt sau khi xem kết quả, không hiệu chỉnh đa kiểm định. Paper 3–6 tháng không đủ về thống kê. Family sheet diễn đạt kill gate sai. | F-022, F-023, F-025 | HIGH / MED / LOW |
| Thực thi | Không kiểm giá sau APPROVE, không có phương án khi SL bị từ chối sau khi khớp | F-007 | HIGH |
| Sizing / chi phí | Đơn vị chi phí; không có stop tối thiểu / trần chi phí; slippage đặt sai chỗ; phí maker; khớp một phần 0.5; funding; bps so với phân số | F-001, F-002, F-004, F-005, F-006, F-021, F-028 | MED/LOW |
| Rủi ro danh mục | Equity, daily loss, cluster và định nghĩa "open" chưa được xác định | F-012, F-013, F-014 | MED |
| SAFE_MODE | SECURITY_AND_OPERATIONS mâu thuẫn với RUNBOOK | F-009 | MED |
| Sự thật về sàn (A2) | 200 algo là toàn tài khoản; ngữ nghĩa algo (không kiểm margin trước trigger, FINISHED ≠ đã khớp); tách URL WS; MARKET_LOT_SIZE/PERCENT_PRICE; SDK float; TradingView HMAC bất khả thi | F-051, F-054, F-053, F-056, F-058, F-052 | MED/LOW |
| Đòn bẩy / margin | Đòn bẩy chỉ đọc, không có kiểm tra thanh lý; Multi-Assets | F-011, F-020 | MED/LOW |
| Duyệt lệnh | Tin nhắn thiếu số tiền; hạn 4 giờ dùng chung; "revalidate" mơ hồ | F-015, F-016, F-017 | MED |

A1 cũng xác nhận **14 nhóm quy tắc docs là đúng** (§17), và phát hành 37 "Corrected Rules" làm thước đo cho stage C.

### 10.2 Quyết định lập kế hoạch do AI tự chọn (stage B)

Sổ quyết định của B1 (phase 01–06) và B2 (phase 07–17). Theo B2, mọi D-xx của phase 07–17 đều được chọn tự động là "(recommended default)" dưới chế độ `--auto --chain`. Số dưới đây do synthesis đếm theo nhãn đứng đầu mỗi dòng; các dòng hỗn hợp như "SOUND (decision) / DRIFT (code)" được tính theo nhãn đầu.

| Sổ | Số dòng | SOUND | QUESTIONABLE | WRONG | RISKY-DEFERRAL | Khác |
|---|---|---|---|---|---|---|
| B1 (01–06) | 52 | 36 | 5 | 4 | 6 | 1 (KNOWN P11) |
| B2 (07–17) | 53 | 29 | 14 | 3 | 7 | 0 |
| **Tổng** | **105** | **65** | **19** | **7** | **13** | 1 |

**Các quyết định WRONG hoặc rủi ro quan trọng:**

| Phase / quyết định | Đã chọn | Verdict | Hệ quả |
|---|---|---|---|
| 01 RESEARCH "Don't hand-roll: acceptance numbers" | Ngưỡng TBD cho tới sau Validation | WRONG | F-903 → F-022 (HIGH) |
| 04 D-08 | TP1 = minimum_rr (cổng RR vô nghĩa) | WRONG → đã sửa (04-REVIEW CR-03) | Nhưng fix vượt quyền checkpoint 04-03 (F-806) |
| 04-03 checkpoint (auto option A) | entry_ref = giữa vùng | SOUND cho live / WRONG khi ánh xạ vào backtest | F-902 |
| 05 D-03 | Cluster {BTC, ETH, SOL, XRP}, bỏ BNB, hard-code | WRONG (thành viên) | F-908 |
| 05 D-03 daily loss | Hoãn ranh giới ngày sang "Phase 7/8" | RISKY-DEFERRAL | F-013, F-963 (P12) |
| 06-01-PLAN | Khớp khi chạm vùng, ở giá giữa, trên cùng nến | WRONG | F-120/F-901, F-902 |
| 06 D-01 | 1m intrabar + SL-first | SOUND chính sách / WRONG cách làm | F-901 |
| 06 D-05 | Chia tập / walk-forward / holdout | RISKY-DEFERRAL (mồ côi) | F-904 |
| 06 REVIEW-FIX skip CR-04, WR-03 | "Cross-phase item" không có chủ | RISKY-DEFERRAL | F-802, F-905 |
| 02 D-01 / D-12 | Universe hoãn; backup OneDrive là "off-host" | RISKY-DEFERRAL | F-907, F-910 → F-108 |
| 07.1 plan | `partial_fill_fraction = 0.5` vì tiện cho hash | WRONG | F-957 → F-006 |
| 07 OQ3 | Độ trễ duyệt cố định 30 s, "hiệu chỉnh ở Phase 10" | RISKY-DEFERRAL | F-961 |
| 08 D-03 | Reconciler chỉ huỷ, nhịp chạy do "discretion" | QUESTIONABLE | F-952, F-955 |
| 08 D-04 | "Exchange dedups", từ chối lưu cờ đã gửi | WRONG (tiền đề sai) | F-951 → F-126 (HIGH) |
| 09 D-02 | Hỗ trợ cả hai position mode; "sweeper never places rescue" | QUESTIONABLE | F-965, F-952 |
| 09 discretion | GTC ở giữa vùng không GTD; `MARK_PRICE` | QUESTIONABLE / RISKY-DEFERRAL | F-959, F-958 |
| 09 WR-07 | Skip (cần quyết định thiết kế) | RISKY-DEFERRAL (mồ côi) | F-952, F-115 |
| 10 D-03 | PASS = quyết định của người, ngưỡng TBD | WRONG (định nghĩa pass) | F-960, F-953 |
| 10 skip WR-01/06/10/12/13 | Chờ quyết định của người | RISKY-DEFERRAL | F-960 |
| P11–P16 goal | Thiếu nhiều chi tiết an toàn | QUESTIONABLE | F-962, F-963, F-964, F-966 |
| ROADMAP thứ tự 9 → 10 → 11…17 | Theo "numeric order" | WRONG | F-954 |
| ROADMAP thiếu phase | Không có phase cho M1–M4, verification, F-951/952/953 | RISKY-DEFERRAL | F-955, F-956 |

**Checkpoint của con người bị bỏ qua:**
- 09-01 "ACK-ONE-WAY: operator=auto-executor", 10-05 "auto-approved", 08-02 halted và 09-04 blocked vẫn được hiển thị là hoàn thành (F-124).
- Thêm 7 checkpoint khác không có quyết định được ghi lại (F-809).
- Checkpoint 02-05 "off-host" do orchestrator đóng (F-108).

### 10.3 Truy vết requirement (L1, Phụ lục A)

- **30 REQ:** 5 IMPLEMENTED+TESTED (trong đó STRAT-02, STRAT-03, RISK-02 chỉ ở mức thư viện, JRN-01 chỉ offline). 2 IMPLEMENTED-UNTESTED (DATA-02, PAPER-03). **23 PARTIAL.** 0 CLAIMED-BUT-MISSING ở cấp REQ, nhưng có sub-claim bị tuyên bố mà thiếu: F-104, F-121, F-126, F-127.
- **Tuyên bố vượt thực tế:** L1 hạ DATA-01..04, DOMN-02/03, STRAT-01, RISK-01, BKTS-02, RSCH-01..03, những mục mà v0.3 audit tính là satisfied. Xác nhận "12 orphaned" của v0.3 (không có VERIFICATION cho phase 07–10). REQUIREMENTS tick [x] cho APRV-01/02, OPS-01, GOV-01, BKTS-02 dù lane đánh giá PARTIAL. JRN-01 cũng được tick, nhưng chỉ đạt IMPLEMENTED+TESTED ở chế độ offline.
- **Requirement bị mất** (docs có MUST mà không có REQ-ID):
  - user-data stream (F-104)
  - cảnh báo vận hành (F-106)
  - kiểm tra chuyển trạng thái (F-111)
  - các entity trades / feature_snapshots / experiment_runs (F-112)
  - điều kiện tiên quyết để bật live (F-105 → F-953)
  - backup mã hoá, trình tự restart, cấm nới SL, lưu constraint snapshot, điều khiển khẩn cấp (F-108, F-116)
  - nạp credential và kiểm quyền key (F-128)
  - trường bắt buộc của experiment record (F-118)
  - tham số TP1/TP2/TIF (F-103)
  - leverage/margin (KNOWN P13/P14)
- **Code không có lý do được ghi lại:** TP2 = 2×(TP1−entry), SL Family B dời xuống dưới mép retest (F-113), thoát một lần vì "conservative" (F-102), `partial_fill_fraction = 0.5`, GTC, enum `ApprovalResult` (F-110).
- **Success criteria:** Phase 5 SC1 (sizing gồm chi phí) NOT MET (F-109). Phase 6 SC1 NOT MET (F-120, F-102). Phase 7 SC3 NOT MET (F-125, F-101). Phase 9 SC3 NOT MET (F-124, F-128). Chi tiết ở L1 A.3.
- **Sổ sách mâu thuẫn:** ROADMAP, STATE, PROJECT, REQUIREMENTS (F-114, F-967). Bảng disposition làm phẳng fix một phần thành "fixed" (F-808).

---

## 11. Hồi quy xuyên phase

Nguồn: lane L8 `historical_regression` (git history, truy vết plan → commit).

| Hồi quy | Được đưa vào bởi | Lan rộng qua | Lẽ ra đã bị bắt ở | ID |
|---|---|---|---|---|
| **Phá hợp đồng chi phí Phase 5 → 6.** Phase 5 dùng quote/đơn vị (fixture "1.0" ở BTC 50.000). Phase 6 trả về tỷ lệ 0,0008. | `77a0659` feat(06-01) | Paper `fffef34`, live `7e6347a`, baseline-v3 `d6bdad4` | 06-REVIEW IN-04 và WR-13 đã bắt được, nhưng WR-13 bị skip với lý do "cross-phase item" không có chủ. 05-VERIFICATION ghi "VERIFIED". Chỉ được theo dõi qua backlog 999.5 do user thêm (`a0ef5fc`). | F-801, F-802, F-109, F-001 |
| **WR-12: thoát trước khi vào.** Fix stamp thời điểm thoát bằng phút 1m của nến tín hiệu, nên `exit_time_utc` < `entry_time_utc`. Phase 10 MFE/MAE đánh dấu mọi giao dịch như vậy INCOMPLETE NEGATIVE_INTERVAL. | `9f5a87d` (06 WR-12 fix) | Phase 10 analytics | Không có test đi kèm fix | F-804 |
| **Lookahead cùng nến** theo đúng plan | 06-01-PLAN:97/109, commit `77a0659` | CR-01 `488bcd0` mở rộng fallback SL | 06-REVIEW CR-04 skip, IN-02b (Info) | F-120/F-901, F-802 |
| **Review-fix commit khi test không chạy được.** 06 (23 fix) và 08 (34 fix) commit trong lúc suite thiếu structlog/tenacity/SDK và chạy trên Python 3.14.3. Cần 4 commit sửa test sau đó. WR-12 không có test. | Các đợt 06 và 08 REVIEW-FIX | — | — | F-803 |
| **Checkpoint tự xoá / bị ghi đè.** 04-03 (một chiều) bị CR-03 ghi đè và golden được regenerate *sau* verification. 03-04, 05-01 "(orchestrator)", 02-05 (OneDrive), 03-01/03-02/07.1-01 không có bản ghi quyết định. 09-01 ACK-ONE-WAY do auto-executor, 10-05 auto-approved. | Nhiều phase | — | — | F-806, F-809, F-124 |
| **VERIFICATION cũ hơn fix.** VERIFICATION phase 02/04/05/07.1 được commit *trước* các đợt fix (36/12/13/3 commit), nhưng milestone audit vẫn tính là pass. | — | v0.3 milestone audit | — | F-807 |
| **Disposition làm phẳng.** 09 CR-04, CR-08 (phần còn lại của F-951), WR-06 được ghi là "fixed". Khoảng 30 fix "cần người xác nhận" chưa bao giờ được xác nhận. | 09/10-REVIEW-DISPOSITION | — | — | F-808 |
| **Parameter set bị sửa tại chỗ.** `bd12652` thêm khoá vào baseline-v1 đã được tham chiếu. Tripwire "được thoả mãn" bằng cách regenerate hash (`1c3c187`). | Review fix Phase 4 | — | Không có hash lock | F-810 |
| **Test đổi theo hành vi mới.** Migration test 07.1 ghi đè cost dict phase-6 "grandfathered" từ 1.0 thành 0.5 trong bộ nhớ. | `d6bdad4` | Mọi test `assemble()` | 07.1-VERIFICATION ghi `0.5` là must-have ✓ | F-812, F-957 |
| **Hợp đồng CLI Phase 10 đổi** mà UI-SPEC không cập nhật. WR-08 bỏ chiều OPPORTUNITY. | Fix 10 WR-05/08/09 | — | — | F-811 |
| **`enable()` chấp nhận WITHIN_BUDGET**, do chính plan tạo ra | `d217a2a`, `5e9dbb3` theo 10-07-PLAN:189 | 7 test ghim hành vi này | 10-REVIEW WR-10 bị skip, 10-05 auto-approved | F-953, F-604 |

L8 cũng xác minh vài điểm an toàn:
- Chỉnh fixture phase 9 là hợp lý.
- Các assert bị gỡ ở phase 10 không làm yếu test.
- Không có skip/xfail nào được thêm để che hành vi (mọi skip đều gắn với PG hoặc nền tảng).
- Commit ngoài GSD là vô hại.

---

## 12. Rủi ro kiến trúc

**Thiếu composition root (M1–M8).** v0.3-MILESTONE-AUDIT đã ghi 4 blocker. L2 (F-201) xác nhận và thêm 4 mục nữa:

| Mã | Mắt xích bị đứt | Hệ quả |
|---|---|---|
| M1 | Sự kiện kill gate (Phase 10) → `enable(kill_gate_state=...)` (Phase 9) | Trạng thái kill gate đã ghi không bao giờ được đọc |
| M2 | Callback APPROVE (Phase 8) → `execute_approved_plan` (Phase 9) | Manager không có importer nào trong `src/` |
| M3 | Paper supervisor → tick → journal → CLI Phase 10 | Không có gì ghi paper journal |
| M4 | Parquet store (Phase 2) → `simulator.run` (Phase 6) | Backtest chỉ chạy trên fixture dict |
| M5 | Phía gửi yêu cầu duyệt (`issue_one_time_token`, `format_approve`, `build_application`) | 0 caller trong src |
| M6 | Lập lịch reconciler / sweeper / health | `OrphanSweeper` và mọi health check: 0 caller. `SafeModeController(` không được khởi tạo ở đâu (V3). |
| M7 | Đầu vào rủi ro lấy từ sàn | `ConstraintSnapshot` chỉ dựng từ fixture. `exchange_info()` không được gọi. Không có nơi sinh `daily_loss` hay `open_algo_count`. |
| M8 | Persistence (F-202) | Mọi mapper `*_to_row`: 0 caller. `JournalLike.record` chỉ có `DrillLog` trong bộ nhớ. `analytics_store` đọc các bảng mà không ai ghi. |

Chỉ có collector và các CLI offline (analytics, coverage, backup) là chạy được. Không có `[project.scripts]` (F-201).

**Hệ quả quan trọng: nhiều lỗi HIGH/MEDIUM đang tiềm ẩn cho tới khi nối dây.** Có ba điều cần hiểu:

1. "Chưa gây hại hôm nay" **không** có nghĩa là an toàn. Verifier giữ mức HIGH vì thiết kế hiện tại *là* thiết kế sẽ được nối (V2, V3, V5).
2. Các phase P11–P17 đang sửa những hàm **chưa có caller production** (F-956). Sửa xong mà không có phase composition thì vẫn không có gì chạy, và cũng không verify được.
3. Chính phase composition là nơi dễ tạo ra lỗi F-302 nhất (symbol/side lấy từ `risk_kwargs`). Vì vậy phase này phải **sở hữu** các assert symbol/side/geometry, cổng unique theo symbol (F-303), bộ giám sát invalidation (F-304) và nguồn sinh daily loss / sổ rủi ro (L3 open question 1).

**Các rẽ nhánh backtest / paper / live** (vi phạm nguyên tắc "identical logic"):
- Sizing được chạy lại lúc đặt lệnh, và qty trong plan là một công thức khác (F-203).
- Mẫu số R khác nhau (F-204).
- Làm tròn tick chỉ ở live (F-207).
- Quantization của lệnh bảo vệ được viết lại riêng (F-208).
- Trigger MARK so với last (F-507).
- Thoát một lần so với bậc TP (F-102).
- Invalidation theo màu nến trong backtest so với không có gì trong live (F-304).

Điểm tốt là vẫn chỉ có **một pipeline rủi ro** `evaluate_risk` dùng chung cho simulator, paper và manager (L2 safe area).

**Seam kiểu dữ liệu:** Protocol `ExecutionAdapter` dùng `**kwargs: Any` (F-206). Lớp domain làm file I/O (F-209).

---

## 13. Rủi ro dữ liệu / đồng thời

- **Race giữa reconcile và thực thi:** sweeper huỷ SL của entry đang chờ (F-401, HIGH).
- **Đồng thời trên approval / cap:** không có khoá hay giữ chỗ rủi ro, nên nhiều approval đồng thời có thể vượt cap (F-407). Idempotency chỉ dựa vào `threading.Lock` trong process (F-404). Schema không có FK, CHECK hay unique cho token / approval / client_order_id (F-404). `_TOKEN_LOCKS` tăng mãi không giới hạn (L7 open question).
- **Không có WAL cho lệnh:** crash giữa ACK entry và ACK SL để lại lệnh không có dấu vết cục bộ (F-703).
- **Schema và DB:** VARCHAR(16) quá hẹp khiến insert thất bại (F-403). Session không ghim UTC khiến mọi dòng bị từ chối (F-406, PROBABLE). ORM thiếu 14 index / unique so với migration, và test dùng `create_all` (F-411). NUMERIC(38,18) làm hỏng khả năng tái tạo plan_hash (F-410). Id journal (tên, ms) trùng khoá chính (F-412).
- **Pipeline dữ liệu:** ngày dở dang thành file bất biến (F-402). Ghi Parquet không atomic (F-408). Nến 0 giao dịch làm dừng backfill (F-409). Supervisor subscribe trước khi backfill (F-413).
- **Luồng Telegram:** APPROVE và SKIP dùng chung short_id nên SKIP luôn INVALIDATED (F-405, PROBABLE). Contract `save_atomic` với mapping short-id chưa rõ, có thể vi phạm PK; purge retention được hứa nhưng không có code (L4 open questions).

L4 xác minh các điểm an toàn: Decimal/UTC ở DB, chuỗi migration tuyến tính, không có `create_all` trong src, `uq_fills_order_trade`, cursor backfill atomic, watermark collector cùng commit, mọi REST gọi qua `asyncio.to_thread` (§17).

---

## 14. Rủi ro tích hợp

**Binance:**
- Mã lỗi: probe algo chỉ map -2011 (F-501, chưa xác nhận). -2013 không được map khi đặt entry (F-503). -2011 trên lệnh huỷ không phân biệt được "đã huỷ" với "đã khớp" (F-502). "UNKNOWN_ORDER" là chuỗi Binance không bao giờ gửi (V2).
- Cấu hình client: timeout 1 s, 3 retry, không key, không testnet (F-504). Không có recvWindow hay kiểm lệch giờ (F-505, F-706). Retry cả khi bị ban 418, bỏ qua retry_after (F-506).
- Ngữ nghĩa lệnh: trigger `MARK_PRICE` (F-507). TP reduce-only bị kiểm MIN_NOTIONAL sai và dùng LOT_SIZE thay MARKET_LOT_SIZE (F-208, F-307, F-056). Cap 200 algo là toàn tài khoản (F-051). Code snapshot đã gọi endpoint toàn tài khoản, nhưng chưa có caller truyền `open_algo_count` (L5).
- Không có user-data stream (F-104, HIGH). ALGO_UPDATE TRIGGERED/FINISHED/REJECTED/EXPIRED chỉ có thể thấy qua polling REST, mà polling đó cũng chưa được lập lịch (L5 open question 4).
- `exchange_info()` sẽ huỷ cả lần refresh nếu *bất kỳ* symbol nào trên sàn thiếu filter (L4, L5 open question). Cần kiểm với snapshot thật khoảng 600 symbol.
- `new_order` dùng response ACK. Adapter yêu cầu `origQty`/`updateTime`; nếu thiếu thì request bị coi là mơ hồ, rồi probe, rồi F-503 (L5 open question 6).

**Telegram:**
- Chỉ kiểm chat id, nên thành viên nhóm có thể APPROVE (F-508/F-707).
- Token không đi trong callback, nên cổng token là phép so tautology (F-127(d)).
- Nút vẫn bấm được sau khi đã quyết định. Handler async chạy I/O đồng bộ. Retry TimedOut. Bỏ qua RetryAfter (F-509).
- SKIP không hoạt động (F-405).

**Paper WS:** thiếu `await` nên soak không khởi động (F-125). Fake là sync (F-607).

**TradingView:** chưa có endpoint nên không có bề mặt tấn công. Yêu cầu HMAC trong AGENTS là bất khả thi (F-052).

L5 xác minh: mọi method và enum của SDK 17.4.0 tồn tại, Decimal→wire an toàn, không auto-retry POST, `closePosition` loại trừ nhau đúng, `priceProtect` mặc định false, position mode đọc lại lúc đặt lệnh, callback_data ≤ 64 byte, không auto-approve (§17).

---

## 15. Rủi ro bảo mật / độ tin cậy

- **Fail-closed bị thủng:**
  - F-701 (compare mù), F-711 (SAFE_MODE tự thoát không cần operator), F-702 (journal-first chặn hành động an toàn).
  - F-127(a): SAFE_MODE chỉ trong bộ nhớ, restart là mất. Ngược lại, enablement mặc định tắt sau restart (hướng an toàn, L2).
  - F-703 (không có WAL).
- **Đồng hồ:** không kiểm server time ở bất cứ đâu. Ký request, hết hạn approval, độ cũ feed đều tin đồng hồ local, và freshness chấp nhận độ cũ âm (F-706, F-505).
- **Quyền duyệt lệnh:** chỉ theo chat id, `.env.example` cho phép group chat (F-707 → F-508).
- **Secrets:**
  - DB URL kèm mật khẩu xuất hiện trong ValueError. Journal ghi nguyên văn lỗi SDK, có thể chứa query string đã ký (F-708).
  - Mật khẩu DB lộ trên argv của pg_dump (F-704).
  - Chưa có cấu hình logging. Nếu sau này bật INFO, httpx sẽ log URL `bot<TOKEN>` (L7 open question 3).
  - Không có credential loader hay kiểm tra quyền key (F-128). IP allowlist chỉ là "preferred" (F-027).
- **Hạ tầng:**
  - Postgres mở trên mọi interface với mật khẩu placeholder. App nhận toàn bộ `.env`. Image không ghim (F-709).
  - HEALTHCHECK dùng sai interpreter (F-705, PROBABLE, chưa chạy Docker).
  - Dockerfile không copy `params/` (F-209).
- **Backup / phục hồi:** không off-host, không mã hoá, không lịch, không retention (F-108). Drill không restore (F-121). Runner hỏng với URL `+psycopg` (F-704).
  - Ghi chú từ L8: một phần công việc chạy trong checkout nằm trong thư mục OneDrive, cũng chính là thư mục sau này được chọn làm backup "off-host" (L8 open question 5).
- **Cảnh báo:** không có cảnh báo vận hành nào (F-106).

---

## 16. Khoảng trống kiểm thử

Lane L6 lập ma trận "nếu hành vi này hỏng, có test nào FAIL không?":

| Hành vi | Có test fail khi hỏng? | ID |
|---|---|---|
| Làm tròn xuống, minQty, minNotional, 60% | CÓ (oracle thật) | — |
| Lỗ SL thực tế ≤ ngân sách rủi ro (gồm chi phí) | **KHÔNG** (golden cho 2,07× mà không assert) | F-601 |
| Duyệt lệnh → tối đa một entry qua replay/restart | **KHÔNG** (probe: 2 `place_entry`) | F-603 → F-126 |
| Đặt lại stop bị mất / đóng reduce-only | **Test khẳng định điều ngược lại** | F-604 |
| Bật live cần ứng viên đã pass | **Test khẳng định điều ngược lại** (WITHIN_BUDGET là happy path) | F-604 |
| Nhân quả trong backtest (khớp sau tín hiệu, thoát sau khớp) | **KHÔNG** | F-602 |
| Tính nhất quán cấu trúc TP1/TP2 giữa backtest và live | **KHÔNG** | F-602 |
| Restart / phục hồi SAFE_MODE, enablement, kill gate | **KHÔNG** | F-606 |
| Migration áp dụng được lên PostgreSQL | **KHÔNG** (skip, `create_all`) | F-606 |
| WS reconnect / resync | Chỉ với fake sync | F-607 |
| Daily loss stop | Một phần (hằng số được tiêm vào, không có nguồn sinh) | — |
| Hết hạn approval, sai chat, sai token, replay 5× | CÓ (trong process) | — |

**Nguyên nhân gốc:**
- Golden được tính bởi chính implementation, nên chỉ phát hiện *thay đổi*, không phải oracle (F-608).
- Fake quá dễ dãi: chấp nhận id trùng vô hạn, không mô hình dedup (F-603). Fake WS là sync (F-607). Journal không bao giờ raise (F-702).
- Khoảng 33 test "coverage" của review-fix chỉ là grep văn bản nguồn (F-609).
- Không CI nào chạy pytest, ruff hay mypy. Các tuyên bố "mypy clean" đã cũ (F-605, F-117). Ba CI gate hiện có chưa từng chạy (F-101).
- Coverage % không được đo (không cài `coverage`). Mọi module src đều được test import, nên L6 tập trung vào *chất lượng oracle* thay vì phần trăm.
- Quan trọng: F-604 cho thấy sửa theo quy tắc đúng **sẽ làm test đỏ**. Kế hoạch sửa phải bao gồm việc viết lại các test này, không được coi đó là hồi quy.

---

## 17. Vùng đã xác minh là an toàn

Tổng hợp từ mục "Verified Safe Areas" của từng lane. Nhãn "an toàn" chỉ áp dụng cho phạm vi mà lane đã kiểm tra.

### 17.1 Code: lõi, rủi ro, Decimal

- **Ranh giới lõi thuần (L2):** `src/core`, `src/domain`, `src/risk` không import polars, duckdb, sqlalchemy, psycopg, fastapi, httpx, telegram, SDK Binance hay asyncio. Hai ngoại lệ nhỏ: `registry.py` dùng pathlib (F-209), `quantization.py:207` import structlog ở call site.
- **SDK và ORM nằm gọn trong adapter (L2):** SDK Binance chỉ có trong `binance_usdm.py` và `paper_ws.py`; PTB chỉ trong `telegram_*.py`. ORM không phải là domain object.
- **Decimal ở đường lệnh (L2, L5, L4):** `_decimal_to_wire` từ chối giá trị không phải Decimal và giá trị không hữu hạn, rồi xuất `format(value,"f")`, nên rủi ro float/số mũ của F-058 **đã được đóng ở tầng code**. Không có giá, qty, notional hay rủi ro nào là float. DB dùng `Numeric(38,18)`; Parquet dùng `pl.Decimal`.
- **Một pipeline rủi ro duy nhất (L2):** `evaluate_risk` được simulator, paper và manager dùng chung.
- **Lượng tử hoá (L3, L6):** làm tròn xuống theo stepSize, không bao giờ làm tròn lên. Thứ tự minQty → notional → utilization. Tử số và mẫu số của 60% đúng (Corrected Rule 4). Test là oracle thật.
- **Fail-closed ở cổng rủi ro (L3):** daily loss None → UNCERTAIN. Constraint cũ hoặc có thời điểm tương lai → STALE. Ngưỡng bool/float → UNCERTAIN. DAILY_STOP/WARNING dùng biên `>=`.
- **Stop không bao giờ bị nới khi làm tròn (L3):** limit LONG làm tròn xuống, SHORT làm tròn lên, SL làm tròn về phía entry. Rủi ro thực tế ≤ rủi ro đã tính khi sizing.
- **Hình học breakout-retest và range-mr (L3):** vùng entry nằm đúng phía so với SL. Chỉ trend-pullback sai (F-301).
- **Nến đã đóng / không lookahead trong feature (L3):** không có pivot nhìn phải. Lookahead chỉ nằm trong simulator.

### 17.2 Duyệt lệnh và thực thi

- **Primitive duyệt lệnh (L7, L3, L6):** token `secrets.token_urlsafe(32)`, `hmac.compare_digest`. Hết hạn `now >= expiry` được kiểm ở callback và lại ở lúc đặt lệnh. Lúc đặt lệnh, action, result và status đều phải là APPROVED, và plan_hash/id/expiry phải khớp. Replay trả về trạng thái hiện có (trong process). Thông báo lỗi không bao giờ tự duyệt. Cổng chat chạy trước mọi truy vấn trạng thái. Callback sai định dạng raise trước khi đổi bất kỳ trạng thái nào.
- **Thứ tự cổng khi đặt lệnh (L3):** enablement → SAFE_MODE → rủi ro → cổng đặt lệnh. Đường gắn lệnh bảo vệ không bị SAFE_MODE chặn.
- **Không retry mù (L5, L7, A2):** cả adapter lẫn SDK đều không retry POST. Manager chỉ retry sau khi probe trả `found=False` dứt khoát; mọi lỗi probe → ENTRY_STATE_UNKNOWN → SAFE_MODE.
- **Không rõ position mode thì không đặt lệnh (L5, L7).** Guard phạm vi live-5 chạy trước mọi lời gọi adapter (L7).
- **Lệnh bảo vệ:** algo CONDITIONAL STOP_MARKET/TAKE_PROFIT_MARKET, `closePosition` không đi kèm quantity/reduceOnly, reduceOnly không dùng ở hedge mode (L3, L5, A2). SL được đặt trước khi khớp (V4 bác F-008). Leg chưa xác nhận không bao giờ bị coi là đã bảo vệ; allow-list `{"NEW"}` (L7).
- **Client ID:** `x-…EN`/`xa-…SL/T1/T2` dài đúng 36 ký tự, đúng regex, lấy từ 128 bit của plan_hash (L7).
- **Enablement mặc định:** `_disabled=True`, restart thì quay về LIVE_ORDERS_DISABLED (L2, L3, L7).

### 17.3 Tích hợp

- Mọi method, tham số và enum của SDK 17.4.0 mà adapter dùng đều tồn tại. Mọi field response được đọc đều có trong model (L5).
- Key MIN_NOTIONAL `notional` đúng. Không đọc MAX_NUM_ALGO_ORDERS (đã bị gỡ). Reconcile snapshot algo gọi endpoint toàn tài khoản (L5).
- `priceProtect` không gửi nên mặc định là false (L5). SDK WS dùng `url_paths=["market","public","private"]`, không hard-code URL cũ. F-053 chỉ là vấn đề docs (A2, L5).
- Kline đóng dùng `x` nguyên văn, cộng cổng kép `x==True and close_time<=now` (L5, B2).
- Telegram: callback_data ≤ 64 byte, luôn `query.answer()`, plain text không `parse_mode` (L5). Không có HTTP trực tiếp và không có webhook, nên không có bề mặt inbound (L5, L7).
- Endpoint algo, quy tắc `closePosition`, việc gỡ CONDITIONAL_ORDER_TRIGGER_REJECT, và giá trị phí 0,0002/0,0005 đều khớp nguồn chính thức (A2).

### 17.4 Dữ liệu / DB

- Chuỗi migration 0001→0003 tuyến tính, downgrade đối xứng. `env.py` từ chối chạy khi thiếu `DATABASE_URL`. Không có `create_all` trong src (L4).
- `uq_fills_order_trade` và `fold_fills` idempotent (L4).
- Analytics chỉ ghi `append_kill_gate_event` (ON CONFLICT DO NOTHING). Dòng hỏng được đếm, không bị bỏ âm thầm (L4).
- Gap của collector được ghi (merge idempotent theo PK). Watermark tiến trong cùng commit. Cursor backfill atomic (tmp + `os.replace`). Coverage CLI tính `gap_count` (L4).
- Mọi REST của adapter chạy qua `asyncio.to_thread` (L4).

### 17.5 Bảo mật, test, lịch sử

- Không có secret bị commit (`git log --all -p`). `.env` bị gitignore. Telegram token không bị log. Container chạy non-root, `uv sync --frozen --no-dev` (L7).
- Dependency: mọi range trong pyproject được thoả bởi `uv.lock` (SDK 17.4.0, sqlalchemy 2.0.54, polars 1.44.2, pydantic 2.13.5, PTB 22.8, httpx 0.28.1, psycopg 3.3.6, alembic 1.20.0, duckdb 1.5.5). Không dùng connector đã archive, không dùng bản pre-release (L7). Tình trạng lỗ hổng đã biết: **UNVERIFIED** (offline).
- Backup từ chối tạo dump rỗng âm thầm (L7).
- Test: tất định và cô lập. Test không chạm mạng hay DB khi chưa có guard. Oracle của quantization, approval và kill-gate là độc lập. Fake execution được ràng buộc chữ ký với adapter thật (`_bind_real`). 5 lỗi mypy đều là nhiễu kiểu. Ruff F841 trong `portfolio.py` chỉ là code chết (L6).
- Lịch sử: chỉnh fixture phase 9 là hợp lý. Assert bị gỡ ở phase 10 không làm yếu test. Không có skip/xfail che hành vi. Coercion `CostModel` của 07.1 không đổi hash (L8).

### 17.6 Docs và quyết định được đánh giá là đúng (A1, B1, B2)

- **Docs đúng (A1, 14 nhóm):** sizing theo rủi ro (không dùng leverage để quyết định size). Lượng tử hoá làm tròn xuống, ưu tiên NO_TRADE. Tính nhất quán giữa các mode. Fail-closed và sàn là nguồn sự thật. Lệnh bảo vệ qua algo CONDITIONAL. Không nới stop. Thiết kế duyệt lệnh. Nến đóng / warm-up. Tie-break bất lợi trước. Các kiểm soát nghiên cứu (holdout, bootstrap, baseline). Kill gate D013/D030 như ngân sách thời gian. Nền tảng vận hành. Tự thu thập OI từ ngày đầu. Phạm vi nhỏ, người duyệt trước.
- **Quyết định đúng (B1/B2):** protocol đóng băng tách riêng. Parquet bất biến + PG vận hành. SDK chính thức. Domain dataclass đóng băng. Registry TOML + SHA-256. Engine chỉ dùng nến đóng. Thứ tự lượng tử hoá Phase 5. Identity 6 trường và bootstrap của Phase 6. Cổng nến đóng kép và pin epoch của Phase 7. Binding approval, PTB polling, drill của Phase 8. Entry LIMIT + algo CONDITIONAL + SL đặt trước khi khớp, key không có quyền rút, LIVE_ORDERS_DISABLED của Phase 9. Analytics read-only và quy tắc kích hoạt D030 của Phase 10.

---

## 18. Vùng chưa xác minh / đáng ngờ

### 18.1 F-501: cần gọi testnet

Đây là finding HIGH duy nhất **chưa xác nhận** (INSUFFICIENT_EVIDENCE). Việc cần làm, ngoài phạm vi audit chỉ đọc này:

1. Trên testnet USD-M, gọi `GET /fapi/v1/algoOrder?clientAlgoId=<xa- id chưa từng đặt>`. Ghi lại HTTP status, `code` và `msg`.
2. Lặp lại với id đã quá hạn lưu (> 3 ngày) và với `DELETE /fapi/v1/algoOrder` cho id không tồn tại hoặc đã TRIGGERED (liên quan F-502: đường huỷ algo cũng dùng mapping -2011).
3. Gọi `GET /fapi/v1/order` với `origClientOrderId` không tồn tại; kỳ vọng -2013 (F-503).
4. Đặt một STOP_MARKET `closePosition=true` khi chưa có vị thế để khẳng định dứt khoát hành vi mà F-008 dựa vào (V4).

Nếu (1) trả mã khác -2011, F-501 thành **CONFIRMED HIGH**. Nếu trả -2011, hạ xuống LOW.

### 18.2 Các finding chính chưa ở mức CONFIRMED (50)

Độ tin cậy của finding stage A/B đã được chuẩn hoá (§4.4): PROBABLE và SUSPICIOUS ở đây phần lớn là **đánh giá thiết kế dựa trên kiến thức giao dịch của mô hình**, chưa có probe code. Không được coi chúng là sự thật đã kiểm chứng.

Tổng: 36 PROBABLE · 13 SUSPICIOUS · 1 UNVERIFIED. Theo mức: 1 HIGH · 31 MEDIUM · 17 LOW · 1 INFO.

| ID | Mức | Độ tin cậy | Nhóm | Nguồn (lane) | Độ tin cậy gốc của lane |
|---|---|---|---|---|---|
| F-501 | HIGH | UNVERIFIED | Thực thi lệnh & tích hợp Binance/Telegram (HIGH) | integrations_external_apis | PROBABLE |
| F-004 | MEDIUM | SUSPICIOUS | Thiết kế tài liệu (docs, stage A) | docs_trading_soundness | MEDIUM |
| F-010 | MEDIUM | SUSPICIOUS | Thiết kế tài liệu (docs, stage A) | docs_trading_soundness | MEDIUM |
| F-014 | MEDIUM | SUSPICIOUS | Thiết kế tài liệu (docs, stage A) | docs_trading_soundness | MEDIUM |
| F-016 | MEDIUM | SUSPICIOUS | Thiết kế tài liệu (docs, stage A) | docs_trading_soundness | MEDIUM |
| F-021 | MEDIUM | SUSPICIOUS | Thiết kế tài liệu (docs, stage A) | docs_trading_soundness | MEDIUM |
| F-024 | MEDIUM | SUSPICIOUS | Thiết kế tài liệu (docs, stage A) | docs_trading_soundness | MEDIUM |
| F-026 | MEDIUM | SUSPICIOUS | Thiết kế tài liệu (docs, stage A) | docs_trading_soundness | MEDIUM |
| F-964 | MEDIUM | SUSPICIOUS | Quyết định lập kế hoạch / ROADMAP (stage B) | planning_decisions_07_17 | MEDIUM |
| F-003 | LOW | SUSPICIOUS | Thiết kế tài liệu (docs, stage A) | docs_trading_soundness | MEDIUM |
| F-019 | LOW | SUSPICIOUS | Thiết kế tài liệu (docs, stage A) | docs_trading_soundness | MEDIUM |
| F-029 | LOW | SUSPICIOUS | Thiết kế tài liệu (docs, stage A) | docs_trading_soundness | MEDIUM |
| F-030 | LOW | SUSPICIOUS | Thiết kế tài liệu (docs, stage A) | docs_trading_soundness | MEDIUM |
| F-031 | INFO | SUSPICIOUS | Thiết kế tài liệu (docs, stage A) | docs_trading_soundness | MEDIUM |
| F-002 | MEDIUM | PROBABLE | Thiết kế tài liệu (docs, stage A) | docs_trading_soundness | HIGH |
| F-005 | MEDIUM | PROBABLE | Thiết kế tài liệu (docs, stage A) | docs_trading_soundness | HIGH |
| F-006 | MEDIUM | PROBABLE | Thiết kế tài liệu (docs, stage A) | docs_trading_soundness | HIGH |
| F-011 | MEDIUM | PROBABLE | Thiết kế tài liệu (docs, stage A) | docs_trading_soundness | HIGH |
| F-012 | MEDIUM | PROBABLE | Thiết kế tài liệu (docs, stage A) | docs_trading_soundness | HIGH |
| F-013 | MEDIUM | PROBABLE | Thiết kế tài liệu (docs, stage A) | docs_trading_soundness | HIGH |
| F-015 | MEDIUM | PROBABLE | Thiết kế tài liệu (docs, stage A) | docs_trading_soundness | HIGH |
| F-017 | MEDIUM | PROBABLE | Thiết kế tài liệu (docs, stage A) | docs_trading_soundness | HIGH |
| F-018 | MEDIUM | PROBABLE | Thiết kế tài liệu (docs, stage A) | docs_trading_soundness | HIGH |
| F-023 | MEDIUM | PROBABLE | Thiết kế tài liệu (docs, stage A) | docs_trading_soundness | HIGH |
| F-107 | MEDIUM | PROBABLE | Yêu cầu & truy vết (requirements) | requirements_docs_plan | PROBABLE |
| F-405 | MEDIUM | PROBABLE | Dữ liệu / DB / đồng thời | data_database_concurrency | PROBABLE |
| F-406 | MEDIUM | PROBABLE | Dữ liệu / DB / đồng thời | data_database_concurrency | PROBABLE |
| F-703 | MEDIUM | PROBABLE | Đối soát (reconcile) / SAFE_MODE / phục hồi | security_reliability | PROBABLE |
| F-704 | MEDIUM | PROBABLE | Bảo mật / vận hành | security_reliability | PROBABLE |
| F-955 | MEDIUM | PROBABLE | Quyết định lập kế hoạch / ROADMAP (stage B) | planning_decisions_07_17 | HIGH |
| F-956 | MEDIUM | PROBABLE | Quyết định lập kế hoạch / ROADMAP (stage B) | planning_decisions_07_17 | HIGH |
| F-958 | MEDIUM | PROBABLE | Quyết định lập kế hoạch / ROADMAP (stage B) | planning_decisions_07_17 | HIGH |
| F-959 | MEDIUM | PROBABLE | Quyết định lập kế hoạch / ROADMAP (stage B) | planning_decisions_07_17 | HIGH |
| F-960 | MEDIUM | PROBABLE | Quyết định lập kế hoạch / ROADMAP (stage B) | planning_decisions_07_17 | HIGH |
| F-961 | MEDIUM | PROBABLE | Quyết định lập kế hoạch / ROADMAP (stage B) | planning_decisions_07_17 | HIGH |
| F-962 | MEDIUM | PROBABLE | Quyết định lập kế hoạch / ROADMAP (stage B) | planning_decisions_07_17 | HIGH |
| F-963 | MEDIUM | PROBABLE | Quyết định lập kế hoạch / ROADMAP (stage B) | planning_decisions_07_17 | HIGH |
| F-020 | LOW | PROBABLE | Thiết kế tài liệu (docs, stage A) | docs_trading_soundness | HIGH |
| F-025 | LOW | PROBABLE | Thiết kế tài liệu (docs, stage A) | docs_trading_soundness | HIGH |
| F-027 | LOW | PROBABLE | Thiết kế tài liệu (docs, stage A) | docs_trading_soundness | HIGH |
| F-028 | LOW | PROBABLE | Thiết kế tài liệu (docs, stage A) | docs_trading_soundness | HIGH |
| F-408 | LOW | PROBABLE | Dữ liệu / DB / đồng thời | data_database_concurrency | PROBABLE |
| F-409 | LOW | PROBABLE | Dữ liệu / DB / đồng thời | data_database_concurrency | PROBABLE |
| F-412 | LOW | PROBABLE | Dữ liệu / DB / đồng thời | data_database_concurrency | PROBABLE |
| F-413 | LOW | PROBABLE | Dữ liệu / DB / đồng thời | data_database_concurrency | PROBABLE |
| F-705 | LOW | PROBABLE | Bảo mật / vận hành | security_reliability | PROBABLE |
| F-909 | LOW | PROBABLE | Quyết định lập kế hoạch / ROADMAP (stage B) | planning_decisions_01_06 | PROBABLE |
| F-965 | LOW | PROBABLE | Quyết định lập kế hoạch / ROADMAP (stage B) | planning_decisions_07_17 | HIGH |
| F-966 | LOW | PROBABLE | Quyết định lập kế hoạch / ROADMAP (stage B) | planning_decisions_07_17 | HIGH |
| F-967 | LOW | PROBABLE | Quyết định lập kế hoạch / ROADMAP (stage B) | planning_decisions_07_17 | HIGH |

### 18.3 Những gì không lane nào kiểm được

| Hạng mục | Lý do | Ảnh hưởng tới finding |
|---|---|---|
| Testnet / live Binance | Charter cấm kết nối sàn | F-501, F-502 (algo), F-503 (-2013 thực tế), F-504 (timeout thực), F-505; hành vi `closePosition` trước khi có vị thế; `-2021` với algo conditional; `countdownCancelAll`; GTD tối thiểu 600 s; chu kỳ funding theo symbol (A1 open questions) |
| PostgreSQL thật | `TEST_DATABASE_URL` bị unset; 6 test PG bị skip | F-403, F-406, F-411, F-404 (hành vi constraint), migration thực tế (F-606) |
| Docker | Không chạy Docker (L2 và L7 đều ghi) | F-705 (PROBABLE), F-209, F-709 |
| Trang phí Binance cần đăng nhập, Telegram 403 | Không truy cập được | F-031, F-005 (mức phí thực tế theo tài khoản) |
| CI history / branch protection | Không có remote GitHub, không có `gh` | F-101, F-605 |
| `exchangeInfo` đầy đủ (~600 symbol) | Fixture chỉ có 5 symbol | L4/L5 open question: một symbol thiếu filter sẽ huỷ cả lần refresh |
| Bisect các đợt review-fix 06/08 | Chỉ biết HEAD xanh | F-803 |
| Transcript chat của user | Không có trong snapshot | Không biết user có thật sự được hỏi ở 05-01 "(orchestrator)", 01-04, 02-01 hay không (F-809, L8 open question 4) |
| `src/analytics/*` (bao gồm `killgate.py`) | Chỉ METADATA_ONLY | Logic "sticky" của kill gate, `--record --as-of` backdate (L8 open question 3) |
| Checkout OneDrive khác (`C:/Users/daotu/OneDrive/...`) | Ngoài phạm vi | Liệu secret hay `.env` từng nằm trong thư mục sync (L8 open question 5) |
| Tình trạng CVE của dependency | Offline, không có advisory DB | L7 |

---

## 19. Khuyến nghị khắc phục

Chú thích:
- **[Lỗi]** = Confirmed defect (CONFIRMED DEFECT hoặc GAP đã được verifier xác nhận).
- **[Cải tiến]** = Recommended improvement hoặc đề xuất thiết kế (bao gồm cả Corrected Rules của audit).
- **[Chưa xác nhận]** = cần kiểm chứng trước.
- Cột "Thuộc phase" ánh xạ vào ROADMAP 11–17 hiện có, hoặc đề xuất **phase MỚI** khi không phase nào sở hữu.

Audit không viết code và không sửa repo.

### 19.1 P0: bắt buộc trước khi dùng BẤT KỲ đồng tiền thật nào

| # | Việc | Loại | ID | Thuộc phase |
|---|---|---|---|---|
| P0-1 | **Runtime composition** có tên từng process: gửi yêu cầu duyệt, bot runner, execution service chỉ dùng dữ liệu đọc từ adapter, lịch reconcile/sweeper/health, paper runner. Mỗi process có smoke test end-to-end. Phase này **sở hữu**: assert symbol/side/geometry (F-302), cổng unique theo symbol (F-303), bộ giám sát invalidation và `TradePlan.status` (F-304), nguồn sinh daily loss và `open_algo_count` (M7). | [Lỗi] + [Cải tiến] | F-201, F-956, F-302, F-303, F-304 | **MỚI**: "Runtime composition (M1–M8)" |
| P0-2 | **Tầng persistence vận hành**: cài đặt PG cho journal, approval store, execution state. Thêm unique/FK/CHECK (token hash, một approval quyết định trên mỗi plan, client_order_id). Ghim UTC cho session. Sửa độ rộng VARCHAR. Đồng bộ index giữa ORM và migration. | [Lỗi] | F-202, F-404, F-403, F-406, F-411, F-412 | **MỚI**: "Persistence layer" (có thể gộp với P0-1) |
| P0-3 | **Tiêu thụ approval và ý định thực thi bền vững** (WAL trước `place_entry`). Replay trả kết quả đã lưu. Sửa 08-CONTEXT D-04 và EXECUTION_SPEC §7. Test gọi `execute_approved_plan` hai lần; fake mô hình dedup chỉ-giữa-lệnh-đang-mở. | [Lỗi] | F-126 (F-951, F-603), F-703 | **MỚI** (trong P0-1/P0-2) |
| P0-4 | **Ràng buộc qty với plan đã duyệt:** chỉ từ chối, không bao giờ tăng size (Corrected Rule 22) | [Lỗi] | F-203 | P0-1 (hoặc P12) |
| P0-5 | **Làm cứng reconcile:** miễn trừ SL của entry đang chờ (F-401). Thêm pass ngược, so amount có dấu, bắt buộc có STOP_LOSS trên sàn (F-701). Thoát SAFE_MODE thủ công, cần operator id, và lưu bền qua restart (F-711, F-127(a)). Journal-first → hành động trước, journal sau với fallback (F-702). Ghi đúng -2011 kèm truy vấn sau khi huỷ (F-502). | [Lỗi] | F-401, F-701, F-711, F-127, F-702, F-502 | **MỚI**: "Reconcile & safety hardening" |
| P0-6 | **User-data stream:** listenKey, ORDER_TRADE_UPDATE, ALGO_UPDATE (`o.rm`), ACCOUNT_UPDATE, URL `/private`. Cấp dữ liệu cho `fold_fills`, reconcile và P12. | [Lỗi] (requirement bị mất) | F-104, F-054 | **MỚI**: "User-data stream" (P12 phụ thuộc vào phase này) |
| P0-7 | **Taxonomy mã lỗi Binance và diễn tập testnet:** xác minh not-found của algo và order (F-501). Map theo `status_code` (-2013, -2019, -4164, -1021…) (F-503). Cấu hình client: timeout, key, testnet/live (F-504, F-128). recvWindow và lệch giờ (F-505, F-706). Không retry khi bị 418 (F-506). | [Chưa xác nhận] F-501 / [Lỗi] phần còn lại | F-501, F-503, F-504, F-505, F-506, F-706, F-128 | **MỚI** hoặc mở rộng 09-04 (buổi rehearsal testnet đang blocked) |
| P0-8 | **Cổng giá trước khi đặt lệnh** (mark + last so với SL/vùng) **cộng phương án sau khi khớp**: SL bị từ chối hoặc không ACK trong N giây → đóng reduce-only, cảnh báo, SAFE_MODE. Thêm thời gian hiệu lực tối thiểu khi duyệt và GTD làm backstop. | [Lỗi] (F-007) + [Cải tiến] | F-007, F-959, F-016, F-955 | **P15** (mở rộng phạm vi) |
| P0-9 | **Sửa đơn vị phí/chi phí đầy đủ:** ×giá, trượt giá lúc thoát, mép bất lợi, max(param, account), taker/GTX, trần chi phí/rủi ro. Test thuộc tính "lỗ SL ≤ ngân sách" với cả symbol giá thấp (XRP). | [Lỗi] | F-001, F-801, F-601, F-962, F-002 | **P11** (mở rộng goal) |
| P0-10 | **Equity và daily loss từ Binance** với định nghĩa đầy đủ (ngày UTC, realized + phí + funding, gốc, lưu bền, DAILY_STOP huỷ entry đang chờ) | [Lỗi] + cần quyết định (§20) | F-012, F-013, F-963, F-128 | **P12** |
| P0-11 | **Leverage / margin / thanh lý / margin khả dụng:** isolated, trần leverage, đệm thanh lý ≥ khoảng SL, tính cả lệnh đang chờ | [Cải tiến] (KNOWN) | F-011, F-964, F-966 | **P13, P14** |
| P0-12 | **Cổng bật live phải "khẳng định":** cần family đã pass (có bản ghi), đã qua paper exit gate, vốn tối thiểu. **Thứ tự ROADMAP:** cấm live cho tới khi P0-1…P0-11 xong. P11 phải đứng trước epoch paper soak. | [Lỗi] (thiết kế) | F-953 (F-105), F-954, F-604 | ROADMAP (thêm dependency) + phase MỚI P0-1 |
| P0-13 | **Chính sách lệnh bảo vệ** (sau khi có quyết định §20): SAFE_MODE miễn trừ lệnh bảo vệ và reduce-only (sửa docs F-009). Xử lý 09 WR-07: expiry để lại SL close-all; emergency close huỷ SL trước khi phẳng vị thế. | [Lỗi] (docs) + quyết định | F-009, F-952, F-115 | **MỚI** hoặc gộp P0-5 |
| P0-14 | **Telegram:** kiểm `from_user.id` và chỉ dùng private chat. Sửa SKIP (short_id riêng cho mỗi action). Sửa tin nhắn và gỡ keyboard sau khi quyết định. Token thực sự đi trong callback hoặc ghi rõ mô hình tin cậy. | [Lỗi] | F-508 (F-707), F-405, F-509, F-127(d) | **P16** (mở rộng) hoặc MỚI |
| P0-15 | **Trigger SL/TP:** chọn CONTRACT_PRICE hoặc MARK_PRICE có chủ đích và ghi lên plan; nếu MARK thì cần backtest mark-price. Quantize TP theo MARKET_LOT_SIZE, bỏ MIN_NOTIONAL cho reduce-only; nếu leg < minQty thì dùng một TP duy nhất. | [Lỗi] + quyết định | F-507, F-958, F-010, F-208, F-307, F-056 | P13 hoặc MỚI |
| P0-16 | **Cảnh báo vận hành** (vị thế không bảo vệ, lệch trạng thái, lệnh lạ, DAILY_STOP, data stale, auth fail) và **backup thật** (off-host, mã hoá, lịch, restore PG thật) | [Lỗi] (requirement bị mất / drift) | F-106, F-108 (F-910), F-121, F-704 | **MỚI**: "Ops minimum" |
| P0-17 | Viết lại các test đang khẳng định quy tắc sai (sẽ đỏ khi sửa P0-5, P0-12, P0-13) | [Lỗi] (test) | F-604 | Đi kèm từng phase |

### 19.2 P1: trước khi tin bằng chứng backtest hoặc paper

| # | Việc | Loại | ID | Thuộc phase |
|---|---|---|---|---|
| P1-1 | **Viết lại simulator theo nhân quả:** vòng đời plan xuyên nhiều nến, khớp chỉ sau nến tín hiệu với trade-through ≥ 1 tick của giá limit, 1m từ thời điểm khớp trở đi, giữ lệnh qua nhiều nến, bậc TP1/TP2 như live, funding thật, slippage ×giá, constraint theo thời điểm (point-in-time), trạng thái danh mục tiến theo thời gian, stamp thời gian đúng. Thêm assert nhân quả (`entry > signal close`, `exit ≥ entry`). **Huỷ mọi bằng chứng cũ.** | [Lỗi] | F-120 (F-901), F-902, F-102, F-305, F-306, F-905, F-804, F-602, F-805 | **MỚI**: "Backtest simulator causality rewrite" |
| P1-2 | **Sửa hình học trend-pullback:** SL ngoài vùng, pivot đã xác nhận, khoảng stop tối thiểu, trần chi phí/rủi ro. Tạo parameter set mới và nghiên cứu lại. | [Lỗi] | F-301, F-909, F-113 | MỚI (hoặc cùng P1-1) |
| P1-3 | **Protocol v1.1.0 pre-registration:** ngưỡng số, số lần thử, hiệu chỉnh đa kiểm định, holdout một lần. Người được bác nhưng không được cho pass. Xử lý các finding WR-01/06/10/12/13 bị skip ở Phase 10. | [Lỗi] (thiết kế) | F-022 (F-903), F-960, F-904 | **MỚI**: "Research governance amendment" |
| P1-4 | **Mô hình chi phí và khớp lệnh:** `partial_fill_fraction = 1.0` giống nhau giữa candidate và baseline. Taker khi marketable. Slippage cho lệnh thoát stop. Quy ước funding. Bỏ ghi đè 0.5 trong test. | [Lỗi] / [Cải tiến] | F-006 (F-957), F-005 (F-055), F-004, F-021, F-812 | P11 hoặc P1-1 |
| P1-5 | **Dữ liệu:** deploy collector ngay (OI 30 ngày mất vĩnh viễn mỗi ngày; nhạy thời gian). Độ sâu lịch sử 2 năm / 6–12 tháng có CLI. Sửa ngày dở dang, ghi atomic, nến 0 giao dịch, `backfill_universe` có runner. Nối Parquet → simulator (M4). | [Lỗi] | F-107, F-906, F-402, F-408, F-409, F-122, F-413 | **MỚI** hoặc mở rộng P0-1 (M4) |
| P1-6 | **Research universe** point-in-time, đóng băng và hash trước khi đánh giá, có cả mã đã delist | [Cải tiến] | F-024, F-907 | MỚI (protocol amendment) |
| P1-7 | **Paper:** sửa `await` (F-125), fake bị ràng buộc với SDK async (F-607), producer fill mô phỏng, đo độ trễ duyệt thật và nút SIMULATE (F-961), tiêu chí thoát paper định lượng (F-023) | [Lỗi] + [Cải tiến] | F-125, F-607, F-961, F-023 | **MỚI** hoặc phần paper của P0-1 |
| P1-8 | **Tính nhất quán R và report:** thống nhất mẫu số R (F-204), regime slice (F-123), trường bắt buộc của ExperimentRecord và `code_version` là git revision (F-118), tick rounding dùng chung (F-207), đăng ký tham số TP1/TP2/TIF (F-103) | [Lỗi] / [Cải tiến] | F-204, F-123, F-118, F-207, F-103 | P1-1 |
| P1-9 | **Verify lại phase 02–10** sau các đợt review-fix, có người xác nhận khoảng 30 fix "requires human verification". Mở lại 05-VERIFICATION. | [Lỗi] (quy trình) | F-807, F-808, F-109, F-956 | **MỚI**: "Verification closure 06–10" |
| P1-10 | **Test PG và migration thật, test restart/rehydrate** (SAFE_MODE, enablement, kill gate) | [Lỗi] (test) | F-606, F-609 | Đi kèm P0-2 |

### 19.3 P2: hygiene

| # | Việc | Loại | ID |
|---|---|---|---|
| P2-1 | CI chạy pytest, ruff, mypy và registry gate trên remote thật. Sửa registry-gate đang đỏ tại HEAD. Format 98 file. Dọn 36 lỗi ruff. | [Cải tiến] | F-605, F-117, F-101 |
| P2-2 | Đồng bộ sổ sách: ROADMAP, STATE, PROJECT, REQUIREMENTS, disposition, UI-SPEC | [Cải tiến] | F-114, F-967, F-811, F-808 |
| P2-3 | GLOSSARY: bỏ mã lý do đồng nghĩa, thêm mã mà code phát ra và `ApprovalResult`. Sửa DECISIONS.md:22, ví dụ alert, link SOURCES. | [Cải tiến] | F-110, F-119, F-057 |
| P2-4 | Docs sự thật về sàn: 200 algo toàn tài khoản, ngữ nghĩa algo, tách URL WS, MARKET_LOT_SIZE/PERCENT_PRICE, bỏ "TradingView HMAC" | [Lỗi] (docs) | F-051, F-054, F-053, F-056, F-052 |
| P2-5 | Seam kiểu dữ liệu và trùng lặp: Protocol `ExecutionAdapter` có kiểu, danh sách live-5 ở một chỗ, fixture parser dùng chung | [Cải tiến] | F-206, F-208, F-209 |
| P2-6 | Hạ tầng: ghim image, Postgres chỉ bind localhost, env tối thiểu, healthcheck dùng venv, copy `params/`, lọc secret khỏi thông báo lỗi, cấu hình logging (hạ mức log httpx) | [Cải tiến] / [Lỗi] | F-709, F-705, F-209, F-708 |
| P2-7 | State-machine validation và các entity bị mất (trades, feature_snapshots, experiment_runs), hoặc ghi DECISIONS để chính thức loại bỏ | [Cải tiến] | F-111, F-112, F-116 |
| P2-8 | Hash lock cho parameter set đã được tham chiếu; tái tạo được plan_hash từ dòng lưu | [Cải tiến] | F-810, F-410 |
| P2-9 | Mục P17 (quote asset): hạ ưu tiên xuống sau các phase an toàn (B2 sổ quyết định: QUESTIONABLE ưu tiên) | [Cải tiến] | — (B2 register) |

**Quy trình (áp dụng từ nay):**
- Checkpoint một chiều phải có quyết định của người được ghi lại, không để auto-executor tự xoá (F-124, F-809).
- Review-fix chỉ được commit khi suite liên quan chạy được (F-803).
- Mọi finding bị "skip" phải có mục ROADMAP/backlog có chủ (F-802, F-115).

---

## 20. Hạng mục cần quyết định nghiệp vụ của con người

Mỗi mục được viết thành câu hỏi, kèm các phương án. **"Đề xuất mặc định"** là **khuyến nghị** của audit, chủ yếu lấy từ Corrected Rules của A1, vốn dựa trên kiến thức mô hình với độ tin cậy Medium. Audit **không** thay user quyết định. Những AMB đã rõ ràng bị hệ quả của một finding chi phối vẫn được liệt kê để user chốt.

### 20.1 Quyền uy nguồn tài liệu

- **AMB-001: Khi docs/, AGENTS.md và .planning mâu thuẫn, bên nào thắng?**
  - Phương án: (a) docs canonical thắng; (b) AGENTS.md thắng (protocol viện dẫn `docs/AGENTS.md`, file không tồn tại); (c) phát biểu mới nhất thắng.
  - *Đề xuất:* thêm một dòng DECISIONS xếp hạng rõ ràng: DECISIONS > GLOSSARY/DATA_MODEL/CONFIGURATION > docs baseline > AGENTS.md > .planning. Đồng thời chuyển các quy tắc P11–P17 thành doc canonical.
- **AMB-021 / AMB-022: Khi nào phải bump `strategy_version`, và chuẩn hoá `1.0` / `1` trong TOML thế nào?**
  - *Đề xuất:* bump version cho mọi thay đổi tham số có ảnh hưởng ngữ nghĩa. Ghi quy tắc chuẩn hoá TOML thành decision. **Không** chọn giá trị tham số chỉ vì tiện cho hash (F-957).

### 20.2 Sizing, phí, lượng tử hoá

- **AMB-002: Chi phí có nằm trong mẫu số khi sizing không, theo đơn vị nào?**
  - Phương án: (a) quote/đơn vị (P11); (b) % cộng thêm vào khoảng cách; (c) chỉ tính trong PnL.
  - *Đề xuất:* (a), theo Corrected Rule 2: `|entry_worst−SL| + entry×fee_in + SL×(fee_out+slip_out)`.
- **AMB-004: Khoảng cách "xấu nhất" tính theo mép nào của vùng?**
  - Phương án: mép bất lợi / giữa vùng / giá limit thực.
  - *Đề xuất:* mép bất lợi cho sizing khi còn giữ "vùng". Hoặc giữ giữa vùng nếu live luôn đặt LIMIT đúng ở giữa, khi đó backtest phải khớp đúng giá đó (F-902). B1 đánh giá giữa vùng là SOUND cho live.
- **AMB-005 + quyết định từ lane: Phí dùng khi sizing live là gì, và entry là maker hay taker?**
  - Phương án: phí trong param / commissionRate của tài khoản / max của hai bên; entry GTC thường hay GTX post-only.
  - *Đề xuất:* max(param, account) theo từng chiều, ghi lên plan. Entry marketable thì tính taker, hoặc dùng GTX (Corrected Rule 8).
- **AMB-006 / AMB-007: Thứ tự các check quantization và định nghĩa "realized risk"?**
  - *Đề xuất:* giữ thứ tự hiện tại (L3/B1 đánh giá SOUND). Tử số là `rounded_qty × risk_per_unit`, mẫu số là `allowed_risk`.
- **AMB-027: minNotional tính theo giá limit hay giá mark?**
  - *Đề xuất:* kiểm cả hai, trượt một trong hai thì từ chối.
- **AMB-003: "Equity" để sizing là số nào, lấy lúc nào?**
  - Phương án: wallet / margin balance / snapshot đầu ngày.
  - *Đề xuất:* min(totalWalletBalance, totalMarginBalance), chụp lúc tạo plan. Lúc đặt lệnh, từ chối nếu rủi ro dự kiến vượt quá 1,05 × risk_rate × equity hiện tại. Không bao giờ tăng size (Corrected Rule 7).
- **Quyết định từ lane: có cần trần chi phí/rủi ro và khoảng stop tối thiểu không?**
  - *Đề xuất:* có. `max_cost_to_risk` là tham số registry, baseline nghiên cứu 0,15 (A1, Medium).

### 20.3 Danh mục, daily loss, leverage

- **AMB-012: Daily loss tính theo ngày nào: UTC hay Asia/Ho_Chi_Minh?**
  - Các câu hỏi con: realized hay cả unrealized, có tính phí và funding không, gốc tính là equity đầu ngày hay hiện tại, reset khi nào, có lưu bền không.
  - *Đề xuất:* ngày UTC, loss = −(realized + commission + funding), gốc là equity lúc 00:00 UTC, so sánh `≥`, DAILY_STOP lưu bền tới ngày UTC kế tiếp, huỷ entry đang chờ nhưng **không** huỷ lệnh bảo vệ (Corrected Rule 10). Hiển thị theo giờ Asia/Ho_Chi_Minh.
- **AMB-016 / AMB-017: Cluster gồm những symbol nào, và "open" gồm những gì?**
  - Phương án cho "open": chỉ vị thế / vị thế + lệnh đang chờ / + plan đã duyệt chưa đặt.
  - *Đề xuất:* cả live-5 là một cluster, giới hạn theo chiều. Open risk = vị thế + entry đang chờ + plan APPROVED chưa đặt. Kiểm dưới khoá tuần tự ở cả lúc duyệt và lúc đặt (Corrected Rule 9). Hiện code bỏ BNB ra ngoài cluster (F-908).
- **Quyết định từ lane (F-303): Có cho phép 2 plan trên cùng một symbol không?**
  - *Đề xuất:* không. Mỗi symbol tối đa một vị thế hoặc entry đang chờ.
- **AMB-019 + quyết định từ lane (F-964): Leverage và margin mode: chỉ đọc hay hệ thống tự đặt? Isolated hay cross?**
  - *Đề xuất:* isolated. Leverage đặt tường minh, là số nguyên nhỏ nhất đủ margin, trần 5x. Giá thanh lý cách SL ít nhất 1× khoảng SL. Không đạt thì NO_TRADE (Corrected Rule 11, Medium).
- **AMB-030 / F-965: Position mode: hỗ trợ cả hai mode hay chỉ one-way?**
  - *Đề xuất:* chỉ One-way + Single-Asset. Mode khác thì không vào lệnh mới (Corrected Rule 17).
- **AMB-018: Nguồn equity và PnL trong paper và backtest?**
  - *Đề xuất:* backtest size theo equity live thực tế ($500 / $1.000) và báo số NO_TRADE theo từng lý do (Corrected Rule 37).

### 20.4 Duyệt lệnh và hết hạn

- **AMB-013 / AMB-031 / F-016: Hạn duyệt, hạn plan và hạn entry quan hệ thế nào? Cơ chế hết hạn là gì?**
  - *Đề xuất:* hạn duyệt = `plan.expiry_utc`. Từ chối duyệt khi thời gian còn lại < max(600 s, `min_remaining_validity`). Hết hạn được thực thi bằng lệnh huỷ cục bộ cộng GTD. Biên được tính bao gồm (Corrected Rule 21).
- **Quyết định từ lane: có giữ hạn 4 giờ không?** Giá trị này đến từ tracer (F-909), không có lý do giao dịch, và người dùng làm việc toàn thời gian.
  - *Đề xuất:* user quyết định dựa trên dữ liệu độ trễ duyệt thật (F-961).
- **AMB-014: "Revalidate" sau khi duyệt có được đổi qty hay giá không?**
  - Phương án: chỉ từ chối / chỉ giảm và cần duyệt lại / đổi tự do.
  - *Đề xuất:* chỉ từ chối. Qty, giá và side là bất biến (Corrected Rule 22, F-203).
- **AMB-025: Ai được quyền duyệt?**
  - Phương án: chỉ chat / chỉ user / cả hai.
  - *Đề xuất:* cả hai, và chỉ trong private chat (F-508).
- **AMB-011 / AMB-010 / AMB-009: SKIP có một hay hai nút, SKIPPED_BUSY sinh ra thế nào, trạng thái CANCELED, và đồ thị chuyển trạng thái?**
  - *Đề xuất:* ghi đồ thị chuyển trạng thái thành decision (F-111). Sửa SKIP (F-405).
- **AMB-028: Tín hiệu từ nến được khôi phục sau gap có phát ra không?**
  - Phương án: chặn và ghi journal / phát với trạng thái hết hạn ngay / phát nếu còn hạn.

### 20.5 Thực thi, bảo vệ lệnh, SAFE_MODE

- **AMB-024 / F-952 / F-009: Chính sách đặt lại stop khi SAFE_MODE: tự động, thủ công, hay tự động có kiểm tra rủi ro?**
  - Hiện tại: reconciler chỉ huỷ, "no rescue".
  - *Đề xuất:* SAFE_MODE chỉ chặn lệnh mở hoặc tăng vị thế. Lệnh bảo vệ và reduce-only luôn được phép sau khi đã truy vấn vị thế có thẩm quyền. Stop bị mất được đặt lại tự động ở đúng SL gốc, không bao giờ nới. Nếu giá đã vượt SL thì đóng reduce-only (Corrected Rule 24). Đây là **quyết định lớn**, đảo ngược 08 D-03 / 09 D-02, và sẽ làm đỏ các test ở F-604.
- **AMB-015 / F-711: Thoát SAFE_MODE thủ công hay tự động? Có lưu bền qua restart không?**
  - *Đề xuất:* thủ công, cần operator id, và lưu bền qua restart (Corrected Rule 25).
- **Quyết định từ lane (F-007, Corrected Rule 14): Khi SL bị từ chối ngay sau khi khớp, có đóng vị thế bằng MARKET reduce-only không?**
  - *Đề xuất:* có, kèm cảnh báo và SAFE_MODE.
- **Quyết định từ lane (F-958 / F-010): SL kích hoạt theo MARK_PRICE hay CONTRACT_PRICE?**
  - *Đề xuất:* CONTRACT_PRICE + `priceProtect=false`, khớp với backtest 1m. Chỉ dùng MARK nếu có backtest theo mark price (Corrected Rule 15).
- **Quyết định từ lane (F-018): Sau TP1, SL xử lý thế nào: giữ nguyên, về hoà vốn, hay trailing?**
  - *Đề xuất:* không dùng breakeven hay trailing trừ khi spec đóng băng khai báo và backtest mô phỏng đúng như vậy (Corrected Rule 16).
- **Quyết định từ lane (F-103): Tỷ lệ chia TP1 bao nhiêu? TP2 = 2× chặng TP1 có hợp lý không?**
  - Cần đưa vào registry.
- **AMB-032: Giới hạn 200 conditional order: hằng số hay đọc động?**
  - *Đề xuất:* hằng số cấu hình kèm trích dẫn changelog 2025-12-29. Tính **toàn tài khoản** (F-051).
- **AMB-033: Đóng vị thế thủ công: V1 tự làm qua hệ thống hay để người thao tác trên sàn rồi reconcile?** Liên quan thứ tự emergency close của WR-07.
- **AMB-023 / F-026: Nhịp reconcile và các ngưỡng freshness?**
  - *Đề xuất:* reconcile REST ≤ 60 s khi có vị thế hoặc lệnh. listenKey keepalive ≤ 30 phút. Nến đóng phải tới trong ≤ 90 s. WS im lặng > 60 s thì reconnect (Corrected Rule 26, Medium).
- **AMB-026: Có cần entity Trade trong V1 không?** (F-112)
- **AMB-038: Candle lưu ở Parquet hay PG?** Hiện là Parquet theo D-05 (L4 không báo lỗi).
- **AMB-039 / F-052: Có webhook TradingView trong V1 không?**
  - *Đề xuất:* không. Nếu có thì không thể dùng HMAC; phải dùng secret trong body hoặc IP allowlist.

### 20.6 Nghiên cứu và kill gate

- **F-022 / F-960: Các ngưỡng số của kill gate / acceptance, đăng ký trước là bao nhiêu?**
  - *Đề xuất:* đóng băng trước lần Validation đầu tiên. Cận dưới CI bootstrap > 0 ở 1× chi phí và ≥ 0 ở 2× chi phí. Số giao dịch tối thiểu mỗi lát cắt. Trần drawdown và chuỗi thua ở equity live. Hiệu chỉnh đa kiểm định (Corrected Rule 31).
- **AMB-034: Có cho phép reset INSUFFICIENT_EDGE không?**
  - *Đề xuất:* chỉ bằng một dòng DECISIONS kèm câu hỏi nghiên cứu mới.
- **L1 open question 3: Có khởi động lại đồng hồ kill gate 6 tháng (bắt đầu 2026-09-19) không?** Hiện chưa có pipeline nghiên cứu hợp lệ nào (F-120, M4, F-125, F-107). Đây là câu hỏi phương pháp.
- **AMB-035: Tie-break trong nến: cố định SL-first hay khai báo theo từng experiment?**
  - *Đề xuất:* cố định bất lợi trước, ghi vào identity (Corrected Rule 20).
- **AMB-036 / F-006: `partial_fill_fraction` bằng bao nhiêu?**
  - *Đề xuất:* 1.0 ở size V1, giống nhau giữa candidate và baseline. Chạm giá không phải là khớp (Corrected Rule 18).
- **AMB-037: Quy ước dấu funding và slippage?**
  - *Đề xuất:* slippage bất lợi ở mọi lần khớp taker (≥ 2 bps BTC/ETH, ≥ 5 bps cho các mã còn lại, kèm lượt chạy stress 3×). Funding có dấu theo chiều vị thế, tính tại mốc funding thật (Corrected Rule 19).
- **F-024 / F-907: Research universe là gì?**
  - *Đề xuất:* top-N point-in-time theo volume quote 30 ngày, đóng băng và hash, gồm cả mã đã delist. Báo live-5 riêng (Corrected Rule 33).
- **AMB-029 / F-953: Có cần cổng code gắn việc bật live với spec đã đóng băng và bằng chứng paper không?**
  - *Đề xuất:* có (P0-12). Paper exit gate: parity replay, fill/slippage/latency trong mô hình, ≥ 30 lệnh đã đóng và ≥ 3 tháng, bắt đầu live ở vốn tối thiểu (Corrected Rule 32).
- **F-113: Việc dời SL của Family B để cổng RR pass là thiết kế hợp lệ hay tinh chỉnh sau khi xem kết quả?** Cần ghi DECISIONS.
- **F-806: Quy tắc TP của checkpoint 04-03 bị review fix ghi đè. User có chấp nhận quy tắc TP hiện tại không?**
- **AMB-020: SignalId có thể trùng giữa các family hay baseline không?** L1 xác nhận code hash một tập lớn hơn (thêm strategy_id và parameter_set_id), nên đây là quyết định xác nhận.

### 20.7 Vận hành

- **F-108 / F-910: Đích backup off-host nào? Có dùng OneDrive không?**
  - *Đề xuất:* host thứ hai hoặc object storage, mã hoá, có lịch và retention, drill restore PG thật.
- **F-027: Cấu hình quyền API key?**
  - *Đề xuất:* bắt buộc IP allowlist. Chỉ quyền futures trade + read. Dùng key read-only riêng cho collector (Corrected Rule 29).
- **L8 open question 5: Có secret nào từng nằm trong checkout OneDrive không?** Cần user tự kiểm tra.

---

## 21. Giới hạn của audit

1. **Không có testnet hay live:**
   - Không kết nối Binance, Telegram hay DB thật.
   - F-501 còn INSUFFICIENT_EVIDENCE.
   - Các mã lỗi thực tế và hành vi `closePosition` khi chưa có vị thế chỉ dựa trên tài liệu công khai và probe với fake SDK.
2. **PostgreSQL:** 6 test PG bị skip (`TEST_DATABASE_URL` unset theo charter). Migration chưa từng được áp lên DB thật. Kết luận F-403, F-406, F-411 dựa trên đọc code và probe metadata.
3. **Docker:** không chạy. F-705 (HEALTHCHECK) chỉ ở mức PROBABLE.
4. **Web không truy cập được:** trang phí Binance cần đăng nhập, trang Telegram trả 403 với một số fetch. Các sự thật được đối chiếu qua trang công khai và mã nguồn SDK/PTB đã cài (A2).
5. **Khoảng trống bao phủ:**
   - 47 file EXCLUDED và 254 file METADATA_ONLY, trong đó 37 file source (gần như toàn bộ `src/analytics/*`, gồm `killgate.py`).
   - Các file `*-VALIDATION.md` và `*-PATTERNS.md` không được đọc.
   - 10-RESEARCH.md (81 KB) chỉ được đọc phần quyết định.
6. **Phán đoán domain dựa trên kiến thức mô hình:**
   - Finding stage A/B và Corrected Rules là đánh giá thiết kế của mô hình. Nhiều mục mang nhãn PROBABLE hoặc SUSPICIOUS.
   - Các ngưỡng số (2/5 bps, trần chi phí/rủi ro 0,15, leverage 5x, 60 s/90 s) là **đề xuất mặc định**, không phải sự thật về sàn (A1 ghi độ tin cậy Medium).
   - "Rule 14/24" không phải là yêu cầu có sẵn trong docs của dự án (V3, V5).
7. **Verification chỉ dùng một mô hình:** mọi verifier là agent context mới *của cùng một mô hình*. Không có mô hình thứ hai để kiểm chéo, nên các thiên lệch chung của mô hình có thể không bị phát hiện.
8. **Lỗi tiềm ẩn trong code chưa nối dây:**
   - Phần lớn finding HIGH nằm trong thư viện chưa có caller production (F-201).
   - Mức độ được đánh giá "cho lúc code được nối dây như thiết kế" (V2, V3, V5).
   - Cách nối dây thực tế trong tương lai có thể làm lỗi nặng hơn (F-302 lên CRITICAL) hoặc làm vài lỗi biến mất.
9. **Không bisect lịch sử:** các đợt review-fix 06 và 08 không được chạy lại ở từng SHA trung gian; chỉ biết HEAD xanh (L8).
10. **Không đo coverage %** (không cài `coverage`). Không có semgrep hay CodeQL.
11. **Không có transcript chat:** không xác định được user có thật sự được hỏi ở các checkpoint "(orchestrator)" hay không (L8).
12. **Không đánh giá khả năng sinh lời** của chiến lược, theo yêu cầu của user (charter §11c).
13. **Tính toàn vẹn của repo gốc:** việc kiểm `git status` và `git diff` so với `baseline/` và ghi `OUTPUT_HASHES.txt` là bước T13 của coordinator, **sau** báo cáo này. Báo cáo này không tự khẳng định kết quả của bước đó.

---

*Hết báo cáo. Nguồn chi tiết: `findings.json` (164 bản ghi), `verification/V1..V5_*_result.md`, `lanes/*.md`, `INVARIANTS.md`, `FILE_COVERAGE.md`, `MANIFEST.md`, `tool-output/*`.*
