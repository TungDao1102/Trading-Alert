# Báo cáo tổng hợp audit dự án Trading (bản dễ đọc)

> Snapshot `63ca176` · Audit ngày 2026-09-29 · Chỉ đọc, không sửa repo.
> Đây là bản rút gọn của `DEEP_AUDIT_REPORT.md` (1.526 dòng). Mỗi vấn đề đều ghi mã `F-xxx` để tra chi tiết trong báo cáo đầy đủ hoặc trong `findings.json`.

---

## 1. Kết luận trong 30 giây

| Câu hỏi | Trả lời |
|---|---|
| Có dùng tiền thật được chưa? | **Chưa, và hiện cũng không thể.** Các mảnh ghép tồn tại riêng lẻ nhưng chưa được nối thành một hệ thống chạy được. |
| Kết quả backtest có tin được không? | **Không.** Simulator "nhìn trước tương lai" trong cùng một nến và khớp lệnh ở mức giá chưa từng giao dịch. Mọi con số backtest tới nay phải bỏ. |
| Docs và kế hoạch AI viết có đúng không? | **Phần lớn đúng.** Riêng 105 quyết định AI tự chọn trong `.planning`: 65 hợp lý, 19 đáng ngờ, 7 sai, 13 là hoãn lại có rủi ro. Docs có một số lỗi thiết kế thật, quan trọng nhất là cách đặt ngưỡng "pass" cho chiến lược. |
| Có sửa được không? | **Có, tất cả đều sửa được.** Không có lỗi nào buộc phải đập đi làm lại toàn bộ. Hai hạng mục lớn là (1) viết lại simulator backtest và (2) xây lớp "nối dây" runtime cộng lưu trữ PostgreSQL. |
| Mức độ nghiêm trọng | 152 vấn đề: **0 CRITICAL · 12 HIGH · 91 MEDIUM · 45 LOW · 4 INFO**. Cả 12 HIGH đều đã được một agent độc lập kiểm tra lại. |

---

## 2. Những gì dự án đã làm TỐT (đã kiểm chứng)

- **Kiến trúc lõi sạch.** `src/core`, `src/domain` và `src/risk` không phụ thuộc SDK sàn, database hay thư viện web.
- **Tính tiền an toàn.** Mọi giá trị tiền dùng `Decimal`, không có `float` nào lọt vào đường đặt lệnh.
- **Làm tròn khối lượng đúng hướng.** Luôn làm tròn xuống theo stepSize; nếu không đủ minQty/minNotional thì chọn NO_TRADE thay vì làm tròn lên.
- **Không retry mù lệnh đặt (POST).** Cả SDK lẫn adapter đều không tự gửi lại.
- **Đặt stop-loss sớm.** SL (`closePosition`) được đặt ngay khi entry được sàn xác nhận, trước cả khi khớp.
- **Token duyệt lệnh an toàn.** Entropy 256 bit, so sánh constant-time, kiểm chat id trước mọi thao tác.
- **Tắt live mặc định.** Không có secret nào trong lịch sử git.
- **Test chạy ổn định.** 1.268 test pass, deterministic. mypy strict chỉ báo 5 lỗi, và cả 5 đều là nhiễu về kiểu, không phải bug.
- **SDK được dùng đúng.** Mọi hàm, tham số và trường dữ liệu SDK Binance mà code gọi đều có thật trong SDK 17.4.0.

---

## 3. Các vấn đề chính (nhóm theo chủ đề)

### 3.1 Hệ thống chưa được "nối dây": chưa chạy được end-to-end

Code hiện là một bộ thư viện; chưa có chương trình nào gọi các bước theo thứ tự tín hiệu → duyệt → đặt lệnh → bảo vệ → đối soát. Những phần còn thiếu:

- **Chưa có tiến trình điều phối** (composition root) cho các luồng: APPROVE → đặt lệnh, kill-gate → bật live, paper → journal, dữ liệu Parquet → backtest. Cũng chưa có tiến trình gửi yêu cầu duyệt, chạy reconcile định kỳ, hay sinh số liệu equity/daily loss (**F-201**, các mục M1–M8).
- **Chưa có lớp lưu trữ vận hành.** Không có code nào ghi journal, approval hay trạng thái lệnh vào PostgreSQL (**F-202**).
- **Chưa có user-data stream** (listenKey, ORDER_TRADE_UPDATE, ALGO_UPDATE), nên hệ thống không biết lệnh đã khớp hay chưa (**F-104**, HIGH).

➡ Hệ quả là nhiều lỗi ở mục 3.3–3.5 hiện đang **tiềm ẩn**: chúng sẽ lộ ra ngay khi có người nối dây theo đúng thiết kế hiện tại.

### 3.2 Backtest không đáng tin

