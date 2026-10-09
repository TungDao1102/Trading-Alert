# Hướng dẫn vận hành triển khai cho người không chuyên DevOps

> Đọc repository ngày 2026-10-09, commit `97a92a6`. Hướng dẫn này được viết lại từ nội dung thật của repository (các script trong `deploy/`, `docker-compose.yml`, `docs/operations/RUNBOOK.md`, các quyết định trong `docs/DECISIONS.md`). Nó không thay thế `docs/operations/RUNBOOK.md`: khi hai bên mâu thuẫn thì RUNBOOK và chính nội dung script thắng, và thứ tự ưu tiên chung là `docs/DECISIONS.md`, rồi `docs/`, rồi `AGENTS.md`, rồi `.planning/` (D031).

Hướng dẫn này đi từ một tài khoản AWS mới (vùng ap-southeast-1) tới một máy EC2 đã dựng xong, collector đã chuyển từ máy cũ sang, sao lưu đã kiểm chứng, và con đường dài về sau (soak, DEMO, CANARY, LIVE). Mỗi bước nói rõ chạy ở máy nào và đã xây hay chưa. Thứ gì repository chưa có thì được ghi nhãn chứ không được cho một lệnh bịa ra.

## 0. Cách đọc hướng dẫn này

### Bốn loại máy

Mọi bước đều ghi một thẻ máy, vì nhầm máy là lỗi phổ biến nhất của người mới.

| Thẻ | Là máy nào | Ghi chú |
| --- | --- | --- |
| `[MÁY CÓ MẠNG]` | Máy của bạn có internet: dùng để vào AWS console, chạy `ssh` tới EC2, tạo bot trên BotFather, vào trang Binance, quản lý S3 | Có thể là Windows (PowerShell hoặc Git Bash) hoặc Linux |
| `[MÁY EC2]` | Máy chủ soak trên AWS, chạy Ubuntu hoặc Debian | Mọi script `deploy/*.sh` chỉ chạy ở loại máy này (và `[MÁY CŨ]` nếu đó là Linux) |
| `[MÁY CŨ]` | Máy đang chạy collector hôm nay, có thể là Windows với Docker Desktop | Nguồn dữ liệu khi di chuyển (mục 5) |
| `[MÁY PHÁT TRIỂN]` | Máy nơi repository này được chỉnh sửa | Hiện tại máy này không có mạng, nên không với tới AWS, Binance, Telegram và không chạy được collector (D061 mục G; lời của bạn được ghi trong `16-DEC-O-12`) |

### Bốn nhãn trạng thái

Mỗi tiêu đề bước dạng `#### Bước N.M` mang ít nhất một nhãn. Một bước có thể mang hai nhãn.

| Nhãn | Ý nghĩa |
| --- | --- |
| `[ĐÃ XÂY]` | Code hoặc script đã có trong repository |
| `[CHƯA XÂY]` | Repository chưa có code đó. Bạn không có lệnh chạy được; chỉ có mô tả |
| `[CHƯA XÁC MINH]` | Có tồn tại hoặc được nêu, nhưng chưa từng chạy trên máy thật, sàn thật hay nhà cung cấp thật; hoặc là sự kiện chép từ trang web mà đợt nghiên cứu ghi "chưa xác minh trực tiếp" |
| `[THỦ CÔNG]` | Việc của con người trong một giao diện (console, ứng dụng), không có code trong repository |

Chữ "đã xây" chỉ có nghĩa là code tồn tại và có kiểm thử với đồ giả. Với các script `deploy/`, RUNBOOK mục 17 nói rõ: chưa có script nào chạy trên một máy thật.

### Thẻ lệnh (operation card)

Mỗi script người dùng chạy có một thẻ với tiêu đề `### Thẻ lệnh: <đường dẫn>` và đúng chín mục: Mục đích, Khi nào chạy, Chạy ở máy nào, Lệnh, Chạy thử, Dấu hiệu thành công, Mã thoát, Khi lỗi, Không bao giờ. Danh sách cờ lấy từ chính script, không từ trí nhớ. "Chạy thử" là lệnh `--dry-run`: in ra kế hoạch mà không thay đổi gì. Script nào không có `--dry-run` thì thẻ ghi "Không áp dụng" kèm lý do.

### Ký hiệu thay thế (stand-in)

Mọi giá trị bạn phải tự điền được viết trong dấu ngoặc nhọn, ví dụ `<elastic-ip>`, `<commit-sha>`, `<instance id>`, `<backup bucket>`, `<UTC timestamp>`, `<snapshot id>`. Hai ví dụ lấy nguyên từ RUNBOOK là `git@example.com:me/trading.git` và `trading@old.example`. Không bao giờ gõ nguyên chữ có ngoặc nhọn.

### Quy tắc về bí mật

- Mật khẩu, khóa truy cập, token bot, địa chỉ URL của dịch vụ giám sát, cụm mật khẩu sao lưu: không dán vào chat, lịch sử shell (shell history), issue, commit hay tài liệu này. Tài liệu này chỉ chứa TÊN biến, không chứa giá trị.
- Các số liệu của bạn về máy EC2 (loại máy, dung lượng ổ, ngân sách, vòng đời S3, dịch vụ heartbeat) chưa được chọn (quyết định `16-DEC-O-12` là hoãn). Chúng được ghi là `[QUYẾT ĐỊNH CỦA BẠN]` và không có số nào trong tài liệu này.

### Lưu ý riêng cho Windows

`ssh` và `scp` chạy được từ PowerShell hoặc Git Bash trên `[MÁY CÓ MẠNG]`. Các script `deploy/*.sh` chỉ chạy trên Linux. Script shell có dấu xuống dòng kiểu Windows (CRLF) sẽ lỗi trên Linux với thông báo `bad interpreter` (RUNBOOK 13.2): hãy sao chép từ một bản checkout sạch hoặc từ `git archive`, đừng sao chép từ thư mục Windows cũ.

### Cấu trúc tài liệu

Mục 1 là bức tranh tổng thể. Mục 2 đến 5 dựng máy và chuyển collector. Mục 6 là sao lưu. Mục 7 đến 9 là phần phụ thuộc Phase 16 và các phase chưa xây. Mục 10 đến 13 là vận hành hằng ngày, cập nhật, khẩn cấp và xử lý sự cố. Mục 14 là bảng tra mọi lệnh và mục 15 là danh sách kiểm tra cuối cùng.

Nguồn: `docs/operations/RUNBOOK.md`, `docs/DECISIONS.md`, `deploy/lib.sh`, `docs/operations/SECURITY_AND_OPERATIONS.md`

## 1. Bức tranh tổng thể

### Các máy và dịch vụ

```text
 [MÁY CÓ MẠNG]  (bạn)                    Internet
   | ssh                                     |
   v                                         v
 +-------------------------------+     +------------------+     +------------------+
 | [MÁY EC2] ap-southeast-1      |     | S3 bucket riêng  |     | Telegram         |
 |  docker compose (project      |---->| (sao lưu mã hóa  |     | (bot soak riêng) |
 |  "trading"):                  |     |  phía máy bạn)   |     +------------------+
 |   postgres   (127.0.0.1 only) |     +------------------+
 |   db-upgrade (chạy một lần)   |                              +------------------+
 |   collector  (OI + funding)   |------ dữ liệu công khai ---->| Binance (public) |
 |   paper/live (chỉ là khung)   |                              +------------------+
 |  ufw, SSH chỉ khóa, chrony    |
 +-------------------------------+     +------------------------------+
        ^                               | Dịch vụ heartbeat bên ngoài  |
        | migrate.sh (rsync qua ssh)    | (chưa chọn, xem mục 8.3)     |
 [MÁY CŨ] (collector hôm nay)           +------------------------------+
```

### Ai làm gì ở đâu

| Việc | Máy | Mục |
| --- | --- | --- |
| Tạo tài khoản, Elastic IP, security group, S3, ngân sách | `[MÁY CÓ MẠNG]` | 2, 3 |
| Chạy `deploy/bootstrap.sh` | `[MÁY EC2]` | 4 |
| Chuyển collector bằng `deploy/migrate.sh` | `[MÁY EC2]` (chạy ở phía máy mới) | 5 |
| Sao lưu, khôi phục, diễn tập | `[MÁY EC2]` | 6 |
| Tạo bot Telegram, khóa Binance, đăng ký heartbeat | `[MÁY CÓ MẠNG]` | 8 |
| Giữ `acceptance.json` và chạy bộ kiểm tra hồ sơ | máy có repository và `uv`, do bạn chọn | 3 |

### Cái gì đã xây, cái gì chưa

| Thành phần | Trạng thái | Chú thích |
| --- | --- | --- |
| `deploy/bootstrap.sh`, `update.sh`, `migrate.sh`, `backup.sh`, `restore.sh`, `backup-drill.sh`, `refresh-pins.sh` | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` | Có kiểm thử với đồ giả; chưa script nào chạy trên máy thật (RUNBOOK 17) |
| Collector và chuỗi sao lưu | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` | Cổng D064 (bằng chứng trên S3 thật) vẫn mở, xem mục 6 |
| Paper runtime và SHADOW | một phần: 14 trong 49 kế hoạch của Phase 16 | Mục 7 |
| Live runtime | `[CHƯA XÂY]` | Service `live` trong compose chỉ là khung báo lỗi, đến Phase 24 |

### Mốc thời gian đã quyết định

- Máy EC2 dự kiến được tạo trong cuối tuần 2026-10-10 (D061 hosts), nhưng việc tạo máy đang bị chặn vì quyết định O-12 được hoãn (mục 2).
- D059 mục 4: hạn chót của collector là 2026-10-08 và là hạn của riêng bạn; mọi khoảng trống sau đó được ghi là khoảng trống bao phủ (coverage gap). `openInterestHist` của Binance chỉ trả khoảng một tháng gần nhất, nên các phút Open Interest đã mất là mất vĩnh viễn.
- Soak dài bắt đầu sau khi Phase 16 đóng lại (D061 hosts), chạy qua Phase 18 đến 25.

### Thứ tự đọc và đường tối thiểu hôm nay

Đường tối thiểu có thể làm được ngay khi O-12 được quyết định: mục 2 (chuẩn bị), 3 (máy EC2), 4 (bootstrap), 5 (collector), 6 (sao lưu). Mọi thứ liên quan tới paper runtime, SHADOW, DEMO, CANARY, LIVE đang chờ các kế hoạch chưa xây (mục 7 đến 9).

Nguồn: `docs/operations/RUNBOOK.md`, `docker-compose.yml`, `docs/DECISIONS.md`, `.planning/ROADMAP.md`

## 2. Chuẩn bị trước khi bắt đầu

Mục này gom mọi thứ cần có trước khi chạm vào máy EC2. Phần lớn là việc ở `[MÁY CÓ MẠNG]`. Mục này không tạo tài nguyên AWS nào; việc tạo nằm ở mục 3.

#### Bước 2.1 Biết rõ tài khoản AWS của bạn [THỦ CÔNG] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY CÓ MẠNG]`

- Tài khoản được tạo ngày 2026-07-25 theo mô hình gói Free (có tín dụng). Theo lời bạn ghi lại trong `16-DEC-O-12`, tài khoản tự đóng vào khoảng 2027-01-25 hoặc khi hết tín dụng, tùy mốc nào tới trước. Nếu giữ máy EC2 thì phải chuyển sang gói Paid trước mốc đó; điều kiện `PAID_PLAN` ở mục 3 kiểm tra việc này.
- Vùng cố định là ap-southeast-1 (Singapore). Đây là quyết định D061 hosts; máy phải ping được `fapi.binance.com` (mục 3.7) trước khi cài bất cứ thứ gì.
- Gói Free có đủ để chạy máy EC2 này hay không thì chưa được quyết định và chưa được xác minh; đừng giả định.

#### Bước 2.2 Năm giá trị bạn chưa chọn (quyết định O-12) [THỦ CÔNG]

**Chạy ở:** `[MÁY CÓ MẠNG]` (bạn trả lời trong phiên làm việc với agent lập kế hoạch)

Quyết định `16-DEC-O-12` được bạn ghi ngày 2026-10-09 với lựa chọn "postpone" (hoãn). Hiện không có con số nào được chọn. Năm giá trị còn để trống, mỗi giá trị là `[QUYẾT ĐỊNH CỦA BẠN]`:

| Giá trị | Trạng thái |
| --- | --- |
| Loại máy (instance type) | `[QUYẾT ĐỊNH CỦA BẠN]` |
| Dung lượng ổ EBS | `[QUYẾT ĐỊNH CỦA BẠN]` |
| Số tiền cảnh báo ngân sách và địa chỉ nhận cảnh báo | `[QUYẾT ĐỊNH CỦA BẠN]` |
| Vòng đời và thời hạn lưu của S3 | `[QUYẾT ĐỊNH CỦA BẠN]` |
| Dịch vụ heartbeat bên ngoài và chu kỳ | `[QUYẾT ĐỊNH CỦA BẠN]` |

Hậu quả của việc hoãn: kế hoạch 16-20 (tạo máy EC2 và chuyển collector) bị chặn cho tới khi bạn ghi các giá trị này, và trong lúc đó collector vẫn ở máy cũ, mọi khoảng trống Open Interest được ghi là khoảng trống bao phủ (D059 mục 4). Theo kế hoạch 16-14, cách ghi lại giá trị là bạn trả lời bằng lựa chọn "values" kèm từng con số theo đúng lời bạn viết; agent ghi vào hồ sơ quyết định. Đừng tự sửa tay tệp quyết định và đừng nhờ ai đề xuất con số hộ bạn.

#### Bước 2.3 Tạo cặp khóa SSH [THỦ CÔNG]

**Chạy ở:** `[MÁY CÓ MẠNG]`

Khóa SSH (SSH key) là một cặp tệp: khóa riêng ở lại máy bạn, khóa công khai (đuôi `.pub`) được đặt lên máy chủ. Máy chủ này tắt đăng nhập bằng mật khẩu, nên khóa là cách duy nhất vào được.

```bash
ssh-keygen -t ed25519
```

Giữ khóa riêng trong trình quản lý mật khẩu hoặc thư mục `~/.ssh` có quyền hạn chế. Không gửi nó đi đâu. Với tài khoản `trading` trên EC2, khóa này về thực chất là khóa root (D042 điều kiện 3): hãy bảo vệ và xoay vòng như khóa root.

#### Bước 2.4 Chuẩn bị tệp authorized_keys [THỦ CÔNG]

**Chạy ở:** `[MÁY CÓ MẠNG]`

Tạo một tệp văn bản (ví dụ `authorized_keys`) chứa ít nhất một dòng là khóa công khai của bạn. Bootstrap kiểm tra từng dòng bằng `ssh-keygen -l -f`; nếu không dòng nào hợp lệ, nó từ chối chạy (chốt chống tự khóa mình ngoài máy, lock-out guard). Tệp phải kết thúc dòng kiểu Linux (LF).

#### Bước 2.5 Soạn tệp bí mật cho máy chủ [THỦ CÔNG]

**Chạy ở:** `[MÁY CÓ MẠNG]` (không bao giờ soạn trên EC2)

Tệp này sẽ trở thành `/opt/trading/.env` (quyền 0600, chủ là user `trading`). Bắt đầu từ `.env.example` rồi điền giá trị thật. Điều script thật sự kiểm tra, theo `deploy/bootstrap.sh`:

- Ba biến `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` phải có và không rỗng.
- Mọi giá trị chứa chữ `change_me` bị từ chối. `.env.example` có chữ này ở `POSTGRES_PASSWORD` và `DATABASE_URL`, nên bạn phải thay mật khẩu và sửa hoặc bỏ dòng `DATABASE_URL`. Compose tự dựng `DATABASE_URL` cho các service từ các biến `POSTGRES_*` (ghi chú ở đầu khối `x-database-env` trong `docker-compose.yml`); việc bỏ dòng đó đã được đọc từ file, chưa chạy thật `[CHƯA XÁC MINH]`.
- `POSTGRES_PASSWORD` chỉ gồm chữ, số và các ký tự `.` `_` `~` `-` (an toàn trong URL), dài tối thiểu 16 ký tự. RUNBOOK nói "ví dụ chuỗi hex"; script mới là nơi quy tắc được thực thi. Hãy để trình quản lý mật khẩu sinh chuỗi này.
- Tệp phải dùng LF; ký tự CR bị từ chối.
- Nhóm `BACKUP_*` được điền sau khi bucket tồn tại (mục 6.1). Ví dụ phần đầu của tệp:

```text
POSTGRES_USER=trading
POSTGRES_PASSWORD=<chuỗi ngẫu nhiên dài từ trình quản lý mật khẩu>
POSTGRES_DB=trading
OI_POLL_INTERVAL_SECONDS=300
IMAGE_TAG=dev
```

