# Trading Strategy Research

> **Status:** Research draft v0.1  
> **Date:** 2026-09-19  
> **Purpose:** Tài liệu nghiên cứu trước khi khóa Trading Strategy V1 và viết code giao dịch.

---

## 0. Mục tiêu của tài liệu

Tài liệu này trả lời câu hỏi:

> **Với một người đi làm full-time, vốn khởi điểm khoảng 500–1,000 USD, thời gian theo dõi thị trường hạn chế và muốn dùng Binance Futures, chiến thuật nào có thể được mô tả hoàn toàn bằng rule, backtest được và phù hợp để giao dịch theo mô hình human-approval + automated execution?**

Tài liệu **không** cố chứng minh rằng một chiến thuật nào đó sẽ tạo lợi nhuận ổn định.

Mục tiêu của research là:

1. Học và chuẩn hóa các khái niệm trading cần thiết.
2. Chuyển các khái niệm định tính thành rule định lượng.
3. So sánh một số strategy candidate bằng cùng một framework backtest.
4. Loại bỏ strategy/parameter chỉ có vẻ tốt do overfitting.
5. Chỉ sau khi có bằng chứng đủ tốt mới khóa `TRADING_STRATEGY_SPEC.md`.

---

# 1. User / Product Constraints

## 1.1. Bối cảnh

- Người dùng đi làm full-time.
- Không thể theo dõi chart liên tục.
- Có thể kiểm tra điện thoại vào một số thời điểm nhưng không thể đảm bảo phản hồi trong vài phút.
- Muốn có thêm thu nhập, nhưng không đặt mục tiêu bắt buộc phải có giao dịch hoặc lợi nhuận mỗi ngày.
- Vốn nghiên cứu/giao dịch ban đầu dự kiến: **500–1,000 USD**.
- Giao dịch: Binance Futures.

## 1.2. Execution model mục tiêu

Không auto-trade hoàn toàn ở giai đoạn đầu.

```text
Market data
    -> Strategy
    -> Trade plan
    -> Telegram alert
    -> Human approve / skip
    -> Order manager
    -> Binance
```

Sau khi `APPROVE`, hệ thống có thể tự đặt và quản lý:

- Entry order.
- Stop Loss.
- Take Profit.
- Expiry / cancel pending order.
- Theo dõi fill/position/order events.

## 1.3. AI policy

**Không sử dụng AI/LLM trong trading decision core.**

AI không được quyết định:

- Long / Short.
- Entry.
- Stop Loss.
- Take Profit.
- Position size.
- Strategy parameter.
- Có/không được giao dịch trong một tình huống cụ thể.

Core strategy phải deterministic:

```text
Same input data + same strategy version
        = same output
```

AI/LLM nếu được dùng sau này chỉ dành cho code assistance, documentation hoặc diễn giải signal, không tham gia quyết định giao dịch.

---

# 2. Nguyên tắc nghiên cứu

## 2.1. Không bắt đầu bằng “indicator soup”

Không mặc định phải sử dụng càng nhiều indicator càng tốt.

Một strategy candidate phải có logic kinh tế/thị trường hoặc market-structure rõ ràng trước khi thêm indicator.

## 2.2. Mọi khái niệm phải chuyển được thành rule

Không chấp nhận định nghĩa kiểu:

> “Resistance là vùng khá mạnh.”

Phải chuyển thành dạng máy tính có thể kiểm tra, ví dụ:

> “Một resistance zone được tạo khi có ít nhất N swing highs trong khoảng giá tối đa X ATR trong lookback Y.”

Các giá trị N/X/Y ban đầu là **research parameters**, không phải chân lý.

## 2.3. Strategy phải có thể backtest

Mỗi strategy cần xác định rõ:

- Input data.
- Timeframe.
- Entry condition.
- Entry price.
- Stop Loss.
- Take Profit.
- Invalidation.
- Expiry.
- Position sizing.
- Fees.
- Funding.
- Slippage.
- Xử lý partial fill.
- Xử lý trường hợp một candle chạm cả SL và TP.

