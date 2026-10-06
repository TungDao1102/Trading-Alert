# Phase 15 - Hướng dẫn các tham số (tiếng Việt)

Tài liệu này giúp bạn trả lời checkpoint 15-08 (`stop` / `ratify` / `edit`). Nó chỉ để đọc, không phải đầu vào cho agent nào. Các giá trị dưới đây là **đề xuất** từ plan 15-08. Không giá trị nào đã được chốt.

## 0. Ba khái niệm cần nắm

- **ATR**: mức dao động trung bình của một nến 1 giờ. Ví dụ BTC giá 60.000, ATR 400 nghĩa là mỗi giờ giá thường đi khoảng 400 (0,67%). Mọi khoảng cách bên dưới tính theo bội số ATR để tự co giãn theo biến động.
- **Vùng vào lệnh**: khoảng giá mà lệnh limit được phép khớp. Lệnh đặt ở giữa vùng.
- **Stop (SL)**: giá cắt lỗ. Quy tắc mới của Phase 15: stop phải nằm **ngoài toàn bộ vùng vào lệnh**. Bản cũ để stop nằm trong vùng, nên 1/3 vùng vào lệnh nằm sau stop.

Ngân sách rủi ro mỗi lệnh là 0,5% equity (`risk_rate`): **2,5 USDT** ở equity 500 và **5 USDT** ở equity 1.000. Khối lượng lệnh được tính ngược từ con số này.

## 1. Ví dụ chính (Family A, trend-pullback, LONG)

Giả sử pivot (đáy đã xác nhận) = 60.000, ATR = 400. Giá trị đề xuất: `zone_tolerance_atr` 0,5, `entry_buffer_atr` 0,1, `sl_buffer_atr` 0,2.

| Thành phần | Giá |
|---|---|
| Vùng vào lệnh | 59.760 đến 60.240 (60.000 ± 0,6 ATR) |
| Giá đặt lệnh (giữa vùng) | 60.000 |
| Stop mới (dưới mép ngoài vùng 0,2 ATR) | 59.680 |
| Stop cũ (nằm trong vùng) | 59.920 |
| Target 1 (đỉnh pivot đối diện) | 61.600, tỷ lệ lời/lỗ khoảng 5,0 |

| | Equity 500 | Equity 1.000 |
|---|---|---|
| Ngân sách rủi ro (0,5%) | 2,5 USDT | 5,0 USDT |
| Khối lượng | 0,003 BTC | 0,007 BTC |
| Giá trị lệnh | 180 USDT | 420 USDT |
| Rủi ro thực tế sau khi làm tròn khối lượng | 1,93 USDT (77% ngân sách) | 4,51 USDT (90% ngân sách) |

Cách tính, bạn có thể tự kiểm: rủi ro cho 1 BTC = (mép vào bất lợi 60.240 - stop 59.680) + phí và trượt giá ước tính = 560 + khoảng 84 = khoảng 644 USDT. Khối lượng = ngân sách / 644, rồi **làm tròn xuống** theo bước 0,001 BTC. Ở equity 500: 2,5 / 644 = 0,0039, làm tròn xuống 0,003. Phần bị làm tròn bỏ đi là lý do rủi ro thực tế chỉ còn 77%. Quy tắc `minimum_risk_utilization_after_rounding` 0,6 yêu cầu ít nhất 60%, nên lệnh này đạt.

Phí và trượt giá chiếm khoảng 13% rủi ro, thấp hơn ngưỡng 15% (`max_cost_to_risk`), nên lệnh qua cổng chi phí. Cùng thiết lập nhưng khi ATR chỉ còn 240 (0,4% giá), tỷ lệ này lên khoảng 20% và lệnh bị loại.

## 2. Các tham số nhóm hình học (bạn sẽ thấy nhiều nhất)