Tuyệt đối không đặt `BINANCE_LIVE_*` vào tệp của máy paper/soak này (OPS-06). Khóa Binance demo/testnet nếu có dùng tên `BINANCE_TESTNET_API_KEY` và `BINANCE_TESTNET_API_SECRET`, và tách thành tệp riêng cho máy khác.

#### Bước 2.6 Quyền truy cập repository [THỦ CÔNG] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY CÓ MẠNG]`

Bootstrap tự `git clone` repository bằng user `trading`. Nếu repository là riêng tư, bạn cần một khóa triển khai (deploy key) chỉ-đọc: tạo một cặp khóa riêng cho việc này, đặt khóa công khai lên máy chủ git ở chế độ chỉ-đọc, và đưa khóa riêng cho bootstrap qua `--deploy-key`. Giao diện của nơi lưu git thì tài liệu này không mô tả vì repository không chứa thông tin đó.

Về `--ref`: trong repository hiện không có tag git nào (lệnh `git tag` cho kết quả trống). Các ví dụ trong RUNBOOK dùng `v0.1.0` chỉ là ví dụ. Bạn phải dùng một mã commit hoặc một tag mà bạn tự tạo và tự đẩy lên remote. Lấy mã commit hiện tại bằng:

```bash
git rev-parse HEAD
```

Việc remote đã có commit/tag đó hay chưa là điều bạn phải tự kiểm tra `[CHƯA XÁC MINH]`.

#### Bước 2.7 Bucket S3, khóa truy cập và mật khẩu mã hóa sao lưu [THỦ CÔNG]

**Chạy ở:** `[MÁY CÓ MẠNG]`

Bạn cần (tạo ở mục 3.6 và 6.1): một bucket S3 riêng tư, mới và trống; một khóa truy cập chỉ có quyền trên bucket đó; và hai chuỗi bí mật (cụm mật khẩu và "muối", salt) để mã hóa sao lưu. Trên máy trạm của bạn, không bao giờ trên VPS, đổi mỗi chuỗi thành dạng "obscured" bằng lệnh sau (đọc từ stdin để không lọt vào lịch sử shell):

```bash
rclone obscure -
```

Giữ chuỗi gốc ở trình quản lý mật khẩu cộng một bản ngoại tuyến thứ hai. Mất cụm mật khẩu thì mọi bản sao lưu không thể phục hồi (RUNBOOK 11, mục "Key custody"). Giá trị trong `.env` là kết quả `rclone obscure`, thứ có thể đảo ngược và không phải mã hóa.

Nguồn: `docs/operations/RUNBOOK.md`, `deploy/bootstrap.sh`, `.env.example`, `.planning/phases/16-paper-runtime-composition/decisions/16-DEC-O-12.md`, `.planning/phases/16-paper-runtime-composition/16-14-PLAN.md`

## 3. Tạo và nghiệm thu máy EC2

Repository không bao giờ tạo, sửa hay xóa tài nguyên AWS nào; mọi bước ở mục này do bạn làm tay hoặc bằng AWS CLI của bạn (RUNBOOK 19). Tên nút và màn hình của AWS console có thể khác với những gì bạn thấy; tài liệu này không mô tả chúng `[CHƯA XÁC MINH]`. Mọi dữ kiện về AWS dưới đây được chép từ RUNBOOK 19, nơi chúng được đọc ngày 2026-10-08 và ghi là "chưa xác minh trực tiếp": trước khi một quyết định dựa vào chúng, hãy đọc lại trang gốc.

#### Bước 3.1 Tạo instance và chọn hệ điều hành [THỦ CÔNG] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY CÓ MẠNG]`

- Hệ điều hành chỉ được là Ubuntu 22.04, Ubuntu 24.04 hoặc Debian 12. Bootstrap từ chối mọi hệ điều hành khác trước khi đổi bất cứ điều gì. Amazon Linux không được hỗ trợ.
- Loại máy và dung lượng ổ EBS là `[QUYẾT ĐỊNH CỦA BẠN]` (O-12 đang hoãn), nên bước tạo máy bị chặn cho tới khi bạn ghi các giá trị đó (mục 2.2). Chọn khóa SSH công khai của bạn (bước 2.3) ngay khi tạo.
- Một điều dễ vấp: RUNBOOK 13.1 giả định bạn đăng nhập được bằng root qua SSH, nhưng các ảnh hệ điều hành của AWS thường chỉ cho đăng nhập bằng một user mặc định, không phải root. Cách lấy phiên root trên ảnh bạn chọn là `[CHƯA XÁC MINH]` (xem bước 4.1).

#### Bước 3.2 Gắn Elastic IP [THỦ CÔNG] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY CÓ MẠNG]`

Elastic IP là một địa chỉ IP công khai cố định gắn vào máy của bạn; không có nó địa chỉ đổi mỗi khi máy khởi động lại. Địa chỉ này vừa là nơi bạn `ssh` tới vừa là địa chỉ bạn đưa vào danh sách IP cho phép (IP whitelist) của khóa Binance sau này (D042 điều kiện 4). Một địa chỉ IPv4 công khai đang dùng, kể cả Elastic IP, bị tính phí 0,005 USD mỗi giờ (RUNBOOK 19.3, chưa xác minh trực tiếp).

#### Bước 3.3 Mã hóa ổ đĩa EBS [THỦ CÔNG] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY CÓ MẠNG]` (cần AWS CLI đã đăng nhập)

Mã hóa EBS mặc định là một cài đặt theo từng vùng, không đổi các ổ đã có, và trang AWS không nói trạng thái ban đầu của tài khoản mới, nên đừng giả định (G12). Hãy kiểm tra TRƯỚC khi tạo ổ của instance:

```bash
aws ec2 get-ebs-encryption-by-default --region ap-southeast-1
```

Nếu kết quả là `false`, bật nó là thay đổi một cài đặt của cả tài khoản, vì vậy đó là quyết định của bạn:

```bash
aws ec2 enable-ebs-encryption-by-default --region ap-southeast-1
```

Cách thay thế là yêu cầu mã hóa rõ ràng khi tạo ổ gốc rồi ghi điều kiện `EBS_ROOT_VOLUME_ENCRYPTED`.

#### Bước 3.4 Security group [THỦ CÔNG] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY CÓ MẠNG]`

Security group là tường lửa phía AWS. Chỉ mở cổng SSH, và chỉ cho địa chỉ nơi bạn chọn truy cập. Không mở cổng PostgreSQL ở chiều vào. Lưu ý: `ufw` trên máy không điều khiển các cổng do Docker công bố, nên kiểm soát thật là việc compose chỉ công bố `127.0.0.1` (điều kiện `POSTGRES_NOT_PUBLIC`).

#### Bước 3.5 Cảnh báo ngân sách và chuyển gói Paid [THỦ CÔNG] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY CÓ MẠNG]`

Tạo ít nhất một ngân sách (Budget) có thông báo gửi tới địa chỉ nhận. AWS Budgets không tính phí theo trang đã đọc ngày 2026-10-08 (chưa xác minh trực tiếp). Số tiền và địa chỉ là `[QUYẾT ĐỊNH CỦA BẠN]`. Rồi chuyển tài khoản sang gói Paid (điều kiện `PAID_PLAN`; không có lệnh, đây là việc xem trên trang Billing).

#### Bước 3.6 Bucket S3 sao lưu [THỦ CÔNG] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY CÓ MẠNG]`

Bucket phải riêng tư (chặn truy cập công khai), có mã hóa mặc định, bật versioning, mới và hoàn toàn trống. Vòng đời và thời hạn lưu là `[QUYẾT ĐỊNH CỦA BẠN]` (O-12). Tạo một khóa truy cập chỉ có quyền trên bucket này. Bật versioning hoặc object lock với thời hạn giữ là một biện pháp do bạn tự làm để khóa bị lộ không xóa được lịch sử (RUNBOOK 11.1 mục 4). Cảnh báo quan trọng: cổng D064 (chứng minh `cryptcheck` trên S3 thật) vẫn mở, nên chưa có bản sao lưu thật nào được chạy và điều kiện `BACKUP_REAL_S3_GATE` chưa PASS. Chi tiết ở mục 6.

#### Bước 3.7 Hành động đầu tiên trên instance: ping Binance [THỦ CÔNG] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]` (đăng nhập bằng khóa SSH; trước khi cài bất cứ thứ gì)

```bash
curl -sS -o /dev/null -w "%{http_code}" https://fapi.binance.com/fapi/v1/ping
```

Điều kiện đạt: lệnh in ra `200`. Đây là điều kiện `REGION_PING_FAPI`. Chạy lại lần nữa sau khi Elastic IP đã được gắn nếu lần đầu máy dùng địa chỉ khác, vì Binance nhìn thấy địa chỉ mà máy thật sự dùng. Nếu kết quả là bất cứ thứ gì khác `200` (mã khác, hết thời gian chờ, lỗi TLS): DỪNG, không cài gì, ghi lại kết quả làm bằng chứng và báo lại. Chọn vùng hay địa chỉ khác là một quyết định mới của bạn; hướng dẫn này không quyết định thay.

#### Bước 3.8 Bảng nghiệm thu theo điều kiện D042 [THỦ CÔNG] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY CÓ MẠNG]` cho các lệnh `aws` và `[MÁY EC2]` cho các lệnh trên máy; điền kết quả vào `acceptance.json`.

Có 16 điều kiện, mỗi điều kiện một mã. Chạy lệnh, chép kết quả vào `acceptance.json` làm `evidence` (một trích đoạn, không bao giờ là bí mật), và chỉ đặt `status` là `PASS` khi điều kiện đạt. Với các dòng mà nguồn là "AWS CLI help", lệnh chưa được đọc từ trang tài liệu: chạy `aws <dịch vụ> <lệnh> help` trước và sửa lệnh trong bằng chứng nếu bản CLI của bạn khác. Vùng của mọi lệnh AWS là `--region ap-southeast-1`. Mọi dòng dưới đây mang nhãn `[CHƯA XÁC MINH]` vì chưa dòng nào được chạy trên máy thật.

| Mã điều kiện | Máy | Khi nào kiểm tra | Lệnh | Điều kiện đạt | Nhãn |
| --- | --- | --- | --- | --- | --- |
| `REGION_PING_FAPI` | `[MÁY EC2]` | ngay (bước 3.7) | `curl -sS -o /dev/null -w "%{http_code}" https://fapi.binance.com/fapi/v1/ping` | in ra `200` | `[CHƯA XÁC MINH]` |
| `ELASTIC_IP` | `[MÁY CÓ MẠNG]` | sau khi gắn IP | `aws ec2 describe-addresses --region ap-southeast-1` và `aws ec2 describe-instances --region ap-southeast-1 --instance-ids <instance id>` | địa chỉ bạn dùng để ssh và cho whitelist là một Elastic IP đã gắn vào instance này, và `PublicIpAddress` của instance bằng nó | `[CHƯA XÁC MINH]` |
| `EBS_ENCRYPTED_BY_DEFAULT` | `[MÁY CÓ MẠNG]` | trước khi tạo ổ | `aws ec2 get-ebs-encryption-by-default --region ap-southeast-1` | kết quả có `"EbsEncryptionByDefault": true` | `[CHƯA XÁC MINH]` |
| `EBS_ROOT_VOLUME_ENCRYPTED` | `[MÁY CÓ MẠNG]` | sau khi tạo instance | `aws ec2 describe-volumes --region ap-southeast-1 --filters Name=attachment.instance-id,Values=<instance id>` | mọi ổ gắn vào instance báo `"Encrypted": true` | `[CHƯA XÁC MINH]` |
| `S3_BUCKET_PRIVATE` | `[MÁY CÓ MẠNG]` | sau khi tạo bucket | `aws s3api get-public-access-block --bucket <backup bucket>` | cả bốn thiết lập chặn đều `true`; không có chính sách hay ACL cho phép công khai | `[CHƯA XÁC MINH]` |
| `S3_DEFAULT_ENCRYPTION` | `[MÁY CÓ MẠNG]` | sau khi tạo bucket | `aws s3api get-bucket-encryption --bucket <backup bucket>` | có một quy tắc mã hóa mặc định (SSE-S3 là mặc định của mọi bucket); không cần SSE-KMS vì chuỗi sao lưu đã mã hóa ở máy | `[CHƯA XÁC MINH]` |
| `S3_VERSIONING` | `[MÁY CÓ MẠNG]` | sau khi tạo bucket | `aws s3api get-bucket-versioning --bucket <backup bucket>` | kết quả có `"Status": "Enabled"` | `[CHƯA XÁC MINH]` |
| `HEARTBEAT_MONITOR_ALERT_RECEIVED` | `[MÁY EC2]` | sau cutover (collector đã chạy trên EC2) | trong `/opt/trading`: `docker compose stop collector`, chờ lâu hơn chu kỳ của dịch vụ giám sát (giá trị `[QUYẾT ĐỊNH CỦA BẠN]`), rồi `docker compose start collector` | một cảnh báo từ dịch vụ bên ngoài đã tới bạn khi collector dừng, và một thông báo phục hồi theo sau khi khởi động lại; ghi cả hai giờ UTC | `[CHƯA XÁC MINH]` |
| `CHRONY_SYNCED` | `[MÁY EC2]` | sau bootstrap | `chronyc tracking` và `chronyc sources` | `chronyc sources` liệt kê `169.254.169.123` với dấu nguồn được chọn, và độ lệch `System time` của `chronyc tracking` nhỏ hơn giới hạn của bootstrap (`--max-drift-ms`, mặc định 100 ms) | `[CHƯA XÁC MINH]` |
| `BUDGET_ALERT` | `[MÁY CÓ MẠNG]` | ngay | `aws budgets describe-budgets --account-id <account id>` và `aws budgets describe-notifications-for-budget --account-id <account id> --budget-name <budget name>` | có ít nhất một ngân sách và nó có thông báo với người nhận; số tiền là `[QUYẾT ĐỊNH CỦA BẠN]` | `[CHƯA XÁC MINH]` |
| `PAID_PLAN` | `[MÁY CÓ MẠNG]` | ngay | mở trang Billing and Cost Management trong trình duyệt và đọc gói tài khoản (không có lệnh) | gói là gói trả phí, không phải gói free; ghi tên gói và ngày | `[THỦ CÔNG]` |
| `SSH_KEY_ONLY` | `[MÁY EC2]` và `[MÁY CÓ MẠNG]` | sau bootstrap | trên máy: `sudo sshd -T`; từ máy bạn: `ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no trading@<elastic ip>` | `sshd -T` có `passwordauthentication no`, `kbdinteractiveauthentication no`, `permitrootlogin no`, `pubkeyauthentication yes`; lần ssh bằng mật khẩu bị từ chối với `Permission denied (publickey)` | `[CHƯA XÁC MINH]` |
| `POSTGRES_NOT_PUBLIC` | `[MÁY EC2]` và `[MÁY CÓ MẠNG]` | sau khi postgres chạy (bước 5) | trên máy: `docker compose ps postgres` và `sudo ss -ltn`; `aws ec2 describe-security-groups --region ap-southeast-1 --group-ids <security group id>` | PostgreSQL chỉ công bố trên `127.0.0.1`; không có cổng lắng nghe nào của nó gắn với `0.0.0.0` hay `::`; security group không có luật vào cho cổng PostgreSQL | `[CHƯA XÁC MINH]` |
| `ENV_FILE_MODE_0600` | `[MÁY EC2]` | sau bootstrap | `stat -c "%a %U" /opt/trading/.env` | in ra `600 trading` | `[CHƯA XÁC MINH]` |
| `SUDO_WITH_PASSWORD` | `[MÁY EC2]` | sau bootstrap, phiên SSH thứ hai của `trading` | `sudo -k` rồi `sudo -v`; thêm `passwd -S trading` | `sudo -v` hỏi mật khẩu và thành công; `passwd -S trading` báo trạng thái `P` | `[CHƯA XÁC MINH]` |
| `BACKUP_REAL_S3_GATE` | không có lệnh trong repository | chưa thể | bản ghi bằng chứng D064 (chưa có) | bản ghi cho thấy trên S3 thật qua lớp crypt, kể cả đối tượng multipart, `rclone cryptcheck` phát hiện được đổi nội dung cùng kích thước, đối tượng bị sửa và bị xóa sau khi tải lên. Cho tới lúc đó trạng thái KHÔNG phải `PASS` và không có sao lưu thật nào chạy | `[CHƯA XÂY]` |

Cấu trúc tệp `acceptance.json` (một mục cho mỗi mã điều kiện ở bảng trên, giữ tệp ở máy bạn, không bao giờ để trong git, không bao giờ dán khóa, token, mật khẩu hay nội dung `.env` vào đó):

```json
{
  "schema": "soak-host-acceptance/1",
  "conditions": {
    "REGION_PING_FAPI": {
      "status": "PASS",
      "command": "<lệnh đã chạy>",
      "evidence": "<trích đoạn ngắn, không có bí mật>",
      "checked_at": "YYYY-MM-DDTHH:MM:SSZ"
    }
  }
}
```