| Vấn đề | Giải thích đời thường | Mã |
|---|---|---|
| Nhìn trước tương lai | Tín hiệu sinh ra lúc đóng nến 09:59:59, nhưng kết quả thắng/thua lại lấy từ các nến 1 phút *trong chính cây nến đó* (09:00–09:59). Có trường hợp lệnh thoát sớm hơn lúc vào 59 phút. | F-120 (= F-901), HIGH |
| Khớp ở giá "ảo" | Chỉ cần giá chạm mép vùng entry là tính khớp ở *giữa* vùng, dù giá chưa từng tới đó. | F-902, HIGH |
| Chỉ giữ lệnh 1 nến, chốt 100% ở TP1 | Trong khi live chia TP1/TP2. | F-102 |
| Chi phí sai | Slippage tính sai đơn vị (lệch hàng chục nghìn lần trên BTC), bỏ qua funding, đóng băng trạng thái danh mục. | F-306, F-905, F-305 |
| Test không phát hiện | Fixture được sinh ra với dữ liệu 1m nằm sẵn trong nến tín hiệu; 7/9 case không có đáp án kỳ vọng. | F-602, F-805 |

### 3.3 Quy trình chọn chiến lược dễ "tự lừa mình"

- Docs đặt ngưỡng pass **sau khi** đã xem kết quả, việc pass do người quyết, và không có hiệu chỉnh khi thử khoảng 25 biến thể. Với người không chuyên trading, đây là con đường ngắn nhất để đưa một chiến lược "may mắn trên dữ liệu" vào tiền thật (**F-022**, HIGH; gốc ở Phase 1: F-903).
- `enable()` cho bật live ngay cả khi **chưa có family nào pass** (F-953).
- ROADMAP xếp các phase sửa an toàn tiền (11–15) **sau** phase go-live (F-954).
- Chiến lược trend-pullback có hình học sai (**F-301**, HIGH):
  - SL nằm *trong* vùng entry, chỉ cách 0,2 ATR, nên chi phí chiếm khoảng 60% mức rủi ro.
  - "Pullback" kích hoạt ngay trên nến vừa tạo đáy mới.
  - Cộng với lỗi phí, một lần dính SL có thể lỗ khoảng 1,4–3,2 lần ngân sách rủi ro.

### 3.4 Đặt lệnh có thể sai hoặc trùng

| Vấn đề | Kịch bản | Mã |
|---|---|---|
| Lệnh trùng | Telegram gửi lại callback, hoặc process khởi động lại, sau khi lệnh đầu đã khớp → hệ thống đặt thêm một entry. Nguyên nhân: kế hoạch Phase 8 tin rằng Binance tự chặn clientOrderId trùng, nhưng Binance chỉ chặn khi lệnh cũ **còn đang mở**. Với $1.000 vốn và rủi ro 0,5%, lỗ khi dính SL thành khoảng $10 thay vì $5. | F-126 (= F-951), HIGH |
| Lệnh không gắn với plan đã duyệt | Symbol và chiều LONG/SHORT lấy từ tham số do nơi gọi truyền vào, không lấy từ plan đã hash. Đảo chiều thì hệ thống đặt SELL với stop nằm sai phía mà vẫn báo OK. **Sẽ thành CRITICAL ngay khi nối dây.** | F-302, HIGH |
| Khối lượng tính lại lúc đặt | Không so với khối lượng trong plan đã duyệt (golden fixture: đặt 3,311 so với 0,500 trong plan). | F-203 |
| Không kiểm giá sau APPROVE | Trong 4 giờ chờ, nếu giá đã vượt qua SL thì lệnh LIMIT khớp ngay, còn SL bị sàn từ chối → vị thế không có stop. | F-007, HIGH |
| Mã lỗi Binance | Code coi "-2011" là "không tìm thấy lệnh algo". Nếu thực tế Binance trả mã khác, SL **không bao giờ** được đặt. Cần gọi thử trên testnet để chốt. | F-501, HIGH (tạm) |

### 3.5 Đối soát (reconcile) và SAFE_MODE có lỗ hổng

- **Sweeper huỷ nhầm SL.** SL được đặt sẵn cho một entry đang chờ khớp bị coi là "mồ côi" và bị huỷ; khi entry khớp sau đó, vị thế không có stop (**F-401**, HIGH).
- **So khớp mù.** Reconcile vẫn báo "khớp" khi vị thế bị nhân đôi, bị đảo chiều, khi có lệnh lạ trên sàn, hoặc khi vị thế chỉ có TP mà không có SL (**F-701**, HIGH).
- **DB lỗi thì mất phanh.** Hệ thống ghi journal trước rồi mới hành động, nên khi DB/journal lỗi thì các lệnh huỷ, tắt live và đóng khẩn cấp không được gửi tới sàn (**F-702**, HIGH).
- **SAFE_MODE yếu.** Nó tự thoát khi so khớp "sạch" (nhưng so khớp lại mù như trên), chỉ lưu trong bộ nhớ, và không đặt lại stop đã mất (F-711, F-127, F-952).

