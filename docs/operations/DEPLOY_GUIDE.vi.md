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