| Tham số | Đề xuất | Ý nghĩa đời thường | Đặt thấp hơn thì | Đặt cao hơn thì | Cơ sở |
|---|---|---|---|---|---|
| `geometry_version` | 1 | Công tắc bật hình học đã sửa. Bộ cũ không có khóa này nên hành vi cũ giữ nguyên | không áp dụng | không áp dụng | Cơ chế thiết kế (không phải tham số chiến lược). Nguồn: CONTEXT D-25, do tôi chọn lúc lập kế hoạch và không hỏi riêng bạn. Bạn ratify nó tại 15-08 cùng cả bảng |
| `pivot_left_bars`, `pivot_right_bars` | 3 và 3 | Một đáy chỉ được coi là "đã xác nhận" khi 3 nến trước không thấp hơn nó và 3 nến sau đều cao hơn hẳn nó (bên trái cho phép bằng, bên phải phải cao hơn). Đáy tại nến `t` được xác nhận lúc nến `t+3` đóng cửa. Trên khung 1H, đó là **3 giờ sau khi nến đáy đóng cửa** (4 giờ sau khi nến đáy mở). Cần ít nhất 7 nến. Family C dùng cùng 3/3 trên khung 4H, nên trễ **12 giờ sau khi nến đáy đóng cửa** (16 giờ sau khi nến mở) | Nhiều pivot hơn nhưng nhiễu | Pivot chắc hơn nhưng trễ hơn, giá có thể đã đi khỏi vùng | PLACEHOLDER |
| `swing_lookback` | 20 | Chỉ dùng pivot trong 20 nến gần nhất | Chỉ mức mới | Dùng cả mức cũ, có thể đã hết ý nghĩa | PLACEHOLDER |
| `zone_tolerance_atr` | 0,5 | Nửa độ rộng vùng quanh pivot | Vùng hẹp, ít lệnh khớp hơn | Vùng rộng, stop phải xa hơn | PLACEHOLDER |
| `entry_buffer_atr` | 0,1 | Nới thêm vùng vào lệnh mỗi bên | Khó khớp hơn | Dễ khớp hơn nhưng stop xa hơn | PLACEHOLDER |
| `sl_buffer_atr` | 0,2 | Khoảng đệm giữa mép ngoài vùng và stop | Stop sát, dễ bị quét | Stop xa, khối lượng nhỏ hơn | PLACEHOLDER |
| `min_stop_atr` | 0,5 | Sàn khoảng cách stop. Dưới sàn thì không ra lệnh | Cho phép stop gần hơn | Bắt buộc stop xa hơn | PLACEHOLDER. Việc phải có khóa này là yêu cầu của ROADMAP criterion 1 (stop ở khoảng cách ATR tối thiểu). Giá trị 0,5 chỉ xuất hiện trong CONTEXT D-08 dưới dạng "PROPOSED" (đề xuất, chưa chốt) và không có nguồn spec hay decision nào chốt con số. Việc nó thấp hơn khoảng stop hiện tại của hình học (A 0,8; B 1,2; C 0,7 ATR từ giá đặt lệnh) chỉ là hệ quả quan sát, không phải lý do chọn |
| `minimum_rr` | 2,0 | Tỷ lệ lời/lỗ tối thiểu. Dưới mức này bỏ lệnh | Nhiều lệnh hơn, nhưng lợi thế mỗi lệnh thấp | Ít lệnh hơn | PLACEHOLDER |
| `signal_expiry_hours` | 4 | Tín hiệu còn hiệu lực bao lâu. Quá hạn mà chưa khớp thì hủy | Hủy sớm, ít khớp | Khớp setup đã cũ | PLACEHOLDER. Nguồn gốc thật: file `params/trend-pullback/baseline-v1.toml` ghi "Seed parameter set (Phase 3, plan 03-01)", và audit F-909 liệt nó là giá trị seed/tracer chưa có lý do. Giữ nguyên từ `baseline-v1` đến `v5`. Việc nó bằng một nến 4H chỉ là nhận xét thêm về sau, không phải lý do ban đầu |
| `minimum_risk_utilization_after_rounding` | 0,6 | Sau khi làm tròn khối lượng, rủi ro thực tế phải đạt ít nhất 60% ngân sách, nếu không bỏ lệnh | Chấp nhận lệnh quá nhỏ so với dự định | Bỏ nhiều lệnh hơn | Dựa trên spec: ràng buộc Quantization trong `AGENTS.md` và `docs/trading/RISK_MANAGEMENT.md` mục 11 (hai tài liệu này trích dẫn "D031"; trong `DECISIONS.md`, D031 lại là quy tắc ưu tiên nguồn tài liệu, một sai lệch trích dẫn có sẵn trong repo) |