### 3.6 Tiền, phí, đòn bẩy (phần lớn đã có trong phase 11–17)

- **Lỗi đơn vị phí** (F-001, đã có Phase 11): vượt ngân sách rủi ro khoảng 8–16% với SL rộng 0,5–1%, càng nhiều khi SL hẹp. Với XRP thì ngược lại, lệnh bị đặt nhỏ hơn mức cần.
- **Mặc định entry là phí maker** trong khi LIMIT có thể khớp như taker (F-005).
- `partial_fill_fraction = 0.5` được chọn vì tiện cho việc hash, không có lý do trading (F-006).
- **Chưa định nghĩa rõ** equity, daily loss (ngày UTC hay giờ VN? tính cả phí và funding không?), và cluster (F-012, F-013, F-014).
- **Đòn bẩy, margin, giá thanh lý chưa được kiểm tra** (F-011; đã có P13/P14).
- **Tin nhắn duyệt thiếu số tiền** (F-015; đã có P16).
- **Nút SKIP không bao giờ hoạt động**, vì APPROVE và SKIP dùng chung một mã (F-405).

### 3.7 Dữ liệu, database, vận hành

- **Collector OI chưa từng được deploy.** Binance chỉ giữ 30 ngày, nên mỗi ngày trôi qua là mất vĩnh viễn một ngày dữ liệu (F-107). *Việc này nhạy thời gian nhất.*
- **Backfill ghi ngày dở dang thành file vĩnh viễn**, và ghi file không atomic (F-402, F-408).
- **Schema DB thiếu ràng buộc:** không có FK và unique; hai cột quá ngắn nên insert sẽ lỗi; múi giờ session không cố định nên dữ liệu đọc ra có thể rỗng (F-404, F-403, F-406).
- **Backup** không off-host, không mã hoá, không tự chạy theo lịch, và chưa từng restore thật. Lệnh pg_dump còn sai định dạng URL (F-108, F-121, F-704).
- **Paper soak không chạy được** vì thiếu một `await` (F-125).
- **CI chưa từng chạy** (remote là đường dẫn local), và registry-gate đang đỏ tại HEAD (F-101).

### 3.8 Quy trình phát triển (vì sao lỗi lọt qua)

- **Review phát hiện rồi "skip" mà không tạo việc theo dõi.** Ví dụ lỗi phí và lỗi lookahead đều đã được review Phase 6 chỉ ra, nhưng bị ghi "sẽ mở item riêng" và item đó không tồn tại (F-802).
- **Checkpoint cần người quyết định bị executor tự xoá.** Có ít nhất 8 checkpoint như vậy (F-124, F-809).
- **Commit review-fix khi test không chạy được** (57 fix; F-803). Báo cáo VERIFICATION được viết *trước* các đợt review-fix (F-807).
- **Test sai cách:**
  - có test tính đáp án bằng chính công thức sai;
  - có test khẳng định quy tắc sai, tức sẽ đỏ khi sửa đúng;
  - fake adapter chấp nhận lệnh trùng vô hạn.
  (F-601, F-604, F-603)

---

## 4. Có giải quyết được không?

**Có.** Mọi vấn đề đều có hướng sửa cụ thể trong mục 19 của báo cáo đầy đủ. Mức công sức là ước lượng tương đối, chưa phải số giờ:

| Nhóm | Công sức | Ghi chú |
|---|---|---|
| Lỗi đơn vị phí + mô hình chi phí (P11 mở rộng) | Nhỏ–Vừa | Công thức đã rõ. Cần thêm test "lỗ tại SL ≤ ngân sách". |
| Gắn symbol/side/qty vào plan đã duyệt (F-302, F-203) | Nhỏ | plan_hash đã chứa symbol/direction qua signal_id, chỉ cần so sánh lại. |
| Sửa reconcile (F-401, F-701, F-711, F-702) | Vừa | Thêm quét ngược, so khối lượng có dấu, miễn trừ SL của entry đang chờ. |
| Kiểm giá trước khi đặt + xử lý SL bị từ chối (P15 mở rộng) | Vừa | |
| Equity/daily loss/leverage/margin (P12–P14) | Vừa | Cần bạn quyết một số định nghĩa trước (mục 6). |
| Viết lại simulator backtest theo nhân quả | **Lớn** | Phải chạy lại toàn bộ nghiên cứu sau khi sửa. |
| Nối dây runtime + persistence PostgreSQL + user-data stream | **Lớn** | Đây là phần "chưa làm" lớn nhất. |
| Sửa quy trình nghiên cứu (đăng ký ngưỡng trước) | Nhỏ (docs) | Nhưng cần bạn chấp nhận nguyên tắc này. |
| Hygiene (CI, format, sổ sách, Docker) | Nhỏ | |