RUNBOOK 19.1 mục 4 nói tệp này nằm ở máy phát triển. Vì máy đó hiện không có mạng nên bạn điền ở `[MÁY CÓ MẠNG]` rồi chép tệp văn bản này sang máy chạy bộ kiểm tra; máy nào chạy bộ kiểm tra là `[QUYẾT ĐỊNH CỦA BẠN]`.

### Thẻ lệnh: scripts/soak_host_acceptance.py

**Mục đích:** kiểm tra tệp `acceptance.json` đã điền: mỗi trong 16 điều kiện bắt buộc phải có, có `status` là `PASS`, có `command`, `evidence` và thời điểm `checked_at` kiểu UTC. Nó không tự quyết điều kiện có thật sự đạt hay không.

**Khi nào chạy:** sau khi bạn đã chạy các kiểm tra ở bước 3.8 (và lại sau cutover ở mục 5), trước khi coi máy là nghiệm thu.

**Chạy ở máy nào:** máy có repository và `uv` (`[MÁY CÓ MẠNG]` hoặc `[MÁY PHÁT TRIỂN]`, do bạn chọn). Không chạy trên `[MÁY EC2]` và không cần mạng.

**Lệnh:**

```bash
uv run python scripts/soak_host_acceptance.py acceptance.json
```

Đối số duy nhất là đường dẫn tệp JSON. Script không có cờ.

**Chạy thử:** Không áp dụng. Script chỉ đọc một tệp, không đổi gì, không liên lạc với máy chủ hay mạng, nên chính nó đã là bản chạy an toàn.

**Dấu hiệu thành công:** in `accepted: 16 conditions PASS` ra stdout và thoát với mã 0.

**Mã thoát:** 0 mọi điều kiện đầy đủ và `PASS`. 1 điều kiện bắt buộc đầu tiên (theo thứ tự trong bảng) bị thiếu, chưa đầy đủ hoặc không phải `PASS`, và thông báo nêu tên nó. 2 đầu vào không dùng được, hoặc một trường chứa thứ trông giống bí mật; thông báo nêu điều kiện và trường nhưng không bao giờ in giá trị.

**Khi lỗi:** mã 1: làm điều kiện được nêu cho tới khi đạt rồi cập nhật tệp. Mã 2: mở tệp, tìm trường được nêu, xóa thứ trông giống bí mật và chỉ giữ trích đoạn không nhạy cảm, rồi chạy lại. Nếu nghi ngờ đã lỡ dán một bí mật, hãy xoay vòng bí mật đó.

**Không bao giờ:** kết nối tới máy chủ, AWS hay mạng; in giá trị trông như bí mật; tự quyết một điều kiện đã đạt.

#### Bước 3.9 Ghi chú: chrony, chi phí, heartbeat [THỦ CÔNG] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]` cho chrony, `[MÁY CÓ MẠNG]` cho phần còn lại.

- Chrony (G14): trên Ubuntu trang AWS đưa ra bước thủ công, cài `chrony` (bootstrap đã làm) rồi thêm dòng sau vào `/etc/chrony/chrony.conf` và khởi động lại chrony. Trang không nói ảnh Ubuntu gốc đã có sẵn dòng này, và không bao quát Debian 12, nên hãy đọc `chronyc sources` trên máy rồi mới quyết, đừng giả định. Runtime chỉ đọc UTC (D-35); không có gì trong repository theo dõi độ lệch sau khi khởi động (D042 điều kiện 5 đòi hỏi theo dõi, để cho một kế hoạch sau).

```text
server 169.254.169.123 prefer iburst minpoll 4 maxpoll 4
```

```bash
sudo systemctl restart chrony
```

- Chi phí: giá tính toán, lưu trữ và yêu cầu S3 chưa đọc được trong đợt nghiên cứu nên vẫn chưa xác minh. Không có con số nào của bạn (loại máy, dung lượng, ngân sách, vòng đời) được viết ở đây.
- Heartbeat: dịch vụ và chu kỳ là lựa chọn của bạn (O-12). Repository này không gửi heartbeat nào (RUNBOOK 11.4), nên phép thử chỉ có ý nghĩa nếu tín hiệu bạn đăng ký phụ thuộc vào việc collector đang chạy. URL mà dịch vụ giám sát cấp cho bạn là một bí mật: không dán nó vào `acceptance.json`. Dừng collector làm gián đoạn thu thập, và các phút Open Interest mất theo cách đó là mất vĩnh viễn: chỉ làm phép thử này khi bạn chấp nhận cái giá đó, và ghi khoảng trống kết quả là một khoảng trống bao phủ.

Nguồn: `docs/operations/RUNBOOK.md`, `scripts/soak_host_acceptance.py`, `deploy/bootstrap.sh`, `docs/DECISIONS.md`

## 4. Dựng máy chủ với bootstrap

`deploy/bootstrap.sh` biến một máy Ubuntu 22.04, Ubuntu 24.04 hoặc Debian 12 mới tinh thành một máy Docker đã gia cố, có repository ở đúng phiên bản và `.env` đã đặt. Nó chỉ dùng apt, ufw, sshd, chrony và Docker Engine thường, không dùng công cụ dòng lệnh của nhà cung cấp đám mây. Nó idempotent: chạy lần hai trên máy đã cấu hình xong thì không thay đổi gì thêm. Thứ tự bên trong: kiểm tra trước (OS, công cụ, quyền root, tệp bí mật, khóa), gói cơ bản (`ca-certificates`, `curl`, `git`, `ufw`, `sudo`), kho apt của Docker và Docker Engine kèm plugin compose, user `trading` vào nhóm `docker` và `sudo` cùng khóa đã cho phép, ufw (mặc định chặn chiều vào, cho phép chiều ra, mở mọi cổng SSH mà `sshd -T` báo, rồi bật), gia cố SSH, chrony, checkout ở đúng `--ref`, và `.env`. Nó không khởi động stack.

#### Bước 4.1 Chuẩn bị và phiên root [THỦ CÔNG] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY CÓ MẠNG]`

Bạn cần (mục 2): máy EC2 đã tạo và qua phép ping ở bước 3.7; tệp bí mật; tệp `authorized_keys`; (nếu repository riêng tư) khóa triển khai; và một mã commit cho `--ref`.

Một điều quan trọng: bootstrap phải chạy với quyền root, và RUNBOOK 13.1 giả định bạn đăng nhập root bằng SSH. Ảnh hệ điều hành của AWS thường không cho đăng nhập root mà chỉ cho một user mặc định. Cách có được một phiên root trên ảnh của bạn tài liệu này không khẳng định. Nếu user mặc định dùng được `sudo`, bạn có thể thử lệnh sau; kết quả chưa từng được kiểm chứng `[CHƯA XÁC MINH]`:

```bash
sudo -i
```

Nếu không có phiên root nào, DỪNG và báo lại, đừng tìm đường vòng. Các đường dẫn `/root/...` bên dưới là của RUNBOOK; nếu bạn không phải root, hãy dùng thư mục nhà của user bạn đăng nhập và sửa các đường dẫn cho khớp.

#### Bước 4.2 Chép tệp lên máy [THỦ CÔNG]

**Chạy ở:** `[MÁY CÓ MẠNG]`

Chép thư mục `deploy/`, tệp bí mật và tệp khóa lên máy (RUNBOOK 13.2). Hãy chép từ một bản checkout sạch (kiểm tra `git status` không báo thay đổi) để không mang theo script kiểu Windows (CRLF). Giữ tệp bí mật ngoài lịch sử shell và ngoài repository.

```bash
git status
```

```bash
scp -r deploy secrets.env authorized_keys root@host:/root/
```

Nếu có khóa triển khai, chép thêm bằng một lệnh `scp` nữa. Thay `host` bằng `<elastic-ip>` của bạn.

#### Bước 4.3 Chạy thử (dry-run) [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]` dưới quyền root

```bash
sudo deploy/bootstrap.sh --dry-run --secrets-file /root/secrets.env --repo git@example.com:me/trading.git --ref <commit-sha> --authorized-keys /root/authorized_keys
```

Lệnh in kế hoạch theo thứ tự (mỗi dòng bắt đầu bằng `+`) và không đổi gì. Chạy nó dưới root, vì nếu không các phép dò chỉ-đọc (ufw, sshd, dpkg) có thể báo thiếu. Đọc kỹ kế hoạch, nhất là các dòng ufw và sshd.

#### Bước 4.4 Chạy thật [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]` dưới quyền root

```bash
sudo deploy/bootstrap.sh --secrets-file /root/secrets.env --repo git@example.com:me/trading.git --ref <commit-sha> --authorized-keys /root/authorized_keys
```

Thêm `--deploy-key /root/deploy_key` nếu repository riêng tư. Giữ phiên root này mở cho tới hết bước 4.6.

#### Bước 4.5 Lần chạy đầu sẽ dừng ở bước SSH cho tới khi bạn đặt mật khẩu `trading` (D062) [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]` dưới quyền root

Sau khi gia cố, root không còn đăng nhập SSH được, nên `trading` là người quản trị. Theo D062, `trading` dùng sudo CÓ mật khẩu; repository không có luật sudo không cần mật khẩu (passwordless sudo rule) ở bất cứ đâu, vì một luật như vậy cho một script mà `trading` có thể sửa sẽ thành quyền root không giới hạn. Tài khoản mới tạo chưa có mật khẩu, nên trên máy mới lần chạy đầu dừng ở bước SSH, sau các bước user và ufw, với một thông báo nêu cách sửa. Trong phiên root, đặt mật khẩu bằng chính tay bạn (bootstrap không bao giờ đặt, đọc hay in nó):

```bash
passwd trading
```

Rồi chạy lại đúng lệnh ở bước 4.4. Vì idempotent nên nó đi tiếp.

#### Bước 4.6 Mở phiên SSH thứ hai và thử `sudo -v` trước khi đóng phiên root [THỦ CÔNG] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY CÓ MẠNG]`, rồi trong phiên mới trên `[MÁY EC2]`

Giữ phiên root mở. Mở một phiên SSH thứ hai với tư cách `trading` bằng khóa của bạn:

```bash
ssh trading@<elastic-ip>
```

Trong phiên đó chạy lệnh sau; nó hỏi mật khẩu `trading` và phải thành công:

```bash
sudo -v
```

Chỉ khi cả hai đều thành công mới đóng phiên root. Nếu không, bạn có thể đã tự khóa mình ngoài máy.

#### Bước 4.7 Danh sách kiểm tra của người vận hành (8 mục, không có gì tự động) [THỦ CÔNG]

**Chạy ở:** `[MÁY CÓ MẠNG]` và `[MÁY EC2]`

Bootstrap in danh sách này ở cuối. Bằng lời đơn giản:

1. Khóa API Binance phải bị giới hạn ở địa chỉ IP công khai của máy này (IP whitelist) và quyền rút tiền phải tắt (mục 8.2).
2. Đăng ký một dịch vụ heartbeat bên ngoài VPS để một máy im lặng thì có người biết (mục 8.3).
3. Cụm mật khẩu mã hóa sao lưu phải được giữ ngoài VPS; mất nó thì mọi bản sao lưu không thể phục hồi (mục 6).
4. Thử phiên SSH thứ hai, kể cả `sudo -v`, trước khi đóng phiên đầu.
5. Mã hóa ổ đĩa của nhà cung cấp phải bật hoặc được xác nhận bật.
6. Đặt các biến `BACKUP_*` trong `/opt/trading/.env` và chạy `deploy/backup.sh --init-remote` bằng user `trading` (mục 6). Root không còn đăng nhập SSH; `trading` ở nhóm `sudo` và sudo hỏi mật khẩu. Sau đó cài timer bằng `sudo /opt/trading/deploy/backup.sh --install-timer` (lệnh cài không đọc `.env`) và dùng `sudo` cho mọi thay đổi apt, ufw hay systemctl về sau.
7. Nhóm `docker` tương đương root: chỉ giữ một tài khoản vận hành. ufw không điều khiển các cổng do Docker công bố; chỉ công bố các cổng `127.0.0.1`.
8. Xóa tệp bí mật đã chép khỏi máy khi `.env` đã được kiểm tra (bước 4.8).

#### Bước 4.8 Xóa tệp bí mật đã chép [THỦ CÔNG] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]`

Kiểm tra `.env` đã đặt đúng quyền và chủ (điều kiện `ENV_FILE_MODE_0600`):

```bash
stat -c "%a %U" /opt/trading/.env
```

Kết quả phải là `600 trading`. Chỉ sau đó mới xóa tệp bí mật bạn đã chép ở bước 4.2 bằng lệnh xóa tệp của hệ điều hành (hướng dẫn này không đưa lệnh xóa vào khối lệnh), rồi liệt kê thư mục để chắc là nó không còn:

```bash
ls -l /root
```

#### Bước 4.9 Giới hạn của lần khởi động đầu cuối tuần dựng máy [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]` bằng user `trading` trong `/opt/trading`

Bootstrap không khởi động stack. Vào thư mục và chỉ làm hai việc an toàn: kiểm tra cấu hình (luôn dùng `-q`; lệnh `config` trần sẽ in ra toàn bộ môi trường đã phân giải, gồm cả bí mật) và dựng hai image:

```bash
cd /opt/trading
```

```bash
docker compose config -q
```

```bash
docker compose --profile ops build
```

Trong cuối tuần dựng máy, KHÔNG chạy `docker compose up -d`: nó sẽ khởi động một collector ghi vào cơ sở dữ liệu mới trước lúc cutover, trong khi cutover khôi phục vào một cơ sở dữ liệu trống (RUNBOOK 19.4 mục 1). Việc khởi động stack chờ tới mục 5.

### Thẻ lệnh: deploy/bootstrap.sh

**Mục đích:** biến máy mới thành máy Docker đã gia cố với repository ở `--ref` và `.env` đã đặt (chi tiết ở đầu mục 4). Thư viện `deploy/lib.sh` là tệp hàm dùng chung (`die`, `run`, `DRY_RUN`, `write_if_changed`...) được script này nạp bằng `source`; nó không có cờ và không bao giờ được chạy trực tiếp.

**Khi nào chạy:** một lần khi dựng máy, và chạy lại được. Hệ điều hành hỗ trợ: Ubuntu 22.04, Ubuntu 24.04, Debian 12; hệ khác bị từ chối trước khi đổi gì.

**Chạy ở máy nào:** `[MÁY EC2]` dưới quyền root (`sudo`). Chạy thử thì cũng nên dùng root.

**Lệnh:**

```bash
sudo deploy/bootstrap.sh --secrets-file /root/secrets.env --repo git@example.com:me/trading.git --ref <commit-sha> --authorized-keys /root/authorized_keys --dir /opt/trading --user trading --deploy-key /root/deploy_key --max-drift-ms 100
```

| Cờ | Bắt buộc | Mặc định | Ý nghĩa |
| --- | --- | --- | --- |
| `--secrets-file PATH` | có | - | tệp bí mật sẽ thành `.env`; được kiểm tra như ở bước 2.5 |
| `--repo URL` | có, trừ khi `--dir` đã có checkout | - | nơi `git clone` lấy mã |
| `--ref REF` | có | - | mã commit hoặc tag cần triển khai; một tên nhánh cục bộ có thể cũ |
| `--authorized-keys PATH` | có, trừ khi user đã có khóa hợp lệ | - | khóa công khai cho user; chốt chống tự khóa mình |
| `--dir PATH` | không | `/opt/trading` | đường dẫn tuyệt đối của checkout |
| `--user NAME` | không | `trading` | tài khoản vận hành |
| `--deploy-key PATH` | không | - | khóa triển khai chỉ-đọc cho repository riêng tư |
| `--max-drift-ms N` | không | `100` | độ lệch đồng hồ tối đa (ms) sau `chronyc waitsync` |
| `--dry-run` | không | tắt | in kế hoạch, không đổi gì |
| `-h`, `--help` | không | - | in cách dùng và thoát với mã 0 |

**Chạy thử:** lệnh dưới đây in kế hoạch và không đổi gì; đọc kỹ các dòng ufw và sshd.

```bash
sudo deploy/bootstrap.sh --dry-run --secrets-file /root/secrets.env --repo git@example.com:me/trading.git --ref <commit-sha> --authorized-keys /root/authorized_keys
```

**Dấu hiệu thành công:** script chạy hết và in "Operator checklist (none of this is automated)" với 8 mục. Lần chạy thứ hai trên máy đã cấu hình xong không báo thay đổi nào (các dòng như "repository already at" và ".env already installed"). SSH được gia cố bằng tệp `/etc/ssh/sshd_config.d/00-trading-hardening.conf` (đặt tên `00-` vì sshd giữ giá trị đầu tiên nó đọc, còn ảnh đám mây có `50-cloud-init.conf` bật mật khẩu); nó chỉ được giữ nếu `sshd -t` qua và `sshd -T` báo đủ bốn giá trị.

