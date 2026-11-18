# Báo cáo tổng hợp audit dự án Trading (bản dễ đọc)

> Snapshot `55885b9` (branch `develop`) · Audit ngày 2026-11-17 → 2026-11-18 · Chỉ đọc, không sửa repo.
> Đây là bản rút gọn của `DEEP_AUDIT_REPORT.md` (cùng thư mục). Mỗi vấn đề có mã `G-xxxx` để tra
> chi tiết trong báo cáo đầy đủ hoặc trong `findings.json`.

---

## 0. Kết luận: có nên đi tiếp không

**Khuyến nghị của audit: không đi tiếp theo kế hoạch hiện tại.** Tạm dừng phần kỹ thuật đặt lệnh (không làm soak
Demo 21 ngày, Phase 26, hay phần nguồn tín hiệu), giữ nguyên việc tắt lệnh thật, và dùng 4 tháng tới mốc dừng mà
chính dự án đã đặt (**19/03/2027**) cho **một** vòng nghiên cứu mới được thiết kế tốt hơn. Nếu tới ngày đó không có
chiến lược nào đạt chuẩn: dừng mục tiêu kiếm tiền, giữ code làm công cụ nghiên cứu. Nếu có: quay lại đúng lộ trình
cũ, phần đã xây không bị phí. (Chi tiết: `DEEP_AUDIT_REPORT.md` mục 9a, lane X11.)

Vì sao, bằng số:

- **Nghiên cứu của chính dự án nói "không":** 0 trong 48 biến thể chiến lược qua được chuẩn mà dự án tự đặt trước.
  Trung bình mỗi lệnh lỗ 0,07–0,10 R (R = số tiền chấp nhận mất cho một lệnh). Chiến lược đang chạy thử trên Demo
  lỗ 0,10 R mỗi lệnh trên 613 lệnh.
- **Trước phí thì gần hòa vốn; phí làm nó thành lỗ.** Phí và trượt giá ăn 6,5–15 % số tiền rủi ro của mỗi lệnh.
  Các chiến lược hiện tại không có lợi thế đủ lớn để bù.
- **Tăng vốn không cứu được.** Phí tính theo tỷ lệ, nên vốn lớn chỉ làm lỗ lớn hơn theo cùng tỷ lệ: với tốc độ hiện
  tại, 500 USDT lỗ khoảng 40 USDT/năm, 20.000 USDT lỗ khoảng 1.600 USDT/năm. Vốn chỉ đáng tăng **sau khi** có một
  chiến lược đạt chuẩn.
- **Lộ trình còn lại không dẫn tới giao dịch thật.** Bước bật lệnh thật đòi hỏi một chiến lược đạt chuẩn, mà không
  bước nào trên lộ trình tạo ra nó. 3–6 tháng chạy paper hay Demo cũng không chứng minh được lợi thế: quá ít lệnh
  (sai số khoảng ±0,11–0,16 R, tức không phân biệt được +0,1 R với -0,1 R). Chúng chỉ chứng minh hệ thống chạy đúng.
- **Ba chiến lược hiện tại là ý tưởng phân tích kỹ thuật phổ biến**, không có nguồn nghiên cứu nào cho thấy chúng
  có lợi thế ở khung 1H/4H trên crypto.

Điều gì sẽ làm khuyến nghị này thay đổi: (1) bạn làm dự án chủ yếu để học kỹ thuật — khi đó đi tiếp là sở thích hợp
lý, miễn không coi kết quả Demo là bằng chứng có lời; (2) vòng nghiên cứu mới có ứng viên đạt chuẩn; (3) tìm ra
nguồn đáng tin cho thấy một trong ba setup có lợi thế ở khung này.

Lưu ý: audit không dự đoán lợi nhuận tương lai; kết luận trên chỉ dựa vào bằng chứng đã có trong dự án. Việc bạn
cần quyết: R-52..R-55 trong `DEEP_AUDIT_REPORT.md` mục 15.4.

---

## 1. Kết luận trong 5 dòng