**Thứ tự đề xuất:**
1. Deploy collector OI ngay (dữ liệu đang mất mỗi ngày).
2. Chốt các quyết định ở mục 6.
3. Sửa simulator và quy trình nghiên cứu → nghiên cứu lại.
4. P11 (phí) → nối dây runtime + persistence + user-data stream, gắn plan → sửa reconcile/SAFE_MODE → P12–P15.
5. Chạy thử trên testnet (chốt F-501).
6. Paper soak.
7. Cuối cùng mới đến live.

---

## 5. Những gì CHƯA làm được

### 5.1 Về hệ thống

- Chưa có tiến trình nào chạy luồng live hoặc paper end-to-end.
- Chưa lưu trạng thái vận hành vào DB.
- Chưa nhận sự kiện khớp lệnh từ sàn (user-data stream).
- Chưa có cảnh báo vận hành: vị thế không có stop, lệch trạng thái, dữ liệu cũ (F-106).
- Chưa có backup off-host, chưa có restore thật.
- Collector chưa deploy; paper soak chưa từng chạy; buổi diễn tập testnet (09-04) đang bị chặn.
- Chưa có bằng chứng nghiên cứu hợp lệ nào để chọn chiến lược.
- Các requirement bị "mất" giữa docs và kế hoạch: user-data stream, cảnh báo, kiểm tra chuyển trạng thái (state machine) (F-104, F-106, F-111, F-116).

### 5.2 Về chính cuộc audit (giới hạn)

- Không gọi testnet/live, nên F-501 (mã lỗi Binance) chưa chốt được.
- Không có PostgreSQL thật (7 test DB bị skip) và không chạy Docker.
- Không mở được trang phí Binance (cần đăng nhập) và tài liệu Telegram (403); đã dùng nguồn thay thế.
- Phần kill-gate trong `src/analytics` mới xem ở mức metadata.
- 47 file không lane nào đọc, 254 file chỉ xem metadata.
- Các nhận định về trading dựa trên kiến thức của mô hình AI, và chỉ một mô hình thực hiện, không có mô hình thứ hai kiểm chéo.
- 50 vấn đề chưa ở mức CONFIRMED (36 PROBABLE, 13 SUSPICIOUS, 1 UNVERIFIED).

---

## 6. Những việc CẦN BẠN QUYẾT ĐỊNH

Audit không tự quyết thay bạn. Dưới đây là các câu hỏi quan trọng nhất, kèm đề xuất mặc định. Chi tiết đầy đủ ở mục 20 của báo cáo lớn.

1. **Khi docs, AGENTS.md và .planning mâu thuẫn, bên nào đúng?** Đề xuất: ghi một thứ tự ưu tiên rõ ràng vào DECISIONS.md.
2. **Ngưỡng "pass" của chiến lược:** có đồng ý đặt ngưỡng bằng số **trước** khi chạy validation, và thêm hiệu chỉnh cho việc thử nhiều biến thể không? Đề xuất: có.
3. **Daily loss:** tính theo ngày UTC hay giờ Việt Nam? Có tính cả lỗ chưa chốt, phí và funding không? Đề xuất: ngày UTC; tính realized cộng phí cộng funding.
4. **SAFE_MODE có được đặt lại stop-loss bị mất không?** Đề xuất: có. Lệnh bảo vệ và reduce-only luôn được phép.
5. **Đòn bẩy và margin:** isolated hay cross, trần đòn bẩy bao nhiêu? Đề xuất: isolated, có trần, và giá thanh lý phải nằm ngoài SL với một khoảng đệm.
6. **Entry:** chấp nhận phí taker khi lệnh khớp ngay, hay bắt buộc post-only (GTX)?
7. **SL kích hoạt theo MARK_PRICE hay giá giao dịch (CONTRACT_PRICE)?** Backtest phải dùng cùng loại giá.
8. **Bỏ `partial_fill_fraction = 0.5`** và dùng 1.0?
9. **Research universe:** chọn danh sách coin cố định theo thời điểm (có cả coin đã delist) trước khi nghiên cứu?

---

## 7. Tra cứu

| File | Nội dung |
|---|---|
| `DEEP_AUDIT_REPORT.md` | Báo cáo đầy đủ 21 mục (chi tiết từng finding, lộ trình P0/P1/P2) |
| `findings.json` | 164 finding dạng máy đọc được (severity cuối, kết quả verify, trùng lặp) |
| `verification/` | Kết quả kiểm tra độc lập 5 lô |
| `lanes/` | 13 báo cáo chuyên đề (docs, plan, code, test, bảo mật, lịch sử git...) |
| `INVARIANTS.md` | 120 quy tắc nghiệp vụ + 39 điểm mơ hồ trích từ docs |