**Mã thoát:** 0 khi thành công hoặc khi dùng `-h`. 1 cho mọi lỗi mà script tự dừng (`die`, in dòng `ERROR:` ra stderr), kể cả cờ lạ. Một lệnh con bị lỗi trong lúc chạy làm script thoát với mã của lệnh đó (suy ra từ `set -e`, chưa quan sát `[CHƯA XÁC MINH]`).

**Khi lỗi:**

| Thông báo (đầu dòng) | Nghĩa và cách xử lý |
| --- | --- |
| `unsupported OS` | OS ngoài danh sách; không có gì bị đổi. Dùng Ubuntu 22.04/24.04 hoặc Debian 12 |
| `must run as root` | chạy lại với `sudo` (hoặc dùng `--dry-run` để xem trước) |
| `secrets file has CR` | tệp bí mật có CRLF; chuyển sang LF rồi chép lại |
| `secrets file is not usable` | dưới đó liệt kê tên biến: thiếu hoặc rỗng, còn `change_me`, mật khẩu không an toàn cho URL hoặc ngắn hơn 16 ký tự; sửa ở máy bạn rồi chép lại |
| `lock-out guard: no authorized_keys line` | không dòng khóa nào hợp lệ; sửa tệp khóa |
| `lock-out guard: ... passwd -S ... not P` | chưa đặt mật khẩu; chạy `passwd trading` trong phiên root rồi chạy lại (bước 4.5) |
| `clock drift ... exceeds` hoặc `chronyc waitsync did not report` | đồng hồ chưa đồng bộ; kiểm tra chrony và cho thời gian rồi chạy lại |
| `refusing to harden SSH` | `sshd_config` không có dòng `Include /etc/ssh/sshd_config.d/*.conf`; dừng và báo lại |
| `--repo is required` | `--dir` chưa có checkout; thêm `--repo` |
| `bad interpreter` (ở shell, không phải thông báo của script) | script bị CRLF; chép lại từ bản checkout sạch |

**Không bao giờ:** khởi động stack; đặt, đọc hoặc in mật khẩu nào; ghi một luật sudo không cần mật khẩu; cài công cụ dòng lệnh của nhà cung cấp đám mây; công bố một cổng khác ngoài `127.0.0.1`; in giá trị bí mật.

Nguồn: `docs/operations/RUNBOOK.md`, `deploy/bootstrap.sh`, `deploy/lib.sh`, `docs/DECISIONS.md`

## 5. Triển khai collector và chuyển dữ liệu từ máy cũ

#### Bước 5.1 Collector làm gì [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]` (khái niệm; áp dụng cho cả `[MÁY CŨ]`)

Collector là một tiến trình thu dữ liệu công khai của Binance: cứ mỗi `OI_POLL_INTERVAL_SECONDS` giây (mặc định trong `.env.example` là 300, tức 5 phút) nó hỏi Open Interest và funding rate, ghi tệp Parquet vào volume `rawdata`, và ghi "mốc đã tới đâu" (watermark) vào PostgreSQL. Service `db-upgrade` chạy `alembic upgrade head` một lần và collector chỉ khởi động sau khi nó thành công. Kiểm tra sức khỏe của collector cho phép sáu phút khởi động đầu tiên (start period) vì cơ sở dữ liệu mới chưa có mốc nào.

Điều bạn phải nhớ: dừng collector làm mất các phút Open Interest vĩnh viễn, vì Binance chỉ phục vụ khoảng một tháng lịch sử và độ phân giải đó không thể lấp lại. Khoảng trống funding thì lấp lại được bằng các công cụ backfill (RUNBOOK 15.4).

#### Bước 5.2 Chọn đường: máy trống hay di chuyển từ máy cũ [THỦ CÔNG]

**Chạy ở:** `[MÁY EC2]`

- Không có dữ liệu cũ cần giữ: khởi động stack bằng user `trading` trong `/opt/trading`. Dữ liệu bắt đầu từ lúc này và mọi khoảng trống trước đó là khoảng trống bao phủ đã được ghi.

```bash
docker compose up -d
```

- Có dữ liệu cũ: KHÔNG chạy lệnh trên; dùng `deploy/migrate.sh` (các bước 5.3 đến 5.8). Cutover khôi phục vào cơ sở dữ liệu trống nên không được có collector nào đã ghi vào đó.

#### Bước 5.3 Điều kiện tiên quyết của việc di chuyển (RUNBOOK 15.1, 19.4) [THỦ CÔNG] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY CŨ]` và `[MÁY EC2]`

1. Cả hai máy đã bootstrap (mục 4) và cùng chạy image `ops` của Phase 13.1. Máy cũ phải có image đó sẵn, vì phía cũ chạy `src.ops.backup dump` và `src.ops.cutover` trong nó. Dựng nó ở máy cũ tại một ref của Phase 13.1:

```bash
docker compose --profile ops build
```

2. Máy cũ phải chấp nhận `ssh` không tương tác với kiểm tra khóa máy chủ nghiêm ngặt (`BatchMode`, `StrictHostKeyChecking=yes`, nên máy cũ phải sẵn trong `known_hosts`), và user ssh trên máy cũ phải chạy được `docker compose` và `docker run` (thuộc nhóm docker).
3. Lưu ý Windows Docker Desktop (RUNBOOK 19.4 mục 3): nếu máy cũ là Windows với Docker Desktop thì điều kiện số 2 không có sẵn. Nếu không đáp ứng được, DỪNG và báo lại. Đường thay thế là đẩy một bản sao lưu từ máy cũ rồi `deploy/restore.sh` ở máy mới: khoảng trống dài hơn, cần cổng D064 trên S3 thật qua trước, và là một quyết định riêng của bạn.
4. RUNBOOK 15.1 đòi một bản sao lưu mới đã được diễn tập trước khi di chuyển, nhưng RUNBOOK 19.4 mục 6 nói bản sao lưu thật đầu tiên chờ cổng D064. RUNBOOK chưa hòa giải hai điều này; hướng dẫn này không tự quyết. Hãy hỏi và ghi lại quyết định của bạn trước khi chạy thật `[CHƯA XÁC MINH]`.
5. Máy mới đã dựng hai image (bước 4.9) nhưng chưa chạy `docker compose up -d`.

#### Bước 5.4 Khóa di chuyển (key directory) [THỦ CÔNG] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]` bằng user `trading`

Thư mục khóa (mặc định `~/.ssh/trading-migrate`, đổi bằng `--key-source`) phải chứa `id_ed25519` và `known_hosts` của máy cũ. Nó được gắn chỉ-đọc vào container nhận và không bao giờ được chép vào image. Tạo khóa chỉ dùng cho việc này:

```bash
mkdir -p ~/.ssh/trading-migrate
```

```bash
chmod 700 ~/.ssh/trading-migrate
```

```bash
ssh-keygen -t ed25519 -f ~/.ssh/trading-migrate/id_ed25519
```

Rồi thêm nửa công khai (`id_ed25519.pub`) vào các khóa được phép của user ssh trên máy cũ (`[MÁY CŨ]`, thủ công). Ghi khóa máy chủ của máy cũ vào `known_hosts` trong thư mục khóa, lấy từ một kênh bạn tin cậy (ví dụ đọc ngay trên máy cũ), không lấy tự động từ mạng. Xóa thư mục khóa sau cutover.

#### Bước 5.5 Thử ssh không tương tác sang máy cũ [THỦ CÔNG] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]` bằng user `trading`

Lệnh này mô phỏng đúng các tùy chọn mà `migrate.sh` dùng cho rsync và hỏi máy cũ có chạy được Docker không. Nó chưa từng được thử trên máy thật:

```bash
ssh -i $HOME/.ssh/trading-migrate/id_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$HOME/.ssh/trading-migrate/known_hosts trading@old.example docker ps
```

Nếu nó hỏi mật khẩu, báo lỗi khóa máy chủ hoặc báo không có quyền Docker, đừng chạy `migrate.sh`.

#### Bước 5.6 Chạy thử (dry-run) [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]` bằng user `trading` trong `/opt/trading` (phía mới luôn là `local`)

```bash
cd /opt/trading
```

```bash
deploy/migrate.sh --dry-run trading@old.example local
```

In kế hoạch có thứ tự và không chạy gì. Phía mới phải là `local`: một đích mới ở xa bị từ chối vì các đối số rsync sẽ mất cách trích dẫn qua bước ssh thứ hai.

#### Bước 5.7 Chạy thật [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]` bằng user `trading`

```bash
deploy/migrate.sh --key-source ~/.ssh/trading-migrate trading@old.example local
```

Thứ tự cố định: (1) kiểm tra trước, kể cả từ chối tiếp tục nếu một trong hai bên đã có `data/backup/cutover/pg.dump` từ lần thử trước; (2) đồng bộ trước Parquet khi collector cũ còn chạy; (3) dừng collector cũ, thứ duy nhất từng bị dừng trên máy cũ; (4) đồng bộ Parquet lần cuối; (5) trên máy cũ: `pg_dump`, dấu vân tay Parquet và ảnh chụp mốc; (6) kéo các tệp đó về; (7) khôi phục ở máy mới (băm của dump được kiểm tra, rồi `alembic upgrade head`); (8) khởi động collector mới, nó tiếp tục từ mốc đã khôi phục; (9) chờ nhịp mới đầu tiên (`--wait-seconds`, mặc định 900; hết giờ không phải lỗi, báo cáo sẽ cho thấy khoảng trống ở cuối); (10) in báo cáo cutover.

Việc truyền dữ liệu là rsync qua ssh trong container `ops` của máy mới chạy bằng root, với `--ignore-existing`, không có tùy chọn xóa nào, loại bỏ tệp tạm, và kiểm tra khóa máy chủ nghiêm ngặt theo `known_hosts` đã gắn. Mặc định phía xa chạy `docker run` image ops trên máy cũ với các volume cũ gắn chỉ-đọc. Đường thay thế `sudo rsync` không có script và chưa được kiểm thử; nếu cần, làm các bước đồng bộ bằng tay.

### Thẻ lệnh: deploy/migrate.sh

**Mục đích:** chuyển collector đang chạy, kho Parquet và cơ sở dữ liệu của nó từ một máy CŨ sang máy MỚI với một khoảng trống dữ liệu có giới hạn và được báo cáo. Nó không bao giờ tắt máy nào.

**Khi nào chạy:** một lần, khi cutover, sau khi các điều kiện ở bước 5.3 đã được đáp ứng và `--dry-run` đã được đọc.

**Chạy ở máy nào:** `[MÁY EC2]` (máy mới) bằng user `trading` trong checkout; đối số thứ hai luôn là `local`.

**Lệnh:**

```bash
deploy/migrate.sh --max-gap-minutes 60 --wait-seconds 900 --key-source ~/.ssh/trading-migrate trading@old.example local
```

| Cờ | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `--dry-run` | tắt | in kế hoạch có thứ tự, không chạy gì |
| `--max-gap-minutes N` | `60` | ngưỡng khoảng trống Open Interest; vượt ngưỡng thì mã thoát 3 |
| `--wait-seconds S` | `900` | thời gian chờ nhịp mới đầu tiên |
| `--key-source PATH_OR_VOLUME` | `~/.ssh/trading-migrate` (hoặc biến `MIGRATE_KEY_SOURCE`) | thư mục (hoặc volume có tên) chứa `id_ed25519` và `known_hosts` |
| `--report-only` | tắt | tính lại dấu vân tay và mốc của máy mới rồi in lại báo cáo so với tệp cũ đã lưu, ví dụ với ngưỡng chặt hơn |
| `-h`, `--help` | - | in cách dùng, mã thoát 0 |

Hai đối số vị trí: `<old-ssh-target>` (ví dụ `trading@old.example`) và `local`.

Các biến môi trường cho cấu trúc khác mặc định (đọc ở đầu script): `MIGRATE_OLD_COMPOSE`, `MIGRATE_NEW_COMPOSE`, `MIGRATE_RSYNC_SOURCE`, `MIGRATE_RSYNC_PATH`, `MIGRATE_REPORT_WINDOW_END`, `MIGRATE_POLL_SECONDS`; thêm trong thân script: `MIGRATE_OLD_DIR` (mặc định `/opt/trading`), `MIGRATE_OLD_PROJECT` (mặc định `trading`), `MIGRATE_NEW_DIR`, `MIGRATE_NEW_PROJECT`. Chỉ đổi chúng khi bạn thật sự hiểu cấu trúc của mình.

**Chạy thử:** in kế hoạch mười bước và không chạy gì.

```bash
deploy/migrate.sh --dry-run trading@old.example local
```

**Dấu hiệu thành công:** các dòng `== step N/10: ...` chạy hết, báo cáo cuối in ra và script thoát với mã 0. Báo cáo so dấu vân tay Parquet cũ và mới (bằng nhau về tập hợp đường dẫn và sha256), các hàng mốc, và đo khoảng trống Open Interest theo phút. Báo cáo JSON nằm trong volume `backupdata` ở `data/backup/cutover/report.json`.

**Mã thoát:** mã của script chính là mã của báo cáo:

| Mã | Ý nghĩa |
| --- | --- |
| 0 | sạch: không mất gì, khoảng trống OI trong ngưỡng |
| 1 | mất dữ liệu: một tệp Parquet hoặc một hàng mốc bị thiếu, bị đổi, hoặc đi lùi |
| 2 | lỗi đầu vào: tệp không đọc được hoặc đối số sai |
| 3 | khoảng trống OI vượt `--max-gap-minutes` |

Lưu ý: các lỗi kiểm tra trước (`die`) cũng thoát với mã 1 và lỗi đối số của script (`usage_error`) thoát với mã 2, cùng giá trị với mã báo cáo; hãy đọc thông báo `ERROR:` để phân biệt. Mã 3 là dữ liệu chứ không phải lỗi cần thử lại: hãy quyết định liệu cái hố đó có quan trọng với nghiên cứu hay không. Khoảng trống OI là mất vĩnh viễn; khoảng trống funding lấp lại được.

**Khi lỗi:**

| Dấu hiệu | Cách xử lý |
| --- | --- |
| `old side is not reachable or lacks the ops image` hoặc `new side ...` | kiểm tra ssh, khóa máy chủ, và image ops ở máy cũ (bước 5.3, 5.5) |
| `... already has .../pg.dump from an earlier run` | kiểm tra rồi tự tay xóa tệp đó ở bên báo; script từ chối tái sử dụng |
| `--key-source ... must contain id_ed25519 and known_hosts` | sửa thư mục khóa (bước 5.4) |
| `the new side must be 'local'` | chạy script ngay trên máy mới |
| `tick probe failed with exit N` | dừng và báo lại thông báo đầy đủ |
| script dừng sau khi collector cũ đã bị dừng | script in đúng lệnh `... start collector` để thu thập tiếp trên máy cũ; chạy nó. Máy cũ không bị xóa gì nên chỉ mất thời gian |

**Không bao giờ:** xóa dữ liệu (rsync không có tùy chọn xóa nào); dừng bất cứ thứ gì trên máy cũ ngoài service collector; chạy `down`; tắt máy; chép khóa vào image.

#### Bước 5.8 Đọc báo cáo [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]`

Dùng bảng mã thoát ở thẻ trên. Để xem lại báo cáo với ngưỡng khác, không cần chạy lại cutover (số 30 chỉ là ví dụ):

```bash
deploy/migrate.sh --report-only --max-gap-minutes 30 trading@old.example local
```

#### Bước 5.9 Ghi khoảng trống bao phủ (D059 mục 4) [THỦ CÔNG]

**Chạy ở:** `[MÁY CÓ MẠNG]`

Khoảng trống OI do `deploy/migrate.sh` in ra được ghi như một khoảng trống bao phủ: mỗi khoảng trống sau 2026-10-08 được viết xuống với lúc bắt đầu, lúc kết thúc và nguyên nhân, và bộ dữ liệu không bao giờ được gọi là "lịch sử đầy đủ" khi còn một khoảng trống đã biết. Nơi lưu bản ghi này chưa được repository quy định `[QUYẾT ĐỊNH CỦA BẠN]`.

#### Bước 5.10 Nếu dừng giữa chừng [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY CŨ]`

Nếu một bước thất bại sau khi collector cũ đã bị dừng, script in đúng lệnh `... start collector` để thu thập tiếp trên máy cũ. Hãy chạy đúng lệnh được in. Không gì trên máy cũ bị gỡ, nên bạn chỉ mất thời gian.

#### Bước 5.11 Sau một báo cáo sạch [THỦ CÔNG]

**Chạy ở:** `[MÁY CÓ MẠNG]` và `[MÁY EC2]`

Chỉ một con người mới tắt máy cũ, và chỉ sau mã thoát 0 (nếu muốn an toàn hơn thì sau một lần diễn tập mới trên máy mới). Script không bao giờ chạy `down`, không tắt máy và không xóa gì. Rồi:

1. Cập nhật IP whitelist của khóa Binance sang Elastic IP của máy mới (mục 8.2).
2. Chuyển dịch vụ heartbeat sang máy mới (mục 8.3).
3. Xóa thư mục khóa di chuyển.
4. Làm lại danh sách 8 mục của bước 4.7 trên máy mới.
5. Chạy các kiểm tra nghiệm thu của bước 3.8 theo thứ tự rồi kiểm tra tệp: `uv run python scripts/soak_host_acceptance.py acceptance.json`.
6. Chạy một lần diễn tập khôi phục trước soak dài (mục 6.6), khi cổng D064 đã qua.

Nguồn: `docs/operations/RUNBOOK.md`, `deploy/migrate.sh`, `docker-compose.yml`, `.env.example`, `Dockerfile`

## 6. Sao lưu, khôi phục và diễn tập

> **CẢNH BÁO.** Cổng D064 (bằng chứng trên một remote S3 thật, qua lớp crypt, kể cả đối tượng multipart) vẫn mở. Điều kiện `BACKUP_REAL_S3_GATE` chưa PASS. Vì vậy chưa có bản sao lưu thật nào được chạy, và mọi thứ ở mục này mới được kiểm thử với một S3 giả (S3 double). Đừng coi một bản sao lưu là đã bảo vệ dữ liệu của bạn cho tới khi cổng này qua và một lần diễn tập (restore drill) thành công.

### Chuỗi sao lưu bằng lời thường

- Mọi logic nằm trong `python -m src.ops.backup` chạy trong image `ops` của compose; các script `deploy/*.sh` chỉ là lớp vỏ mỏng truyền nguyên mã thoát của lệnh Python.
- Sao lưu được mã hóa ngay trên máy của bạn bằng `rclone` với lớp `crypt` rồi đẩy lên bất kỳ kho S3 nào (AWS S3, Backblaze B2 qua điểm cuối S3, Wasabi...). Nhà cung cấp chỉ thấy bản mã và tên tệp đã mã hóa.
- Bố cục trên remote: thư mục `parquet/` chỉ-thêm (copy với `--immutable`, không bao giờ đồng bộ, di chuyển hay xóa); mỗi bản sao lưu một thư mục `snapshots/<YYYYMMDDTHHMMSSZ>/` chứa `pg.dump` và `manifest.json`; và `_sentinel/sentinel.txt` để chứng minh khóa đúng trước mọi thao tác.
- Giữ lại theo quy tắc 7/4/6: bản mới nhất của mỗi ngày trong 7 ngày UTC gần nhất, 4 tuần ISO và 6 tháng có bản sao lưu; bản mới nhất luôn được giữ. Việc giữ lại chỉ chạy sau khi lần đẩy đã được kiểm bằng `cryptcheck`, và chỉ xóa các thư mục `snapshots/<id>`. Thư mục `parquet/` là dữ liệu nghiên cứu và không bao giờ bị xóa từ xa, nên bucket lớn dần theo bộ dữ liệu.
- Vì sao một snapshot cần cả `pg.dump` lẫn toàn bộ cây Parquet đã kiểm (D066): `manifest.json` chỉ được công bố sau khi cả cây Parquet và `pg.dump` đã qua `cryptcheck`. Không có bản sao lưu PostgreSQL đứng riêng trên remote, và không có lệnh nào công bố một snapshot mà Parquet chưa kiểm. Đây là chủ ý.
- Quản lý khóa: mất cụm mật khẩu crypt thì mọi bản sao lưu không thể phục hồi, và với khóa sai bucket trông như trống hoặc rối loạn; công cụ từ chối tiếp tục chứ không coi đó là kho trống. Giữ bản gốc của cụm mật khẩu và muối (`BACKUP_CRYPT_PASSWORD2`) ngoài VPS, trong trình quản lý mật khẩu cộng một bản ngoại tuyến.

#### Bước 6.1 Cấu hình remote [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY CÓ MẠNG]` (tạo bucket, khóa, đổi cụm mật khẩu), rồi `[MÁY EC2]` (đặt biến)

1. Tạo bucket mới và trống cùng một khóa truy cập chỉ có quyền trên nó (bước 3.6).
2. Chọn một cụm mật khẩu dài và một cụm thứ hai (muối). Trên máy trạm của bạn, không bao giờ trên VPS, đổi từng cụm sang dạng obscured bằng `rclone obscure -` (đọc từ stdin để tránh lịch sử shell). rclone từ chối cụm mật khẩu thô.
3. Đặt các biến sau vào `/opt/trading/.env` (mode 0600) bằng user `trading`. Một biến thiếu làm lệnh dừng và nêu TÊN biến, không bao giờ nêu giá trị:

```text
BACKUP_S3_PROVIDER=AWS
BACKUP_S3_REGION=ap-southeast-1
BACKUP_S3_BUCKET=<backup bucket>
BACKUP_S3_ACCESS_KEY_ID=<từ trình quản lý mật khẩu>
BACKUP_S3_SECRET_ACCESS_KEY=<từ trình quản lý mật khẩu>
BACKUP_CRYPT_PASSWORD=<kết quả rclone obscure>
BACKUP_CRYPT_PASSWORD2=<kết quả rclone obscure>
```

   `BACKUP_S3_PROVIDER` nhận `AWS`, `Wasabi` hoặc `Other`; với `Other` (ví dụ Backblaze B2) còn phải đặt thêm `BACKUP_S3_ENDPOINT`. Hai biến cuối nhận kết quả obscured, thứ có thể đảo ngược và không phải mã hóa.
4. Bật bảo vệ phía nhà cung cấp như một biện pháp của người vận hành: versioning hoặc object lock với thời hạn giữ, để một khóa bị đánh cắp không xóa được lịch sử. Các script không bao giờ xóa gì ngoài `snapshots/<id>` nhưng không ngăn được một khóa bị chiếm quyền.

#### Bước 6.2 Khởi tạo remote, đúng một lần, trên bucket trống [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]` bằng user `trading`

```bash
deploy/backup.sh --init-remote --dry-run
```

```bash
deploy/backup.sh --init-remote
```

Lệnh dựng một bundle ở `data/backup/bundle` (volume `backupdata`) rồi chạy `push --init-remote`, thứ chỉ ghi sentinel khi danh sách đã giải mã trống, danh sách thô của bucket trống và sentinel chưa tồn tại. Trên bucket không trống, hoặc với khóa sai, nó từ chối.

#### Bước 6.3 Cài timer hằng ngày [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]` bằng `sudo` (lệnh cài không đọc `.env`)

```bash
sudo deploy/backup.sh --install-timer --dry-run
```

```bash
sudo deploy/backup.sh --install-timer
```

Lệnh ghi `trading-backup.service` và `trading-backup.timer` vào `/etc/systemd/system`, thay đường dẫn checkout này vào đó, chạy `systemctl daemon-reload` chỉ khi một unit đổi, và bật timer. Nó phải chạy bằng root và từ chối đường dẫn checkout có khoảng trắng. Kiểm tra:

```bash
systemctl list-timers trading-backup.timer
```

```bash
systemctl status trading-backup
```

```bash
journalctl -u trading-backup
```

#### Bước 6.4 Chạy một bản sao lưu ngay [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]` bằng user `trading`

```bash
deploy/backup.sh --dry-run
```

```bash
deploy/backup.sh
```

Thứ tự: dump cơ sở dữ liệu, sao lưu Parquet, kiểm bundle với manifest sha256, đẩy lên (Parquet mới, rồi `cryptcheck` cây Parquet, rồi `pg.dump` và `cryptcheck` của nó, rồi kiểm bundle với manifest lần hai, rồi `manifest.json` và `cryptcheck` của nó), rồi áp dụng việc giữ lại. Bước nào lỗi thì lệnh, và cả unit systemd, lỗi một cách thấy được. Chú ý: không có gì trong repository ping một dịch vụ giám sát bên ngoài; nếu bạn không đăng ký một heartbeat ngoài VPS thì một máy chết hay một unit lỗi sẽ im lặng (mục 8.3).

#### Bước 6.5 Khôi phục lên một máy trống [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]` bằng user `trading`

Điều kiện: máy đã bootstrap, `.env` có cùng các giá trị `BACKUP_*` (các cụm mật khẩu obscured suy ra từ cụm thô bạn giữ ngoài VPS), và checkout ở phiên bản bạn muốn. Hãy đọc kế hoạch trước, rồi dùng `--no-start` để xem dữ liệu đã khôi phục trước khi collector chạy:

```bash
deploy/restore.sh --dry-run
```

```bash
deploy/restore.sh --snapshot 20260930T031500Z --no-start
```

Nó chỉ khởi động PostgreSQL, kéo bản sao lưu mới nhất đã kiểm (hoặc `--snapshot` bạn chỉ định) vào thư mục mới `data/backup/restore-<UTC timestamp>`, chạy bước khôi phục có từ chối (kiểm bundle, kiểm đích trống, `pg_restore`, sao chép Parquet không ghi đè vào `data/raw`, `alembic upgrade head`), rồi khởi động cả stack trừ khi có `--no-start`. Nó từ chối bundle bị đụng chạm, cơ sở dữ liệu hay đích Parquet không trống nếu không có `--force`, và dừng với bất kỳ tệp nào đã tồn tại với nội dung khác ngay cả khi có `--force`: tệp thô là bất biến.

#### Bước 6.6 Diễn tập khôi phục và nhịp độ [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]` bằng user `trading` (PostgreSQL của stack phải đang chạy)

```bash
deploy/backup-drill.sh --dry-run
```

```bash
deploy/backup-drill.sh
```

Một bản sao lưu chưa hợp lệ cho tới khi một lần diễn tập qua. RUNBOOK không cho một con số cho nhịp độ: chạy sau khi dựng xong, sau mọi thay đổi nhà cung cấp, khóa hay image, và định kỳ về sau. Chu kỳ định kỳ là `[QUYẾT ĐỊNH CỦA BẠN]`. Một collector thêm một hàng symbol mới đúng lúc diễn tập có thể làm phép so sánh lỗi: chạy lại.

#### Bước 6.7 Dọn dẹp thư mục cũ [THỦ CÔNG]

**Chạy ở:** `[MÁY EC2]` bằng user `trading`

`restore.sh` và lần diễn tập cố ý để lại các thư mục `data/backup/restore-<timestamp>` và `data/backup/drill-<timestamp>` trong volume `backupdata`; không script nào xóa đường dẫn của người vận hành. Xóa các thư mục cũ bằng tay, ví dụ như RUNBOOK 11.7:

```bash
docker compose --profile ops run --rm -T --no-deps ops rm -r /app/data/backup/drill-<timestamp>
```

Các con số giữ lại 7/4/6 là giá trị mặc định của `select_retained` trong `src/ops/backup_remote.py`, không phải biến môi trường; đổi chúng là một commit được duyệt.

#### Bước 6.8 Khi bước đẩy Parquet thất bại (RUNBOOK 11.8, D066) [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]`

Bước đẩy thoát với mã khác 0. Đọc cả thông báo bằng `journalctl -u trading-backup` (hoặc đầu ra terminal của `deploy/backup.sh`); những từ đầu cho biết đó là trường hợp nào. Không có tùy chọn ghi đè hay ép buộc nào, và bước đẩy không bao giờ ghi đè một đối tượng từ xa. Một lần từ chối vì nội dung khác nhau lặp lại ở mọi lần chạy lại tới khi nội dung được xử lý. Một lỗi tạm thời (mạng, một mã thoát rclone khác 1, `snapshot id ... already exists`) có thể qua ở lần chạy lại. Đường dẫn được nêu trong thông báo tối đa năm, rồi "and N more".

| Đầu thông báo | Nghĩa | Xem gì | Lặp lại? Ai quyết |
| --- | --- | --- | --- |
| `parquet push refused: path(s) already published with different content` | một snapshot hoàn chỉnh trên remote nêu một đường dẫn với sha256 khác tệp cục bộ, hoặc hai snapshot bất đồng ("manifests disagree"); không có gì được tải lên | đường dẫn và id snapshot trong thông báo; sha256 của tệp cục bộ với giá trị trong `manifest.json` cục bộ | lặp lại cho tới khi xử lý nội dung; bạn quyết |
| `parquet push refused: remote object(s) differ from the local file(s) and no complete snapshot names them` | một đường dẫn đã có trên remote (thường do lần đẩy trước chết trước khi có manifest) với nội dung khác tệp cục bộ; không có gì tải lên | như trên | lặp lại; bạn quyết |
| `parquet verification failed` | Parquet đã tải xong nhưng `cryptcheck` thấy cây Parquet trên remote khác cây cục bộ (đối tượng bị đổi, thiếu hay không đọc được, được nêu tên), hoặc chính phép kiểm lỗi với mã khác 1 (`rclone cryptcheck failed (exit N)` trong thông báo) | đọc N; không có thư mục snapshot, `pg.dump` hay `manifest.json` mới trên remote | lặp lại nếu có đường dẫn bị nêu; có thể qua ở lần chạy lại nếu N khác 1 (lỗi mạng hay công cụ) |
| `manifest verification failed: snapshot <id> left incomplete` | tải manifest hoặc kiểm nó lỗi và manifest đã bị gỡ lại; snapshot chỉ có `pg.dump` | thông báo mang lỗi rclone gốc | chạy lại có thể qua |
| `manifest verification failed AND the manifest of snapshot <id> could not be removed` | cả hai lần gỡ đều lỗi, nên snapshot trông hoàn chỉnh dù manifest đã không qua kiểm | gỡ đối tượng `snapshots/<id>/manifest.json` qua remote crypt (tên phía nhà cung cấp đã mã hóa nên console của họ không tìm được theo tên đó); đừng tin snapshot đó cho tới lúc gỡ xong | bạn quyết và tự làm |
| `refusing to publish manifest: bundle changed during push: <path>: sha256 mismatch` | một tệp của bundle thay đổi sau khi đã được kiểm và trước khi manifest được công bố; remote không sai; snapshot chỉ có `pg.dump` và còn dở | tìm cái gì ghi vào thư mục bundle nếu lặp lại | lần chạy theo lịch kế dựng bundle mới |
| `rclone cryptcheck failed (exit N)`, `rclone lsf failed (exit N)`, `rclone cat failed (exit N)`, `rclone copy failed (exit N)`, `rclone copyto failed (exit N)` | công cụ hoặc mạng lỗi, không phải một phát hiện về nội dung; việc liệt kê đọc mã 3 là thư mục chưa tồn tại, mọi mã khác kể cả 4 là lỗi và bước đẩy dừng trước khi ghi gì | đoạn trích sau mã thoát | chạy lại có thể qua; nếu lặp lại thì báo |
| `unreadable manifest of complete snapshot <id>` | không đọc hoặc không phân tích được một manifest từ xa, và từ chối thay vì bỏ qua; không có gì tải lên | id snapshot | báo lại |
| `snapshot id <id> already exists on the remote` | một snapshot cùng id (theo giây UTC) đã hoàn chỉnh; không có gì được ghi | không | chạy lại có thể qua |

**Khi cây Parquet bị hỏng (D066).** Một lần khôi phục thất bại trước khi chạm cơ sở dữ liệu: `deploy/restore.sh` chạy `pull` trước, nó chép thư mục snapshot, lấy đúng các tệp Parquet mà manifest nêu và kiểm cả bundle; một đối tượng thiếu hay bị đổi dừng nó ở đó với `pulled bundle failed verification` và một dòng `missing from bundle` hay `sha256 mismatch`. Không bao giờ có trạng thái cơ sở dữ liệu đã khôi phục trong khi tệp Parquet không qua kiểm. Đừng cho rằng một snapshot cũ hơn khôi phục được: cây `parquet/` dùng chung cho mọi snapshot và không bị xóa, nên một đối tượng mất hay hỏng làm mọi snapshot hoàn chỉnh có nêu đường dẫn đó không kéo về được. Để tìm snapshot mới nhất khôi phục được, thử từ mới nhất xuống, mỗi lần vào một thư mục trống riêng:

```bash
docker compose --profile ops run --rm -T --no-deps ops /app/.venv/bin/python -m src.ops.backup pull --dest <empty dir> --snapshot <snapshot id>
```

Snapshot đầu tiên kéo về không lỗi là bản mới nhất đã kiểm; khôi phục nó bằng `deploy/restore.sh --snapshot <snapshot id>`. Nếu không cái nào kéo được thì không có điểm khôi phục đã kiểm và lựa chọn tiếp theo là của bạn, không phải của hướng dẫn này. Mô tả này chỉ nói về chuỗi sao lưu; nó không biến một bản sao lưu thành bản ghi bằng chứng bền vững của Phase 16.

### Thẻ lệnh: deploy/backup.sh

**Mục đích:** lớp vỏ gọi `python -m src.ops.backup` trong image ops của compose, với ba chế độ: chạy một bản sao lưu theo lịch ngay bây giờ, khởi tạo remote lần đầu, hoặc cài timer hằng ngày. Nó không giữ logic sao lưu, mã hóa hay remote nào.