1. **Hệ thống đã chạy được từ đầu tới cuối trên Demo**, và các nguyên tắc an toàn quan trọng nhất đều có trong code và có test bảo vệ. Hiện tại (lệnh thật bị tắt) không có lỗi nghiêm trọng nào.
2. **Nếu bật lệnh thật trên mainnet với code như hôm nay thì có 8 vấn đề mức HIGH**, đều đã được kiểm tra lại độc lập và xác nhận. Phần lớn là trường hợp một vị thế có thể nằm trên sàn mà không có stop-loss.
3. **Kết quả nghiên cứu của chính dự án: chưa có chiến lược nào đạt chuẩn** mà dự án tự đặt ra trước. Chiến lược đang chạy thử trên Demo có kết quả âm (-0,10 R mỗi lệnh trên 613 lệnh). Chưa ai ghi lại kết luận này.
4. **Nhiều "quyết định của owner" thật ra là chấp nhận hàng loạt đề xuất của AI**, chưa từng được trình bày kèm hậu quả bằng tiền. Nhiều quyết định đúng, một số đáng ngờ, vài cái sai.
5. **Toàn bộ 12 lỗi HIGH của audit trước (2026-09-29) đã được sửa thật**, không cái nào bị đóng sai.

| Con số | Hiện tại (lệnh thật tắt) | Khi bật lệnh thật trên mainnet |
|---|---|---|
| CRITICAL | 0 | 0 |
| HIGH | 0 | **8** |
| MEDIUM | 22 | 76 |
| LOW | 103 | 48 |
| INFO | 19 | 12 |
| Tổng (đã bỏ trùng) | 144 | 144 |

16 vấn đề nặng nhất được gửi cho người kiểm tra độc lập (chỉ nhận mô tả và vị trí): 9 xác nhận, 7 hạ mức, 0 bác bỏ.

---

## 2. Tám vấn đề HIGH trên mainnet, nói bằng lời thường

Ví dụ dùng tài khoản 1.000 USDT, mỗi lệnh rủi ro 0,5 % (= 5 USDT, gọi là 1R), đòn bẩy 5x isolated.

1. **Lệnh chờ không có stop khi máy chủ chết (G-2100).** Hệ thống đặt lệnh mua/bán chờ khớp mà chưa có stop-loss; stop chỉ được đặt khi chương trình thấy lệnh khớp. Nếu máy chủ tắt, khởi động lại, hoặc mất mạng đúng lúc đó, lệnh khớp mà không ai đặt stop, và chương trình được cấu hình không tự khởi động lại. Thay vì mất 5 USDT, có thể mất tới khoảng 88 USDT (toàn bộ ký quỹ của vị thế). Tài liệu của dự án lại nói "stop luôn nằm trên sàn" — điều này không còn đúng.
2. **Chương trình tưởng vị thế đã đóng rồi tự xoá stop (G-0300).** Ngay sau khi khớp lệnh, nếu sàn trả về "vị thế = 0" hai lần liên tiếp (hai lần hỏi cách nhau vài mili giây, khi dữ liệu của sàn có thể chưa cập nhật), chương trình kết luận vị thế đã đóng và huỷ luôn stop của mình, trong khi vị thế vẫn còn. Chưa biết sàn thật có hay trả như vậy không, nhưng nếu có thì vị thế nằm trần cho tới khi bạn phát hiện.
3. **Lệnh đóng khẩn cấp bị "đóng băng" mãi (G-0301 + G-2203).** Khi phải đóng gấp một vị thế không có stop mà sàn trả lời không rõ ràng (hoặc từ chối bằng một mã lỗi chương trình chưa biết, ví dụ khi thị trường chạy nhanh), chương trình chỉ gửi đúng một lần rồi chờ mãi, không thử lại, không đặt stop, và cả lệnh điều khiển của bạn cũng bị từ chối. Ví dụ: 0,02 BTC ở 60.000, ký quỹ 240 USDT, có thể mất cả 240 USDT thay vì 5–10 USDT.
4. **Không ghi lại các lệnh đã khớp (G-1101).** Không có đoạn code nào ghi bảng "fills" trong database. Hậu quả: báo cáo kết quả live luôn thấy 0 giao dịch. Ví dụ: 20 lệnh Demo lỗ ròng -3R sẽ được báo là "0 lệnh". Không đánh giá được Demo campaign, và trên mainnet các cơ chế dựa vào kết quả thật sẽ mù.
5. **Cảnh báo khẩn cấp có thể bị mất (G-0801).** Nếu gửi Telegram thất bại (3 lần trong 30 giây), cảnh báo bị bỏ luôn tới khi chương trình khởi động lại; trong 5 phút sau các cảnh báo giống vậy cũng bị bỏ qua. Mà chính lúc mạng hay sàn trục trặc là lúc cảnh báo quan trọng nhất và cũng dễ gửi thất bại nhất.
6. **Công cụ chấm "Demo chạy ổn 3 tuần" có thể chấm đậu một lần chạy không hề diễn ra (G-1302).** Hai dòng log cách nhau 22 ngày là đủ để được "PASS", dù ở giữa chương trình không chạy và không có lệnh nào. Đây lại là bằng chứng dùng để quyết định có lên tiền thật hay không.
7. **Chưa có lần chạy toàn bộ test có database nào được ghi lại kể từ 2026-10-20 (G-1508).** Từ đó tới nay có 572 commit và hơn 43.000 dòng code mới, gồm toàn bộ phần chạy live. Code sẽ đặt lệnh tiền thật chưa có bằng chứng kiểm thử đầy đủ gắn với một phiên bản cụ thể.