`min_stop_atr` bắt buộc có trong bộ trend-pullback (ROADMAP criterion 1). Bạn chỉ chọn giá trị, không chọn bỏ nó. Với giá trị 0,5, khoảng cách stop thực tế của Family A khoảng 0,8 ATR tính từ giá đặt lệnh, nên sàn này là lớp dự phòng chứ không phải ràng buộc chính.

## 3. Tham số riêng của Family B (breakout-retest)

Ý tưởng: giá phá vỡ một mức, rồi quay lại thử lại mức đó, và ta vào lệnh theo hướng phá vỡ.

| Tham số | Đề xuất | Ý nghĩa | Ghi chú |
|---|---|---|---|
| `breakout_confirmation_bars` | **1** | Số nến đóng cửa liên tiếp vượt vùng để coi là phá vỡ. Sheet Stage B baseline là B1 (một nến đóng cửa), tức 1. Giá trị 3 trong bộ v5 là cài đặt cũ của code, không khớp dòng nào của sheet (B4 đa nến là 2 nến, không phải 3) | Dựa trên spec (sheet B1). Giữ 3 chỉ khi bạn chọn `edit`, và khi đó phải ghi là độ lệch. Lý do duy nhất để đổi 3 thành 1 là sheet, không phải để có thêm tín hiệu |
| `retest_window_bars` | 5 | Retest phải xảy ra trong 5 nến gần nhất. Plan 15-05 neo retest vào đúng nến đang xét | PLACEHOLDER |
| `retest_depth_atr` | 0,3 | Giá được phép chọc sâu vào vùng retest bao nhiêu ATR | PLACEHOLDER |
| `atr_period` | 14 | Số nến tính ATR | PLACEHOLDER, giá trị chuẩn phổ biến |

Cơ sở của cách đặt stop B (D-23) là chính sheet: `breakout-retest.md` mục 2.2 định nghĩa "vùng bị phá" bằng `resistance_zone_lower_bound` và `resistance_zone_upper_bound`; Q6 ghi stop S3 là "phía bên kia của vùng bị phá"; mục 6 ghi `zone_tolerance_atr` là nửa độ rộng vùng và `sl_buffer_atr` là đệm của S3. Tỷ lệ cạnh qua guard chi phí (93,5% so với 88%) chỉ là bối cảnh quan sát, đã hiển thị khi bạn quyết định, và không phải lý do chọn cách đọc này; quyết định không được tối ưu theo mức sống sót qua guard.

Ví dụ B (từ plan 15-08, ATR 600): stop mới ở 60.180, chi phí khoảng 10% rủi ro, khối lượng 0,002 BTC ở equity 500 và 0,005 BTC ở equity 1.000. Stop cũ chỉ cách khoảng 0,3% giá nên bị chặn vì quá gần. Giá trị tôi đã tính lại bằng số học Decimal: chi phí/rủi ro 0,098; khối lượng 0,002 BTC dùng 69,2% ngân sách rủi ro ở equity 500 (sàn là 60%, nên khá sát) và 0,005 BTC dùng 86,5% ở equity 1.000. Stop cách giá đặt lệnh 1,2 ATR, cách cạnh bất lợi 1,3 ATR. Plan không nêu swing high; tôi suy ra 60.600 vì đó là giá trị cho đúng stop 60.180. **Lưu ý ATR:** ATR ở đây là ATR14 trên chuỗi nến 1H (giống mọi ví dụ). Ví dụ này dùng ATR 600 (khoảng 0,99% giá), khác tỷ lệ ATR/giá của ví dụ A (400, 0,67%), nên B và C không cùng điều kiện với A. Ở ATR/giá thấp hơn, chi phí/rủi ro vượt 15% và lệnh bị loại: B chỉ qua guard khi ATR/giá từ khoảng 0,61% trở lên. Đây là hệ quả quan sát được, không phải lý do để chọn hay chỉnh tham số.