**Khi nào chạy:** chế độ `--init-remote` đúng một lần trên bucket trống; chế độ `--install-timer` một lần khi dựng máy; chế độ trần mỗi khi bạn muốn một bản sao lưu ngay (timer gọi nó mỗi ngày) và trước mỗi lần cập nhật.

**Chạy ở máy nào:** `[MÁY EC2]`; hai chế độ đầu bằng user `trading`, chế độ cài timer bằng `sudo`.

**Lệnh:**

```bash
deploy/backup.sh
```

```bash
deploy/backup.sh --init-remote
```

```bash
sudo deploy/backup.sh --install-timer
```

Cờ: `--init-remote` (khởi tạo remote), `--install-timer` (cài hai unit và bật timer), `--dry-run` (in kế hoạch), `-h`/`--help`. Hai cờ `--init-remote` và `--install-timer` không dùng chung được. Biến môi trường `COMPOSE_PROJECT_NAME` và `TRADING_ENV_FILE` được tôn trọng.

**Chạy thử:** mỗi chế độ có `--dry-run` riêng, in lệnh sẽ chạy mà không chạy:

```bash
deploy/backup.sh --dry-run
```

```bash
deploy/backup.sh --init-remote --dry-run
```

```bash
sudo deploy/backup.sh --install-timer --dry-run
```

**Dấu hiệu thành công:** chế độ trần: lệnh `scheduled` kết thúc với mã 0 và nhật ký có `push-OK snapshot=<id>`; `journalctl -u trading-backup` cho thấy unit chạy xong. Chế độ cài timer: `systemctl list-timers trading-backup.timer` liệt kê timer.

**Mã thoát:** `-h` thoát 0. Lỗi cờ (cờ lạ, dùng chung `--init-remote` với `--install-timer`) thoát 2 (`usage_error`). Cài timer không phải root, đường dẫn checkout có khoảng trắng hay thiếu mẫu unit thoát 1 (`die`). Ở các chế độ khác, mã thoát chính là mã của lệnh Python; ý nghĩa từng số không được script liệt kê `[CHƯA XÁC MINH]`, hãy đọc thông báo.

**Khi lỗi:** một biến `BACKUP_*` thiếu: lệnh nêu tên biến (bước 6.1). Lỗi đẩy Parquet: bảng ở bước 6.8. `--install-timer must run as root`: chạy với `sudo`.

**Không bao giờ:** xóa gì ngoài các thư mục `snapshots/<id>` theo quy tắc giữ lại; ghi đè một đối tượng từ xa; cung cấp tùy chọn ép buộc; ping một dịch vụ giám sát bên ngoài.

### Thẻ lệnh: deploy/systemd/trading-backup.service

**Mục đích:** unit systemd kiểu oneshot gọi `deploy/backup.sh` mỗi lần timer kích hoạt, để một bản sao lưu lỗi làm unit lỗi một cách thấy được.

**Khi nào chạy:** không chạy tay. Nó được cài bởi `sudo deploy/backup.sh --install-timer` và được timer gọi. Các thiết lập đáng biết: `User=trading`, `TimeoutStartSec=2h`, `Requires=docker.service`, `WorkingDirectory` và `ExecStart` mang thẻ thay thế thư mục checkout mà bộ cài điền.

**Chạy ở máy nào:** `[MÁY EC2]`, dưới systemd.

**Lệnh:** cài bằng lệnh sau; xem trạng thái và nhật ký bằng hai lệnh còn lại.

```bash
sudo deploy/backup.sh --install-timer
```

```bash
systemctl status trading-backup
```

```bash
journalctl -u trading-backup
```

**Chạy thử:** Không áp dụng cho chính tệp unit, vì nó không được chạy tay. Để xem trước việc cài, dùng lệnh `sudo deploy/backup.sh --install-timer --dry-run` ở thẻ `deploy/backup.sh`.

**Dấu hiệu thành công:** `systemctl status trading-backup` cho thấy lần chạy gần nhất thoát thành công, và `journalctl -u trading-backup` có `push-OK`.

**Mã thoát:** unit lỗi khi lớp vỏ thoát khác 0, tức là mã thoát của lệnh `python -m src.ops.backup scheduled`; vì vậy một bản sao lưu lỗi hiện ra như một unit lỗi.

**Khi lỗi:** đọc `journalctl -u trading-backup`; dùng bảng ở bước 6.8 cho các lỗi đẩy Parquet.

**Không bao giờ:** sửa tay bản đã cài trong `/etc/systemd/system` (bộ cài ghi lại khi nội dung khác); đổi `User=` sang tài khoản không thuộc nhóm docker; cài khi đường dẫn checkout có khoảng trắng (bộ cài từ chối).

### Thẻ lệnh: deploy/systemd/trading-backup.timer

**Mục đích:** timer kích hoạt `trading-backup.service` hằng ngày lúc 03:15 UTC.

**Khi nào chạy:** không chạy tay. `OnCalendar=*-*-* 03:15:00 UTC`; `Persistent=true` để một lần bị lỡ trong lúc máy tắt được chạy bù sau đó; `RandomizedDelaySec=5m` để nhiều máy không cùng đập nhà cung cấp trong cùng một giây; `Unit=trading-backup.service`.

**Chạy ở máy nào:** `[MÁY EC2]`, dưới systemd.

**Lệnh:** timer được cài và bật bởi cùng lệnh cài, và kiểm tra bằng:

```bash
sudo deploy/backup.sh --install-timer
```

```bash
systemctl list-timers trading-backup.timer
```

**Chạy thử:** Không áp dụng cho chính tệp unit. Xem trước bằng `sudo deploy/backup.sh --install-timer --dry-run`.

**Dấu hiệu thành công:** `systemctl list-timers trading-backup.timer` liệt kê timer với thời điểm kích hoạt kế tiếp.

**Mã thoát:** timer không có mã thoát; kết quả nằm ở unit service mà nó kích hoạt.

**Khi lỗi:** timer không xuất hiện: chạy lại lệnh cài và đọc đầu ra của nó. Timer có nhưng không chạy: `systemctl status trading-backup` và `journalctl -u trading-backup`. Việc timer kích hoạt đúng giờ và chạy bù sau thời gian tắt máy chỉ máy thật mới chứng minh được `[CHƯA XÁC MINH]`.

**Không bao giờ:** thay lịch bằng tay trong bản đã cài (bộ cài ghi lại); coi timer đang bật là bằng chứng bản sao lưu có hiệu lực trước khi cổng D064 qua và một lần diễn tập thành công.

### Thẻ lệnh: deploy/restore.sh

**Mục đích:** khôi phục bản sao lưu đã kiểm mới nhất từ xa lên một máy TRỐNG.

**Khi nào chạy:** khi dựng lại sau mất máy, hoặc khi cần quay về từ một bản sao lưu (ví dụ sau một migration mà mã cũ không đọc được, mục 11).

**Chạy ở máy nào:** `[MÁY EC2]` bằng user `trading` trong checkout.

**Lệnh:**

```bash
deploy/restore.sh --snapshot 20260930T031500Z --force --no-start
```

Cờ: `--snapshot ID` (id dạng `YYYYMMDDTHHMMSSZ`; không có thì dùng bản mới nhất), `--force` (cho phép đích không trống; tệp không bao giờ bị ghi đè), `--no-start` (không khởi động stack sau khi khôi phục), `--dry-run`, `-h`/`--help`.

**Chạy thử:**

```bash
deploy/restore.sh --dry-run
```

**Dấu hiệu thành công:** các bước `pull`, `restore` kết thúc không lỗi; với `--no-start` có dòng "restore finished; the stack was not started (--no-start)"; không có `--no-start` thì `docker compose up -d` chạy cuối.

**Mã thoát:** `-h` thoát 0. `--snapshot` sai dạng hoặc cờ lạ thoát 2 (`usage_error`). Một bước lỗi thì script dừng với chính mã của bước đó.

**Khi lỗi:** `pulled bundle failed verification` (bảng ở bước 6.8, mục D066: thử snapshot cũ hơn); đích không trống: kiểm tra trước khi dùng `--force`; `already exists in the target with different content`: dừng và điều tra, không có tùy chọn nào ghi đè.

**Không bao giờ:** ghi đè một tệp Parquet đã tồn tại; khôi phục khi cây Parquet không qua kiểm; chạy trên một máy đang có dữ liệu thật mà chưa có sao lưu.

### Thẻ lệnh: deploy/backup-drill.sh

**Mục đích:** chứng minh cả chuỗi sao lưu mà không đụng dữ liệu sống: sao lưu, đẩy, kéo snapshot vào `data/backup/drill-<UTC timestamp>`, kiểm, khôi phục vào một cơ sở dữ liệu tạm tên `<db>_drill_<YYYYMMDDHHMMSS>`, so sánh số hàng `collector_watermarks` với bản sống rồi xóa cơ sở dữ liệu tạm.

**Khi nào chạy:** sau khi dựng xong, sau mọi thay đổi nhà cung cấp, khóa hay image, và định kỳ về sau (chu kỳ `[QUYẾT ĐỊNH CỦA BẠN]`).

**Chạy ở máy nào:** `[MÁY EC2]` bằng user `trading`; PostgreSQL của stack phải đang chạy.

**Lệnh:**

```bash
deploy/backup-drill.sh
```

Cờ: `--dry-run`, `-h`/`--help`. Không có cờ nào khác.

**Chạy thử:**

```bash
deploy/backup-drill.sh --dry-run
```

**Dấu hiệu thành công:** lệnh con `drill-remote` kết thúc với mã 0 và thư mục tạm còn lại để bạn kiểm.

**Mã thoát:** `-h` thoát 0; cờ lạ thoát 2; còn lại là mã của chính lần diễn tập.

**Khi lỗi:** so sánh lỗi vì một collector vừa thêm một hàng symbol: chạy lại. Mọi lỗi đẩy hay kéo: bảng ở bước 6.8.

**Không bao giờ:** chạm dữ liệu sống (cơ sở dữ liệu tạm bị xóa sau đó); tự xóa thư mục `drill-<timestamp>` (bạn xóa tay, bước 6.7).

### Thẻ lệnh: scripts/backup-drill.ps1

**Mục đích:** lớp vỏ PowerShell mỏng chạy hai lệnh con `backup` rồi `drill` của `python -m src.ops.backup` trên một bundle cục bộ; mọi logic nằm trong module Python, script chỉ chuyển đối số và đưa mã thoát ra ngoài. Script này không gọi `push`, `pull` hay `drill-remote`, nên không đụng tới chuỗi S3 mã hóa của Phase 13.1; nó thuộc giai đoạn Phase 2 (bundle cục bộ), và trên Linux việc của nó là `deploy/backup-drill.sh`.

**Khi nào chạy:** chỉ khi bạn ở trên Windows và muốn diễn tập bundle cục bộ; không phải bước bắt buộc của hướng dẫn này.

**Chạy ở máy nào:** `[MÁY PHÁT TRIỂN]` hoặc một `[MÁY CŨ]` chạy Windows; không bao giờ trên `[MÁY EC2]`.

**Lệnh:**

```powershell
powershell -NoProfile -File scripts/backup-drill.ps1
```

Biến môi trường (theo header của script): `BACKUP_TARGET` (gốc sao lưu, mặc định `data/backup`; nếu thiếu thì dùng `OFF_HOST_BACKUP_TARGET`), `SCRATCH_ROOT` (mặc định `data/backup-drill`), `PARQUET_ROOTS` (các gốc Parquet, ngăn cách bằng `;`, mặc định `data/raw`), `PYTHON_BIN` (mặc định `python`).

**Chạy thử:** Không áp dụng: script không có cờ chạy thử và nhận đối số qua biến môi trường. Pha `drill` làm việc trên một thư mục tạm riêng (`SCRATCH_ROOT`).

**Dấu hiệu thành công:** script in `backup-drill: drill-OK` và thoát 0.

**Mã thoát:** 0 khi cả hai pha qua; khi một pha lỗi, script thoát với chính mã thoát của pha đó (kèm dòng lỗi "backup phase failed" hoặc "drill phase failed").

**Khi lỗi:** đọc dòng lỗi của pha tương ứng; mô-đun Python in chi tiết. Việc nó có chạy được trên máy của bạn (cần `pg_dump` và môi trường Python) chưa được kiểm chứng `[CHƯA XÁC MINH]`.

**Không bao giờ:** dùng thay cho lần diễn tập chuỗi S3 của `deploy/backup-drill.sh`; chạy trên Linux.

Nguồn: `docs/operations/RUNBOOK.md`, `deploy/backup.sh`, `deploy/restore.sh`, `deploy/backup-drill.sh`, `deploy/systemd/trading-backup.service`, `deploy/systemd/trading-backup.timer`, `scripts/backup-drill.ps1`, `src/ops/backup.py`, `docs/DECISIONS.md`

## 7. Paper runtime và soak SHADOW (Phase 16)

#### Bước 7.1 Phase 16 làm gì, bằng lời thường [CHƯA XÂY]

**Chạy ở:** đọc, không chạy gì (`[MÁY PHÁT TRIỂN]` cho mã, `[MÁY EC2]` cho soak)

Phase 16 dựng một tiến trình paper chạy được: nó theo dõi dữ liệu thị trường Binance trực tiếp, tạo tín hiệu và kế hoạch, và gửi cho bạn các thông báo Telegram nhãn SHADOW kèm nút APPROVE/SKIP rồi bước CONFIRM (D041), ghi nhật ký quyết định cùng các lần khớp lệnh mô phỏng, và không có bất kỳ đường nào dẫn tới một lệnh thật (D040). Mục đích là bắt đầu một đợt soak tính theo đồng hồ treo tường để quan sát. Những tiêu chí thành công (SC) quan trọng với người vận hành, theo ROADMAP: SC2 adapter WebSocket thật sự `await` lời gọi SDK; SC3 nút SIMULATE hoạt động và độ trễ phê duyệt được đo chứ không cố định 30 giây; SC5 thông báo ghi rõ "SHADOW" và mọi quyết định được ghi nhật ký; SC6 cô lập cứng (không khóa giao dịch, không adapter lệnh); SC7 một lần smoke trực tiếp; SC8 và SC9 trial soak và quy tắc đóng yêu cầu. Hôm nay mới có 14 trong 49 kế hoạch.

#### Bước 7.2 Hôm nay máy EC2 chạy được gì [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]`

Chỉ ba service chạy theo mặc định: `postgres`, `db-upgrade` (chạy một lần) và `collector`. Service `paper` trong compose (profile `paper`) là một khung giữ chỗ chạy là thoát ngay: nó in "paper runner not implemented yet: arrives in Phase 16" và `restart` là `"no"`. Bạn không có gì để khởi động bằng profile `paper` hôm nay.

#### Bước 7.3 Bảng đủ 49 kế hoạch của Phase 16 [ĐÃ XÂY] [CHƯA XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY CÓ MẠNG]` (chỉ để đọc; không có máy nào chạy gì ở bước này)

Quy tắc đọc: 16-01 đến 16-14 có tệp SUMMARY trong `.planning/phases/16-paper-runtime-composition/`, nên được ghi `[ĐÃ XÂY]`; 16-15 đến 16-49 chưa có, nên là `[CHƯA XÂY]`. Lưu ý: "đã xây" nghĩa là code và kiểm thử ở mức đồ giả; chưa có gì chạy trên máy EC2, nên các hàng cần bằng chứng trên máy thật, sàn thật hay Telegram thật còn mang thêm `[CHƯA XÁC MINH]`. Ngày đọc: 2026-10-09.