(G-0301 và G-2203 là một cặp nên tám vấn đề được kể thành bảy mục.)

---

## 3. Kết quả nghiên cứu

- Dự án đã chạy xong "research run 1": 48 phương án chiến lược (3 họ × 16 bộ tham số), đo trên dữ liệu kiểm định.
- **45/48 phương án có kết quả trung bình âm.** Một phương án không đủ số lệnh. Hai phương án dương nhưng chỉ dương khoảng +0,003 R và +0,0007 R, nhỏ hơn rất nhiều so với độ dao động ngẫu nhiên.
- Theo chính các tiêu chí mà dự án đặt ra **trước khi chạy**, **không phương án nào đạt**.
- Phương án đang dùng cho chạy thử Demo/paper (gọi là a01): **-0,1019 R mỗi lệnh trên 613 lệnh**. Ví dụ: 100 lệnh thật với 1R = 5 USDT sẽ mất khoảng 50 USDT trước cả chi phí máy chủ.
- **Không có file nào ghi lại kết luận này.** Bộ "kill gate" (cơ chế dừng nghiên cứu khi không có gì đạt) vẫn báo "còn trong ngân sách", vì nó chỉ đếm những gì con người tự ghi tay — mà chưa ai ghi.
- Giới hạn: danh sách từng lệnh của lần chạy đã bị xoá, nên không tính lại được khoảng tin cậy chính xác; các con số lấy từ file log của lần chạy. Một phát biểu trước đó ("a01 âm có ý nghĩa thống kê, z = -2,29") là **nói quá**; câu đúng là "a01 âm, đủ để trượt tiêu chí". Đây là kết quả theo quy tắc của dự án, không phải dự báo lời lỗ tương lai.
- Thêm một điểm cần biết: với tài khoản 500–1.000 USDT, 1R chỉ 2,5–5 USDT; ngay cả một chiến lược có lợi thế +0,10 R trên 250 lệnh/năm cũng chỉ lãi khoảng 62–125 USDT/năm, có thể thấp hơn chi phí thuê máy chủ (G-2105).

---

## 4. Những gì đã kiểm và đứng vững

- **Không bao giờ gửi một lệnh hai lần.** Nếu sàn trả lời không rõ, hệ thống hỏi lại một lần rồi dừng ở chế độ an toàn, không gửi lại.
- **Khối lượng luôn làm tròn xuống**; nếu không đủ mức tối thiểu thì bỏ lệnh chứ không làm tròn lên. Đã thử với hàng nghìn trường hợp: rủi ro thực không bao giờ vượt mức cho phép.
- **Không mở lệnh mới khi còn vị thế chưa có stop.** Chế độ an toàn (SAFE_MODE) chặn lệnh mới nhưng không bao giờ chặn hành động bảo vệ.
- **Lệnh chỉ được đặt sau khi bạn APPROVE rồi CONFIRM**, và chỉ đúng người, đúng chat riêng; lệnh gửi lên sàn đúng symbol, đúng chiều, không lớn hơn khối lượng đã duyệt.
- **Lệnh thật bị khoá chắc chắn**: mode LIVE hiện không có cách nào bật nếu không sửa code.
- **Khởi động lại thì tự bảo vệ**: nếu chương trình được chạy lại sau khi một lệnh khớp lúc nó chết, nó tìm ra và đặt stop (đã thử với thời gian chết 5 giây và 1 giờ).
- **Bộ mô phỏng backtest không nhìn trước tương lai**, cho kết quả giống hệt nhau qua nhiều lần chạy; 73 bộ tham số khớp với mã khoá; dữ liệu kiểm định cuối cùng (holdout) chưa bị đụng tới.
- **Kiểm tra "phá thử" khoảng 90 điểm an toàn** (cố ý làm hỏng code để xem test có bắt được không): các chốt chặn then chốt đều có test báo đỏ ngay. Chỉ 3 lỗ nhỏ không ảnh hưởng tiền.
- Bí mật (key, mật khẩu) không lọt vào lệnh hệ thống hay log ở các đường chính; container chạy không quyền root; công cụ Demo không thể chạm sàn thật.

