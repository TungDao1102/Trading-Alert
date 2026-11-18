# Post-mortem: Trading-Alert (2026-09-19 → 2026-11-18)

Ngày viết: 2026-11-18. Dạng: blameless (không đổ lỗi), dựa trên số liệu trong repo và bản deep audit
2026-11-17 (`.planning/audits/2026-11-17-deep-audit/`). Đây là bản nháp để chủ dự án sửa, không phải quyết định.

## 1. Tóm tắt

Trong 2 tháng, dự án xây được một hệ thống kỹ thuật chất lượng cao: 3.167 commit, khoảng 135 nghìn dòng code
trong `src/`, khoảng 10.400 test, 114 quyết định được ghi lại, Demo smoke chạy 21/21 bước. Bản audit thứ hai
không tìm thấy lỗi CRITICAL hay HIGH nào ở trạng thái hiện tại.

Nhưng câu hỏi quan trọng nhất, "chiến lược có lợi nhuận không", đã có câu trả lời từ 2026-10-20 và câu trả lời
là **không**: research run 1 cho 0/48 ứng viên vượt cổng, trung bình −0,07 đến −0,10 R mỗi lệnh. Sau ngày đó,
khoảng 1.000 commit nữa được dành cho phần thực thi lệnh (Phase 18–25), trong khi kết quả run 1 chưa được ghi
nhận chính thức và kill gate chưa được đánh giá.

**Vấn đề gốc không phải là bug, mà là thứ tự công việc:** kỹ thuật thực thi được làm song song và vượt xa bằng
chứng về lợi thế giao dịch.

## 2. Mốc thời gian

| Ngày | Sự kiện |
|---|---|
| 2026-09-19 | Khởi tạo dự án, research ban đầu, Phase 1 (formalize research) |
| 2026-09-26 | Phase 6 bắt đầu: backtest simulator và experiment registry |
| 2026-09-28 | Phase 9 bắt đầu: live execution rollout, **trước khi có bất kỳ kết quả backtest nào** |
| 2026-09-29 | Deep audit lần 1: 12 HIGH; roadmap được lập lại thành Phase 11–27 |
| 2026-09-30 | D043, D049: các tham số nghiên cứu then chốt (protocol, độ sâu dữ liệu 24 tháng) được chốt từ "auto-mode defaults" của agent |
| 2026-10-12 | Đăng ký trước research run 1: 3 họ chiến lược, 48 bộ tham số, khóa hash |
| 2026-10-14 | D069: một phép Holm trên 48 giả thuyết |
| 2026-10-17 | Simulator 2.3.0, protocol v2.6.0, chạy lại run 1 |
| **2026-10-20** | **Kết quả run 1: 0/48 có thể pass** |
| 2026-10-19 → 2026-11-15 | Phase 18–25: user-data stream, plan binding, SAFE_MODE, equity, margin, Telegram, live runtime, Demo campaign (khoảng 1.000 commit) |
| 2026-11-06 | Demo smoke 21/21 bước |
| 2026-11-17 → 18 | Deep audit lần 2, thêm lane đánh giá chiến lược (X11): khuyến nghị tạm dừng kỹ thuật thực thi |
| 2027-03-19 | Ngày kill gate (D013/D030) có thể kích hoạt |

## 3. Điều làm tốt

- **Kỷ luật nghiên cứu thật sự có.** Run 1 được đăng ký trước, tham số khóa hash, không chỉnh theo kết quả. Nhờ
  vậy kết quả âm là đáng tin, không phải nhiễu do cách làm.
- **Có điểm dừng từ đầu.** D013 (kill gate) được đặt ngay ngày đầu; nhiều dự án trading cá nhân không có.
- **An toàn được ưu tiên đúng.** Placement vẫn tắt, chưa có lệnh thật, chưa mất tiền. Fail-closed, không gửi lại
  lệnh, Decimal, quantization làm tròn xuống đều được kiểm bằng máy.
- **Chất lượng kỹ thuật cao và tự sửa được.** 12 HIGH của audit lần 1 đều đã đóng; audit lần 2 không còn HIGH
  ở trạng thái hiện tại.
- **Mọi thứ có dấu vết.** Quyết định, evidence, kế hoạch đều ghi lại, nên audit có thể dựng lại chính xác điều gì
  đã xảy ra. Bản post-mortem này viết được là nhờ đó.

## 4. Điều chưa tốt

### 4.1 Giả định rủi ro nhất được kiểm tra muộn nhất
Giả định "có lợi thế sau phí" quyết định toàn bộ giá trị dự án, nhưng roadmap xếp nó sau rất nhiều phase kỹ
thuật. Execution (Phase 9) bắt đầu ngày thứ 10; kết quả nghiên cứu đầu tiên đến ngày thứ 31. Một backtest thô
vài ngày, kể cả không hoàn hảo, đã có thể cho tín hiệu cảnh báo sớm về chi phí giao dịch.

### 4.2 Kết quả âm không làm thay đổi kế hoạch
Sau 2026-10-20, không có bước nào trong quy trình buộc phải dừng lại và hỏi "giờ làm gì". Kết quả run 1 không
được ghi thành trạng thái chính thức (G-0901), kill gate không có ai ghi trạng thái để nó có thể kích hoạt
(G-0903), và các phase tiếp theo đã được lên lịch sẵn nên cứ thế chạy. Roadmap còn lại (soak, go-live gate)
không có bước nào tạo ra một ứng viên chiến lược (G-2300).