| Kế hoạch | Việc | Trạng thái | Dùng ở bước nào |
| --- | --- | --- | --- |
| 16-01 | Viết lại adapter WebSocket paper theo đúng hình dạng thật của SDK Binance và buộc mọi đồ giả theo hình dạng đó | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` | nền của runtime (7.4); bằng chứng trên socket thật nằm ở 16-21 |
| 16-02 | Siết kiểm tra từng mục của allowlist paper và để cổng khởi động cùng vòng lặp đọc chung một registry | `[ĐÃ XÂY]` | cổng PAPER_START_ALLOWLIST (7.6) |
| 16-03 | Tách phần dữ liệu thị trường công khai khỏi adapter lệnh để runtime SHADOW không bao giờ dựng adapter lệnh | `[ĐÃ XÂY]` | cô lập SHADOW (7.8) |
| 16-04 | Biến một kế hoạch thành cảnh báo SHADOW có nhãn với nút APR/SKP và hai hàng phê duyệt PENDING | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` | 8.1; chạm Telegram thật ở 16-40 |
| 16-05 | Chốt chặn kill-gate: báo "NOT CONCLUDED" thay vì kết luận khi bằng chứng thật còn các mục review chưa xử lý | `[ĐÃ XÂY]` | 9 |
| 16-06 | Bộ chạy nghiên cứu chỉ chạy khi có tệp ủy quyền của bạn gắn băm của lưới tham số và của manifest dữ liệu | `[ĐÃ XÂY]` | chuỗi đóng (7.6) |
| 16-07 | Văn bản RUNBOOK 19 cho máy EC2 và bộ kiểm tra hồ sơ nghiệm thu | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` | mục 3 |
| 16-08 | Supervisor paper bất đồng bộ chỉ giao nến đóng, tự bù bằng REST khi đứt kết nối, ghi khoảng trống có mã lý do | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` | runtime (7.4) |
| 16-09 | Kiểm tra freeze hằng giờ đọc bộ tham số được cấp qua allowlist, báo SKIPPED khi allowlist rỗng | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` | 7.6, 7.7 |
| 16-10 | Hạt nhân đánh giá từng nến đóng cho runtime và bộ so sánh bề mặt quyết định với dung sai bằng không | `[ĐÃ XÂY]` | runtime (7.4) |
| 16-11 | Bước CONFIRM của D041 chạy trong SHADOW, hiệu lực 60 giây, dùng một lần | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` | 8.1 |
| 16-12 | Cổng khả thi và cỡ mẫu, chỉ báo cáo, không hạ ngưỡng, không xếp hạng | `[ĐÃ XÂY]` | chuỗi đóng (7.6) |
| 16-13 | Bộ kiểm tra đăng ký ứng viên: bộ tham số đủ lý do cho từng giá trị, không còn PLACEHOLDER, có băm | `[ĐÃ XÂY]` | chuỗi đóng (7.6) |
| 16-14 | Điều kiện tiên quyết cho máy EC2 và hai quyết định của bạn (O-12 hoãn, Q-L bot riêng) | `[ĐÃ XÂY]` | 2.2, 8.1 |
| 16-15 | Hàm thuần tính bằng chứng sức khỏe và độ bao phủ của runtime, và tính liên tục của tick freeze (EVIDENCE_GAP) | `[CHƯA XÂY]` | 7.7 |
| 16-16 | Một cổng lưu trạng thái sống qua khởi động lại (epoch đã ghim, nến cuối, khoảng trống, heartbeat) và bản ghi giải thích mọi khoảng trống | `[CHƯA XÂY]` | 7.5 |
| 16-17 | Công cụ cho lần smoke trực tiếp SC7 và ghi nhận các dữ kiện bên ngoài mà phase dựa vào | `[CHƯA XÂY]` | 7.10 |
| 16-18 | Hoàn thiện báo cáo của bộ chạy: vùng phẳng tham số, số lệnh giữ qua lỗ hổng mark price, giới hạn của chi phí mô hình | `[CHƯA XÂY]` | 7.6 |
| 16-19 | Bộ tạo khớp lệnh mô phỏng dùng đúng ngữ nghĩa khớp của Phase 14 trên nến 1 phút trực tiếp | `[CHƯA XÂY]` | 7.4 |
| 16-20 | Tạo máy EC2 và chuyển collector (bước của bạn, chặn bởi O-12) | `[CHƯA XÂY]` | mục 3 đến 5 |
| 16-21 | Chạy smoke trực tiếp SC7, chỉ dữ liệu công khai, không khóa | `[CHƯA XÂY]` | 7.10 |
| 16-22 | Điểm vào `python -m src.paper.runtime`, cổng khởi động một lần, lớp môi trường của cô lập SHADOW | `[CHƯA XÂY]` | 7.4 |
| 16-23 | Sổ cái mô phỏng cho SHADOW, vốn ban đầu đúng bằng vốn live dự định | `[CHƯA XÂY]` | 7.4 |
| 16-24 | Đường ống xử lý từng nến đóng của runtime | `[CHƯA XÂY]` | 7.4 |
| 16-25 | Bộ đánh giá tiêu chí thoát và quy tắc đóng yêu cầu | `[CHƯA XÂY]` | 7.7 |
| 16-26 | Vòng lặp sống của tiến trình paper: asyncio, hàng đợi, kiểm tra lệch đồng hồ | `[CHƯA XÂY]` | 7.4 |
| 16-27 | Gom mọi con số định nghĩa feed khỏe và để bạn phê chuẩn trước trial soak (O-07) | `[CHƯA XÂY]` | 7.7 |
| 16-28 | Cổng giao thức v2.2.0 trước khi cho phép chạy nghiên cứu | `[CHƯA XÂY]` | 7.6 |
| 16-29 | Khởi động lại an toàn: warm-up từ REST, trạng thái lấy từ cơ sở dữ liệu soak, nến lỡ là khoảng trống chứ không là tín hiệu | `[CHƯA XÂY]` | 7.9 |
| 16-30 | Xuất bằng chứng trial thành một gói kiểm chứng được và đưa hai quyết định lưu trữ cho bạn | `[CHƯA XÂY]` | 7.7 |
| 16-31 | Nối các mảnh SHADOW đã xây rời nhau vào tiến trình đang chạy | `[CHƯA XÂY]` | 7.4 |
| 16-32 | Cấu hình triển khai soak cụ thể: service paper có probe thật, project compose riêng, volume cơ sở dữ liệu riêng | `[CHƯA XÂY]` | 7.5 |
| 16-33 | Phần vận hành soak của runbook và ý nghĩa của "image đã ghim" | `[CHƯA XÂY]` | 7.5 |
| 16-34 | Ghi đầu vào tài khoản và phạm vi của bạn cho cỡ lệnh SHADOW và tệp cấu hình runtime | `[CHƯA XÂY]` | 7.4 |
| 16-35 | Thay độ trễ phê duyệt cố định 30 giây bằng độ trễ đo được và thêm các trường bản ghi SHADOW | `[CHƯA XÂY]` | 7.4 |
| 16-36 | Báo cáo lịch sử quyết định SHADOW qua đường phân tích sẵn có | `[CHƯA XÂY]` | 7.7 |
| 16-37 | Chốt nội dung dữ liệu của lần nghiên cứu thật đầu tiên và đóng băng thành manifest | `[CHƯA XÂY]` | 7.6 |
| 16-38 | Chứng minh SC6 bằng ba lớp: không khóa giao dịch, không dựng adapter lệnh, không đường nào từ CONFIRM tới lệnh | `[CHƯA XÂY]` | 7.8 |
| 16-39 | Đường thử riêng cho một tín hiệu thử có nhãn, chạy trước trial soak | `[CHƯA XÂY]` | 7.10 |
| 16-40 | Chạy buổi diễn tập tín hiệu thử với các cú chạm Telegram thật | `[CHƯA XÂY]` | 7.10 |
| 16-41 | Đưa hai câu hỏi bằng chứng mở (OQ-1 và O-10) cho bạn sau lần nghiên cứu thật đầu | `[CHƯA XÂY]` | 7.6 |
| 16-42 | Bạn cho phép đúng một băm trong PAPER_START_ALLOWLIST | `[CHƯA XÂY]` | 7.6 |
| 16-43 | Paper bắt đầu, epoch được ghim, trial soak khởi động | `[CHƯA XÂY]` | 7.6 |
| 16-44 | Trial soak đạt tiêu chí đã phê chuẩn và bạn tuyên bố đạt | `[CHƯA XÂY]` | 7.6 |
| 16-45 | Giả thuyết và lưới tham số do bạn viết hoặc duyệt | `[CHƯA XÂY]` | 7.6 |
| 16-46 | Lệnh riêng của bạn cho phép chạy nghiên cứu, rồi lần chạy thật đầu tiên | `[CHƯA XÂY]` | 7.6 |
| 16-47 | Cài vào code hai quyết định lưu trữ bằng chứng và cách freeze check lấy epoch đã ghim | `[CHƯA XÂY]` | 7.7 |
| 16-48 | Bạn chỉ định ứng viên hợp lệ trong số các ứng viên đã đăng ký | `[CHƯA XÂY]` | 7.6 |
| 16-49 | Cấu hình đích lưu bằng chứng bền vững bạn đã chọn và chứng minh đường công bố bằng gói thử | `[CHƯA XÂY]` | 7.7 |

#### Bước 7.4 Điểm vào của runtime [CHƯA XÂY]

**Chạy ở:** `[MÁY EC2]` (khi nó tồn tại)

Điểm vào dự kiến của tiến trình paper là module dưới đây (kế hoạch 16-22). Nó là `[CHƯA XÂY]`: repository không có tệp src/paper/runtime.py. Khối dưới đây chỉ để bạn biết tên; đừng chạy nó và đừng tìm cờ của nó:

```bash
python -m src.paper.runtime
```

Vòng lặp sống, pipeline từng nến, sổ cái mô phỏng, bộ tạo khớp lệnh, độ trễ đo được và việc nối các mảnh SHADOW là các kế hoạch 16-19, 16-23, 16-24, 16-26, 16-31, 16-34, 16-35 trong bảng ở bước 7.3; tất cả là `[CHƯA XÂY]`.

#### Bước 7.5 Cấu hình triển khai soak và phần vận hành [CHƯA XÂY]

**Chạy ở:** `[MÁY EC2]` (khi các kế hoạch tồn tại)

Cấu hình triển khai soak cụ thể (kế hoạch 16-32) và phần vận hành soak của runbook (16-33) chưa tồn tại. Các quy tắc ĐÃ quyết định (D061 hosts) mà chúng sẽ tuân theo: cơ sở dữ liệu soak tách khỏi cơ sở dữ liệu phát triển và kiểm thử; soak chạy từ một image đã ghim chứ không từ cây làm việc; sao lưu phải tồn tại trước soak dài; và không bao giờ chạy `docker compose down` kèm cờ xóa volume trên project soak. Cách một image "đã ghim" được tạo ra (CI hôm nay không đẩy image nào) cũng là việc của 16-33.

#### Bước 7.6 Chuỗi đóng (closure chain) và ai quyết định từng bước [THỦ CÔNG] [CHƯA XÂY]

**Chạy ở:** `[MÁY CÓ MẠNG]` cho mọi bước chạm Binance hoặc Telegram

Phase 16 chỉ đóng sau chuỗi dưới đây (D061 mục J). Mọi bước chạm Binance hoặc Telegram là blocking-human: không có gì tự tiến.

1. Runtime sẵn sàng, được chứng minh bởi 16-38 và buổi diễn tập 16-40.
2. Bạn viết hoặc duyệt giả thuyết và lưới tham số (16-45); agent chỉ soạn nháp bằng ngôn ngữ thường kèm lý do và nguồn.
3. Một LỆNH RIÊNG của bạn cho phép chạy nghiên cứu (16-46); duyệt lưới không có nghĩa là cho phép chạy. Trước đó phải có bản sửa giao thức v2.2.0 (16-28, D065) như một nhiệm vụ tiên quyết riêng.
4. Một ứng viên hợp lệ (có lý do, đã đăng ký trước, đúng cấu trúc, không còn PLACEHOLDER, đã đăng ký và có băm) được bạn chỉ định (16-48). Nó KHÔNG cần qua G1 đến G5, và G1 đến G5 không bao giờ dùng để xếp hạng ứng viên.
5. Bạn cho phép đúng băm đó trong `PAPER_START_ALLOWLIST` bằng `strategy_id`, `parameter_set_id` và SHA-256 64 ký tự cùng `purpose`, `approved_at`, `basis` (16-42). Hôm nay allowlist RỖNG theo quyết định của bạn; đó là trạng thái an toàn hợp lệ, không phải lỗi.
6. Paper bắt đầu và epoch được ghim (16-43). Mỗi chuyển trạng thái là một lệnh rõ ràng của bạn.
7. Trial soak đạt các tiêu chí đã phê chuẩn và bạn tuyên bố đạt (16-44).

Không được chọn bất kỳ giá trị nào từ kết quả backtest hay nghiên cứu. Hai câu hỏi bằng chứng mở (OQ-1 về lệnh giữ qua lỗ hổng mark price, và O-10 về chi phí mô hình) được hỏi bạn sau lần nghiên cứu thật đầu (16-41).

#### Bước 7.7 Tiêu chí thoát đã phê chuẩn và bằng chứng [CHƯA XÂY]

**Chạy ở:** `[MÁY EC2]` tạo bằng chứng; `[MÁY CÓ MẠNG]` đọc kết quả

Các tiêu chí sau đã được bạn phê chuẩn ngày 2026-10-07 (D061 mục D; nhãn DECISION, chọn vì lý do vận hành, không bao giờ suy từ kết quả backtest hay nghiên cứu):

- Trial soak dài 14 ngày lịch trên máy EC2, tức 336 giờ.
- Độ bao phủ runtime ít nhất 95 phần trăm của cửa sổ với feed khỏe, tức 319,2 trong 336 giờ. Chỉ thời gian HEALTHY được tính là đã bao phủ; một lần khởi động lại có kế hoạch, một sự cố hay mọi khoảng trống khác, có giải thích hay không, đều là thời gian chưa bao phủ và mang mã lý do (D063 mục 1). Phân bố theo giờ trong ngày chỉ được báo cáo, không là điều kiện đạt.
- Kiểm tra freeze phải CLEAN ở mọi tick từ lúc ghim epoch tới hết trial; một tick lịch bị thiếu là EVIDENCE_GAP, không bao giờ CLEAN, và làm khởi động lại cửa sổ đủ điều kiện (D063 mục 2).
- Dung sai parity bằng không cho logic quyết định (cùng các nến đóng cho cùng tín hiệu, kế hoạch và phán quyết rủi ro).
- Mọi khoảng trống phải được giải thích bởi một lần dừng tiến trình hay mất kết nối đã ghi; không có nến bịa và không có khoảng trống không giải thích.
- Sau mỗi lần khởi động lại, warm-up xong rồi mới đánh giá nến đầu tiên; không có tín hiệu trùng và không thiếu hàng nhật ký.
- Không có số lệnh tối thiểu. Một tín hiệu thử có nhãn chỉ được chạy ở buổi diễn tập riêng trước trial, không bao giờ trong soak và không bao giờ tính là bằng chứng chiến lược (D063 mục 3).

Muốn đổi bất kỳ tiêu chí nào trước khi trial bắt đầu phải có sự chấp thuận mới của bạn. Bộ đánh giá (16-25), hàm bằng chứng (16-15), gói xuất (16-30), con số định nghĩa feed khỏe (16-27) và đích lưu bằng chứng (16-47, 16-49) đều `[CHƯA XÂY]`; nơi lưu bằng chứng bền vững là quyết định mở O-01 của bạn.

#### Bước 7.8 Cô lập SHADOW [CHƯA XÂY]

**Chạy ở:** `[MÁY EC2]`

Quy tắc: trong SHADOW tiến trình không nạp khóa giao dịch nào và không bao giờ dựng adapter lệnh (SC6, D040). Phần dữ liệu công khai đã được tách riêng (16-03, đã xây). Bằng chứng rằng không có đường nào từ CONFIRM tới `execute_approved_plan` hay một điểm cuối lệnh là kế hoạch 16-38, chưa xây; cho tới lúc đó đừng đặt BẤT KỲ khóa Binance trade nào trên máy soak (OPS-06).

#### Bước 7.9 Cập nhật ảnh hưởng thế nào tới soak [CHƯA XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]`

Một lần cập nhật khởi động lại tiến trình paper. Theo D063 mục 1, một lần khởi động lại có kế hoạch có mã lý do riêng nhưng vẫn là thời gian chưa bao phủ. Mã thực thi quy tắc này (16-15, 16-29) chưa xây, nên hôm nay không có gì đo nó; coi mỗi lần cập nhật trong lúc trial chạy là thời gian mất khỏi 336 giờ.

#### Bước 7.10 Smoke trực tiếp và buổi diễn tập tín hiệu thử [CHƯA XÂY] [THỦ CÔNG]

**Chạy ở:** `[MÁY CÓ MẠNG]`

Hai việc, đều chưa xây và đều blocking-human. Lần smoke trực tiếp (16-17 chuẩn bị công cụ, 16-21 chạy) chỉ dùng dữ liệu công khai, không khóa, để chứng minh trên socket thật rằng supervisor nhận được nến đóng. Buổi diễn tập tín hiệu thử (16-39 xây đường thử riêng, 16-40 chạy) dùng các cú chạm Telegram thật trong một cửa sổ riêng TRƯỚC trial soak. Hướng dẫn này không có lệnh cho chúng.

#### Bước 7.11 Hôm nay làm được gì, phải chờ gì [THỦ CÔNG]

**Chạy ở:** `[MÁY CÓ MẠNG]`

Làm được hôm nay: hoàn thành mục 2 đến 6; chuẩn bị bot Telegram riêng (mục 8.1). Phải chờ: quyết định O-12 để tạo máy; mọi thứ từ 16-15 đến 16-49. Không có tiến trình paper để khởi động, không có epoch để ghim và không có trial để đo.

Nguồn: `.planning/ROADMAP.md`, `.planning/phases/16-paper-runtime-composition/16-CONTEXT.md`, `docker-compose.yml`, `docs/DECISIONS.md`, `.planning/phases/16-paper-runtime-composition/16-22-PLAN.md`