---

## 5. Các quyết định quan trọng nhất đang chờ bạn

Danh sách đầy đủ (51 mục, mỗi mục có phương án, ví dụ bằng số và hậu quả nếu để nguyên) ở mục 15 của `DEEP_AUDIT_REPORT.md`. Mười mục nên quyết trước:

| Mã | Câu hỏi | Ví dụ |
|---|---|---|
| R-25 | Ghi lại "run 1 không có phương án nào đạt" chưa? Demo campaign tiếp theo là bước tới tiền thật, hay chỉ để kiểm tra kỹ thuật? | 45/48 âm; a01 -0,10 R × 613 lệnh |
| R-01 | Bảo vệ lệnh chờ khi máy chủ chết: đặt stop cùng lúc với lệnh, dùng hẹn giờ tự huỷ của sàn, cho chương trình tự khởi động lại, hay chỉ đặt lệnh khi bạn có mặt? | lỗ có thể tới ~88 USDT thay vì 5 |
| R-03 | Lệnh đóng khẩn cấp không rõ kết quả: cho phép gửi lại lệnh đóng (chỉ giảm vị thế, không thể mở thêm) sau một số lần kiểm tra? | ký quỹ 240 USDT có thể mất hết |
| R-35 | Xây phần ghi lệnh đã khớp trước Demo campaign, hay đánh giá bằng lịch sử xuất tay từ Binance? | 20 lệnh -3R bị báo là 0 lệnh |
| R-36 | Demo soak được phép tắt tối đa bao lâu? Có bắt buộc phải có lệnh? | 21 ngày, 95 % ⇒ tối đa 25,2 giờ tắt; hiện chấp nhận ~502 giờ |
| R-43 | Kênh cảnh báo thứ hai ngoài Telegram (email/SMS qua heartbeat)? | Telegram mất 02:00–07:00, vị thế 0,5 ETH trần, giá -5 % = 75 USDT |
| R-23 | Cảnh báo gửi thất bại: thử lại tới khi gửi được? Có muốn tin nhắn báo kết quả sau CONFIRM? | Telegram mất 40 giây lúc 03:00 ⇒ cảnh báo mất |
| R-02 | Bao nhiêu lần sàn nói "không thấy stop" thì mới đóng vị thế? | một lần trả lời sai ⇒ đóng một lệnh đang tốt, ~-4 USDT + dừng giao dịch |
| R-24 | Điều kiện để bật tiền thật: bắt buộc có phương án đạt chuẩn, hay cho canary nhỏ với giới hạn lỗ viết tay? | xem mục 3 |
| R-30 | Trình lại từng con số tiền mà AI đặt mặc định, mỗi số một ví dụ bằng USDT | 180 giây không stop, 3 ngày khoá khi bị ban, 0,5 % cluster cap... |

---

## 6. Nên làm gì tiếp theo, theo thứ tự

**Trước Phase 25 (Demo campaign):**
1. Quyết R-25 (kết quả run 1) — nó quyết định Demo campaign để làm gì.
2. Sửa phần ghi lệnh đã khớp (G-1101), nếu không campaign không đo được gì.
3. Sửa công cụ chấm soak (G-1302).
4. Chạy và lưu lại một lần chạy toàn bộ test có database trên code hiện tại (G-1508); vào GitHub Actions xem CI có chạy và có đậu không (G-1401).
5. Cho bằng chứng Demo ghi rõ phiên bản code (G-1501) và giữ câu trả lời gốc của sàn (G-1502).
6. Không để mất cảnh báo khẩn cấp (G-0801), thêm kênh thứ hai (G-2003), thêm tin nhắn kết quả sau CONFIRM (G-0802).
7. Nếu muốn Demo kiểm cả đường "chiến lược → lệnh" thì phải xây nguồn tín hiệu chiến lược cho chương trình live (G-1052); hiện chỉ có tín hiệu giả của smoke test.