## 4. Tham số riêng của Family C (range-mr)

Ý tưởng: giá đi ngang giữa hai mức, mua gần đáy range và chốt gần giữa.

| Tham số | Đề xuất | Ý nghĩa | Ghi chú |
|---|---|---|---|
| `tp_mode` | T_MID | Chốt ở giữa range thay vì mép đối diện | STRUCTURAL: đúng sheet Stage C |
| `regime_filter_lookback` | 50 | Quét 50 nến 4H (khoảng 8 ngày) để tìm 2 đỉnh và 2 đáy pivot gần nhất, nhằm biết thị trường có đang đi ngang hay không | PLACEHOLDER |
| `zone_min_touches` | 2 | Mép range cần chạm ít nhất 2 lần | PLACEHOLDER |
| `zone_aging_bars` | 50 | Vùng bị bỏ nếu quá 50 nến chưa được chạm | PLACEHOLDER |
| `range_break_buffer_atr` | 0,2 | Giá đóng ngoài range quá mức này thì range bị coi là phá vỡ | PLACEHOLDER |
| `touch_tolerance_atr` | 0,3 | Sai số khi tính một lần "chạm" mép | PLACEHOLDER |

Ví dụ C (từ plan 15-08, range 59.000 đến 61.000, ATR 600): stop mới 58.580, target giữa range 60.000, tỷ lệ lời/lỗ khoảng 2,38, khối lượng 0,004 BTC ở equity 500 và 0,008 BTC ở equity 1.000. Với target ở giữa range, tỷ lệ lời/lỗ thấp hơn nên một số setup sẽ bị `minimum_rr` loại. Census của plan 15-07 sẽ đếm cụ thể. Giá trị tôi đã tính lại: chi phí/rủi ro **0,1464** (sát ngưỡng 15%; đây là hệ quả quan sát của ví dụ này, không dùng làm lý do chọn tham số); khối lượng 0,004 BTC dùng 90,0% ngân sách ở equity 500 và 0,008 BTC dùng 90,0% ở equity 1.000; stop cách giá đặt lệnh 0,7 ATR, cách cạnh bất lợi 0,8 ATR. **Lưu ý ATR:** ATR14 trên chuỗi nến 1H, ATR 600 (khoảng 1,02% giá), không cùng tỷ lệ ATR/giá với ví dụ A. Với ATR/giá thấp hơn nhiều chi phí/rủi ro vượt 15% và lệnh bị loại. Regime của Family C dùng pivot trên khung **4H** (R=3 nghĩa là trễ 12 giờ kể từ lúc nến pivot đóng cửa) và không dùng ATR.

## 5. Tham số danh mục và lỗ trong ngày (giữ nguyên từ bản trước)

| Tham số | Giá trị | Ở equity 500 | Ở equity 1.000 | Cơ sở |
|---|---|---|---|---|
| `risk_rate` | 0,5% | 2,5 USDT mỗi lệnh | 5 USDT mỗi lệnh | Dựa trên spec: `RISK_MANAGEMENT.md` mục 1 |
| `max_open_positions` | 2 | tối đa 2 vị thế mở | như vậy | PLACEHOLDER. `RISK_MANAGEMENT.md` mục 4 gọi nó là "Initial research placeholders... to be validated by research" |
| `max_aggregate_open_risk` | 1,0% | tổng rủi ro đang mở tối đa 5 USDT | 10 USDT | PLACEHOLDER (như trên) |
| `cluster_cap` | 0,5% | 2,5 USDT | 5 USDT | PLACEHOLDER. `RISK_MANAGEMENT.md` mục 4 ghi giá trị này là `TBD` |
| `daily_loss_warning_threshold` | 0,5% | cảnh báo khi lỗ 2,5 USDT trong ngày | 5 USDT | DECISION D033 |
| `daily_loss_stop_threshold` | 1,0% | dừng vào lệnh mới khi lỗ 5 USDT trong ngày | 10 USDT | DECISION D033 |

## 6. Tham số chi phí (không đổi từ Phase 12)