TradingView định nghĩa backtesting là tái tạo cách strategy hoạt động trên dữ liệu lịch sử; forward testing là kiểm tra strategy trong dữ liệu realtime. Đây là hai giai đoạn cần tách biệt trong nghiên cứu. [TradingView – Strategies, backtesting and forward testing](https://www.tradingview.com/support/solutions/43000562362-what-are-strategies-backtesting-and-forward-testing/)

## 2.4. Không tối ưu trực tiếp trên toàn bộ dataset

Cần tách ít nhất:

```text
Development / Research
        -> Validation
        -> Forward / Out-of-sample
```

hoặc dùng walk-forward validation.

Mục tiêu là tránh kết luận:

> “Parameter này đẹp nhất trên dữ liệu quá khứ”

rồi coi nó là bằng chứng rằng parameter đó sẽ tiếp tục hoạt động.

---

# 3. Những gì chúng ta đã chốt tạm thời

| Thành phần | Quyết định tạm thời |
|---|---|
| Data source chính | Binance Futures |
| TradingView | Research/visual verification/optional webhook adapter |
| AI trading decision | Không dùng |
| Main timeframe | 4H + 1H |
| 15M | Optional, không bắt buộc ở V1 |
| 5M | Không dùng làm timing bắt buộc |
| Execution | Human approval -> automated order management |
| Entry | Trade plan sinh từ strategy, không AI |
| SL | Structure/volatility based, cần research cụ thể |
| TP | Structure/R-multiple based, cần research cụ thể |
| Risk baseline | 0.5% equity/trade chỉ là giả thuyết ban đầu để test |
| Universe ban đầu | BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT |
| Order model V1 | Ưu tiên LIMIT zone + protective SL/TP |
| Signal | Có expiry + invalidation |

**Lưu ý:** Các giá trị/choices ở trên chưa phải trading strategy đã được xác nhận.

---

# 4. Kiến thức nền cần chuẩn hóa

Phần này dành cho người xây system nhưng chưa có nền tảng trading sâu.

## 4.1. Market structure

Cần hiểu các khái niệm:

- Swing High.
- Swing Low.
- Higher High (HH).
- Higher Low (HL).
- Lower High (LH).
- Lower Low (LL).
- Trend.
- Range.
- Breakout.
- Retest.
- Failed breakout.

### Câu hỏi cần định nghĩa bằng code

1. Swing high được phát hiện bằng bao nhiêu candle trái/phải?
2. Khi nào swing được xem là đã “confirmed”?
3. Có dùng pivot chưa đóng không?
4. Có chấp nhận repaint không?
5. Trend 4H được định nghĩa bằng structure, MA, hay cả hai?

### Baseline research idea

Có thể bắt đầu bằng pivot-based market structure vì dễ deterministic hơn price-action “bằng mắt”.

---

## 4.2. Support / Resistance

Support/resistance không nên được hiểu như một đường giá duy nhất; strategy cần quyết định có dùng zone.

Một research implementation có thể thử:

```text
Swing highs/lows
       +
price tolerance based on ATR
       ↓
Support / Resistance zone
```

Các public Pine scripts trên TradingView cũng cho thấy cách tiếp cận phổ biến là phát hiện các swing tương đồng trong một tolerance điều chỉnh theo volatility rồi hình thành zone; sau đó theo dõi breakout/retest của zone. Đây là **một ví dụ về cách định lượng**, không phải bằng chứng rằng method đó có lợi nhuận. [TradingView open-source example: Support Resistance with Breaks and Retests](https://www.tradingview.com/script/Xeeko6TV-Support-Resistance-with-Breaks-and-Retests/) và một implementation khác mô tả việc xác nhận zone bằng nhiều swing trong volatility-adjusted tolerance. [TradingView open-source example](https://www.tradingview.com/script/X81PJSiH-Support-and-Resistance-Retest-Breakout-Signals-AlgoAlpha/)

### Các biến cần research

- Lookback.
- Minimum touches.
- Price tolerance.
- ATR multiplier cho zone width.
- Zone aging.
- Khi nào zone mất hiệu lực.
- Có ưu tiên zone có volume cao hơn không.

---

## 4.3. Breakout

Khái niệm đơn giản:

> Giá vượt qua một vùng/level mà trước đó được xem là support/resistance.

Nhưng `breakout` có nhiều cách định nghĩa.

### Candidate definitions

**B1 — Close breakout**

```text
close > resistance upper bound
```

**B2 — Wick + close confirmation**

```text
high > resistance
AND close > resistance
```

**B3 — Volume-confirmed breakout**

```text
close > resistance
AND volume / avgVolume > threshold
```

**B4 — Multi-bar confirmation**

```text
2 consecutive closes > resistance
```

TradingView có các strategy breakout rất đơn giản dựa trên highest/lowest value của một lookback window, cho thấy breakout có thể được định nghĩa hoàn toàn bằng rule định lượng. [TradingView – Channel BreakOut Strategy](https://www.tradingview.com/support/solutions/43000599828-channel-breakout-strategy/)

### Research question

Không được giả định breakout nào “tốt hơn”. Phải test các định nghĩa với cùng cost model.

---

## 4.4. Retest

Một cách định nghĩa cơ bản:

```text
Resistance bị breakout
        ↓
Price quay lại vùng resistance cũ
        ↓
Không đóng cửa xác nhận breakdown sâu
        ↓
Reclaim / rejection
        ↓
Retest confirmed
```

Đối với short, đảo chiều logic:

```text
Support bị breakdown
        ↓
Price quay lại support cũ
        ↓
Rejection từ phía dưới
        ↓
Retest confirmed
```

Các public TradingView scripts minh họa nhiều cách định nghĩa retest; điểm cần lưu ý là “retest” không phải một khái niệm duy nhất và một số implementation có thể repaint khi đang chờ retest, vì vậy system của chúng ta phải dùng rule closed-bar rõ ràng. [TradingView open-source example](https://www.tradingview.com/script/Xeeko6TV-Support-Resistance-with-Breaks-and-Retests/)

### Research parameters

- Maximum bars after breakout để retest còn hợp lệ.
- Maximum distance từ zone.
- Retest phải touch hay close vào zone?
- Có cần rejection candle không?
- Có cần volume confirmation không?
- Có cần cấu trúc 15M xác nhận không?

---

# 5. Candidate Strategy Families

Mục tiêu ban đầu là nghiên cứu 2–3 family, không build 10 strategy.

## 5.1. Candidate A — Trend Pullback

### Ý tưởng

Giao dịch theo xu hướng lớn sau khi giá hồi về vùng structure/MA/zone.

### Hypothesis

Nếu thị trường đang có xu hướng, pullback về vùng hỗ trợ/kháng cự cũ có thể tạo điểm vào có stop tương đối rõ.

### Khung dự kiến

```text
4H -> regime
1H -> pullback/setup
```

### Các phiên bản cần test

A1. Structure-only.

A2. Structure + EMA.

A3. Structure + ATR.

A4. Structure + volume confirmation.

---

## 5.2. Candidate B — Breakout + Retest

### Ý tưởng

```text
Consolidation / S-R zone
        ↓
Breakout
        ↓
Retest
        ↓
Continuation
```

### Hypothesis

Một breakout sau đó retest thành công có thể giảm một phần false breakout so với việc vào ngay khi giá vừa phá level.

### Baseline candidate

```text
4H -> direction/regime
1H -> zone + breakout + retest
```

### Điều phải test

- Breakout bằng wick hay close.
- Volume confirmation.
- Retest depth.
- Retest timeframe.
- Entry tại zone hay sau confirmation candle.
- SL bên kia zone hay bên kia swing.
- TP fixed-R hay structure-based.

---

## 5.3. Candidate C — Range Mean Reversion

### Ý tưởng

Khi market không trend mạnh:

```text
Range high -> SHORT
Range low  -> LONG
```

với stop ngoài range và TP về trung tâm/opposite boundary.

### Lý do cần nghiên cứu

Nếu chỉ nghiên cứu trend-following, hệ thống có thể tạo ít signal hoặc hoạt động kém trong thị trường đi ngang. Range strategy có thể là candidate riêng thay vì cố nhồi thêm filter vào trend strategy.

### Rủi ro đặc biệt

Range strategy dễ bị phá trend. Cần regime filter rõ.

---

# 6. Entry / Stop Loss / Take Profit — Research Framework

## 6.1. Entry zone

Không dùng “current market price” làm entry mặc định.

Candidate methods:

### E1 — Level retest

```text
Entry = broken level / zone
```

### E2 — Zone + ATR buffer

```text
entry zone = structure level ± k * ATR
```

### E3 — Confirmation close

```text
Entry = close của confirmation candle
```

### E4 — Hybrid

```text
LIMIT zone
+
optional confirmation condition
```

### Research metric

Không chỉ đo win rate; cần đo:

- Fill rate.
- Missed-trade rate.
- Average entry slippage.
- MFE sau khi chạm zone.
- MAE trước khi đạt TP.

---

## 6.2. Stop Loss

SL phải có nghĩa là:

> “Nếu giá chạm mức này, giả thuyết trade đã sai hoặc structure không còn hợp lệ.”

Không đặt SL chỉ vì muốn cố định X%.

### Candidate methods

**S1 — Swing based**

```text
Long: dưới swing low
Short: trên swing high
```

**S2 — Structure + ATR buffer**

```text
Long SL = swingLow - k*ATR
Short SL = swingHigh + k*ATR
```

**S3 — Zone invalidation**

```text
SL = phía bên kia của support/resistance zone
```

CME mô tả một nguyên tắc quản trị rủi ro quan trọng: trước khi tính position size phải xác định stop hợp lý; stop nên ở mức có ý nghĩa với trade thesis, sau đó kích thước vị thế được tính từ số tiền/tỷ lệ tài khoản chấp nhận rủi ro. [CME – Proper Position Size](https://www.cmegroup.com/education/courses/trade-and-risk-management/proper-position-size)

---

## 6.3. Take Profit

### Candidate methods

**T1 — Fixed R**

```text
TP = Entry + R * riskDistance
```

Ví dụ 2R.

**T2 — Next structure**

```text
TP = resistance/support tiếp theo
```

**T3 — Hybrid**

```text
TP1 = nearest valid structure
TP2 = fixed R hoặc next structure
```

### Constraint cần test

Nếu target khả dụng nhỏ hơn minimum R:R thì:

```text
NO TRADE
```

Không được cố giảm SL/đẩy TP một cách tùy tiện để “làm đẹp” R:R.

---

# 7. Position Sizing & Risk

## 7.1. Baseline research assumption

```text
Risk per trade = 0.5% equity
```

Đây chỉ là baseline để backtest/paper trade, không phải cam kết hay khuyến nghị mức rủi ro cá nhân.

Với account `A` và risk fraction `r`:

```text
risk_budget = A * r
```

Nếu risk per unit là:

```text
abs(entry - stop)
```

thì quantity cơ bản:

```text
quantity = risk_budget / abs(entry - stop)
```

Sau đó phải điều chỉnh theo:

- Contract specification.
- Tick size / step size.
- Fees.
- Estimated slippage.
- Funding.
- Margin requirements.
- Maximum notional.
- Portfolio exposure.

CME cũng nhấn mạnh rằng position size nên được xác định từ stop và số tiền/tỷ lệ tài khoản muốn mạo hiểm, thay vì chọn size trước rồi mới tìm stop. [CME – Proper Position Size](https://www.cmegroup.com/education/courses/trade-and-risk-management/proper-position-size)

---

## 7.2. Portfolio risk

Không coi:

```text
BTC LONG 0.5%
ETH LONG 0.5%
SOL LONG 0.5%
```

là ba risk hoàn toàn độc lập.

V1 có thể dùng các giới hạn đơn giản:

- Max total open risk.
- Max concurrent positions.
- Max correlated positions.

Correlation model chi tiết có thể làm ở phase sau.

---

# 8. Data Requirements

## 8.1. Canonical data source

**Binance Futures** là source of truth cho live system và backtest execution assumptions.

TradingView chỉ là:

- Chart/research tool.
- Pine implementation để cross-check strategy.
- Optional webhook adapter.

TradingView hỗ trợ strategy backtesting/forward testing và strategy alerts, nên có thể dùng làm công cụ kiểm chứng trực quan và so sánh implementation. [TradingView – Backtesting and forward testing](https://www.tradingview.com/support/solutions/43000562362-what-are-strategies-backtesting-and-forward-testing/) [TradingView – Strategy Alerts](https://www.tradingview.com/support/solutions/43000481368-strategy-alerts/)

## 8.2. Core data

### Candles

- 1m execution simulation.
- 1H strategy.
- 4H regime.

Binance Futures API cung cấp kline history với các interval gồm 1m, 5m, 15m, 1h, 4h và các interval khác. [Binance Futures market data](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Kline-Candlestick-Data)

### Volume

Cần lưu volume/taker-buy related fields nếu có thể.

### Funding

Funding history có thể được lấy qua Binance API với start/end time và pagination; do đó funding có thể được dùng như một feature phụ trong backtest nếu dataset được đồng bộ thời gian. [Binance – Get Funding Rate History](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History)

### Open Interest

Binance cung cấp current OI và OI historical statistics. Historical OI statistics trên endpoint này hiện chỉ có dữ liệu trong 30 ngày gần nhất, vì vậy nếu OI muốn dùng cho nghiên cứu dài hạn thì phải bắt đầu tự thu thập snapshot OI càng sớm càng tốt. [Binance – Open Interest Statistics](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics)

**Research decision:** OI không phải điều kiện bắt buộc của core strategy V1; OI là experimental feature cho đến khi có đủ dataset tự thu thập.

---

# 9. Realtime / Candle Rules

## 9.1. No-repaint baseline

Core signal phải dựa trên **closed candles**.

Không dùng giá trị cuối cùng của một candle đang hình thành để tạo tín hiệu backtest “đã biết trước”.

TradingView public implementations cũng cho thấy sự khác biệt giữa tín hiệu khi candle đang chạy và bar-confirmed signals; nếu mục tiêu là tránh repaint thì system cần xác định rõ lúc nào bar được coi là confirmed. [TradingView open-source example](https://vn.tradingview.com/script/Xeeko6TV-Support-Resistance-with-Breaks-and-Retests/)

## 9.2. Warm-up

Indicator cần historical warm-up trước khi signal engine bắt đầu hoạt động.

Ví dụ EMA200 trên 4H không được coi là hợp lệ ngay sau khi service khởi động chỉ vì đã có một vài candle.

## 9.3. Time standard

- DB: UTC.
- UI/Telegram: convert sang Asia/Ho_Chi_Minh (UTC+7) khi cần.
- Windows runtime: cần cài thêm `tzdata` wheel vì OS không có zoneinfo database; dùng `zoneinfo.ZoneInfo("Asia/Ho_Chi_Minh")` thay vì hard-code UTC+7 offset.

---

# 10. Backtest Execution Model

Đây là phần bắt buộc để tránh backtest ảo.

## 10.1. Strategy timeframe vs execution timeframe

Đề xuất:

```text
Strategy decision: 1H / 4H
Execution simulation: 1m
```

Lý do: nếu một 1H candle vừa chạm TP vừa chạm SL, OHLC của 1H không cho biết thứ tự.

Execution ở 1m cho phép mô phỏng thứ tự hợp lý hơn.

## 10.2. Intrabar ambiguity

Nếu ngay cả 1m vẫn chạm cả SL và TP trong cùng candle, cần deterministic tie-breaking policy.

Không được mặc định “TP trước” chỉ vì muốn kết quả đẹp.

Candidate policies:

- Conservative: assume adverse level hit first.
- Next finer timeframe nếu data có.
- Mark as ambiguous và loại riêng khỏi metric chính.

Policy phải được cố định trước khi chạy evaluation chính.

## 10.3. Fees

Backtest phải trừ:

- Entry fee.
- Exit fee.
- Partial-fill fee nếu có.

## 10.4. Funding

Nếu position giữ qua funding event, phải tính funding vào PnL.

## 10.5. Slippage

Cần ít nhất một mô hình đơn giản:

```text
effective entry = intended entry + slippage
```

và tương ứng cho exit.

Sau live/paper stage, actual execution data sẽ được dùng để calibrate model.

---

# 11. Metrics

Không dùng win rate làm metric duy nhất.

## 11.1. Core metrics

- Number of trades.
- Win rate.
- Average winner (R).
- Average loser (R).
- Expectancy per trade (R).
- Profit factor.
- Max drawdown.
- Average trade duration.
- Median trade duration.

## 11.2. Execution metrics

- Fill rate.
- Missed entry rate.
- Partial fill rate.
- Entry slippage.
- Exit slippage.
- Expired-order rate.

## 11.3. Opportunity metrics

- MFE.
- MAE.
- Time to MFE.
- Time to MAE.
- Return after signal if user skipped.

---

# 12. System Performance vs User Performance

Do selection bias không làm hỏng journal; nó làm cho **một metric duy nhất trở nên dễ gây hiểu nhầm**.

Mỗi signal cần có trạng thái theo canonical `SignalStatus` (`GLOSSARY.md` §2):

```text
DETECTED
NOTIFIED
VIEWED
APPROVED
SKIPPED_USER
SKIPPED_BUSY
EXPIRED
INVALIDATED
```

Sau khi signal/plan được approve, order và trade đi theo canonical `OrderStatus` (`GLOSSARY.md` §5) và `TradeStatus` (`GLOSSARY.md` §6):

```text
OrderStatus: PLANNED, SUBMITTING, NEW, PARTIALLY_FILLED, FILLED, CANCELED, EXPIRED, REJECTED, UNKNOWN
TradeStatus: PENDING, OPEN, CLOSED, ABORTED, UNKNOWN
```

## Hai bảng performance

### System Performance

> Nếu toàn bộ signal được thực hiện theo rule.

### User Executed Performance

> Những signal mà người dùng thực sự approve.

Ngoài ra cần lưu:

```text
SignalTime
ApproveTime
OrderTime
FillTime
```

để đo impact của việc phản ứng chậm.

---

# 13. Signal validity

Mỗi setup phải có:

### Time expiry

```text
valid_until
```

### Price/structure invalidation

Ví dụ:

```text
1H close below invalidation level
=> setup invalid
```

### Optional volatility invalidation

Nếu volatility vượt một ngưỡng đã được backtest xác định thì setup có thể bị hủy.

Không tự suy luận:

```text
high ATR = news
```

trừ khi hệ thống thực sự có event/news dataset.

---

# 14. Candidate Research Plan

## Stage A — Baseline trend strategy

Mục tiêu: có một benchmark đơn giản.

Ví dụ:

```text
4H trend
+
1H pullback
+
structure entry
+
structure SL
+
2R TP
```

## Stage B — Breakout/retest

So sánh:

- Close breakout.
- Breakout + volume.
- Retest zone.
- Retest confirmation.

## Stage C — Range strategy

Chỉ nghiên cứu nếu regime filter và dataset cho thấy market có những period phù hợp.

## Stage D — Context features

Chỉ sau khi core strategy có baseline:

- Funding.
- OI.
- Taker flow.
- Volatility regime.
- Session/time-of-day.

Mục tiêu là kiểm tra feature có **incremental value** hay không.

---

# 15. Research Questions

Các câu hỏi phải được trả lời trước khi khóa Strategy V1.

## Q1. Trend definition

4H bullish/bearish được xác định bằng:

- Structure?
- EMA?
- Structure + EMA?

## Q2. Support/resistance definition

Level hay zone?

Bao nhiêu touches?

Tolerance tính theo:

- % price?
- ATR?

## Q3. Breakout definition

- High/low vượt level?
- Candle close vượt level?
- Có cần volume?
- Có cần 2 candle xác nhận?

## Q4. Retest definition

- Price touch zone?
- Close vào zone?
- Rejection candle?
- Maximum số bar sau breakout?

## Q5. Entry

- Limit tại zone?
- Confirmation close?
- Hybrid?

## Q6. Stop

- Swing low/high?
- Structure zone?
- ATR buffer bao nhiêu?

## Q7. TP

- Fixed R?
- Next structure?
- Hybrid?

## Q8. Minimum R:R

Có nên reject setup nếu target structure không cho minimum R:R?

## Q9. Regime filter

Khi nào hệ thống trả về `NO_TRADE`?

## Q10. Session effect

Performance có khác đáng kể giữa:

- Asia.
- London.
- New York.
- Weekend.

không?

## Q11. Asset effect

Strategy có hoạt động giống nhau trên:

- BTC.
- ETH.
- BNB.
- SOL.
- XRP.

hay chỉ tốt ở một subset?

## Q12. OI/Funding

Có thực sự cải thiện expectancy sau cost hay chỉ làm strategy phức tạp hơn?

---

# 16. Anti-Overfitting Rules

Đây là một trong những phần quan trọng nhất.

## Rule 1 — Parameter changes phải có lý do

Không thay parameter chỉ vì backtest xấu.

## Rule 2 — Không chọn “top parameter” duy nhất

Nếu:

```text
ATR buffer 0.20 -> tốt
ATR buffer 0.21 -> xấu
ATR buffer 0.19 -> xấu
```

thì đây là dấu hiệu đáng nghi.

Một parameter tốt hơn khi **một vùng giá trị lân cận cũng hoạt động tương đối ổn định**.

## Rule 3 — Out-of-sample bắt buộc

Không đánh giá strategy chỉ trên dataset dùng để phát triển.

## Rule 4 — Tính tất cả costs

Không được chọn strategy trước rồi mới thêm fee/funding.

## Rule 5 — Không target daily PnL

Không thêm trade chỉ vì “3 ngày chưa có signal”.

## Rule 6 — Không optimize trên skipped trades

Phải giữ riêng performance của system và phần trade người dùng thực sự thực hiện.

---

# 17. Research Acceptance Criteria — Draft

Chưa chốt số cụ thể.

Một candidate strategy chỉ được đưa vào `TRADING_STRATEGY_SPEC.md` nếu thỏa các nhóm điều kiện:

### Statistical

- Có đủ sample size.
- Expectancy dương sau cost trong development và validation.
- Profit factor không chỉ đến từ một vài trade lớn.
- Drawdown nằm trong phạm vi chấp nhận được.

### Robustness

- Không phụ thuộc vào một parameter quá chính xác.
- Không phụ thuộc vào một coin duy nhất.
- Không phụ thuộc vào một giai đoạn duy nhất.
- Không suy giảm hoàn toàn ở out-of-sample.

### Operational

- Có thể chạy với closed-bar rules.
- Không cần ngồi nhìn màn hình liên tục.
- Entry có thể chờ hợp lý.
- SL/TP có thể tự quản lý sau khi approve.
- Có thể audit vì sao signal được tạo.

### User fit

- Phù hợp với vốn 500–1,000 USD khi dùng position sizing theo risk.
- Không yêu cầu hàng chục giao dịch mỗi ngày.
- Không yêu cầu prediction AI.

---

# 18. TradingView Role

TradingView không phải source of truth của live execution.

## Có thể dùng TradingView cho:

1. Visual inspection.
2. Pine Strategy prototype.
3. Strategy Tester.
4. Cross-check với Python implementation.
5. Optional webhook adapter.

TradingView cho phép strategy alerts chạy bản copy của strategy trên server; alerts realtime có thể phát sinh khi strategy order được broker emulator thực hiện. [TradingView – Strategy Alerts](https://www.tradingview.com/support/solutions/43000481368-strategy-alerts/)

Điều này hữu ích cho verification, nhưng không thay thế canonical Binance data cho hệ thống giao dịch.

---

# 19. Binance Role

Binance là canonical source cho:

- Live candles.
- Market data.
- Funding.
- Open interest collection.
- Orders.
- Positions.
- Fill status.

Binance khuyến nghị ưu tiên user-data WebSocket khi theo dõi order/position vì REST có thể có query delay trong điều kiện biến động; user-data stream cũng có yêu cầu keepalive/reconnect cần đưa vào production design. [Binance – User Data Streams](https://developers.binance.com/en/docs/products/derivatives-trading-coin-futures/user-data-streams)

---

# 20. Data Collection to Start Immediately

Ngay cả trước khi Strategy V1 được chọn, nên bắt đầu lưu raw data để không mất thời gian lịch sử.

## Collector

```text
BTCUSDT
ETHUSDT
BNBUSDT
SOLUSDT
XRPUSDT
```

## Data

- 1m OHLCV.
- 1H/4H có thể derive từ 1m hoặc lưu thêm trực tiếp.
- Funding snapshots/history.
- OI snapshots.
- Mark price nếu cần.

## OI collector

Đề xuất:

```text
Every 5 minutes
```

và lưu:

```text
Symbol
TimestampUtc
OpenInterest
OpenInterestValue (nếu có)
```

Lý do: historical OI endpoint hiện chỉ có khoảng dữ liệu mới nhất 30 ngày, nên dataset OI do chính hệ thống thu thập sẽ trở thành tài sản nghiên cứu dài hạn. [Binance – Open Interest Statistics](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics)

---

# 21. Initial Strategy Research Backlog

## Priority P0

- [ ] Học và định nghĩa swing high/low.
- [ ] Chọn pivot confirmation rule.
- [ ] Định nghĩa support/resistance zone.
- [ ] Định nghĩa breakout.
- [ ] Định nghĩa retest.
- [ ] Định nghĩa entry.
- [ ] Định nghĩa stop.
- [ ] Định nghĩa target.
- [ ] Chốt execution simulation.

## Priority P1

- [ ] Implement Candidate A.
- [ ] Implement Candidate B.
- [ ] Backtest cùng cost model.
- [ ] So sánh out-of-sample.
- [ ] Kiểm tra MFE/MAE.

## Priority P2

- [ ] Range strategy.
- [ ] Funding feature.
- [ ] OI feature.
- [ ] Session analysis.
- [ ] Portfolio correlation.

---

# 22. Decision Log

## Current decision: không dùng AI cho prediction

**Reason:**

- Deterministic strategy dễ audit.
- Dễ backtest.
- Không phụ thuộc LLM context freshness.
- Không để mô hình ngôn ngữ tự thay đổi logic giao dịch.

## Current decision: không khóa Strategy V1 ngay

**Reason:**

Chúng ta chưa có đủ bằng chứng để chọn giữa các candidate strategy.

## Current decision: nghiên cứu trước, coding production sau

**Reason:**

Architecture phụ thuộc vào strategy contract; viết architecture quá sớm có thể dẫn tới refactor nếu strategy thay đổi.

---

# 23. Next Research Step

Bước tiếp theo là hoàn thiện **Candidate Strategy A/B** bằng cách trả lời chính xác các câu hỏi sau:

1. Swing high/low được xác định thế nào?
2. Support/resistance zone được tạo thế nào?
3. Breakout được xác nhận bằng điều kiện nào?
4. Retest được xác nhận bằng điều kiện nào?
5. Entry zone được tính thế nào?
6. SL được tính thế nào?
7. TP được tính thế nào?
8. Khi nào setup bị invalidated?
9. Khi nào setup hết hạn?
10. Backtest sẽ mô phỏng fill/SL/TP ra sao?

Sau khi trả lời xong 10 câu hỏi trên, tài liệu này có thể được dùng để tạo:

```text
TRADING_STRATEGY_SPEC.md
```

và sau đó mới tiếp tục sang architecture + implementation docs.

---

# 24. References

1. TradingView — Strategies, backtesting and forward testing  
   https://www.tradingview.com/support/solutions/43000562362-what-are-strategies-backtesting-and-forward-testing/

2. TradingView — Strategy Alerts  
   https://www.tradingview.com/support/solutions/43000481368-strategy-alerts/

3. TradingView — Technical alerts  
   https://www.tradingview.com/support/solutions/43000763315-getting-started-with-technical-alerts/

4. TradingView — Channel BreakOut Strategy  
   https://www.tradingview.com/support/solutions/43000599828-channel-breakout-strategy/

5. TradingView — Open-source Support Resistance with Breaks and Retests  
   https://www.tradingview.com/script/Xeeko6TV-Support-Resistance-with-Breaks-and-Retests/

6. Binance — USDⓈ-M Futures Kline/Candlestick Data  
   https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Kline-Candlestick-Data  
   Binance — USDⓈ-M Futures Funding Rate History  
   https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History  
   Binance — USDⓈ-M Futures Open Interest Statistics  
   https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics

7. Binance — USDⓈ-M Futures User Data Streams  
   https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-api/user-data-streams

8. CME Group — Proper Position Size  
   https://www.cmegroup.com/education/courses/trade-and-risk-management/proper-position-size

9. Moskowitz, Ooi & Pedersen (2012) — Time Series Momentum, Journal of Financial Economics 104(2), 228–250  
   https://doi.org/10.1016/j.jfineco.2011.11.003

10. Hurst, Ooi & Pedersen — A Century of Evidence on Trend-Following Investing  
    https://www.aqr.com/insights/research/journal-article/a-century-of-evidence-on-trend-following-investing

---

# Appendix A — Important caution

Research evidence from traditional futures markets does not automatically transfer to crypto perpetual futures. Any candidate strategy must therefore be evaluated on the actual Binance instrument, actual timeframe, actual fees/funding assumptions, and realistic execution model intended for the project.

Historical profitability is not evidence of guaranteed future profitability.

---

# 25. Research stop conditions

The project must have an explicit stopping rule so that weak evidence does not trigger endless strategy complexity.

Provisional research kill gate:

- at least 3 independently specified candidate strategy families tested;
- at least 6 months of research elapsed;
- same backtest/validation methodology used for all candidates;
- if none passes the acceptance methodology, stop adding indicators/strategy complexity;
- keep live trading disabled;
- classify the system as a research/journal platform until a new evidence-backed question is approved.

A `NO_TRADE` result is a valid research outcome.

## 26. Statistical uncertainty questions

For every candidate, ask:

1. How many independent-ish trade opportunities exist?
2. How sensitive is expectancy to block/bootstrap assumptions?
3. Do quarterly/symbol/regime slices tell the same story?
4. Does a broader research universe improve or merely rescue the result?
5. Does a parameter plateau exist, or is performance concentrated at one narrow setting?


## Appendix — Implementation language note

The research implementation uses Python. This does not change any trading hypothesis or acceptance criterion. Research notebooks, exploratory analysis, and the canonical deterministic strategy engine must call the same strategy library rather than maintain separate logic. See `TECHNOLOGY_STACK.md`.