**Trước khi đặt bất kỳ lệnh tiền thật nào:**
8. Giải quyết ba vấn đề "vị thế trần": G-2100, G-0300, G-0301 + G-2203 (và G-1801: sau khi bạn tự đóng tay, hệ thống vẫn kẹt).
9. Các trường hợp chương trình tự chặn chính hành động bảo vệ: khoá 3 ngày khi bị ban (G-0700), dừng 120 giây sau giới hạn tốc độ (G-0701), luồng dữ liệu tài khoản không tự kết nối lại (G-0702).
10. Giám sát chương trình: trạng thái "đỏ" không làm gì (G-0600), lỗi im lặng (G-0601, G-0602, G-0603).
11. Kiểm tra quyền của API key bằng code (không cho rút tiền, giới hạn IP) (G-1752); chỉ cho phép một chương trình live (G-1203).
12. Cập nhật hướng dẫn tiếng Việt và runbook (G-2001, G-2002, G-2004, G-2005), sao lưu journal live (G-1201, G-1202).

**Sau:** các mục vệ sinh code, tài liệu lệch, và quy tắc cho lần nghiên cứu sau (xem mục 14.3 của báo cáo đầy đủ).

---

## 7. Giải thích vài từ dùng trong báo cáo

| Từ | Nghĩa |
|---|---|
| Demo | Môi trường giả lập của Binance, tiền ảo. Mọi thứ hiện nay chỉ chạy ở đây. |
| Mainnet | Sàn thật, tiền thật. Hiện bị khoá trong code. |
| Stop-loss (stop) | Lệnh tự đóng vị thế khi giá đi ngược tới một mức, để giới hạn lỗ. |
| Vị thế "trần" | Vị thế đang mở mà không có stop-loss trên sàn. |
| 1R | Số tiền dự định chấp nhận mất cho một lệnh (ở đây 0,5 % tài khoản = 5 USDT với 1.000 USDT). |
| Isolated, ký quỹ | Mỗi vị thế có một khoản ký quỹ riêng; lỗ tối đa của vị thế đó là khoản ký quỹ này. |
| SAFE_MODE | Chế độ an toàn: không mở lệnh mới, vẫn theo dõi và bảo vệ; chỉ bạn mới tắt được. |
| APPROVE / CONFIRM | Hai lần bấm trên Telegram mà bạn phải làm trước khi một lệnh được đặt. |
| Kill gate | Cơ chế dừng nghiên cứu khi không chiến lược nào đạt chuẩn sau một thời gian. |
| Soak | Chạy liên tục nhiều tuần để chứng minh hệ thống ổn định. |
| Gate tuần tự có PG | Một lần chạy toàn bộ test, kể cả test cần database, được lưu lại kèm phiên bản code. |
| HIGH / MEDIUM / LOW | Mức nghiêm trọng: HIGH = có thể mất tiền hoặc vị thế không được bảo vệ; MEDIUM = sai số liệu hoặc lỗi bị chặn bởi lớp bảo vệ khác; LOW = vệ sinh. |
| "now" / "mainnet" | Mức nghiêm trọng ở trạng thái hiện tại (lệnh thật tắt) / khi bật lệnh thật. |
| Verifier mù | Một người kiểm tra độc lập chỉ nhận mô tả vấn đề và vị trí code, không biết kết luận của lane gốc. |

---

## 8. Giới hạn của audit này

- Test có database (PostgreSQL) không được chạy; không chạy Docker, Demo hay máy chủ thật; không có quan sát nào trên mainnet.
- Không biết kết quả CI trên GitHub.
- Không đọc sâu được hết 135.000 dòng code; một số file chỉ được xem theo nhóm.
- Một số vấn đề HIGH là cơ chế đã xác nhận nhưng chưa biết sàn thật có hay gặp hay không (ví dụ G-0300).
- Lane X11 ("có nên đi tiếp") đang chạy; kết quả của nó sẽ được điền vào mục 0 ở trên và không nằm trong các con số của báo cáo này.

---

**Đọc chi tiết:** `DEEP_AUDIT_REPORT.md` (cùng thư mục) — mục 5 cho 8 vấn đề HIGH, mục 8 cho đánh giá từng quyết định, mục 9 cho nghiên cứu, mục 12 cho những gì đứng vững, mục 15 cho toàn bộ danh sách việc chờ bạn quyết.