## 8. Telegram, Binance và giám sát bên ngoài

#### Bước 8.1 Bot Telegram riêng cho máy soak (quyết định Q-L) [THỦ CÔNG] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY CÓ MẠNG]` (ứng dụng Telegram của bạn)

Quyết định `16-DEC-Q-L` (ngày 2026-10-09) là "separate-bot": máy soak dùng một bot Telegram riêng, khác bot của máy phát triển. Lý do bằng lời thường: Telegram chỉ cho một bên "long polling" cho mỗi token bot (giả định A1 trong nghiên cứu; đoạn thông báo lỗi 409 khi có hai bên chưa được xác minh). Nếu máy phát triển cũng chạy bot trên cùng token, nó có thể âm thầm giành mất các cú bấm nút của máy soak (Pitfall P17 trong nghiên cứu Phase 16). Hai bot riêng thì không xảy ra chuyện này.

- Tạo bot: bạn tự làm trong ứng dụng Telegram bằng BotFather (nơi `.env.example` ghi là nguồn cấp token). Các lệnh và câu hỏi của BotFather không nằm trong repository nên hướng dẫn này không liệt kê chúng `[CHƯA XÁC MINH]`.
- Token chỉ nằm ở trình quản lý mật khẩu và trong tệp bí mật ngoài VPS, dưới tên biến `TELEGRAM_BOT_TOKEN`. Không bao giờ dán token vào một dòng lệnh terminal, chat, issue hay tài liệu này. Mã bot cho hệ thống thấy token đó, nhưng agent và người viết kế hoạch không bao giờ cần nhìn thấy nó.
- Thêm biến `TELEGRAM_AUTHORIZED_CHAT_ID`: số nguyên của cuộc trò chuyện riêng được phép nhận thông báo SIMULATE (có thể âm đối với nhóm).
- Cẩn thận: `.env.example` gợi ý lấy mã chat bằng một URL `getUpdates` có nhúng chính token. Một URL như vậy nằm trong lịch sử shell, nhật ký proxy và có thể bị chụp màn hình. Cách an toàn để biết mã chat chưa được kế hoạch 16-34 hay 16-40 nêu, nên nó là `[CHƯA XÁC MINH]`; hỏi trong phiên lập kế hoạch trước khi tự chế một cách.
- Thu hồi hay tạo lại token trong BotFather nếu nghi bị lộ: việc đó nằm ngoài repository và là `[CHƯA XÁC MINH]`.
- Hành vi dự kiến của thông báo: mọi thông báo SHADOW mang nhãn "SHADOW — no real order" và nhấn APPROVE chỉ chuyển thông báo thành thẻ xác nhận (D041); chỉ nút CONFIRM, mã CONFIRM riêng, dùng một lần, hiệu lực mặc định 60 giây, mới được ghi nhận. Các mô-đun cho phần này đã xây ở mức đồ giả (16-04, 16-11) nhưng chưa nối vào một tiến trình chạy được (16-31), nên `[CHƯA XÂY]` ở cấp vận hành.

#### Bước 8.2 Binance: khóa nào cần ở giai đoạn nào [THỦ CÔNG] [CHƯA XÂY]

**Chạy ở:** `[MÁY CÓ MẠNG]`

- Soak SHADOW chỉ dùng dữ liệu thị trường công khai và KHÔNG cần khóa nào.
- Giai đoạn DEMO về sau dùng khóa testnet/demo, tên biến `BINANCE_TESTNET_API_KEY` và `BINANCE_TESTNET_API_SECRET` (người dùng là Phase 18).
- Giai đoạn CANARY dùng một khóa mainnet CHỈ-ĐỌC (không giao dịch, không rút tiền, giới hạn theo IP của VPS theo D042). Tên biến cho khóa này chưa được repository định nghĩa `[CHƯA XÂY]`.
- `BINANCE_LIVE_*` chỉ được phép nằm trong tệp env riêng của một triển khai live, không bao giờ trên máy paper/soak (OPS-06). Việc tách `env_file` theo từng service (WR-06) phải làm xong TRƯỚC khi bất kỳ khóa live nào vào `.env` (D061 hosts).
- Quy tắc IP whitelist: mỗi khóa Binance bị giới hạn ở đúng Elastic IP của máy, quyền rút tiền tắt, và danh sách IP được cập nhật sau mỗi lần cutover hay khi địa chỉ đổi (D042 điều kiện 4; RUNBOOK 13.5 mục 1 và 15.6). Giao diện Binance để làm việc đó không được repository mô tả; việc này là `[THỦ CÔNG]` và chưa được kiểm chứng.
- Phép ping vùng ở bước 3.7 vẫn là phép thử đầu tiên: Binance phải chấp nhận địa chỉ của máy.

#### Bước 8.3 Dịch vụ heartbeat bên ngoài [THỦ CÔNG] [CHƯA XÂY]

**Chạy ở:** `[MÁY CÓ MẠNG]`

- Repository này không gửi heartbeat nào (RUNBOOK 11.4). D042 điều kiện 1 đòi một dịch vụ giám sát ngoài VPS báo cho bạn khi một tiến trình chạy dài dừng, vì một máy đơn là một điểm hỏng đơn.
- Dịch vụ và chu kỳ là `[QUYẾT ĐỊNH CỦA BẠN]` (O-12 đang hoãn). URL mà dịch vụ giám sát cấp cho bạn là một bí mật, không dán vào `acceptance.json`, chat hay tài liệu này.
- Phép thử `HEARTBEAT_MONITOR_ALERT_RECEIVED` (RUNBOOK 19.3, bước 3.8) dừng collector rồi khởi động lại; nó làm mất vĩnh viễn các phút Open Interest trong lúc dừng, và khoảng trống đó phải được ghi là khoảng trống bao phủ.
- Có kế hoạch nào xây bộ gửi heartbeat ra dịch vụ ngoài không? Tìm "heartbeat" trong các tệp kế hoạch của Phase 16: các kế hoạch 16-07 và 16-14 chỉ nói về điều kiện nghiệm thu và quyết định của bạn; các kế hoạch 16-15, 16-16, 16-24, 16-26, 16-30 và 16-43 nói về các hàng heartbeat nội bộ của runtime trong cơ sở dữ liệu soak (dùng để tính độ bao phủ). Không kế hoạch nào xây một bộ gửi tín hiệu tới dịch vụ giám sát ngoài VPS, nên nó là `[CHƯA XÂY]`. Mọi cách bạn tự dựng nằm ngoài repository và chưa được kiểm chứng.
- Chú ý cho timer sao lưu: nếu máy chết thì bản sao lưu im lặng. Dịch vụ heartbeat nên mong một tín hiệu mỗi ngày (RUNBOOK 11.4).

Nguồn: `.env.example`, `.planning/phases/16-paper-runtime-composition/decisions/16-DEC-Q-L.md`, `.planning/phases/16-paper-runtime-composition/16-RESEARCH.md`, `docs/operations/RUNBOOK.md`, `docs/DECISIONS.md`

## 9. Lộ trình SHADOW, DEMO, CANARY, LIVE

#### Bước 9.1 Con đường an toàn từ D040 và D041 [CHƯA XÂY]

**Chạy ở:** `[MÁY CÓ MẠNG]` (đọc; hôm nay bạn không có lệnh nào cho các giai đoạn DEMO đến LIVE)

D040 quy định con đường phát hành an toàn SHADOW, DEMO, CANARY, LIVE, KHÔNG BỎ QUA giai đoạn nào, mỗi giai đoạn có tiêu chí thoát viết sẵn. D041 quy định bước xác nhận hai lần: APPROVE không bao giờ đặt lệnh; nó biến thông báo thành thẻ xác nhận (chế độ, cặp, chiều, khối lượng, giá trị, lỗ ước tính tại SL, giá mark so với giá vào và SL, thời hạn còn lại) với CONFIRM và CANCEL. Chỉ CONFIRM mới đặt lệnh. Mã CONFIRM tách khỏi mã phê duyệt, dùng một lần, gắn với cùng người dùng và băm kế hoạch, hết hạn sau một TTL ngắn (mặc định 60 giây). CANCEL hay hết hạn không đặt gì và được ghi nhật ký. Mọi kiểm tra trước khi đặt lệnh chạy lại lúc xác nhận.

| Giai đoạn | Cái gì chạy | Khóa nạp | Lệnh | Tiêu chí thoát | Phase xây | Trạng thái |
| --- | --- | --- | --- | --- | --- | --- |
| SHADOW | tiến trình paper trên dữ liệu thị trường công khai; thông báo có nhãn, APPROVE/SKIP rồi CONFIRM; khớp lệnh mô phỏng; không đường nào tới lệnh thật | không khóa giao dịch nào | không có (không dựng adapter lệnh) | trial soak đạt các tiêu chí ở bước 7.7 và chuỗi đóng ở bước 7.6 | Phase 16 (đang thực hiện, 14/49), Phase 17 đã xong | `[CHƯA XÂY]` ở cấp vận hành |
| DEMO | APPROVE rồi CONFIRM đặt lệnh trên Binance Demo Trading (demo-fapi.binance.com) | khóa demo/testnet | chỉ lệnh trên tài khoản demo | bộ kịch bản demo tự động qua và một soak demo nhiều tuần với không có sai lệch không giải thích, không có vị thế nào thiếu SL phía sàn, không có lệnh vào trùng | Phase 18 đến 25 | `[CHƯA XÂY]` |
| CANARY | khóa mainnet chỉ-đọc xác minh exchangeInfo, hoa hồng, giá mark và số dư thật; rồi một tài khoản phụ nhỏ biệt lập (cỡ USD 50 đến 100, cỡ tối thiểu) giao dịch khi người vận hành theo dõi | khóa chỉ-đọc, rồi khóa của tài khoản phụ | lệnh thật cỡ nhỏ | số lệnh đã đăng ký trước, không có sai lệch | Phase 26 | `[CHƯA XÂY]` |
| LIVE | chỉ sau khi tiêu chí thoát CANARY đạt | `BINANCE_LIVE_*` chỉ trong env riêng của triển khai live | lệnh thật | do Phase 26 xác định | Phase 24 và 26 | `[CHƯA XÂY]` |

#### Bước 9.2 Các phase từ 16 tới 26 [CHƯA XÂY]

**Chạy ở:** `[MÁY CÓ MẠNG]` (đọc)

Phase 27 (đồng tiền định giá cấu hình được, sẵn sàng USDC) nằm ngoài con đường này.

| Phase | Mục tiêu | Phụ thuộc | Trạng thái |
| --- | --- | --- | --- |
| Phase 16 | tiến trình paper chạy được và chế độ phê duyệt SHADOW | Phase 12, 13.1, 15, 17 | đang thực hiện, 14/49 kế hoạch (bước 7.3) |
| Phase 17 | lớp lưu trữ PostgreSQL cho nhật ký, phê duyệt, thực thi | trước đó | xong ngày 2026-10-07 `[ĐÃ XÂY]` |
| Phase 18 | luồng dữ liệu người dùng của Binance (listenKey, sự kiện lệnh, thuật toán, tài khoản), bảng phân loại lỗi sàn, công tắc demo/testnet | Phase 17 | `[CHƯA XÂY]` |
| Phase 19 | cái bạn phê duyệt đúng là cái được đặt (cùng cặp, chiều, khối lượng không lớn hơn), SL bị từ chối không để vị thế trần | Phase 17, 18 | `[CHƯA XÂY]` |
| Phase 20 | đối chiếu thấy mọi sai lệch nguy hiểm, SL bảo vệ không bao giờ bị hủy hay để thiếu, SAFE_MODE sống qua khởi động lại, tự đặt lại SL (D034) | Phase 17, 18 | `[CHƯA XÂY]` |
| Phase 21 | vốn và lỗ ngày lấy từ Binance, không từ hằng số | Phase 18 | `[CHƯA XÂY]` |
| Phase 22 | đòn bẩy, ký quỹ ISOLATED, bảo vệ thanh lý (tối đa 5x) | Phase 21 | `[CHƯA XÂY]` |
| Phase 23 | củng cố phê duyệt Telegram, bước xác nhận hai lần, số tiền | Phase 12, 21, 22 | `[CHƯA XÂY]` |
| Phase 24 | nối runtime live hoàn chỉnh và diễn tập end-to-end trên Binance Demo | Phase 16, 19, 20, 21, 22, 23 | `[CHƯA XÂY]` |
| Phase 25 | chiến dịch kiểm thử tích hợp trên Binance Demo, gồm cả đường lỗi | Phase 24 | `[CHƯA XÂY]` |
| Phase 26 | cổng sẵn sàng go-live: bật live chỉ bằng hành động khẳng định | Phase 25 | `[CHƯA XÂY]` |

#### Bước 9.3 Các cổng quan trọng, trích từ ROADMAP [CHƯA XÂY]

**Chạy ở:** `[MÁY CÓ MẠNG]` (đọc)

- Phase 25: bộ kịch bản demo tự động tách khỏi kiểm thử đơn vị, có thông tin xác thực lấy từ môi trường và mặc định không chạy trong CI. Nó gồm ít nhất đường thuận lợi, khớp một phần, giá cắt SL trước khi đặt (-2021), SL bị từ chối sau khớp, hủy đua với khớp, callback phê duyệt hay xác nhận bị lặp, khởi động lại giữa luồng, đứt WebSocket và hết hạn listenKey, lệch đồng hồ, giới hạn tốc độ hoặc 418, sự cố cơ sở dữ liệu trong lúc giảm rủi ro, DAILY_STOP, từ chối của bảo vệ thanh lý và ký quỹ, vào và ra SAFE_MODE, và lệnh ngoại lai hay vị thế nhân đôi bị đối chiếu phát hiện. Ví dụ trong ROADMAP về cách chạy (marker `demo` chưa tồn tại, `[CHƯA XÂY]`):

```bash
pytest -m demo
```

- Phase 25: một soak demo liên tục ít nhất 3 tuần (thời lượng đăng ký trước) kết thúc với không có sai lệch cục bộ-so-với-sàn nào không giải thích, không vị thế nào thiếu SL phía sàn, không lệnh vào trùng, mọi cảnh báo đều được giải thích. Gặp bất kỳ lỗi nào thì đồng hồ soak bắt đầu lại sau khi sửa.
- Phase 26 `enable()` yêu cầu: một ứng viên đạt đã ghi nhận, cổng thoát paper đã đạt, chiến dịch demo Phase 25 đã qua, và vốn tối thiểu; WITHIN_BUDGET bị từ chối; các mục review WR-01, WR-06, WR-10, WR-12, WR-13 đã xử lý và `enable()` gắn với registry WR chung (D065 mục 1).
- CANARY (D040, Phase 26): trước hết khóa mainnet chỉ-đọc (tắt giao dịch và rút, giới hạn theo IP của VPS), rồi một tài khoản phụ biệt lập nhỏ, cỡ USD 50 đến 100, với người vận hành theo dõi, và không có sai lệch nào trước khi cho phép LIVE đầy đủ.
- PAPER-03 cần quan sát 3 đến 6 tháng theo đồng hồ treo tường và không chỉnh tham số; Phase 26 xác nhận cửa sổ quan sát và quy tắc không chỉnh, nó không bắt đầu soak.
- D056: trạng thái DEGRADED không bao giờ là bằng chứng sẵn sàng live; bộ kịch bản và soak cũng phải chạy ở trạng thái khỏe. D058: giá mark thiếu hay cũ làm chặn thực thi và LIVE. D055: mô hình thực thi (đặt SL trước hay sau khi vào lệnh) vẫn là một quyết định MỞ của bạn.

#### Bước 9.4 Bạn làm gì ở mỗi cổng, và những điều không bao giờ làm [THỦ CÔNG] [CHƯA XÂY]

**Chạy ở:** `[MÁY CÓ MẠNG]`

Hôm nay bạn không có lệnh chạy được cho các giai đoạn DEMO đến LIVE. Bằng lời:

- Cổng SHADOW: bạn viết hoặc duyệt giả thuyết và lưới, cho phép chạy nghiên cứu, chỉ định ứng viên, cho phép đúng băm, rồi khởi động trial và tuyên bố nó đạt (bước 7.6).
- Cổng DEMO: bạn đọc báo cáo của bộ kịch bản và của soak 3 tuần; bạn quyết có chấp nhận kết quả hay không.
- Cổng CANARY: bạn tạo khóa chỉ-đọc, tài khoản phụ nhỏ và theo dõi từng lệnh.
- Cổng LIVE: bạn bật `enable()` sau khi mọi điều kiện của Phase 26 đạt.

Những điều không bao giờ làm: không đặt khóa live trước khi WR-06 xong; không bỏ qua giai đoạn nào; không chỉnh tham số theo kết quả soak hay backtest; không coi một lần chạy ở trạng thái DEGRADED là bằng chứng.

Nguồn: `.planning/ROADMAP.md`, `docs/DECISIONS.md`, `.env.example`, `docker-compose.yml`