Bốn khóa sau không có giá trị nào được spec hay decision ấn định, nên đều là PLACEHOLDER (lấy từ Phase 5 và 6): `funding_treatment` ADDITIVE, `slippage_model` FIXED_BPS, `spread_fill_assumptions` FULL_FILL, `constraint_snapshot_ttl_seconds` 3600. `RESEARCH_PROTOCOL` mục 2 và `RISK_MANAGEMENT` mục 12 chỉ yêu cầu phải có các trường này.

Phí vào và ra 0,05% mỗi chiều (taker), trượt giá vào 0,01%, trượt giá khi stop khớp 0,03%. Hai cổng bảo vệ: stop gần hơn 0,3% giá bị loại (`min_stop_distance_rate`), và chi phí quá 15% rủi ro bị loại (`max_cost_to_risk`). Phase 15 không sửa các số này. Nguồn: phí taker 0,05% theo D036; `partial_fill_fraction` 1,0 theo D038; trigger theo mark price D037; `exit_slippage_rate` 0,0003, `min_stop_distance_rate` 0,003 và `max_cost_to_risk` 0,15 theo D046 (giá trị mặc định của Phase 12, mục 6 của D046 được operator ratify ngày 2026-10-04). `expected_slippage` 0,0001 cũng thuộc D046. Vai trò của hai cổng chi phí là COST_GUARD; nguồn quyết định là D046.

## 7. "Cơ sở" nghĩa là gì và vì sao nó quan trọng

| Nhãn | Nghĩa |
|---|---|
| STRUCTURAL | Giá trị suy ra từ hình học hoặc sheet, ví dụ stop gần 0,8 ATR theo cấu trúc |
| COST_GUARD | Suy ra từ ngưỡng chi phí |
| DECISION | Từ một quyết định đã ghi trong DECISIONS |
| EXPERIMENT | Có bằng chứng từ thí nghiệm. Hiện chưa giá trị nào có |
| PLACEHOLDER | Giả định, chưa có bằng chứng |

Hệ thống từ chối đóng băng một bộ cho paper nếu còn giá trị `PLACEHOLDER`. Hầu hết số đề xuất đang là `PLACEHOLDER`, nên bộ v6 là bộ để **nghiên cứu**, chưa phải bộ để chạy paper. Đây là hành vi đúng, không phải lỗi.

## 8. Cách trả lời

- Không thấy con số nào vô lý: gõ `ratify`.
- Muốn đổi một số: gõ `edit`, rồi mỗi dòng một thay đổi theo dạng `trend-pullback: min_stop_atr = 0.8 (STRUCTURAL, lý do)`.
- Chưa sẵn sàng: gõ `stop`. Không trả lời cũng được tính là `stop`.

Quy tắc vàng: **không chỉnh số vì "muốn nhiều lệnh hơn" hay "muốn lãi hơn".** Nếu chỉnh theo kết quả backtest, nghiên cứu sẽ bị overfit và mất giá trị (D-17).

## 9. Lưu ý về độ chắc của các con số

- Ví dụ Family A ở mục 1 do tôi tính lại bằng tay và khớp với kết quả nghiên cứu.
- Ví dụ B và C lấy từ plan 15-08, và tôi đã tái tạo lại cả hai bằng số học Decimal (không dùng dữ liệu hay backtest): mọi con số khớp. Plan 15-07 sẽ tính lại trên dữ liệu thật trước khi bạn duyệt. Khi hai nguồn khác nhau, hãy ưu tiên con số của plan 15-07.
- Giá trị `swing_lookback` 20, `zone_tolerance_atr` 0,5, `entry_buffer_atr` 0,1, `sl_buffer_atr` 0,2, `minimum_rr` 2,0 và `signal_expiry_hours` 4 có từ ngày 2026-09-22 (Phase 3), trước commit simulator đầu tiên (2026-09-26), và không đổi từ `baseline-v1` đến `v5`. Chúng không được chọn theo kết quả backtest, nhưng cũng chưa có lý do thực nghiệm.
- Số đếm setup trên dữ liệu thật (census) chưa có. Chúng sẽ có sau khi plan 15-07 chạy.