### 4.3 Thiết kế nghiên cứu thiếu sức mạnh thống kê
Với 24 tháng dữ liệu (D049) và Holm trên 48 giả thuyết, run 1 chỉ phát hiện được lợi thế từ khoảng +0,13 R trở
lên, trong khi lợi thế hợp lý của chiến lược nhỏ lẻ là 0,05–0,2 R (G-2301). Độ sâu dữ liệu được chọn vì lý do
xử lý dữ liệu, không phải vì lợi thế cần tìm. Nghĩa là ngay từ đầu, run 1 gần như chỉ có thể "fail" hoặc "pass
nhờ may mắn"; nó không thể xác nhận một lợi thế nhỏ nhưng thật.

### 4.4 Chi phí giao dịch không được đối chiếu sớm với khung thời gian
Phí và trượt giá chiếm 6,5–15 % của 1R mỗi lệnh ở khung 4H/1H. Trước phí, các họ chiến lược gần hòa vốn; sau phí
thì lỗ. Phép tính này làm được trên giấy từ tuần đầu tiên.

### 4.5 Quyết định của AI được chấp nhận theo mặc định
Nhiều quyết định nền tảng ghi "auto-mode defaults ... the user may override" (ví dụ D043, D049). Các đề xuất
nghe hợp lý và được làm cẩn thận, nhưng câu hỏi cấp kinh doanh ("với vốn 500–1.000 USD và phí này, lợi thế tối
thiểu là bao nhiêu thì đáng làm?") không được agent nào đặt ra, và quy trình cũng không bắt buộc đặt ra. AI tối
ưu rất tốt cho câu hỏi được giao; nó ít khi tự hỏi câu hỏi đó có đúng không.

### 4.6 Tốc độ kỹ thuật che khuất câu hỏi chiến lược
Agent viết code nhanh, nên luôn có việc kỹ thuật "tiếp theo" để làm, và tiến độ trông rất tốt (phase hoàn thành,
test pass). Cảm giác tiến bộ này đến từ phần dễ đo, không phải phần quyết định thành bại.

## 5. Nguyên nhân gốc

1. **Roadmap được tổ chức theo thành phần kỹ thuật** (data → core → risk → backtest → paper → live), không theo
   mức độ rủi ro của giả định.
2. **Không có cổng quyết định gắn với kết quả nghiên cứu.** Kill gate chỉ có ngày, không có người hoặc bước nào
   bắt buộc đánh giá khi có kết quả.
3. **Không có phép tính kinh tế ở đầu dự án:** vốn, phí, lợi thế tối thiểu, số lệnh cần để chứng minh.
4. **Tin vào quy trình thay vì vào câu hỏi:** quy trình GSD đảm bảo làm đúng việc đã lên kế hoạch, không đảm bảo
   kế hoạch đúng.

## 6. Bài học mang theo

- **Kiểm tra giả định chết người trước.** Với dự án trading: "có lợi thế sau phí không?" phải là việc đầu tiên,
  bằng công cụ rẻ nhất có thể, trước khi xây hệ thống đặt lệnh.
- **Tính kinh tế trên giấy trước khi viết code:** vốn × rủi ro mỗi lệnh × số lệnh × lợi thế kỳ vọng − phí.
- **Thiết kế thí nghiệm theo lợi thế cần tìm:** chọn trước mức lợi thế tối thiểu, tính số lệnh cần, rồi mới chọn
  dữ liệu và số giả thuyết.
- **Mỗi kết quả nghiên cứu phải kích hoạt một quyết định có ghi lại**, kể cả khi quyết định là "tiếp tục".
- **Quyết định do AI đề xuất cần một câu hỏi phản biện bắt buộc:** "điều gì khiến đề xuất này sai?" và "nó phục
  vụ mục tiêu cuối cùng thế nào?".
- **Audit định kỳ nên có một lane về chiến lược và kinh tế**, không chỉ về code. Lane X11 lẽ ra nên có từ audit
  lần 1.

## 7. Hành động đề xuất (chủ dự án quyết định)

| # | Hành động | Liên quan |
|---|---|---|
| 1 | Chọn hướng đi: (a) tiếp tục, (b) tạm dừng và làm run 2, (c) đổi chiến lược, (d) dừng | R-52, OD-1 |
| 2 | Ghi nhận chính thức run 1 FAIL vào DECISIONS và STATE, để kill gate có trạng thái | G-0901, G-0903 |
| 3 | Nếu chọn (b): ghi trước mức lợi thế tối thiểu, dữ liệu cần, ngưỡng alpha cho run 2, và việc làm nếu fail | OD-2, G-2102 |
| 4 | Nếu chọn (b): chỉ đưa vào run 2 giả thuyết có nguồn hoặc cơ chế giải thích | OD-3 |
| 5 | Thêm vào quy trình: mỗi kết quả nghiên cứu phải có một dòng quyết định trong DECISIONS | mới |
| 6 | Dù chọn hướng nào: giữ simulator, tầng dữ liệu, risk/quantization làm nền để thử ý tưởng mới nhanh | mới |

## 8. Những gì vẫn còn giá trị

Dù mục tiêu kiếm tiền chưa đạt, dự án đã tạo ra: một simulator tất định có test kỹ, một quy trình nghiên cứu
chống tự lừa mình, một tầng thực thi an toàn đã chạy trên Demo, và một kết quả âm đáng tin. Kết quả âm đáng tin
không phải thất bại của nghiên cứu: nó ngăn việc đem tiền thật vào một chiến lược lỗ.
