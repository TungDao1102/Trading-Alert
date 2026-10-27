# Hướng dẫn vận hành triển khai cho người không chuyên DevOps

> Đọc repository ngày 2026-10-09, commit `97a92a6`. Hướng dẫn này được viết lại từ nội dung thật của repository (các script trong `deploy/`, `docker-compose.yml`, `docs/operations/RUNBOOK.md`, các quyết định trong `docs/DECISIONS.md`). Nó không thay thế `docs/operations/RUNBOOK.md`: khi hai bên mâu thuẫn thì RUNBOOK và chính nội dung script thắng, và thứ tự ưu tiên chung là `docs/DECISIONS.md`, rồi `docs/`, rồi `AGENTS.md`, rồi `.planning/` (D031).

Hướng dẫn này đi từ một tài khoản AWS mới (vùng ap-southeast-1) tới một máy EC2 đã dựng xong, collector đã chuyển từ máy cũ sang, sao lưu đã kiểm chứng, và con đường dài về sau (soak, DEMO, CANARY, LIVE). Mỗi bước nói rõ chạy ở máy nào và đã xây hay chưa. Thứ gì repository chưa có thì được ghi nhãn chứ không được cho một lệnh bịa ra.

## 0. Cách đọc hướng dẫn này

> - **Để làm gì:** Giải thích cách đọc cả tài liệu: bốn loại máy, bốn nhãn trạng thái, thẻ lệnh, ký hiệu thay thế và quy tắc về bí mật.
> - **Giải quyết vấn đề gì:** Tránh ba lỗi hay gặp của người mới: chạy lệnh nhầm máy, tưởng "đã xây" nghĩa là "đã chạy thử trên máy thật", và dán bí mật vào nơi không an toàn.
> - **Mức quan trọng:** **BẮT BUỘC** đọc trước khi gõ bất kỳ lệnh nào. Đây là quy ước của chính hướng dẫn này; repository không quy định mức quan trọng của việc đọc.

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

- Mật khẩu, khóa truy cập, token bot, địa chỉ URL ping của dịch vụ giám sát (healthchecks.io), cụm mật khẩu sao lưu: không dán vào chat, lịch sử shell (shell history), issue, commit hay tài liệu này. Tài liệu này chỉ chứa TÊN biến, không chứa giá trị.
- Các số liệu của bạn về máy EC2 (loại máy, dung lượng ổ, ngân sách, vòng đời S3, chu kỳ và thời gian ân hạn của heartbeat) chưa được chọn (quyết định `16-DEC-O-12` là hoãn). Chúng được ghi là `[QUYẾT ĐỊNH CỦA BẠN]` và không có số nào trong tài liệu này. Riêng dịch vụ heartbeat thì bạn đã chọn healthchecks.io ngày 2026-10-09 (mục 8.3).

### Lưu ý riêng cho Windows

`ssh` và `scp` chạy được từ PowerShell hoặc Git Bash trên `[MÁY CÓ MẠNG]`. Các script `deploy/*.sh` chỉ chạy trên Linux. Script shell có dấu xuống dòng kiểu Windows (CRLF) sẽ lỗi trên Linux với thông báo `bad interpreter` (RUNBOOK 13.2): hãy sao chép từ một bản checkout sạch hoặc từ `git archive`, đừng sao chép từ thư mục Windows cũ.

### Cấu trúc tài liệu

Mục 1 là bức tranh tổng thể. Mục 2 đến 5 dựng máy và chuyển collector. Mục 6 là sao lưu. Mục 7 đến 9 là phần phụ thuộc Phase 16 và các phase chưa xây. Mục 10 đến 13 là vận hành hằng ngày, cập nhật, khẩn cấp và xử lý sự cố. Mục 14 là bảng tra mọi lệnh và mục 15 là danh sách kiểm tra cuối cùng.

Nguồn: `docs/operations/RUNBOOK.md`, `docs/DECISIONS.md`, `deploy/lib.sh`, `docs/operations/SECURITY_AND_OPERATIONS.md`

## 1. Bức tranh tổng thể

> - **Để làm gì:** Cho bạn bản đồ tổng thể: có những máy nào, ai làm gì ở đâu, cái gì đã xây và cái gì chưa, và đường tối thiểu hôm nay.
> - **Giải quyết vấn đề gì:** Không bị lạc giữa nhiều mục, và biết ngay phần nào chưa có code nên chưa thể làm.
> - **Mức quan trọng:** **NÊN LÀM** đọc một lần, không có thao tác nào; bỏ qua được nếu bạn đã nắm mô hình. Mức này là đánh giá của hướng dẫn này, repository không quy định.

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
        | migrate.sh (rsync qua ssh)    | (healthchecks.io, xem 8.3)   |
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
| Paper runtime và SHADOW | một phần: 14 trong 50 kế hoạch của Phase 16 | Mục 7 |
| Bộ gửi heartbeat ra ngoài VPS (tới healthchecks.io) | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` | Kế hoạch 16-50 "Off-host heartbeat sender": script `deploy/heartbeat.sh` và hai unit đã có, kiểm thử bằng đồ giả; chưa cài và chưa chạy trên máy thật, vì chu kỳ và thời gian ân hạn chưa được bạn chọn; mục 8.3 |
| Live runtime | `[CHƯA XÂY]` | Service `live` trong compose chỉ là khung báo lỗi, đến Phase 24 |

### Mốc thời gian đã quyết định

- Máy EC2 dự kiến được tạo trong cuối tuần 2026-10-10 (D061 hosts), nhưng việc tạo máy đang bị chặn vì quyết định O-12 được hoãn (mục 2).
- D059 mục 4: hạn chót của collector là 2026-10-08 và là hạn của riêng bạn; mọi khoảng trống sau đó được ghi là khoảng trống bao phủ (coverage gap). `openInterestHist` của Binance chỉ trả khoảng một tháng gần nhất, nên các phút Open Interest đã mất là mất vĩnh viễn.
- Soak dài bắt đầu sau khi Phase 16 đóng lại (D061 hosts), chạy qua Phase 18 đến 25.

### Thứ tự đọc và đường tối thiểu hôm nay

Đường tối thiểu có thể làm được ngay khi O-12 được quyết định: mục 2 (chuẩn bị), 3 (máy EC2), 4 (bootstrap), 5 (collector), 6 (sao lưu). Mọi thứ liên quan tới paper runtime, SHADOW, DEMO, CANARY, LIVE đang chờ các kế hoạch chưa xây (mục 7 đến 9).

Nguồn: `docs/operations/RUNBOOK.md`, `docker-compose.yml`, `docs/DECISIONS.md`, `.planning/ROADMAP.md`

## 2. Chuẩn bị trước khi bắt đầu

> - **Để làm gì:** Gom mọi thứ phải có trước khi chạm vào máy EC2: tài khoản AWS, các giá trị chưa chọn, khóa SSH, tệp khóa được phép, tệp bí mật, quyền vào repository, bucket S3 và cụm mật khẩu mã hóa sao lưu.
> - **Giải quyết vấn đề gì:** Bootstrap từ chối chạy khi thiếu khóa hợp lệ hoặc tệp bí mật sai; chuẩn bị trước tránh dừng giữa chừng và tránh tự khóa mình ngoài máy.
> - **Mức quan trọng:** **BẮT BUỘC** (bootstrap kiểm tra khóa và tệp bí mật trước khi đổi bất cứ điều gì, mục 4). Riêng các giá trị của O-12 đang hoãn nên bước tạo máy bị chặn (bước 2.2).

Mục này gom mọi thứ cần có trước khi chạm vào máy EC2. Phần lớn là việc ở `[MÁY CÓ MẠNG]`. Mục này không tạo tài nguyên AWS nào; việc tạo nằm ở mục 3.

#### Bước 2.1 Biết rõ tài khoản AWS của bạn [THỦ CÔNG] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY CÓ MẠNG]`

- Tài khoản được tạo ngày 2026-07-25 theo mô hình gói Free (có tín dụng). Theo lời bạn ghi lại trong `16-DEC-O-12`, tài khoản tự đóng vào khoảng 2027-01-25 hoặc khi hết tín dụng, tùy mốc nào tới trước. Nếu giữ máy EC2 thì phải chuyển sang gói Paid trước mốc đó; điều kiện `PAID_PLAN` ở mục 3 kiểm tra việc này.
- Vùng cố định là ap-southeast-1 (Singapore). Đây là quyết định D061 hosts; máy phải ping được `fapi.binance.com` (mục 3.7) trước khi cài bất cứ thứ gì.
- Gói Free có đủ để chạy máy EC2 này hay không thì chưa được quyết định và chưa được xác minh; đừng giả định.

#### Bước 2.2 Các giá trị bạn chưa chọn (quyết định O-12) [THỦ CÔNG]

**Chạy ở:** `[MÁY CÓ MẠNG]` (bạn trả lời trong phiên làm việc với agent lập kế hoạch)

Quyết định `16-DEC-O-12` được bạn ghi ngày 2026-10-09 với lựa chọn "postpone" (hoãn). Hiện không có con số nào được chọn. Có năm hạng mục; bốn hạng mục còn để trống hoàn toàn và hạng mục thứ năm (heartbeat) mới có dịch vụ, chưa có chu kỳ. Mỗi giá trị còn thiếu là `[QUYẾT ĐỊNH CỦA BẠN]`:

| Giá trị | Trạng thái |
| --- | --- |
| Loại máy (instance type) | `[QUYẾT ĐỊNH CỦA BẠN]` |
| Dung lượng ổ EBS | `[QUYẾT ĐỊNH CỦA BẠN]` |
| Số tiền cảnh báo ngân sách và địa chỉ nhận cảnh báo | `[QUYẾT ĐỊNH CỦA BẠN]` |
| Vòng đời và thời hạn lưu của S3 | `[QUYẾT ĐỊNH CỦA BẠN]` |
| Dịch vụ heartbeat bên ngoài | healthchecks.io, bạn chọn ngày 2026-10-09 (đã ghi vào tệp `16-DEC-O-12` bởi kế hoạch 16-50 với dòng `heartbeat_service`) |
| Chu kỳ và thời gian ân hạn (grace period) của heartbeat | `[QUYẾT ĐỊNH CỦA BẠN]` |

Hậu quả của việc hoãn các giá trị còn thiếu: kế hoạch 16-20 (tạo máy EC2 và chuyển collector) bị chặn cho tới khi bạn ghi các giá trị này, và trong lúc đó collector vẫn ở máy cũ, mọi khoảng trống Open Interest được ghi là khoảng trống bao phủ (D059 mục 4). Theo kế hoạch 16-14, cách ghi lại giá trị là bạn trả lời bằng lựa chọn "values" kèm từng con số theo đúng lời bạn viết; agent ghi vào hồ sơ quyết định. Đừng tự sửa tay tệp quyết định và đừng nhờ ai đề xuất con số hộ bạn.

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

Tuyệt đối không đặt `BINANCE_LIVE_*` vào tệp của máy paper/soak này (OPS-06). Khóa Binance Demo nếu có dùng tên `BINANCE_DEMO_API_KEY` và `BINANCE_DEMO_API_SECRET`, và tách thành tệp riêng cho máy khác.

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

> - **Để làm gì:** Tạo máy EC2 trên AWS và nghiệm thu nó theo 16 điều kiện của D042: vùng, IP cố định, mã hóa ổ, tường lửa, ngân sách, bucket sao lưu, đồng hồ, SSH chỉ khóa.
> - **Giải quyết vấn đề gì:** Một máy đơn là một điểm hỏng đơn (D042); các điều kiện này bảo đảm máy ở vùng Binance chấp nhận, có địa chỉ cố định để giới hạn khóa sàn, không để lộ cơ sở dữ liệu ra ngoài và có cảnh báo chi phí.
> - **Mức quan trọng:** **BẮT BUỘC** nếu bạn đi tiếp tới soak: D061 hosts quy định cả trial soak lẫn soak dài chạy trên một máy EC2 ở ap-southeast-1 dựng theo các điều kiện D042. Mỗi bước bên dưới có mức riêng.

Repository không bao giờ tạo, sửa hay xóa tài nguyên AWS nào; mọi bước ở mục này do bạn làm tay hoặc bằng AWS CLI của bạn (RUNBOOK 19). Tên nút và màn hình của AWS console có thể khác với những gì bạn thấy; tài liệu này không mô tả chúng `[CHƯA XÁC MINH]`. Mọi dữ kiện về AWS dưới đây được chép từ RUNBOOK 19, nơi chúng được đọc ngày 2026-10-08 và ghi là "chưa xác minh trực tiếp": trước khi một quyết định dựa vào chúng, hãy đọc lại trang gốc.

#### Bước 3.1 Tạo instance và chọn hệ điều hành [THỦ CÔNG] [CHƯA XÁC MINH]

> - **Để làm gì:** Chọn hệ điều hành và tạo máy chủ ảo (instance) sẽ chạy toàn bộ stack.
> - **Giải quyết vấn đề gì:** Bootstrap chỉ chạy trên Ubuntu 22.04, Ubuntu 24.04 hoặc Debian 12; chọn sai ảnh (ví dụ Amazon Linux) thì phải dựng lại.
> - **Mức quan trọng:** **BẮT BUỘC** (D061 hosts: một máy EC2 ở ap-southeast-1). Loại máy và dung lượng ổ là giá trị của bạn, chưa chọn (O-12).

**Chạy ở:** `[MÁY CÓ MẠNG]`

- Hệ điều hành chỉ được là Ubuntu 22.04, Ubuntu 24.04 hoặc Debian 12. Bootstrap từ chối mọi hệ điều hành khác trước khi đổi bất cứ điều gì. Amazon Linux không được hỗ trợ.
- Loại máy và dung lượng ổ EBS là `[QUYẾT ĐỊNH CỦA BẠN]` (O-12 đang hoãn), nên bước tạo máy bị chặn cho tới khi bạn ghi các giá trị đó (mục 2.2). Chọn khóa SSH công khai của bạn (bước 2.3) ngay khi tạo.
- Một điều dễ vấp: RUNBOOK 13.1 giả định bạn đăng nhập được bằng root qua SSH, nhưng các ảnh hệ điều hành của AWS thường chỉ cho đăng nhập bằng một user mặc định, không phải root. Cách lấy phiên root trên ảnh bạn chọn là `[CHƯA XÁC MINH]` (xem bước 4.1).

#### Bước 3.2 Gắn Elastic IP [THỦ CÔNG] [CHƯA XÁC MINH]

> - **Để làm gì:** Gắn một địa chỉ IP công khai cố định (Elastic IP) vào máy.
> - **Giải quyết vấn đề gì:** Không có nó, địa chỉ đổi mỗi lần máy khởi động lại: hỏng đường `ssh` và làm khóa Binance giới hạn theo IP bị từ chối.
> - **Mức quan trọng:** **BẮT BUỘC** (D061 hosts: Elastic IP cố định; D042 điều kiện 4: IP cố định là danh sách cho phép của khóa API; điều kiện `ELASTIC_IP`). Có chi phí nhỏ, xem bước 3.10.

**Chạy ở:** `[MÁY CÓ MẠNG]`

Elastic IP là một địa chỉ IP công khai cố định gắn vào máy của bạn; không có nó địa chỉ đổi mỗi khi máy khởi động lại. Địa chỉ này vừa là nơi bạn `ssh` tới vừa là địa chỉ bạn đưa vào danh sách IP cho phép (IP whitelist) của khóa Binance sau này (D042 điều kiện 4). Một địa chỉ IPv4 công khai đang dùng, kể cả Elastic IP, bị tính phí 0,005 USD mỗi giờ (RUNBOOK 19.3, chưa xác minh trực tiếp).

#### Bước 3.3 Mã hóa ổ đĩa EBS [THỦ CÔNG] [CHƯA XÁC MINH]

> - **Để làm gì:** Bảo đảm ổ đĩa EBS của máy được mã hóa.
> - **Giải quyết vấn đề gì:** Ổ không mã hóa làm lộ `.env` và dữ liệu nếu ổ bị chụp lại hay lấy đi; D045 dựa vào mã hóa ổ của nhà cung cấp thay cho mã hóa bí mật trong ứng dụng.
> - **Mức quan trọng:** **BẮT BUỘC** (D061 hosts: EBS mã hóa; hai điều kiện `EBS_ENCRYPTED_BY_DEFAULT` và `EBS_ROOT_VOLUME_ENCRYPTED` nằm trong 16 điều kiện).

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

> - **Để làm gì:** Cấu hình tường lửa phía AWS (security group): chỉ mở SSH, chỉ cho địa chỉ bạn chọn.
> - **Giải quyết vấn đề gì:** Một cổng PostgreSQL hay cổng lạ mở ra internet là cửa vào cho kẻ tấn công; ufw trên máy không điều khiển các cổng do Docker công bố.
> - **Mức quan trọng:** **BẮT BUỘC** (D042 điều kiện 3: cổng mở tối thiểu; điều kiện `POSTGRES_NOT_PUBLIC`).

**Chạy ở:** `[MÁY CÓ MẠNG]`

Security group là tường lửa phía AWS. Chỉ mở cổng SSH, và chỉ cho địa chỉ nơi bạn chọn truy cập. Không mở cổng PostgreSQL ở chiều vào. Lưu ý: `ufw` trên máy không điều khiển các cổng do Docker công bố, nên kiểm soát thật là việc compose chỉ công bố `127.0.0.1` (điều kiện `POSTGRES_NOT_PUBLIC`).

#### Bước 3.5 Cảnh báo ngân sách và chuyển gói Paid [THỦ CÔNG] [CHƯA XÁC MINH]

> - **Để làm gì:** Đặt cảnh báo ngân sách (Budget) và chuyển tài khoản sang gói Paid.
> - **Giải quyết vấn đề gì:** Chi phí tăng bất ngờ mà không ai biết; gói Free tự đóng khoảng 2027-01-25 hoặc khi hết tín dụng, kéo theo mất máy.
> - **Mức quan trọng:** **BẮT BUỘC** (D061 hosts: cảnh báo ngân sách và gói trả phí; điều kiện `BUDGET_ALERT` và `PAID_PLAN`). Số tiền là giá trị của bạn.

**Chạy ở:** `[MÁY CÓ MẠNG]`

Tạo ít nhất một ngân sách (Budget) có thông báo gửi tới địa chỉ nhận. AWS Budgets không tính phí theo trang đã đọc ngày 2026-10-08 (chưa xác minh trực tiếp). Số tiền và địa chỉ là `[QUYẾT ĐỊNH CỦA BẠN]`. Rồi chuyển tài khoản sang gói Paid (điều kiện `PAID_PLAN`; không có lệnh, đây là việc xem trên trang Billing).

#### Bước 3.6 Bucket S3 sao lưu [THỦ CÔNG] [CHƯA XÁC MINH]

> - **Để làm gì:** Tạo bucket S3 riêng tư, mã hóa mặc định, bật versioning, làm nơi chứa bản sao lưu ngoài máy.
> - **Giải quyết vấn đề gì:** Sao lưu nằm trên chính máy EC2 thì mất máy là mất cả bản sao lưu; bucket công khai, hoặc xóa sạch được bằng một khóa bị lộ, là rủi ro.
> - **Mức quan trọng:** **BẮT BUỘC** (D042 điều kiện 2, D061 hosts: bucket S3 riêng tư mã hóa; ba điều kiện `S3_BUCKET_PRIVATE`, `S3_DEFAULT_ENCRYPTION`, `S3_VERSIONING`). Object lock và vòng đời là biện pháp và giá trị của bạn.

**Chạy ở:** `[MÁY CÓ MẠNG]`

Bucket phải riêng tư (chặn truy cập công khai), có mã hóa mặc định, bật versioning, mới và hoàn toàn trống. Vòng đời và thời hạn lưu là `[QUYẾT ĐỊNH CỦA BẠN]` (O-12). Tạo một khóa truy cập chỉ có quyền trên bucket này. Bật versioning hoặc object lock với thời hạn giữ là một biện pháp do bạn tự làm để khóa bị lộ không xóa được lịch sử (RUNBOOK 11.1 mục 4). Cảnh báo quan trọng: cổng D064 (chứng minh `cryptcheck` trên S3 thật) vẫn mở, nên chưa có bản sao lưu thật nào được chạy và điều kiện `BACKUP_REAL_S3_GATE` chưa PASS. Chi tiết ở mục 6.

#### Bước 3.7 Hành động đầu tiên trên instance: ping Binance [THỦ CÔNG] [CHƯA XÁC MINH]

> - **Để làm gì:** Lệnh đầu tiên trên máy mới: hỏi Binance xem địa chỉ của máy có được chấp nhận không.
> - **Giải quyết vấn đề gì:** Một số vùng hoặc địa chỉ bị Binance chặn; phát hiện sau khi đã cài và chạy thì mất công và có thể mất dữ liệu.
> - **Mức quan trọng:** **BẮT BUỘC** (D061 hosts: xác nhận bằng ping công khai trước khi cam kết; điều kiện `REGION_PING_FAPI`). Không in ra 200 thì DỪNG.

**Chạy ở:** `[MÁY EC2]` (đăng nhập bằng khóa SSH; trước khi cài bất cứ thứ gì)

```bash
curl -sS -o /dev/null -w "%{http_code}" https://fapi.binance.com/fapi/v1/ping
```

Điều kiện đạt: lệnh in ra `200`. Đây là điều kiện `REGION_PING_FAPI`. Chạy lại lần nữa sau khi Elastic IP đã được gắn nếu lần đầu máy dùng địa chỉ khác, vì Binance nhìn thấy địa chỉ mà máy thật sự dùng. Nếu kết quả là bất cứ thứ gì khác `200` (mã khác, hết thời gian chờ, lỗi TLS): DỪNG, không cài gì, ghi lại kết quả làm bằng chứng và báo lại. Chọn vùng hay địa chỉ khác là một quyết định mới của bạn; hướng dẫn này không quyết định thay.

#### Bước 3.8 Bảng nghiệm thu theo điều kiện D042 [THỦ CÔNG] [CHƯA XÁC MINH]

> - **Để làm gì:** Hồ sơ `acceptance.json` ghi 16 điều kiện nghiệm thu máy: lệnh đã chạy, bằng chứng ngắn, giờ UTC, và một script kiểm tra hồ sơ.
> - **Giải quyết vấn đề gì:** Không có bằng chứng thì "máy đạt chuẩn" chỉ là lời nói; hồ sơ buộc mỗi điều kiện có lệnh, kết quả và thời điểm, và chặn bí mật lọt vào.
> - **Mức quan trọng:** **BẮT BUỘC** để tuyên bố máy đã nghiệm thu (RUNBOOK 19.1 mục 4: thoát 0 chỉ khi đủ 16 PASS). Việc tệp này chặn bước nào của soak thì repository chưa nêu.

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
| `HEARTBEAT_MONITOR_ALERT_RECEIVED` | `[MÁY EC2]` | sau cutover (collector đã chạy trên EC2) | trong `/opt/trading`: `docker compose stop collector`, chờ lâu hơn chu kỳ cộng thời gian ân hạn đã đặt ở healthchecks.io (hai giá trị đó là `[QUYẾT ĐỊNH CỦA BẠN]`), rồi `docker compose start collector` | một cảnh báo từ dịch vụ bên ngoài đã tới bạn khi collector dừng, và một thông báo phục hồi theo sau khi khởi động lại; ghi cả hai giờ UTC. Cần bộ gửi tín hiệu của kế hoạch 16-50 (`deploy/heartbeat.sh`, mục 8.3) đã được cài | `[CHƯA XÁC MINH]` |
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

> - **Để làm gì:** Kiểm tra tệp `acceptance.json` đã đủ 16 điều kiện nghiệm thu máy EC2, mỗi điều kiện có lệnh, bằng chứng ngắn và giờ UTC.
> - **Giải quyết vấn đề gì:** Biến "tôi nghĩ máy đạt" thành hồ sơ kiểm được, và chặn bí mật lọt vào hồ sơ (thoát 2 mà không in giá trị).
> - **Mức quan trọng:** **BẮT BUỘC** để tuyên bố máy đã nghiệm thu (RUNBOOK 19.1 mục 4: thoát 0 chỉ khi đủ 16 PASS). Script không tự quyết điều kiện có thật sự đạt; việc nó chặn bước nào của soak thì repository chưa nêu.

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

#### Bước 3.9 Đồng bộ đồng hồ với chrony (G14) [THỦ CÔNG] [CHƯA XÁC MINH]

> - **Để làm gì:** Bảo đảm đồng hồ máy đồng bộ với nguồn giờ của AWS bằng chrony (G14).
> - **Giải quyết vấn đề gì:** Đồng hồ lệch làm sai dấu thời gian của dữ liệu và nhật ký; runtime chỉ đọc UTC (D-35) nên cần nguồn giờ đúng.
> - **Mức quan trọng:** **BẮT BUỘC** kiểm tra (điều kiện `CHRONY_SYNCED`; D042 điều kiện 5). Dòng cấu hình thêm tay chỉ cần nếu `chronyc sources` chưa liệt kê nguồn của AWS; trang AWS không bảo đảm ảnh Ubuntu đã có sẵn và không bao quát Debian 12.

**Chạy ở:** `[MÁY EC2]`

Trên Ubuntu trang AWS đưa ra bước thủ công: cài `chrony` (bootstrap đã làm) rồi thêm dòng sau vào `/etc/chrony/chrony.conf` và khởi động lại chrony. Trang không nói ảnh Ubuntu gốc đã có sẵn dòng này, và không bao quát Debian 12, nên hãy đọc `chronyc sources` trên máy rồi mới quyết, đừng giả định. Runtime chỉ đọc UTC (D-35); không có gì trong repository theo dõi độ lệch sau khi khởi động (D042 điều kiện 5 đòi hỏi theo dõi, để cho một kế hoạch sau).

```text
server 169.254.169.123 prefer iburst minpoll 4 maxpoll 4
```

```bash
sudo systemctl restart chrony
```

#### Bước 3.10 Chi phí AWS [THỦ CÔNG] [CHƯA XÁC MINH]

> - **Để làm gì:** Ghi nhận các khoản chi phí AWS đã biết và chưa biết.
> - **Giải quyết vấn đề gì:** Tránh bất ngờ về hóa đơn: biết khoản nào đã có nguồn (IPv4 công khai, Budgets) và khoản nào chưa đọc được (giá máy, ổ, yêu cầu S3).
> - **Mức quan trọng:** **CHƯA RÕ** như một bước riêng: repository không quy định việc ghi chi phí, chỉ đòi cảnh báo ngân sách (bước 3.5). Mọi mức giá còn `[CHƯA XÁC MINH]` và số tiền là giá trị của bạn (O-12).

**Chạy ở:** `[MÁY CÓ MẠNG]`

Giá tính toán, lưu trữ và yêu cầu S3 chưa đọc được trong đợt nghiên cứu nên vẫn chưa xác minh. Không có con số nào của bạn (loại máy, dung lượng, ngân sách, vòng đời) được viết ở đây. Hai mức giá đã có nguồn nằm ở bước 3.2 và 3.5.

#### Bước 3.11 Heartbeat và phép thử nghiệm thu [THỦ CÔNG] [CHƯA XÁC MINH] [CHƯA XÂY]

> - **Để làm gì:** Làm phép thử nghiệm thu heartbeat: dừng collector rồi xem cảnh báo từ dịch vụ bên ngoài có tới không.
> - **Giải quyết vấn đề gì:** Một heartbeat chưa từng được thử thì chưa biết có báo được khi cần hay không.
> - **Mức quan trọng:** **BẮT BUỘC** (điều kiện `HEARTBEAT_MONITOR_ALERT_RECEIVED`; D042 điều kiện 1). Cần bộ gửi tín hiệu của kế hoạch 16-50 (`deploy/heartbeat.sh`, đã xây nhưng chưa cài) và hai giá trị O-12 của bạn; phép thử này chờ cho tới sau khi bộ gửi được cài và trước kế hoạch 16-43.

**Chạy ở:** `[MÁY EC2]` cho phép thử, `[MÁY CÓ MẠNG]` cho tài khoản dịch vụ

Dịch vụ đã chọn là healthchecks.io; chu kỳ và thời gian ân hạn là lựa chọn của bạn (O-12). Phần giải thích đầy đủ, các giới hạn và dữ kiện về gói miễn phí nằm ở bước 8.3. Điều cần nhớ khi làm phép thử `HEARTBEAT_MONITOR_ALERT_RECEIVED` ở bước 3.8: bộ gửi của kế hoạch 16-50 (`deploy/heartbeat.sh`) chỉ ping khi đầu dò collector qua, nên dừng collector làm tín hiệu im; phép thử cần bộ gửi đó đã được cài (bước 8.3). URL ping mà dịch vụ cấp cho bạn là một bí mật: không dán nó vào `acceptance.json`. Dừng collector làm gián đoạn thu thập, và các phút Open Interest mất theo cách đó là mất vĩnh viễn: chỉ làm phép thử này khi bạn chấp nhận cái giá đó, và ghi khoảng trống kết quả là một khoảng trống bao phủ (D059 mục 4).

Nguồn: `docs/operations/RUNBOOK.md`, `scripts/soak_host_acceptance.py`, `deploy/bootstrap.sh`, `docs/DECISIONS.md`

## 4. Dựng máy chủ với bootstrap

> - **Để làm gì:** Biến máy mới thành máy Docker đã gia cố: user vận hành `trading`, SSH chỉ khóa, ufw, chrony, repository đúng phiên bản và `.env` quyền 0600.
> - **Giải quyết vấn đề gì:** Làm tay hàng chục bước dễ sai thứ tự và dễ tự khóa mình ngoài máy; script làm theo thứ tự cố định, chạy lại được, có chốt chống tự khóa (D042 điều kiện 3, D062).
> - **Mức quan trọng:** **BẮT BUỘC** trong đường đi của hướng dẫn này (RUNBOOK 13 là đường dựng máy chuẩn); repository không mô tả cách dựng tay thay thế.

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
2. Đăng ký một dịch vụ heartbeat bên ngoài VPS (dịch vụ đã chọn là healthchecks.io; bộ gửi là `deploy/heartbeat.sh`, bước 8.3) để một máy im lặng thì có người biết (mục 8.3).
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

> - **Để làm gì:** Dựng máy mới thành máy Docker đã gia cố: user `trading`, SSH chỉ khóa, ufw, chrony, repository ở đúng `--ref` và `.env` quyền 0600; không khởi động stack.
> - **Giải quyết vấn đề gì:** Làm tay dễ sai thứ tự và dễ tự khóa mình ngoài máy; script chạy lại được, có `--dry-run` và chốt chống tự khóa (D042 điều kiện 3, D062).
> - **Mức quan trọng:** **BẮT BUỘC** trong đường đi của hướng dẫn này (RUNBOOK 13 là đường dựng máy chuẩn); repository không mô tả cách dựng tay thay thế.

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

> - **Để làm gì:** Đưa collector (thu Open Interest và funding) lên máy EC2: bắt đầu trống, hoặc chuyển dữ liệu từ máy cũ bằng `deploy/migrate.sh`.
> - **Giải quyết vấn đề gì:** Mỗi phút collector không chạy là mất vĩnh viễn một phút Open Interest (D059 mục 4: Binance chỉ giữ khoảng một tháng); chuyển máy có kiểm tra để biết đúng mình mất bao nhiêu.
> - **Mức quan trọng:** **BẮT BUỘC** đưa collector chạy ổn định trên EC2 (D061 hosts: collector chuyển lên EC2 trước soak dài). Còn dùng `migrate.sh` hay bắt đầu trống là **TÙY CHỌN**, tùy bạn có dữ liệu cũ cần nối liền hay không.

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

> - **Để làm gì:** Chuyển collector, kho Parquet và cơ sở dữ liệu từ máy cũ sang máy mới trong một lần cutover có thứ tự cố định, rồi in báo cáo khoảng trống.
> - **Giải quyết vấn đề gì:** Mỗi phút collector ngừng là mất vĩnh viễn một phút Open Interest (D059 mục 4); script giữ khoảng trống nhỏ, không xóa gì ở máy cũ và cho bạn con số khoảng trống chính xác.
> - **Mức quan trọng:** **TÙY CHỌN**: chỉ cần khi bạn có dữ liệu cũ muốn nối liền (bước 5.2). Bắt đầu trống và ghi khoảng trống bao phủ là lựa chọn hợp lệ của bạn (D059 mục 4).

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

> - **Để làm gì:** Sao lưu hằng ngày có mã hóa lên S3 riêng, khôi phục lên máy trống, và diễn tập để biết bản sao lưu dùng được.
> - **Giải quyết vấn đề gì:** Mất máy hay xóa nhầm volume sẽ mất dữ liệu nghiên cứu không thu lại được (nhất là Open Interest); một bản sao lưu chưa từng khôi phục thử thì chưa đáng tin.
> - **Mức quan trọng:** **BẮT BUỘC** (D042 điều kiện 2: sao lưu mã hóa ngoài VPS, có lịch, quy tắc giữ và một lần diễn tập thật; D061 hosts: có sao lưu trước soak dài). Cảnh báo: cổng D064 chưa qua nên chưa có bản sao lưu thật nào chạy.

> **CẢNH BÁO.** Cổng D064 (bằng chứng trên một remote S3 thật, qua lớp crypt, kể cả đối tượng multipart) vẫn mở. Điều kiện `BACKUP_REAL_S3_GATE` chưa PASS. Vì vậy chưa có bản sao lưu thật nào được chạy, và mọi thứ ở mục này mới được kiểm thử với một S3 giả (S3 double). Đừng coi một bản sao lưu là đã bảo vệ dữ liệu của bạn cho tới khi cổng này qua và một lần diễn tập (restore drill) thành công.

### Chuỗi sao lưu bằng lời thường

- Mọi logic nằm trong `python -m src.ops.backup` chạy trong image `ops` của compose; các script `deploy/*.sh` chỉ là lớp vỏ mỏng truyền nguyên mã thoát của lệnh Python.
- Sao lưu được mã hóa ngay trên máy của bạn bằng `rclone` với lớp `crypt` rồi đẩy lên bất kỳ kho S3 nào (AWS S3, Backblaze B2 qua điểm cuối S3, Wasabi...). Nhà cung cấp chỉ thấy bản mã và tên tệp đã mã hóa.
- Bố cục trên remote: thư mục `parquet/` chỉ-thêm (copy với `--immutable`, không bao giờ đồng bộ, di chuyển hay xóa); mỗi bản sao lưu một thư mục `snapshots/<YYYYMMDDTHHMMSSZ>/` chứa `pg.dump` và `manifest.json`; và `_sentinel/sentinel.txt` để chứng minh khóa đúng trước mọi thao tác.
- Giữ lại theo quy tắc 7/4/6: bản mới nhất của mỗi ngày trong 7 ngày UTC gần nhất, 4 tuần ISO và 6 tháng có bản sao lưu; bản mới nhất luôn được giữ. Việc giữ lại chỉ chạy sau khi lần đẩy đã được kiểm bằng `cryptcheck`, và chỉ xóa các thư mục `snapshots/<id>`. Thư mục `parquet/` là dữ liệu nghiên cứu và không bao giờ bị xóa từ xa, nên bucket lớn dần theo bộ dữ liệu.
- Vì sao một snapshot cần cả `pg.dump` lẫn toàn bộ cây Parquet đã kiểm (D066): `manifest.json` chỉ được công bố sau khi cả cây Parquet và `pg.dump` đã qua `cryptcheck`. Không có bản sao lưu PostgreSQL đứng riêng trên remote, và không có lệnh nào công bố một snapshot mà Parquet chưa kiểm. Đây là chủ ý.
- Quản lý khóa: mất cụm mật khẩu crypt thì mọi bản sao lưu không thể phục hồi, và với khóa sai bucket trông như trống hoặc rối loạn; công cụ từ chối tiếp tục chứ không coi đó là kho trống. Giữ bản gốc của cụm mật khẩu và muối (`BACKUP_CRYPT_PASSWORD2`) ngoài VPS, trong trình quản lý mật khẩu cộng một bản ngoại tuyến.

#### Bước 6.1 Cấu hình remote [ĐÃ XÂY] [CHƯA XÁC MINH]

> - **Để làm gì:** Khai báo các biến `BACKUP_*` để bản sao lưu được mã hóa và đẩy lên S3 của bạn.
> - **Giải quyết vấn đề gì:** Thiếu biến thì lệnh dừng và nêu tên biến; mất cụm mật khẩu thì mọi bản sao lưu không phục hồi được.
> - **Mức quan trọng:** **BẮT BUỘC** (D042 điều kiện 2). Bật versioning hoặc object lock là biện pháp RUNBOOK 11 giao cho người vận hành; repository không ép.

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

Thứ tự: dump cơ sở dữ liệu, sao lưu Parquet, kiểm bundle với manifest sha256, đẩy lên (Parquet mới, rồi `cryptcheck` cây Parquet, rồi `pg.dump` và `cryptcheck` của nó, rồi kiểm bundle với manifest lần hai, rồi `manifest.json` và `cryptcheck` của nó), rồi áp dụng việc giữ lại. Bước nào lỗi thì lệnh, và cả unit systemd, lỗi một cách thấy được. Chú ý: hôm nay không có gì trong repository ping một dịch vụ giám sát bên ngoài (bộ gửi heartbeat là kế hoạch 16-50, `[CHƯA XÂY]`); nếu bạn không có heartbeat ngoài VPS (healthchecks.io, mục 8.3) thì một máy chết hay một unit lỗi sẽ im lặng.

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

> - **Để làm gì:** Chạy một bản sao lưu mã hóa lên S3 ngay bây giờ, hoặc khởi tạo remote lần đầu, hoặc cài timer hằng ngày.
> - **Giải quyết vấn đề gì:** Mất máy hay xóa nhầm volume sẽ mất dữ liệu nghiên cứu không thu lại được; bản sao lưu nằm ngoài VPS và mã hóa nên nhà cung cấp chỉ thấy bản mã.
> - **Mức quan trọng:** **BẮT BUỘC** (D042 điều kiện 2; D061 hosts: có sao lưu trước soak dài). Cảnh báo: cổng D064 chưa qua nên chưa có bản sao lưu thật nào.

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

```bash
sudo deploy/backup.sh --install-soak-timer --soak-env-file /home/trading/soak.env
```

Cờ: `--init-remote` (khởi tạo remote), `--install-timer` (cài hai unit và bật timer), `--install-soak-timer` cùng `--soak-env-file` (cài cặp unit sao lưu của project soak, kế hoạch 16-55; tệp env soak phải có `BACKUP_S3_BUCKET` riêng, khác bucket của `trading-backup`), `--dry-run` (in kế hoạch), `-h`/`--help`. Hai cờ `--init-remote` và `--install-timer` không dùng chung được. Biến môi trường `COMPOSE_PROJECT_NAME` và `TRADING_ENV_FILE` được tôn trọng.

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

**Không bao giờ:** xóa gì ngoài các thư mục `snapshots/<id>` theo quy tắc giữ lại; ghi đè một đối tượng từ xa; cung cấp tùy chọn ép buộc; ping một dịch vụ giám sát bên ngoài (unit sao lưu không ping gì; bộ gửi heartbeat là một script riêng, `deploy/heartbeat.sh`, mục 8.3, và nó chỉ dò collector).

### Thẻ lệnh: deploy/systemd/trading-backup.service

> - **Để làm gì:** Đơn vị systemd gọi `deploy/backup.sh` mỗi khi timer kích hoạt.
> - **Giải quyết vấn đề gì:** Bản sao lưu lỗi làm unit lỗi một cách thấy được thay vì im lặng; chạy bằng user `trading` có quyền docker.
> - **Mức quan trọng:** **BẮT BUỘC** nếu bạn muốn sao lưu tự động (D042 điều kiện 2 đòi có lịch); bạn cài bằng một lệnh và không sửa tay. Lưu ý: unit lỗi vẫn không tự báo cho bạn; heartbeat của collector ở mục 8.3 không bao phủ sao lưu (RUNBOOK 11.4).

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

> - **Để làm gì:** Hẹn giờ kích hoạt bản sao lưu mỗi ngày lúc 03:15 UTC, và chạy bù nếu máy tắt đúng lúc đó.
> - **Giải quyết vấn đề gì:** Không ai phải nhớ sao lưu; `Persistent=true` chạy bù lần lỡ, `RandomizedDelaySec=5m` tránh dồn nhiều máy vào cùng một giây.
> - **Mức quan trọng:** **BẮT BUỘC** nếu bạn muốn sao lưu tự động (D042 điều kiện 2: có lịch).

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

### Thẻ lệnh: deploy/systemd/trading-soak-backup.service

> - **Để làm gì:** Đơn vị systemd sao lưu cơ sở dữ liệu của project soak (`trading-soak`), nơi chứa bằng chứng soak.
> - **Giải quyết vấn đề gì:** Unit `trading-backup` không đặt project nên chỉ sao lưu project `trading`; volume `trading-soak_pgdata` sẽ không được sao lưu nếu thiếu unit này (review B2-WR-07).
> - **Mức quan trọng:** **BẮT BUỘC** trước soak dài (RUNBOOK 20.5; D061 hosts: có sao lưu trước soak dài). Bucket riêng của soak do chủ dự án tạo trước kế hoạch 16-43.

**Mục đích:** unit oneshot gọi `deploy/backup.sh` với `COMPOSE_PROJECT_NAME=trading-soak` và `TRADING_ENV_FILE` là tệp env soak. Remote sao lưu không có tên project trong đường dẫn, nên project soak phải dùng một bucket riêng với mật khẩu crypt riêng; dùng chung một bucket thì hai project thành một chuỗi snapshot và quy tắc giữ lại sẽ xóa bản sao lưu hằng ngày của một trong hai.

**Khi nào chạy:** không chạy tay. Cài một lần bằng `sudo deploy/backup.sh --install-soak-timer --soak-env-file <đường dẫn tuyệt đối>`, sau khi bucket riêng đã được khởi tạo bằng `--init-remote` cho project soak (RUNBOOK 20.5). Lệnh cài từ chối khi `BACKUP_S3_BUCKET` của tệp env soak rỗng hoặc trùng bucket của tệp `.env` của `trading-backup`, và chỉ in tên biến, không in giá trị.

**Chạy ở máy nào:** `[MÁY EC2]`, dưới systemd.

**Lệnh:** khởi tạo remote của soak, cài, rồi xem trạng thái và nhật ký:

```bash
COMPOSE_PROJECT_NAME=trading-soak TRADING_ENV_FILE=/home/trading/soak.env deploy/backup.sh --init-remote
```

```bash
sudo deploy/backup.sh --install-soak-timer --soak-env-file /home/trading/soak.env
```

```bash
systemctl status trading-soak-backup
```

```bash
journalctl -u trading-soak-backup
```

**Chạy thử:** Không áp dụng cho chính tệp unit. Xem trước việc cài bằng `sudo deploy/backup.sh --install-soak-timer --soak-env-file /home/trading/soak.env --dry-run`.

**Dấu hiệu thành công:** `journalctl -u trading-soak-backup` có `push-OK`; lần diễn tập khôi phục cho project soak (`COMPOSE_PROJECT_NAME=trading-soak TRADING_ENV_FILE=/home/trading/soak.env deploy/backup-drill.sh`) thành công.

**Mã thoát:** unit lỗi khi lớp vỏ thoát khác 0. Lệnh cài thoát 1 khi bucket rỗng, trùng bucket của `trading-backup`, tệp env không đọc được, hay đường dẫn không tuyệt đối; thoát 2 khi thiếu `--soak-env-file`.

**Khi lỗi:** đọc `journalctl -u trading-soak-backup`; bucket bị từ chối: tạo bucket riêng cho soak, đặt tên đó vào tệp env soak, chạy `--init-remote` cho project soak rồi cài lại.

**Không bao giờ:** đặt cho tệp env soak cùng bucket với `trading-backup`; sửa tay bản đã cài trong `/etc/systemd/system`; sửa cặp unit `trading-backup` để dùng cho soak.

### Thẻ lệnh: deploy/systemd/trading-soak-backup.timer

> - **Để làm gì:** Hẹn giờ sao lưu project soak mỗi ngày theo đúng lịch của `trading-backup.timer`.
> - **Giải quyết vấn đề gì:** Bằng chứng soak có bản sao lưu hằng ngày ngoài máy mà không ai phải nhớ; `Persistent=true` chạy bù lần lỡ.
> - **Mức quan trọng:** **BẮT BUỘC** trước soak dài (RUNBOOK 20.5).

**Mục đích:** timer kích hoạt `trading-soak-backup.service` hằng ngày lúc 03:15 UTC, cùng `OnCalendar`, `Persistent` và `RandomizedDelaySec` với `trading-backup.timer`; hai project đẩy vào hai bucket khác nhau.

**Khi nào chạy:** không chạy tay; được cài và bật bởi `sudo deploy/backup.sh --install-soak-timer --soak-env-file <đường dẫn>`.

**Chạy ở máy nào:** `[MÁY EC2]`, dưới systemd.

**Lệnh:**

```bash
systemctl list-timers trading-soak-backup.timer
```

**Chạy thử:** Không áp dụng cho chính tệp unit. Xem trước bằng `sudo deploy/backup.sh --install-soak-timer --soak-env-file /home/trading/soak.env --dry-run`.

**Dấu hiệu thành công:** `systemctl list-timers trading-soak-backup.timer` liệt kê timer với thời điểm kích hoạt kế tiếp.

**Mã thoát:** timer không có mã thoát; kết quả nằm ở unit service mà nó kích hoạt.

**Khi lỗi:** timer không xuất hiện: chạy lại lệnh cài và đọc đầu ra. Việc timer kích hoạt đúng giờ chỉ máy thật mới chứng minh được `[CHƯA XÁC MINH]`.

**Không bao giờ:** coi timer đang bật là bằng chứng bản sao lưu có hiệu lực trước khi một lần diễn tập khôi phục cho project soak thành công.

### Thẻ lệnh: deploy/restore.sh

> - **Để làm gì:** Khôi phục bản sao lưu đã kiểm mới nhất từ S3 lên một máy trống.
> - **Giải quyết vấn đề gì:** Dựng lại sau khi mất máy, hoặc quay về từ migration mà mã cũ không đọc được; script từ chối bundle bị sửa và không bao giờ ghi đè tệp Parquet.
> - **Mức quan trọng:** **BẮT BUỘC** phải có khả năng này và đã diễn tập (D042 điều kiện 2: một lần diễn tập khôi phục thật); bản thân lệnh chỉ chạy khi có sự cố.

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

> - **Để làm gì:** Diễn tập cả chuỗi sao lưu và khôi phục vào một cơ sở dữ liệu tạm, rồi so số hàng với bản sống mà không đụng dữ liệu sống.
> - **Giải quyết vấn đề gì:** Một bản sao lưu chưa từng khôi phục thử thì chưa biết có dùng được; diễn tập phát hiện khóa sai hay bundle hỏng trước khi bạn cần đến nó.
> - **Mức quan trọng:** **BẮT BUỘC** (D042 điều kiện 2: có một lần diễn tập khôi phục thật; RUNBOOK: bản sao lưu chưa hợp lệ cho tới khi một lần diễn tập qua). Chu kỳ định kỳ là quyết định của bạn.

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

### Thẻ lệnh: deploy/backup-real-s3-gate.sh

> - **Để làm gì:** Chạy cổng D064 trên S3 thật: kiểm từng khẳng định phát hiện của bước đẩy Parquet (so SHA-256 với manifest, `cryptcheck` sau khi tải lên, đối tượng nhiều phần) với remote mà bản sao lưu đang dùng, dưới một prefix dùng một lần.
> - **Giải quyết vấn đề gì:** D064 chỉ chấp nhận thiết kế đẩy khi các khẳng định đó được chứng minh trên S3 thật qua lớp crypt; kết quả S3 thật còn chờ cho tới khi bạn chạy lệnh này và thấy `RESULT: PASS` (RUNBOOK 11, "Real-S3 gate").
> - **Mức quan trọng:** **BẮT BUỘC** trước bản sao lưu thật đầu tiên của project soak (D064; quyết định của chủ dự án ngày 2026-10-20; RUNBOOK 11; checklist 16-43 bước 1a).

**Mục đích:** lớp vỏ mỏng chạy `python -m src.ops.backup real-s3-gate` trong image `ops`. Mọi đối tượng được ghi dưới prefix mới `d064-gate-<UTC>-<12 hex>` ngay dưới bucket đã cấu hình (từ chối nếu prefix không trống), prefix bị xóa sạch ở mọi lối ra, và kết quả là một dòng `CLAIM <id>: PASS` hay `FAIL` cho mỗi khẳng định, kết thúc bằng `RESULT: PASS` hoặc `RESULT: FAIL`. Không in bucket (hiện là `<bucket>`) hay khóa nào.

**Khi nào chạy:** trước bản sao lưu thật đầu tiên, và lại sau mọi thay đổi nhà cung cấp, phiên bản rclone hay image.

**Chạy ở máy nào:** `[MÁY EC2]` bằng user `trading`, từ checkout có commit 261020-bkp.

**Lệnh:**

```bash
COMPOSE_PROJECT_NAME=trading-soak TRADING_ENV_FILE=/home/trading/soak.env deploy/backup-real-s3-gate.sh --execute --evidence-dir /home/trading/gate-evidence
```

Cờ: `--execute`, `--evidence-dir DIR` (mặc định `$HOME/trading-evidence`, ngoài checkout), `--dry-run`, `-h`/`--help`. Không có `--execute` thì chỉ in kế hoạch, không gọi remote.

**Chạy thử:**

```bash
COMPOSE_PROJECT_NAME=trading-soak TRADING_ENV_FILE=/home/trading/soak.env deploy/backup-real-s3-gate.sh --execute --dry-run
```

Không có `--execute`, lệnh chỉ in kế hoạch (prefix và các khẳng định) mà không gọi remote.

**Dấu hiệu thành công:** tệp bằng chứng `d064-real-s3-gate-<UTC>.txt` có mọi dòng `CLAIM ...: PASS` (kể cả `cleanup`) và dòng cuối `RESULT: PASS`.

**Mã thoát:** 0 mọi khẳng định qua; 1 có khẳng định trượt hoặc bị ngắt; 2 lỗi cách dùng hay cấu hình (không đụng gì, kể cả khi `BACKUP_REMOTE=none`).

**Khi lỗi:** một dòng `FAIL`: dừng, không sao lưu thật, báo cho chủ dự án (D064: thiết kế khi đó không được coi là bảo vệ toàn vẹn). `cleanup` trượt: xóa tay prefix được nêu tên.

**Không bao giờ:** chạy với một prefix tự chọn ngoài dạng `d064-gate-...`; dán nội dung tệp env hay khóa vào bằng chứng.

### Thẻ lệnh: scripts/backup-drill.ps1

> - **Để làm gì:** Diễn tập bundle sao lưu cục bộ trên Windows (hai pha backup rồi drill), không qua S3.
> - **Giải quyết vấn đề gì:** Cho người dùng Windows kiểm một bundle cục bộ của Phase 2; nó không kiểm chuỗi S3 mã hóa của Phase 13.1.
> - **Mức quan trọng:** **TÙY CHỌN**: script thuộc Phase 2 và không đụng chuỗi S3 của D050; hướng dẫn này không coi nó là bước bắt buộc và nó không thay `deploy/backup-drill.sh`.

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

> - **Để làm gì:** Mô tả tiến trình paper và soak SHADOW của Phase 16: bảng 50 kế hoạch, điểm vào, chuỗi đóng phase và tiêu chí thoát.
> - **Giải quyết vấn đề gì:** Cho bạn thấy chính xác phần nào đã có và phần nào chưa (14 trong 50 kế hoạch), để không đi tìm lệnh không tồn tại và biết mình phải quyết định gì ở từng cổng.
> - **Mức quan trọng:** **BẮT BUỘC** về mặt con đường (D061 mục J: Phase 16 chỉ đóng sau chuỗi này) nhưng hôm nay chỉ để đọc, vì chưa có lệnh nào chạy được.

#### Bước 7.1 Phase 16 làm gì, bằng lời thường [CHƯA XÂY]

> - **Để làm gì:** Giải thích bằng lời thường Phase 16 làm ra gì: tiến trình paper, thông báo SHADOW, nhật ký quyết định, khớp lệnh mô phỏng.
> - **Giải quyết vấn đề gì:** Cho bạn biết mục đích của soak (quan sát theo đồng hồ treo tường, không có đường nào tới lệnh thật, D040) trước khi bạn trả tiền thuê máy.
> - **Mức quan trọng:** **NÊN LÀM** đọc; không có thao tác. Mức này là đánh giá của hướng dẫn này.

**Chạy ở:** đọc, không chạy gì (`[MÁY PHÁT TRIỂN]` cho mã, `[MÁY EC2]` cho soak)

Phase 16 dựng một tiến trình paper chạy được: nó theo dõi dữ liệu thị trường Binance trực tiếp, tạo tín hiệu và kế hoạch, và gửi cho bạn các thông báo Telegram nhãn SHADOW kèm nút APPROVE/SKIP rồi bước CONFIRM (D041), ghi nhật ký quyết định cùng các lần khớp lệnh mô phỏng, và không có bất kỳ đường nào dẫn tới một lệnh thật (D040). Mục đích là bắt đầu một đợt soak tính theo đồng hồ treo tường để quan sát. Những tiêu chí thành công (SC) quan trọng với người vận hành, theo ROADMAP: SC2 adapter WebSocket thật sự `await` lời gọi SDK; SC3 nút SIMULATE hoạt động và độ trễ phê duyệt được đo chứ không cố định 30 giây; SC5 thông báo ghi rõ "SHADOW" và mọi quyết định được ghi nhật ký; SC6 cô lập cứng (không khóa giao dịch, không adapter lệnh); SC7 một lần smoke trực tiếp; SC8 và SC9 trial soak và quy tắc đóng yêu cầu. Hôm nay mới có 14 trong 50 kế hoạch.

#### Bước 7.2 Hôm nay máy EC2 chạy được gì [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]`

Chỉ ba service chạy theo mặc định: `postgres`, `db-upgrade` (chạy một lần) và `collector`. Service `paper` trong compose (profile `paper`) là một khung giữ chỗ chạy là thoát ngay: nó in "paper runner not implemented yet: arrives in Phase 16" và `restart` là `"no"`. Bạn không có gì để khởi động bằng profile `paper` hôm nay.

#### Bước 7.3 Bảng đủ 50 kế hoạch của Phase 16 [ĐÃ XÂY] [CHƯA XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY CÓ MẠNG]` (chỉ để đọc; không có máy nào chạy gì ở bước này)

Quy tắc đọc: 16-01 đến 16-14 có tệp SUMMARY trong `.planning/phases/16-paper-runtime-composition/`, nên được ghi `[ĐÃ XÂY]`; từ 16-15 trở đi chưa có (trừ 16-50, xem dưới), nên là `[CHƯA XÂY]`. Kế hoạch 16-50 "Off-host heartbeat sender" (bộ gửi heartbeat ra ngoài VPS) được thêm sau 16-49; ROADMAP đọc ngày 2026-10-09 đã kể đủ 16-01 đến 16-50. Kế hoạch 16-50 đã có tệp SUMMARY (script `deploy/heartbeat.sh` và hai unit, kiểm thử bằng đồ giả); việc cài nó vẫn chờ bạn ghi hai giá trị O-12 (chu kỳ gửi và thời gian ân hạn của dịch vụ giám sát) vào bản ghi quyết định O-12; agent không tự chọn hai giá trị đó. Kế hoạch 16-43 (khởi động trial soak) phụ thuộc vào 16-50: bộ gửi heartbeat phải xây xong và phép thử `HEARTBEAT_MONITOR_ALERT_RECEIVED` phải đạt trước khi epoch được ghim (D042 điều kiện 1). Lưu ý: "đã xây" nghĩa là code và kiểm thử ở mức đồ giả; chưa có gì chạy trên máy EC2, nên các hàng cần bằng chứng trên máy thật, sàn thật hay Telegram thật còn mang thêm `[CHƯA XÁC MINH]`. Ngày đọc: 2026-10-09.

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
| 16-43 | Paper bắt đầu, epoch được ghim, trial soak khởi động; phụ thuộc cả 16-50 (bộ gửi heartbeat phải xây xong trước) | `[CHƯA XÂY]` | 7.6 |
| 16-44 | Trial soak đạt tiêu chí đã phê chuẩn và bạn tuyên bố đạt | `[CHƯA XÂY]` | 7.6 |
| 16-45 | Giả thuyết và lưới tham số do bạn viết hoặc duyệt | `[CHƯA XÂY]` | 7.6 |
| 16-46 | Lệnh riêng của bạn cho phép chạy nghiên cứu, rồi lần chạy thật đầu tiên | `[CHƯA XÂY]` | 7.6 |
| 16-47 | Cài vào code hai quyết định lưu trữ bằng chứng và cách freeze check lấy epoch đã ghim | `[CHƯA XÂY]` | 7.7 |
| 16-48 | Bạn chỉ định ứng viên hợp lệ trong số các ứng viên đã đăng ký | `[CHƯA XÂY]` | 7.6 |
| 16-49 | Cấu hình đích lưu bằng chứng bền vững bạn đã chọn và chứng minh đường công bố bằng gói thử | `[CHƯA XÂY]` | 7.7 |
| 16-50 | Bộ gửi heartbeat ra ngoài VPS ("Off-host heartbeat sender") để dịch vụ giám sát bên ngoài, đã chọn là healthchecks.io, biết khi tín hiệu dừng; đã xây (script `deploy/heartbeat.sh` và hai unit); việc cài nó vẫn chờ bạn ghi hai giá trị O-12 (chu kỳ và thời gian ân hạn) và phép thử `HEARTBEAT_MONITOR_ALERT_RECEIVED`, và 16-43 phải chờ phép thử đó | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` | 3.11, 8.3 |

#### Bước 7.4 Điểm vào của runtime [CHƯA XÂY]

**Chạy ở:** `[MÁY EC2]` (khi nó tồn tại)

Điểm vào dự kiến của tiến trình paper là module dưới đây (kế hoạch 16-22). Nó là `[CHƯA XÂY]`: repository không có tệp src/paper/runtime.py. Khối dưới đây chỉ để bạn biết tên; đừng chạy nó và đừng tìm cờ của nó:

```bash
python -m src.paper.runtime
```

Vòng lặp sống, pipeline từng nến, sổ cái mô phỏng, bộ tạo khớp lệnh, độ trễ đo được và việc nối các mảnh SHADOW là các kế hoạch 16-19, 16-23, 16-24, 16-26, 16-31, 16-34, 16-35 trong bảng ở bước 7.3; tất cả là `[CHƯA XÂY]`.

#### Bước 7.5 Cấu hình triển khai soak và phần vận hành [CHƯA XÂY]

**Chạy ở:** `[MÁY EC2]` (khi các kế hoạch tồn tại)

Kế hoạch 16-32 đã thêm cấu hình triển khai soak vào repository (`[ĐÃ XÂY]` `[CHƯA XÁC MINH]`: chưa chạy trên máy thật). Service `paper` trong `docker-compose.yml` chạy tiến trình paper với cờ `--hold-on-refusal` và probe thật `--healthcheck`, dùng volume `logs`, chính sách restart `on-failure`: khi allowlist rỗng tiến trình thoát 0 và không bị khởi động lại, còn khi cấu hình bị từ chối (mã thoát 3 đến 6) container ở lại, báo không khỏe, thay vì lặp lại khởi động. Script `deploy/compose-soak.sh` luôn chạy project `trading-soak` (volume cơ sở dữ liệu riêng, tách khỏi stack phát triển và các cơ sở dữ liệu kiểm thử) và từ chối lệnh `down` kèm cờ xóa volume (thẻ lệnh bên dưới). Mẫu `deploy/soak.env.example` chỉ liệt kê tên biến, không có giá trị và không có tên khóa giao dịch; một biến có tên bắt đầu bằng tiền tố của khóa giao dịch làm tiến trình paper từ chối khởi động. 

Mọi service `x-app` dùng chung một env_file nên container paper cũng thấy các biến `BACKUP_*` cho tới khi tách env_file theo service ở Phase 24 (WR-06). Kế hoạch 16-33 đã thêm mục 20 của runbook, phần vận hành project soak (chỉ qua script bọc, mỗi lần triển khai trong trial là PLANNED_RESTART không được phủ, bot Telegram riêng, diễn tập trong project riêng, sao lưu và diễn tập khôi phục trước soak dài). Các quy tắc ĐÃ quyết định (D061 hosts): cơ sở dữ liệu soak tách khỏi cơ sở dữ liệu phát triển và kiểm thử; soak chạy từ một image đã ghim chứ không từ cây làm việc; sao lưu phải tồn tại trước soak dài; và không bao giờ chạy `docker compose down` kèm cờ xóa volume trên project soak. Cách một image "đã ghim" được tạo ra (CI hôm nay không đẩy image nào) do người dùng quyết định ngày 2026-10-10 (Q-I, lựa chọn `host-build-recorded`): dựng trên máy chủ tại một commit đã ghi, gắn thẻ bằng commit và ghi mã image.

Script `deploy/soak-image.sh` thực hiện việc đó (thẻ lệnh bên dưới; `[ĐÃ XÂY]` `[CHƯA XÁC MINH]`: chưa chạy trên máy thật). Hai lựa chọn còn lại không phải phương án dự phòng tự động.

Kế hoạch 16-47 thêm bước xuất và đăng bằng chứng trial (mục 20.7 của runbook; `[ĐÃ XÂY]` `[CHƯA XÁC MINH]`: chưa chạy trên máy thật, chưa có bucket thật). Nơi lưu là kho S3 riêng cho bằng chứng, không đi qua lớp mã hóa của chuỗi sao lưu. Địa chỉ và thông tin đăng nhập của kho này chỉ đến từ các tên biến cố định `EVIDENCE_S3_*`, khác hẳn các tên `BACKUP_*`; mẫu tên nằm ở tệp `deploy/evidence.env.example` (chỉ có tên, không có giá trị). Tệp thật đặt ngoài checkout, quyền 0600, chỉ nạp vào shell chạy lệnh xuất, và không nằm trong tệp môi trường soak dùng chung với container paper. Lệnh `--publish` không nhận địa chỉ gõ tay.

Kế hoạch 16-53 thêm script bọc cho buổi diễn tập trước soak (mục 20.4 của runbook; `[ĐÃ XÂY]` `[CHƯA XÁC MINH]`: chưa chạy trên máy thật). Buổi diễn tập chạy trong project riêng `trading-rehearsal`, có volume cơ sở dữ liệu riêng và tệp môi trường riêng đặt ngoài checkout, không bao giờ trong project soak. Script từ chối mọi biến có tên bắt đầu bằng tiền tố của khóa giao dịch (trong môi trường lẫn trong tệp môi trường, chỉ in tên) và từ chối chạy khi project soak còn container đang chạy. Chính `scripts/shadow_rehearsal.py` cũng từ chối biến loại đó ở cả hai chế độ.

### Thẻ lệnh: deploy/compose-soak.sh

> - **Để làm gì:** Chạy `docker compose` chỉ trên project soak `trading-soak` và từ chối mọi lệnh `down` kèm cờ xóa volume.
> - **Giải quyết vấn đề gì:** Một lệnh gõ nhầm có thể xóa volume cơ sở dữ liệu của soak, nơi giữ bằng chứng của trial; script chặn điều đó và giữ soak tách khỏi stack phát triển (project `trading`).
> - **Mức quan trọng:** **BẮT BUỘC** cho mọi lệnh compose trên máy soak (D061 mục hosts: lệnh `down` kèm cờ xóa volume không bao giờ chạy trên project soak).

**Mục đích:** chuyển mọi lệnh `docker compose` sang project `trading-soak` (volume như `trading-soak_pgdata`) và từ chối `down` kèm `-v` hoặc `--volumes`, dù cờ nằm ở đâu và dù tên project được đưa vào bằng cờ `-p`, cờ `--project-name` hay biến `COMPOSE_PROJECT_NAME`. Cờ `-p` hay `--project-name` trỏ sang project khác cũng bị từ chối.

**Khi nào chạy:** thay cho `docker compose` trong mọi thao tác trên máy soak (khởi động, xem trạng thái, xem nhật ký, dừng).

**Chạy ở máy nào:** `[MÁY EC2]`, trong checkout; biến `TRADING_ENV_FILE` chọn tệp môi trường soak (tạo từ `deploy/soak.env.example`, đặt ngoài checkout, quyền 0600).

**Lệnh:**

```bash
deploy/compose-soak.sh ps
```

```bash
deploy/compose-soak.sh up -d
```

Mọi đối số được chuyển nguyên cho compose của project soak; chọn profile `paper` bằng cờ `--profile paper` của compose đặt trước lệnh con.

**Chạy thử:** đặt `DRY_RUN=1` trong môi trường: script chỉ in lệnh sẽ chạy và không chạy gì (script không có cờ riêng để chạy thử).

**Dấu hiệu thành công:** script in lệnh compose sẽ chạy, bắt đầu bằng dấu cộng và có cờ `-p` với project trading-soak, rồi thoát với mã của chính lệnh compose.

**Mã thoát:** 0 khi `docker compose` thành công. 1 khi script từ chối (`down` kèm cờ xóa volume, hoặc tên project khác `trading-soak`) với thông báo "refused: ...". Các mã khác là mã của `docker compose`.

**Khi lỗi:** thông báo "refused: down -v on the soak project" nghĩa là lệnh bị chặn có chủ ý; đừng tìm cách vòng qua. Muốn xóa volume soak là quyết định của con người trên máy chủ, sau một buổi diễn tập khôi phục, không bao giờ qua script này.

**Không bao giờ:** gõ trực tiếp `docker compose` kèm `down` và cờ xóa volume trên project soak; đặt giá trị khóa giao dịch vào tệp môi trường soak; chép tệp môi trường thật vào git.

### Thẻ lệnh: deploy/soak-image.sh

> - **Để làm gì:** Dựng image của soak ngay trên máy chủ từ một commit sạch, gắn thẻ image bằng commit đó và ghi lại commit cùng mã image.
> - **Giải quyết vấn đề gì:** CI hôm nay không đẩy image nào, nên "image đã ghim" cần một cách làm cụ thể; script từ chối cây làm việc còn thay đổi chưa commit, để bằng chứng của trial luôn trỏ tới đúng một commit và một image, và soak không bao giờ chạy từ thư mục làm việc.
> - **Mức quan trọng:** **BẮT BUỘC** trước khi khởi động soak và sau mỗi commit đổi allowlist hoặc mã nguồn (D-32 và mục 20.6 của RUNBOOK; quyết định Q-I của người dùng, lựa chọn `host-build-recorded`, ghi ở `16-DEC-Q-I.md`).

**Mục đích:** dựng `trading-alert:<commit>` và `trading-alert-ops:<commit>` (commit đầy đủ 40 ký tự) bằng `deploy/compose-soak.sh`, kiểm tra cây làm việc và HEAD không đổi trong lúc dựng, rồi ghi `GIT_SHA`, `IMAGE_TAG`, `APP_IMAGE_ID` và `OPS_IMAGE_ID` vào `.deploy/soak-image.env` (quyền 0600, không vào git; bản cũ giữ thành `soak-image.env.prev`, mỗi lần dựng được nối vào `.deploy/soak-image.history`). Tệp này tách khỏi `last-good.env` của `deploy/update.sh`, vì `update.sh` ghi đè `last-good.env` ở mỗi lần chạy `--ref`.

**Khi nào chạy:** trên máy soak, sau khi checkout đúng commit cần chạy và sau commit đổi allowlist (allowlist là hằng số trong mã nguồn nên image phải được dựng lại sau commit đó); mỗi lần triển khai trong lúc trial cũng bắt đầu bằng lệnh này và là một PLANNED_RESTART không được tính là thời gian có phủ.

**Chạy ở máy nào:** `[MÁY EC2]`, trong checkout; cần Docker và bộ công cụ dựng image như bước khởi động đầu tiên của mục 13.6 của runbook.

**Lệnh:**

```bash
deploy/soak-image.sh
```

Sau đó khởi động soak qua script bọc với biến `IMAGE_TAG` bằng giá trị `GIT_SHA` đã ghi, theo lệnh đã cho ở mục 20.6 của runbook (cờ `--no-build` của compose giữ cho compose không dựng thêm gì).

**Chạy thử:** `deploy/soak-image.sh --dry-run` in các lệnh và bản ghi sẽ ghi, không dựng và không ghi gì; việc từ chối cây làm việc bẩn vẫn áp dụng.

**Dấu hiệu thành công:** script in dòng `commit`, hai dòng `image`, lệnh dựng bắt đầu bằng dấu cộng, bản ghi bốn dòng và dòng "soak image recorded"; `docker image inspect --format '{{.Id}}' trading-alert:<commit>` in đúng giá trị `APP_IMAGE_ID` đã ghi.

**Mã thoát:** 0 khi dựng và ghi xong. 1 khi cây làm việc có thay đổi chưa commit (kể cả tệp chưa theo dõi), HEAD đổi trong lúc dựng, hoặc image không tồn tại sau khi dựng. 2 khi dùng tùy chọn sai. Các mã khác là mã của lệnh dựng.

**Khi lỗi:** thông báo "uncommitted changes" nghĩa là phải commit hoặc bỏ thay đổi trước, rồi chạy lại; đừng sửa tệp trong lúc đang dựng. Nếu lệnh dựng lỗi, không có bản ghi nào được ghi và không được khởi động soak từ một image không có bản ghi.

**Không bao giờ:** khởi động soak từ thư mục làm việc gắn vào container (bind mount) hoặc từ một image không có dòng trong `.deploy/soak-image.history`; sửa tay `soak-image.env`; dùng `deploy/update.sh` cho project soak.

### Thẻ lệnh: deploy/compose-rehearsal.sh

> - **Để làm gì:** Chạy `docker compose` chỉ trên project diễn tập `trading-rehearsal`, tách khỏi project soak và stack phát triển.
> - **Giải quyết vấn đề gì:** Buổi diễn tập SHADOW dùng bot Telegram thật nên phải có cơ sở dữ liệu riêng, không dính vào cơ sở dữ liệu soak là nơi giữ bằng chứng của trial; script chặn tên project khác, tệp môi trường soak lẫn vào, khóa giao dịch và việc chạy chồng lên soak.
> - **Mức quan trọng:** **NÊN LÀM** trước khi diễn tập (mục 20.4 của RUNBOOK; ngăn rủi ro T-16-92 của kế hoạch 16-40, đánh giá của hướng dẫn: không bắt buộc về mặt kỹ thuật nhưng thay cho lệnh `docker compose` gõ tay).

**Mục đích:** chuyển mọi lệnh `docker compose` sang project `trading-rehearsal` (volume như `trading-rehearsal_pgdata`), lấy tệp môi trường chỉ từ biến `TRADING_ENV_FILE`, và từ chối trước khi gọi docker khi: biến đó chưa đặt, không đọc được hoặc trỏ vào trong checkout; có biến tên bắt đầu bằng tiền tố của khóa giao dịch trong môi trường hoặc trong tệp; cờ `-p` hay `--project-name` trỏ sang project khác; có cờ `--env-file`; hoặc project soak còn container đang chạy.

**Khi nào chạy:** thay cho `docker compose` trong mọi thao tác của buổi diễn tập (khởi động cơ sở dữ liệu diễn tập, xem trạng thái, dừng), sau khi runtime soak đã thoát ở trạng thái SKIPPED.

**Chạy ở máy nào:** `[MÁY EC2]`, trong checkout; tệp môi trường diễn tập tạo tay, đặt ngoài checkout, quyền 0600, có cổng `POSTGRES_PORT` khác cổng của soak và không có tên khóa giao dịch nào.

**Lệnh:**

```bash
TRADING_ENV_FILE=/home/trading/rehearsal.env deploy/compose-rehearsal.sh up -d db-upgrade
```

```bash
TRADING_ENV_FILE=/home/trading/rehearsal.env deploy/compose-rehearsal.sh ps
```

```bash
TRADING_ENV_FILE=/home/trading/rehearsal.env deploy/compose-rehearsal.sh stop
```

Mọi đối số sau đó được chuyển nguyên cho compose của project diễn tập; `stop` giữ lại volume.

**Chạy thử:** `TRADING_ENV_FILE=/home/trading/rehearsal.env deploy/compose-rehearsal.sh --dry-run up -d db-upgrade` in lệnh compose sẽ chạy, không gọi docker và không kiểm tra project soak (bản chạy thật mới kiểm tra); cờ `--dry-run` chỉ được nhận khi đứng đầu các đối số, và biến `DRY_RUN=1` cho kết quả tương tự.

**Dấu hiệu thành công:** script in dòng bắt đầu bằng dấu cộng, có cờ `-p` với project trading-rehearsal và cờ `--env-file` với tệp diễn tập, rồi thoát với mã của chính lệnh compose.

**Mã thoát:** 0 khi `docker compose` thành công (hoặc khi chạy thử). 1 khi script từ chối với thông báo "refused: ...". 2 khi không có đối số compose nào. Các mã khác là mã của `docker compose`.

**Khi lỗi:** "trade-capable variable present" kèm tên biến nghĩa là phải xóa biến đó khỏi môi trường và khỏi tệp diễn tập (chỉ tên được in, không in giá trị); "has running containers" nghĩa là dừng soak trước bằng `deploy/compose-soak.sh stop` (không xóa volume), rồi chạy lại; đừng tìm cách vòng qua bằng lệnh `docker compose` gõ tay.

**Không bao giờ:** dùng tệp môi trường soak cho buổi diễn tập; đặt giá trị khóa giao dịch hay token vào tệp diễn tập đưa vào git; chạy buổi diễn tập trên cơ sở dữ liệu của project soak.

#### Bước 7.6 Chuỗi đóng (closure chain) và ai quyết định từng bước [THỦ CÔNG] [CHƯA XÂY]

> - **Để làm gì:** Chuỗi bước và ai quyết định từng bước để Phase 16 đóng: giả thuyết, lưới tham số, lệnh cho chạy nghiên cứu, ứng viên, băm trong allowlist, trial soak.
> - **Giải quyết vấn đề gì:** Không có gì tự tiến: mọi bước chạm Binance hay Telegram cần người, và không giá trị nào được chọn từ kết quả backtest.
> - **Mức quan trọng:** **BẮT BUỘC** (D061 mục J). Hôm nay `PAPER_START_ALLOWLIST` rỗng là trạng thái an toàn hợp lệ, không phải lỗi.

**Chạy ở:** `[MÁY CÓ MẠNG]` cho mọi bước chạm Binance hoặc Telegram

Phase 16 chỉ đóng sau chuỗi dưới đây (D061 mục J). Mọi bước chạm Binance hoặc Telegram là blocking-human: không có gì tự tiến.

1. Runtime sẵn sàng, được chứng minh bởi 16-38 và buổi diễn tập 16-40.
2. Bạn viết hoặc duyệt giả thuyết và lưới tham số (16-45); agent chỉ soạn nháp bằng ngôn ngữ thường kèm lý do và nguồn.
3. Một LỆNH RIÊNG của bạn cho phép chạy nghiên cứu (16-46); duyệt lưới không có nghĩa là cho phép chạy. Trước đó phải có bản sửa giao thức v2.2.0 (16-28, D065) như một nhiệm vụ tiên quyết riêng.
4. Một ứng viên hợp lệ (có lý do, đã đăng ký trước, đúng cấu trúc, không còn PLACEHOLDER, đã đăng ký và có băm) được bạn chỉ định (16-48). Nó KHÔNG cần qua G1 đến G5, và G1 đến G5 không bao giờ dùng để xếp hạng ứng viên.
5. Bạn cho phép đúng băm đó trong `PAPER_START_ALLOWLIST` bằng `strategy_id`, `parameter_set_id` và SHA-256 64 ký tự cùng `purpose`, `approved_at`, `basis` (16-42). Hôm nay allowlist RỖNG theo quyết định của bạn; đó là trạng thái an toàn hợp lệ, không phải lỗi.
6. Paper bắt đầu và epoch được ghim (16-43), sau khi bộ gửi heartbeat 16-50 đã xây, đã cài và phép thử cảnh báo đã đạt. Mỗi chuyển trạng thái là một lệnh rõ ràng của bạn.
7. Trial soak đạt các tiêu chí đã phê chuẩn và bạn tuyên bố đạt (16-44).

Không được chọn bất kỳ giá trị nào từ kết quả backtest hay nghiên cứu. Hai câu hỏi bằng chứng mở (OQ-1 về lệnh giữ qua lỗ hổng mark price, và O-10 về chi phí mô hình) được hỏi bạn sau lần nghiên cứu thật đầu (16-41).

#### Bước 7.7 Tiêu chí thoát đã phê chuẩn và bằng chứng [CHƯA XÂY]

> - **Để làm gì:** Liệt kê tiêu chí thoát bạn đã phê chuẩn ngày 2026-10-07 cho trial soak 14 ngày.
> - **Giải quyết vấn đề gì:** Quyết định trước thế nào là "đạt" để không chọn ngưỡng sau khi đã thấy kết quả (D061 mục D).
> - **Mức quan trọng:** **BẮT BUỘC** (D061 mục D: đổi bất kỳ tiêu chí nào trước khi trial bắt đầu phải có sự chấp thuận mới của bạn). Chưa có code đo chúng.

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

Làm được hôm nay: hoàn thành mục 2 đến 6; chuẩn bị bot Telegram riêng (mục 8.1). Phải chờ: quyết định O-12 để tạo máy; mọi thứ từ 16-15 đến 16-50. Không có tiến trình paper để khởi động, không có epoch để ghim và không có trial để đo.

Nguồn: `.planning/ROADMAP.md`, `.planning/phases/16-paper-runtime-composition/16-CONTEXT.md`, `docker-compose.yml`, `docs/DECISIONS.md`, `.planning/phases/16-paper-runtime-composition/16-22-PLAN.md`, `deploy/compose-soak.sh`, `deploy/compose-rehearsal.sh`, `deploy/soak.env.example`

## 8. Telegram, Binance và giám sát bên ngoài

> - **Để làm gì:** Ba kênh ra ngoài máy: bot Telegram riêng cho máy soak, khóa Binance theo từng giai đoạn kèm danh sách IP cho phép (whitelist), và dịch vụ heartbeat giám sát từ ngoài VPS.
> - **Giải quyết vấn đề gì:** Hai nơi dùng chung một token bot có thể giành cú bấm của nhau (Q-L); khóa Binance sai quyền hay không giới hạn IP là rủi ro mất tiền; một máy im lặng không ai biết nếu không có giám sát bên ngoài.
> - **Mức quan trọng:** Bot Telegram riêng và heartbeat là **BẮT BUỘC** (Q-L; D042 điều kiện 1). Khóa Binance không cần ở SHADOW; whitelist IP là **BẮT BUỘC** từ lúc có khóa đầu tiên (D042 điều kiện 4).

#### Bước 8.1 Bot Telegram riêng cho máy soak (quyết định Q-L) [THỦ CÔNG] [CHƯA XÁC MINH]

> - **Để làm gì:** Tạo một bot Telegram riêng cho máy soak, tách khỏi bot của máy phát triển.
> - **Giải quyết vấn đề gì:** Telegram chỉ cho một bên polling mỗi token (giả định A1, chưa xác minh trực tiếp), nên hai nơi dùng chung token có thể âm thầm giành cú bấm APPROVE/SKIP của nhau (Pitfall P17).
> - **Mức quan trọng:** **BẮT BUỘC** cho SHADOW có thông báo (quyết định `16-DEC-Q-L`: bot riêng). Chưa có tiến trình gửi thông báo nên chưa thử được.

**Chạy ở:** `[MÁY CÓ MẠNG]` (ứng dụng Telegram của bạn)

Quyết định `16-DEC-Q-L` (ngày 2026-10-09) là "separate-bot": máy soak dùng một bot Telegram riêng, khác bot của máy phát triển. Lý do bằng lời thường: Telegram chỉ cho một bên "long polling" cho mỗi token bot (giả định A1 trong nghiên cứu; đoạn thông báo lỗi 409 khi có hai bên chưa được xác minh). Nếu máy phát triển cũng chạy bot trên cùng token, nó có thể âm thầm giành mất các cú bấm nút của máy soak (Pitfall P17 trong nghiên cứu Phase 16). Hai bot riêng thì không xảy ra chuyện này.

- Tạo bot: bạn tự làm trong ứng dụng Telegram bằng BotFather (nơi `.env.example` ghi là nguồn cấp token). Các lệnh và câu hỏi của BotFather không nằm trong repository nên hướng dẫn này không liệt kê chúng `[CHƯA XÁC MINH]`.
- Token chỉ nằm ở trình quản lý mật khẩu và trong tệp bí mật ngoài VPS, dưới tên biến `TELEGRAM_BOT_TOKEN`. Không bao giờ dán token vào một dòng lệnh terminal, chat, issue hay tài liệu này. Mã bot cho hệ thống thấy token đó, nhưng agent và người viết kế hoạch không bao giờ cần nhìn thấy nó.
- Thêm biến `TELEGRAM_AUTHORIZED_CHAT_ID`: số nguyên của cuộc trò chuyện riêng được phép nhận thông báo SIMULATE (có thể âm đối với nhóm).
- Thêm biến `TELEGRAM_AUTHORIZED_USER_IDS`: danh sách mã người dùng Telegram được phép bấm nút, là các số nguyên dương phân cách bằng dấu phẩy. Chủ sở hữu tự đặt giá trị trong `.env` trên máy chạy (mặc định chỉ một mã, là mã Telegram của bạn); không ghi mã nào vào repository, tài liệu này hay chat. Từ Phase 23 (đã xây ở mức thư viện), nếu Telegram đã được cấu hình (có token và mã chat) mà thiếu biến này thì runtime từ chối khởi động; danh sách rỗng không bao giờ có nghĩa là cho phép tất cả.
- Cẩn thận: `.env.example` gợi ý lấy mã chat bằng một URL `getUpdates` có nhúng chính token. Một URL như vậy nằm trong lịch sử shell, nhật ký proxy và có thể bị chụp màn hình. Cách an toàn để biết mã chat chưa được kế hoạch 16-34 hay 16-40 nêu, nên nó là `[CHƯA XÁC MINH]`; hỏi trong phiên lập kế hoạch trước khi tự chế một cách.
- Thu hồi hay tạo lại token trong BotFather nếu nghi bị lộ: việc đó nằm ngoài repository và là `[CHƯA XÁC MINH]`.
- Hành vi dự kiến của thông báo: mọi thông báo SHADOW mang nhãn "SHADOW — no real order" và nhấn APPROVE chỉ chuyển thông báo thành thẻ xác nhận (D041); chỉ nút CONFIRM, mã CONFIRM riêng, dùng một lần, hiệu lực mặc định 60 giây, mới được ghi nhận. Các mô-đun cho phần này đã xây ở mức đồ giả (16-04, 16-11) nhưng chưa nối vào một tiến trình chạy được (16-31), nên `[CHƯA XÂY]` ở cấp vận hành.

> **Hỏi nhanh về bot Telegram (đáp bằng lời thường)**
>
> 1. **Tạo bot riêng được không?** Được: tạo bằng BotFather như một bot thứ hai, tách hẳn: lệnh `/newbot`, tên riêng, username riêng, token riêng (`16-DEC-Q-L`). Token không dán vào đâu cả (mục 8.1). Hai token không bao giờ được hai tiến trình cùng polling một lúc. Các bước và câu hỏi chi tiết của BotFather `[CHƯA XÁC MINH]`.
> 2. **Có cần tạo group không?** Không. Chat riêng (private) với từng bot là đủ. Cổng `authorized_chat_gate` trong `src/adapters/telegram_callbacks.py` chỉ so mã chat của cú bấm với `TELEGRAM_AUTHORIZED_CHAT_ID`. Với chat riêng, mã này nhiều khả năng chính là mã Telegram của bạn `[CHƯA XÁC MINH]` (repository không nói). Group không được chấp nhận: từ Phase 23 (đã xây ở mức thư viện) có cổng thứ hai `authorized_user_gate`, kiểm mã người dùng của cú bấm với `TELEGRAM_AUTHORIZED_USER_IDS` và chỉ nhận chat có loại đúng bằng `private`, nên cú bấm từ group bị từ chối ngay cả khi mã chat của group đúng là mã đã cấu hình. Việc thử thật bằng tài khoản thứ hai hoặc từ một group là việc của chủ sở hữu và chưa chạy (kiểm tra G2-014), nên hành vi thật `[CHƯA XÁC MINH]`. Khuyến nghị: chat riêng.
> 3. **Người lạ tìm ra username bot rồi bấm /start thì sao?** Telegram không chặn được việc đó. Trong `src/` không có xử lý lệnh `/start` hay lệnh nào khác (chỉ có bộ xử lý cú bấm nút), tin nhắn của hệ thống chỉ gửi tới mã chat đã cấu hình, và cú bấm từ mã chat khác bị cổng từ chối. Nên: chọn username khó đoán; bạn là người đầu tiên bấm Start; nếu nghi lộ token thì thu hồi trong BotFather (lệnh và các bước chính xác `[CHƯA XÁC MINH]`, xem tài liệu BotFather).
> 4. **healthchecks.io báo về Telegram bằng gì?** Bằng tích hợp (bot) của chính họ, bạn nối với chat của bạn ngay trên trang healthchecks.io `[CHƯA XÁC MINH]`, hãy đọc tài liệu của họ. Nó độc lập với các bot của dự án này, và token của dự án không bao giờ đưa cho họ.

#### Bước 8.2 Binance: khóa nào cần ở giai đoạn nào [THỦ CÔNG] [CHƯA XÂY]

> - **Để làm gì:** Cho biết khóa Binance nào cần ở giai đoạn nào, và giới hạn mỗi khóa ở đúng IP của máy với quyền rút tiền tắt (whitelist).
> - **Giải quyết vấn đề gì:** Khóa lộ mà không giới hạn IP hay còn quyền rút tiền thì kẻ cắp lấy được tiền; khóa live trên máy soak vi phạm OPS-06.
> - **Mức quan trọng:** SHADOW không cần khóa nào. Whitelist IP và tắt quyền rút là **BẮT BUỘC** từ lúc có khóa đầu tiên (D042 điều kiện 4; RUNBOOK 13.5 mục 1); địa chỉ đổi thì phải cập nhật.

**Chạy ở:** `[MÁY CÓ MẠNG]`

- Soak SHADOW chỉ dùng dữ liệu thị trường công khai và KHÔNG cần khóa nào.
- Giai đoạn DEMO về sau dùng khóa Demo, tên biến `BINANCE_DEMO_API_KEY` và `BINANCE_DEMO_API_SECRET` (người dùng là Phase 18).
- Giai đoạn CANARY dùng một khóa mainnet CHỈ-ĐỌC (không giao dịch, không rút tiền, giới hạn theo IP của VPS theo D042). Tên biến cho khóa này chưa được repository định nghĩa `[CHƯA XÂY]`.
- `BINANCE_LIVE_*` chỉ được phép nằm trong tệp env riêng của một triển khai live, không bao giờ trên máy paper/soak (OPS-06). Việc tách `env_file` theo từng service (WR-06) phải làm xong TRƯỚC khi bất kỳ khóa live nào vào `.env` (D061 hosts).
- Quy tắc IP whitelist: mỗi khóa Binance bị giới hạn ở đúng Elastic IP của máy, quyền rút tiền tắt, và danh sách IP được cập nhật sau mỗi lần cutover hay khi địa chỉ đổi (D042 điều kiện 4; RUNBOOK 13.5 mục 1 và 15.6). Giao diện Binance để làm việc đó không được repository mô tả; việc này là `[THỦ CÔNG]` và chưa được kiểm chứng.
- Phép ping vùng ở bước 3.7 vẫn là phép thử đầu tiên: Binance phải chấp nhận địa chỉ của máy.

#### Bước 8.3 Dịch vụ heartbeat bên ngoài: healthchecks.io [THỦ CÔNG] [ĐÃ XÂY] [CHƯA XÁC MINH]

> - **Để làm gì:** Một dịch vụ bên ngoài VPS (đã chọn: healthchecks.io) nhận tín hiệu "còn sống" đều đặn và báo cho bạn khi tín hiệu ngừng.
> - **Giải quyết vấn đề gì:** Collector hay cả máy chết trong im lặng thì mỗi phút Open Interest mất là mất vĩnh viễn (D059 mục 4); không có giám sát từ ngoài thì bạn chỉ biết khi tự mở máy xem.
> - **Mức quan trọng:** **BẮT BUỘC** (D042 điều kiện 1; điều kiện `HEARTBEAT_MONITOR_ALERT_RECEIVED`). Bộ gửi tín hiệu là kế hoạch 16-50 (`deploy/heartbeat.sh`, đã xây, chưa chạy trên máy thật), và heartbeat chỉ báo cho bạn, không bảo vệ vị thế.

**Chạy ở:** `[MÁY CÓ MẠNG]` (đăng ký tài khoản, tạo check, đặt chu kỳ), `[MÁY EC2]` (nơi bộ gửi tín hiệu sẽ chạy)

**Đã chọn gì.** Bạn chọn healthchecks.io làm dịch vụ heartbeat ngày 2026-10-09 (quyết định của người dùng, thuộc hạng mục heartbeat của `16-DEC-O-12`). Chu kỳ và thời gian ân hạn (grace period) vẫn là `[QUYẾT ĐỊNH CỦA BẠN]`; hướng dẫn này không viết con số nào.

**Dùng để làm gì (năm mục đích).**

1. Phát hiện collector hoặc cả máy chết trong im lặng. D042 điều kiện 1 đòi một dịch vụ giám sát NGOÀI VPS báo cho bạn khi một tiến trình chạy dài dừng, vì một máy đơn là một điểm hỏng đơn.
2. Rút ngắn thời gian mất dữ liệu không bù được: các phút Open Interest không thu được là mất vĩnh viễn (D059 mục 4: `openInterestHist` chỉ phục vụ khoảng một tháng), nên biết sớm có giá trị hơn biết muộn.
3. Là nội dung của điều kiện nghiệm thu `HEARTBEAT_MONITOR_ALERT_RECEIVED` (bước 3.8): cảnh báo phải thật sự tới bạn khi collector dừng.
4. Cho thông báo phục hồi (recovery notice) khi tín hiệu quay lại; phép thử nghiệm thu đòi cả cảnh báo lẫn thông báo phục hồi.
5. Bắt trường hợp timer sao lưu im lặng: bộ gửi của repository chỉ dò collector, nên việc này cần một check riêng bạn tự đăng ký (RUNBOOK 11.4). Hai mục đích (collector, sao lưu) có thể cần hai chu kỳ khác nhau, và chu kỳ thật là của bạn; hướng dẫn này không chọn thay.

**Những gì heartbeat KHÔNG làm.**

- Nó không phải cảnh báo giao dịch: không báo tín hiệu, kế hoạch, lệnh, khớp hay lời lỗ.
- Nó không phải tín hiệu sức khỏe nghiệp vụ: một ping đúng giờ chỉ nói bộ gửi còn chạy, không chứng minh dữ liệu đúng, không có khoảng trống hay feed khỏe. Tín hiệu chỉ có ý nghĩa nếu nó phụ thuộc vào việc collector đang chạy (RUNBOOK 19.3).
- Nó không bảo vệ vị thế: SL luôn nằm trên sàn (D042 điều kiện 1), nên heartbeat sống hay chết thì vị thế đã đặt vẫn được bảo vệ phía sàn. Heartbeat chỉ báo cho bạn.

**Gói miễn phí của healthchecks.io `[CHƯA XÁC MINH]`.** Các dữ kiện sau chỉ được xác minh một phần, từ trang của bên thứ ba chứ chưa đọc trực tiếp trang giá chính thức. Hãy đọc https://healthchecks.io/pricing/ trước khi một quyết định dựa vào chúng:

- 20 check cho gói miễn phí `[CHƯA XÁC MINH]`;
- 100 bản ghi log (log entries) cho mỗi check `[CHƯA XÁC MINH]`;
- chưa tìm thấy giới hạn số ping mỗi ngày `[CHƯA XÁC MINH]`: "không thấy giới hạn" không có nghĩa là không có;
- giới hạn tần suất ping mỗi phút chưa được xác nhận `[CHƯA XÁC MINH]`.

**URL ping là bí mật.** Ai có URL mà dịch vụ cấp cho một check đều báo "còn sống" thay được máy của bạn. Không bao giờ để nó trong git, nhật ký, `acceptance.json`, chat, issue hay tài liệu này; hướng dẫn này không có URL nào. Bộ gửi của repository cất URL trong một tệp chỉ root đọc được (`/etc/trading/heartbeat.url`, chế độ 0600), không đặt nó thành biến môi trường hay biến `.env`, vì bộ che bí mật của D050 che theo tên biến (PASSWORD, SECRET, TOKEN, API_KEY, ACCESS_KEY, CRYPT, PRIVATE) và một tên không khớp thì URL có thể lọt vào nhật ký; công cụ nghiệm thu `scripts/soak_host_acceptance.py` thoát 2 trên mọi giá trị trông như URL ping.

**Bộ gửi tín hiệu: kế hoạch 16-50 "Off-host heartbeat sender" `[ĐÃ XÂY]`.** Nó thuộc Phase 16: script `deploy/heartbeat.sh` và hai unit `trading-heartbeat.service`, `trading-heartbeat.timer` đã có (các thẻ lệnh bên dưới và RUNBOOK 11.9), kiểm thử bằng đồ giả; chưa cài và chưa chạy trên máy thật, nên mọi bước trên máy EC2 còn `[CHƯA XÁC MINH]`. Thứ tự: tạo check và đặt chu kỳ cùng thời gian ân hạn ở dịch vụ bên ngoài (`[QUYẾT ĐỊNH CỦA BẠN]`, ghi ở `16-DEC-O-12`); cất URL bằng `sudo deploy/heartbeat.sh --set-url`; cài timer bằng `sudo deploy/heartbeat.sh --install-timer --interval-seconds <N>`; rồi làm phép thử ở bước 3.8. Đừng nhầm với các hàng heartbeat nội bộ của runtime trong cơ sở dữ liệu soak (các kế hoạch 16-15, 16-16, 16-24, 16-26, 16-30 và 16-43 nói về chúng, để tính độ bao phủ): chúng không gửi gì ra ngoài. Các kế hoạch 16-07 và 16-14 chỉ nói điều kiện nghiệm thu và quyết định của bạn.

**Phạm vi.** Bộ gửi chỉ dò collector; đầu dò cho tiến trình paper và live thuộc Phase 24 trong ROADMAP.

**Nếu bạn vẫn muốn tự dựng một bộ gửi riêng `[THỦ CÔNG]` `[CHƯA XÁC MINH]`.** Không cần, vì repository đã có `deploy/heartbeat.sh`. Nếu bạn vẫn dựng một bộ gửi ngoài repository, hướng dẫn này không đưa lệnh nào cho cách đó và nó chưa từng được chạy thử; nếu tín hiệu chỉ nói "máy còn bật" mà không phụ thuộc collector thì phép thử `HEARTBEAT_MONITOR_ALERT_RECEIVED` không có ý nghĩa.

**Đối chiếu với RUNBOOK.** RUNBOOK 11.4 (đọc ngày 2026-10-09) từng nói không có gì trong repository ping một dịch vụ giám sát. Kế hoạch 16-50 đã sửa câu đó và thêm RUNBOOK 11.9; khi RUNBOOK và hướng dẫn này khác nhau thì RUNBOOK thắng và hướng dẫn này phải được cập nhật theo.

### Thẻ lệnh: deploy/heartbeat.sh

> - **Để làm gì:** Gửi tín hiệu "còn sống" của collector ra dịch vụ giám sát ngoài VPS (healthchecks.io), cất URL ping vào tệp chỉ root đọc được và cài timer gửi định kỳ.
> - **Giải quyết vấn đề gì:** Collector hay cả máy chết trong im lặng thì Open Interest mất vĩnh viễn; tín hiệu chỉ được gửi khi đầu dò collector qua, nên dừng collector làm tín hiệu im và dịch vụ bên ngoài báo cho bạn.
> - **Mức quan trọng:** **BẮT BUỘC** (D042 điều kiện 1; RUNBOOK 11.9; điều kiện `HEARTBEAT_MONITOR_ALERT_RECEIVED`). Nó chỉ báo cho bạn, không bảo vệ vị thế: SL luôn nằm trên sàn.

**Mục đích:** script phục vụ hai check: collector (mặc định, như dưới đây) và, với `--target paper`, heartbeat riêng của paper runtime trong project soak (kế hoạch 16-56; đầu dò `--liveness` qua `deploy/compose-soak.sh`, URL riêng, unit riêng, lệnh cài cần thêm `--soak-env-file`; thẻ `deploy/systemd/trading-soak-paper-heartbeat.service`). Với mỗi check, script có ba chế độ. Chế độ trần chạy đầu dò chỉ-đọc của collector (`python -m src.data.collector --healthcheck` trong service `collector`) rồi gửi đúng một ping thành công, và chỉ khi đầu dò qua. `--set-url` cất URL ping vào tệp chỉ root đọc được. `--install-timer --interval-seconds <N>` cài `trading-heartbeat.service` và `trading-heartbeat.timer`. Nó không giữ logic giám sát nào và không bao giờ dừng hay khởi động lại collector.

**Khi nào chạy:** `--set-url` một lần, sau khi bạn tạo check ở dịch vụ bên ngoài (bước 8.3). `--install-timer` một lần sau `--set-url`, với `<N>` là chu kỳ ping bạn đã ghi ở `16-DEC-O-12` (hướng dẫn này không chọn con số). Chế độ trần do timer gọi; bạn chỉ chạy tay khi muốn thử một lần. Chỉ chạy sau khi collector đã nằm trên máy EC2 (mục 5).

**Chạy ở máy nào:** `[MÁY EC2]`; hai chế độ đầu bằng `sudo` (cần root), chế độ trần bằng user `trading` hoặc do timer gọi.

**Lệnh:**

```bash
sudo deploy/heartbeat.sh --set-url
```

```bash
sudo deploy/heartbeat.sh --install-timer --interval-seconds <N>
```

```bash
deploy/heartbeat.sh
```

Cờ: `--set-url` (đọc một dòng từ đầu vào chuẩn, không hiện lại, cất vào tệp chế độ 0600), `--install-timer` (cài hai unit và bật timer), `--interval-seconds` (chu kỳ ping tính bằng giây; bắt buộc đi cùng `--install-timer` và không có mặc định), `--fail-ping` (đầu dò hỏng thì gửi một ping báo hỏng), `--url-file` (đường dẫn tuyệt đối của tệp URL khác), `--dry-run` (in kế hoạch), `-h`/`--help`. Hai cờ `--set-url` và `--install-timer` không dùng chung được. Biến môi trường `HEARTBEAT_URL_FILE`, `HEARTBEAT_FAIL_PING` và `HEARTBEAT_STEP_TIMEOUT_SECONDS` được tôn trọng.

**Chạy thử:** mỗi chế độ có `--dry-run` riêng, in việc sẽ làm mà không làm:

```bash
deploy/heartbeat.sh --dry-run
```

```bash
sudo deploy/heartbeat.sh --set-url --dry-run
```

```bash
sudo deploy/heartbeat.sh --install-timer --interval-seconds <N> --dry-run
```

Chế độ trần với `--dry-run` vẫn đọc và kiểm tra tệp URL, nên thoát 4 nếu tệp thiếu hay sai.

**Dấu hiệu thành công:** chế độ trần thoát 0 và nhật ký có dòng `heartbeat: success ping delivered`; bảng điều khiển của dịch vụ bên ngoài ghi một ping. `--set-url` in thông báo đã cất URL (không in giá trị). Chế độ cài timer: `systemctl list-timers trading-heartbeat.timer` liệt kê timer. Việc tín hiệu thật sự tới dịch vụ bên ngoài chỉ máy thật mới chứng minh được `[CHƯA XÁC MINH]`.

**Mã thoát:** 0 đầu dò qua và ping đã gửi (hoặc `--dry-run`); 1 đầu dò collector hỏng (đúng thiết kế: tín hiệu im); 2 lỗi cờ hoặc biến môi trường; 3 đầu dò qua nhưng ping không tới nơi (nhật ký ghi `curl exit <n>`, không ghi URL); 4 tệp URL thiếu, sai định dạng hay cho nhóm hoặc người khác đọc.

**Khi lỗi:** mã 4: chạy `sudo deploy/heartbeat.sh --set-url` hoặc sửa chế độ tệp về 0600; thông báo không bao giờ in nội dung URL. Mã 3: lỗi mạng, URL sai hay dịch vụ từ chối; chạy lại sau, nếu lặp lại hãy đọc `journalctl -u trading-heartbeat`. Mã 1: xem `docker compose logs --tail 200 collector` và bước 10.3. Việc systemd chuyển URL cho user `trading` qua `LoadCredential` chỉ máy thật mới chứng minh được `[CHƯA XÁC MINH]`.

**Không bao giờ:** dán URL ping vào `.env`, `acceptance.json`, chat hay lịch sử shell; chạy script dưới `bash -x` (script từ chối); để script đụng tới collector ngoài đầu dò chỉ-đọc; tự chọn chu kỳ hay thời gian ân hạn thay bạn; bật `--fail-ping` mà không hiểu rằng ping báo hỏng báo ngay và bỏ qua thời gian ân hạn; coi một ping đúng giờ là bằng chứng dữ liệu đúng hay vị thế an toàn.

### Thẻ lệnh: deploy/systemd/trading-heartbeat.service

> - **Để làm gì:** Đơn vị systemd chạy `deploy/heartbeat.sh` một lần mỗi khi timer kích hoạt: dò collector rồi gửi một ping.
> - **Giải quyết vấn đề gì:** Tín hiệu bên ngoài chạy tự động và không bao giờ làm ảnh hưởng collector; URL ping được systemd chuyển qua `LoadCredential` từ tệp chỉ root đọc được nên không nằm trong tệp unit hay `.env`.
> - **Mức quan trọng:** **BẮT BUỘC** nếu bạn muốn giám sát ngoài VPS (D042 điều kiện 1; RUNBOOK 11.9); bạn cài bằng một lệnh và không sửa tay.

**Mục đích:** unit systemd kiểu oneshot chạy `deploy/heartbeat.sh` bằng user `trading`. Nó chỉ sắp thứ tự sau mạng và docker, không có phụ thuộc, khởi động lại hay móc lỗi nào tới unit khác.

**Khi nào chạy:** không chạy tay. Nó được cài bởi `sudo deploy/heartbeat.sh --install-timer --interval-seconds <N>` và được `trading-heartbeat.timer` gọi. Các thiết lập đáng biết: `User=trading`, `LoadCredential` trỏ tới tệp URL, `HEARTBEAT_FAIL_PING` (0 hoặc 1 tùy `--fail-ping` lúc cài), `WorkingDirectory` và `ExecStart` mang thẻ thay thế thư mục checkout mà bộ cài điền.

**Chạy ở máy nào:** `[MÁY EC2]`, dưới systemd.

**Lệnh:** cài bằng lệnh sau; xem trạng thái và nhật ký bằng hai lệnh còn lại.

```bash
sudo deploy/heartbeat.sh --install-timer --interval-seconds <N>
```

```bash
systemctl status trading-heartbeat
```

```bash
journalctl -u trading-heartbeat
```

**Chạy thử:** Không áp dụng cho chính tệp unit, vì nó không được chạy tay. Để xem trước việc cài, dùng lệnh `sudo deploy/heartbeat.sh --install-timer --interval-seconds <N> --dry-run` ở thẻ `deploy/heartbeat.sh`.

**Dấu hiệu thành công:** `systemctl status trading-heartbeat` cho thấy lần chạy gần nhất thoát thành công và `journalctl -u trading-heartbeat` không chứa URL nào `[CHƯA XÁC MINH]`.

**Mã thoát:** unit lỗi khi script thoát khác 0: 1 đầu dò collector hỏng, 3 ping không tới nơi, 4 tệp URL thiếu hay sai. Một đầu dò hỏng làm unit lỗi nhưng không đụng tới collector.

**Khi lỗi:** đọc `journalctl -u trading-heartbeat`. Nếu unit không khởi động được vì không tìm thấy tệp credential, chạy lại `sudo deploy/heartbeat.sh --set-url`. Quyền sở hữu và chế độ của bản credential mà systemd giao cho user `trading` chỉ máy thật mới chứng minh được `[CHƯA XÁC MINH]`.

**Không bao giờ:** sửa tay bản đã cài trong `/etc/systemd/system` (bộ cài ghi lại khi nội dung khác); thêm `Requires`, `Restart` hay `OnFailure` vào unit này; đổi `User=` sang tài khoản không thuộc nhóm docker.

### Thẻ lệnh: deploy/systemd/trading-heartbeat.timer

> - **Để làm gì:** Hẹn giờ gọi `trading-heartbeat.service` theo chu kỳ bạn đặt khi cài, tính từ lúc máy khởi động và từ lần chạy trước.
> - **Giải quyết vấn đề gì:** Tín hiệu đều đặn để dịch vụ bên ngoài phát hiện khi nó ngừng; không chạy bù và không trễ ngẫu nhiên nên một lần máy tắt không bị che bằng một ping bù.
> - **Mức quan trọng:** **BẮT BUỘC** nếu bạn muốn giám sát ngoài VPS (D042 điều kiện 1; RUNBOOK 11.9). Chu kỳ là của bạn (`16-DEC-O-12`), không có mặc định.

**Mục đích:** timer kích hoạt `trading-heartbeat.service` sau mỗi chu kỳ bạn đã truyền cho `--interval-seconds`, kể từ lúc khởi động (`OnBootSec`) và kể từ lần chạy trước (`OnUnitActiveSec`).

**Khi nào chạy:** không chạy tay. Cố ý không có `Persistent` và không có `RandomizedDelaySec`: một ping gửi bù sau thời gian tắt máy sẽ che đúng sự cố mà dịch vụ bên ngoài sinh ra để báo. `AccuracySec` là thiết lập cấu trúc, không phải giá trị giám sát.

**Chạy ở máy nào:** `[MÁY EC2]`, dưới systemd.

**Lệnh:** timer được cài và bật bởi cùng lệnh cài, và kiểm tra bằng:

```bash
sudo deploy/heartbeat.sh --install-timer --interval-seconds <N>
```

```bash
systemctl list-timers trading-heartbeat.timer
```

**Chạy thử:** Không áp dụng cho chính tệp unit. Xem trước bằng `sudo deploy/heartbeat.sh --install-timer --interval-seconds <N> --dry-run`.

**Dấu hiệu thành công:** `systemctl list-timers trading-heartbeat.timer` liệt kê timer với thời điểm kích hoạt kế tiếp.

**Mã thoát:** timer không có mã thoát; kết quả nằm ở unit service mà nó kích hoạt.

**Khi lỗi:** timer không xuất hiện: chạy lại lệnh cài và đọc đầu ra của nó. Muốn đổi chu kỳ thì chạy lại lệnh cài với `<N>` mới, bộ cài ghi lại timer và khởi động lại nó. Việc timer kích hoạt đúng chu kỳ chỉ máy thật mới chứng minh được `[CHƯA XÁC MINH]`.

**Không bao giờ:** thêm `Persistent=true` hay trễ ngẫu nhiên vào timer này; đặt chu kỳ ping dài hơn chu kỳ của check ở dịch vụ bên ngoài (hai giá trị phải phù hợp nhau, và cả hai là của bạn); sửa tay bản đã cài (bộ cài ghi lại).

### Thẻ lệnh: deploy/systemd/trading-soak-paper-heartbeat.service

> - **Để làm gì:** Đơn vị systemd chạy `deploy/heartbeat.sh --target paper` một lần mỗi khi timer kích hoạt: dò độ sống của paper runtime trong project soak rồi gửi một ping tới check riêng của paper.
> - **Giải quyết vấn đề gì:** Đầu dò container của paper chỉ xét tuổi nến (3900 giây), quá trễ so với trần 900 giây khoảng trống liên tục; một paper bị giữ sau từ chối, một vòng lặp sự kiện bị treo hay một nguồn dữ liệu im lặng phải làm check riêng im đi, tách khỏi heartbeat của collector.
> - **Mức quan trọng:** **BẮT BUỘC** trước kế hoạch 16-43 (quyết định của chủ dự án `16-DEC-HUNG-RUNTIME`, 16-55 Q2 = B; chỉnh sửa 2 của `16-DEC-FIXPLANS`). Chủ dự án tạo check thứ hai và cất URL ping riêng của nó trước 16-43 (RUNBOOK 20.9).

**Mục đích:** unit oneshot chạy `deploy/heartbeat.sh --target paper` bằng user `trading`. Một lần chạy gọi đầu dò chỉ-đọc `python -m src.paper.runtime --liveness` trong service `paper` qua `deploy/compose-soak.sh`, rồi chỉ gửi ping thành công khi đầu dò thoát 0: container không giữ marker từ chối, và dấu thời gian vòng lặp sự kiện cùng thông điệp thị trường cuối đều mới hơn `feed_silence_timeout_seconds` (`config/paper/paper-runtime-v2.toml`, quyết định `16-DEC-WS-WATCHDOG`). URL ping của paper là bí mật riêng, không bao giờ là URL của collector: tệp root-only `/etc/trading/heartbeat-paper.url`, credential systemd `heartbeat-paper-url`. Unit đặt `TRADING_ENV_FILE` là tệp env soak cho `deploy/compose-soak.sh`.

**Khi nào chạy:** không chạy tay. Cài một lần sau khi đã cất URL, với chu kỳ đã ghi trong `16-DEC-HUNG-RUNTIME` (60 giây; chu kỳ check 60 giây và thời gian ân hạn 120 giây đặt trong bảng điều khiển của healthchecks.io, không đặt trong repository).

**Chạy ở máy nào:** `[MÁY EC2]`, dưới systemd.

**Lệnh:** cất URL, cài, rồi xem trạng thái và nhật ký:

```bash
sudo deploy/heartbeat.sh --target paper --set-url
```

```bash
sudo deploy/heartbeat.sh --target paper --install-timer --interval-seconds 60 --soak-env-file /home/trading/soak.env
```

```bash
systemctl status trading-soak-paper-heartbeat
```

```bash
journalctl -u trading-soak-paper-heartbeat
```

**Chạy thử:** Không áp dụng cho chính tệp unit. Xem trước việc cài bằng `sudo deploy/heartbeat.sh --target paper --install-timer --interval-seconds 60 --soak-env-file /home/trading/soak.env --dry-run`.

**Dấu hiệu thành công:** `journalctl -u trading-soak-paper-heartbeat` có dòng `heartbeat: success ping delivered` và không chứa URL nào; check của paper trong bảng điều khiển ghi ping `[CHƯA XÁC MINH]`.

**Mã thoát:** như `deploy/heartbeat.sh`: 0 đầu dò qua và ping đã gửi, 1 đầu dò không qua (paper bị giữ, vòng lặp treo hay nguồn dữ liệu im), 2 lỗi cách dùng, 3 đầu dò qua nhưng ping không tới, 4 nguồn URL thiếu hoặc sai.

**Khi lỗi:** mã 1: đọc `deploy/compose-soak.sh logs paper` và RUNBOOK 20.9; mã 4: chạy lại `sudo deploy/heartbeat.sh --target paper --set-url`. Heartbeat chỉ là cảnh báo, không phải bằng chứng đã phục hồi: một lần paper dừng lâu hơn trần bao phủ vẫn làm trial trượt tiêu chí bao phủ.

**Không bao giờ:** dùng chung URL ping với collector; trỏ `--url-file` của paper vào `/etc/trading/heartbeat.url`; sửa tay bản đã cài trong `/etc/systemd/system`; dựa vào `--healthcheck` (tuổi nến) để cảnh báo paper bị treo.

### Thẻ lệnh: deploy/systemd/trading-soak-paper-heartbeat.timer

> - **Để làm gì:** Hẹn giờ gọi `trading-soak-paper-heartbeat.service` mỗi 60 giây, tính từ lúc máy khởi động và từ lần chạy trước.
> - **Giải quyết vấn đề gì:** Tín hiệu đều đặn để check riêng của paper phát hiện khi paper ngừng sống; không chạy bù và không trễ ngẫu nhiên nên một lần tắt máy không bị che bằng một ping bù.
> - **Mức quan trọng:** **BẮT BUỘC** trước kế hoạch 16-43 (`16-DEC-HUNG-RUNTIME`; RUNBOOK 20.9).

**Mục đích:** timer kích hoạt `trading-soak-paper-heartbeat.service` sau mỗi chu kỳ đã truyền cho `--interval-seconds` (giá trị đã ghi là 60 giây), kể từ lúc khởi động (`OnBootSec`) và kể từ lần chạy trước (`OnUnitActiveSec`).

**Khi nào chạy:** không chạy tay; được cài và bật bởi `sudo deploy/heartbeat.sh --target paper --install-timer --interval-seconds 60 --soak-env-file <đường dẫn>`. Cố ý không có `Persistent` và không có `RandomizedDelaySec`.

**Chạy ở máy nào:** `[MÁY EC2]`, dưới systemd.

**Lệnh:**

```bash
systemctl list-timers trading-soak-paper-heartbeat.timer
```

**Chạy thử:** Không áp dụng cho chính tệp unit. Xem trước bằng `sudo deploy/heartbeat.sh --target paper --install-timer --interval-seconds 60 --soak-env-file /home/trading/soak.env --dry-run`.

**Dấu hiệu thành công:** `systemctl list-timers trading-soak-paper-heartbeat.timer` liệt kê timer với thời điểm kích hoạt kế tiếp.

**Mã thoát:** timer không có mã thoát; kết quả nằm ở unit service mà nó kích hoạt.

**Khi lỗi:** timer không xuất hiện: chạy lại lệnh cài và đọc đầu ra. Việc timer kích hoạt đúng chu kỳ chỉ máy thật mới chứng minh được `[CHƯA XÁC MINH]`.

**Không bao giờ:** thêm `Persistent=true` hay trễ ngẫu nhiên; đổi chu kỳ khác giá trị đã ghi trong `16-DEC-HUNG-RUNTIME` mà không có quyết định mới của chủ dự án.

Nguồn: `.env.example`, `.planning/phases/16-paper-runtime-composition/decisions/16-DEC-Q-L.md`, `.planning/phases/16-paper-runtime-composition/16-RESEARCH.md`, `docs/operations/RUNBOOK.md`, `docs/DECISIONS.md`, `deploy/heartbeat.sh`, `deploy/systemd/trading-heartbeat.service`, `deploy/systemd/trading-heartbeat.timer`, `deploy/systemd/trading-soak-paper-heartbeat.service`, `deploy/systemd/trading-soak-paper-heartbeat.timer`, `.planning/phases/16-paper-runtime-composition/decisions/16-DEC-HUNG-RUNTIME.md`

## 9. Lộ trình SHADOW, DEMO, CANARY, LIVE

> - **Để làm gì:** Cho thấy lộ trình phát hành SHADOW, DEMO, CANARY, LIVE theo D040 và D041, và các phase 18 đến 26 còn phải xây.
> - **Giải quyết vấn đề gì:** Ngăn nhảy cóc sang tiền thật: mỗi giai đoạn có tiêu chí thoát viết sẵn, APPROVE không bao giờ đặt lệnh, chỉ CONFIRM mới đặt.
> - **Mức quan trọng:** Thứ tự giai đoạn là **BẮT BUỘC**, không bỏ qua giai đoạn nào (D040). Với bạn hôm nay mục này chỉ để đọc (**NÊN LÀM** đọc một lần), vì DEMO đến LIVE chưa có code.

#### Bước 9.1 Con đường an toàn từ D040 và D041 [CHƯA XÂY]

> - **Để làm gì:** Mô tả con đường SHADOW, DEMO, CANARY, LIVE (D040) và bước xác nhận hai lần APPROVE rồi CONFIRM (D041).
> - **Giải quyết vấn đề gì:** Ngăn một lệnh thật bị đặt chỉ vì một cú bấm: APPROVE chỉ mở thẻ xác nhận, chỉ CONFIRM (mã riêng, dùng một lần, hết hạn nhanh) mới đặt lệnh.
> - **Mức quan trọng:** **BẮT BUỘC** (D040: không bỏ qua giai đoạn nào; D041). Hôm nay chỉ để đọc vì chưa có code cho DEMO đến LIVE.

**Chạy ở:** `[MÁY CÓ MẠNG]` (đọc; hôm nay bạn không có lệnh nào cho các giai đoạn DEMO đến LIVE)

D040 quy định con đường phát hành an toàn SHADOW, DEMO, CANARY, LIVE, KHÔNG BỎ QUA giai đoạn nào, mỗi giai đoạn có tiêu chí thoát viết sẵn. D041 quy định bước xác nhận hai lần: APPROVE không bao giờ đặt lệnh; nó biến thông báo thành thẻ xác nhận (chế độ, cặp, chiều, khối lượng, giá trị, lỗ ước tính tại SL, giá mark so với giá vào và SL, thời hạn còn lại) với CONFIRM và CANCEL. Chỉ CONFIRM mới đặt lệnh. Mã CONFIRM tách khỏi mã phê duyệt, dùng một lần, gắn với cùng người dùng và băm kế hoạch, hết hạn sau một TTL ngắn (mặc định 60 giây). CANCEL hay hết hạn không đặt gì và được ghi nhật ký. Mọi kiểm tra trước khi đặt lệnh chạy lại lúc xác nhận.

| Giai đoạn | Cái gì chạy | Khóa nạp | Lệnh | Tiêu chí thoát | Phase xây | Trạng thái |
| --- | --- | --- | --- | --- | --- | --- |
| SHADOW | tiến trình paper trên dữ liệu thị trường công khai; thông báo có nhãn, APPROVE/SKIP rồi CONFIRM; khớp lệnh mô phỏng; không đường nào tới lệnh thật | không khóa giao dịch nào | không có (không dựng adapter lệnh) | trial soak đạt các tiêu chí ở bước 7.7 và chuỗi đóng ở bước 7.6 | Phase 16 (đang thực hiện, 14/50), Phase 17 đã xong | `[CHƯA XÂY]` ở cấp vận hành |
| DEMO | APPROVE rồi CONFIRM đặt lệnh trên Binance Demo Trading (demo-fapi.binance.com) | khóa Demo | chỉ lệnh trên tài khoản demo | bộ kịch bản demo tự động qua và một soak demo nhiều tuần với không có sai lệch không giải thích, không có vị thế nào thiếu SL phía sàn, không có lệnh vào trùng | Phase 18 đến 25 | `[CHƯA XÂY]` |
| CANARY | khóa mainnet chỉ-đọc xác minh exchangeInfo, hoa hồng, giá mark và số dư thật; rồi một tài khoản phụ nhỏ biệt lập (cỡ USD 50 đến 100, cỡ tối thiểu) giao dịch khi người vận hành theo dõi | khóa chỉ-đọc, rồi khóa của tài khoản phụ | lệnh thật cỡ nhỏ | số lệnh đã đăng ký trước, không có sai lệch | Phase 26 | `[CHƯA XÂY]` |
| LIVE | chỉ sau khi tiêu chí thoát CANARY đạt | `BINANCE_LIVE_*` chỉ trong env riêng của triển khai live | lệnh thật | do Phase 26 xác định | Phase 24 và 26 | `[CHƯA XÂY]` |

#### Bước 9.2 Các phase từ 16 tới 26 [CHƯA XÂY]

**Chạy ở:** `[MÁY CÓ MẠNG]` (đọc)

Phase 27 (đồng tiền định giá cấu hình được, sẵn sàng USDC) nằm ngoài con đường này.

| Phase | Mục tiêu | Phụ thuộc | Trạng thái |
| --- | --- | --- | --- |
| Phase 16 | tiến trình paper chạy được và chế độ phê duyệt SHADOW | Phase 12, 13.1, 15, 17 | đang thực hiện, 14/50 kế hoạch (bước 7.3) |
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

> - **Để làm gì:** Các cổng trước khi lên tiền thật: bộ kịch bản demo, soak demo ít nhất 3 tuần, điều kiện của `enable()` ở Phase 26, CANARY.
> - **Giải quyết vấn đề gì:** Chặn việc bật live khi còn sai lệch chưa giải thích, vị thế thiếu SL phía sàn, hoặc khi trạng thái DEGRADED bị coi là bằng chứng.
> - **Mức quan trọng:** **BẮT BUỘC** trước LIVE (ROADMAP Phase 25 và 26; D040, D056, D058, D065). Chưa xây.

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

> - **Để làm gì:** Nói rõ phần việc của con người ở từng cổng go-live và những điều không bao giờ làm.
> - **Giải quyết vấn đề gì:** Tránh để agent hay script tự quyết thay bạn các việc an toàn như cho phép chạy nghiên cứu, chỉ định ứng viên, bật `enable()`.
> - **Mức quan trọng:** **BẮT BUỘC** (D061 mục H: agent không bao giờ tự quyết các việc này). Chưa xây.

**Chạy ở:** `[MÁY CÓ MẠNG]`

Hôm nay bạn không có lệnh chạy được cho các giai đoạn DEMO đến LIVE. Bằng lời:

- Cổng SHADOW: bạn viết hoặc duyệt giả thuyết và lưới, cho phép chạy nghiên cứu, chỉ định ứng viên, cho phép đúng băm, rồi khởi động trial và tuyên bố nó đạt (bước 7.6).
- Cổng DEMO: bạn đọc báo cáo của bộ kịch bản và của soak 3 tuần; bạn quyết có chấp nhận kết quả hay không.
- Cổng CANARY: bạn tạo khóa chỉ-đọc, tài khoản phụ nhỏ và theo dõi từng lệnh.
- Cổng LIVE: bạn bật `enable()` sau khi mọi điều kiện của Phase 26 đạt.

Những điều không bao giờ làm: không đặt khóa live trước khi WR-06 xong; không bỏ qua giai đoạn nào; không chỉnh tham số theo kết quả soak hay backtest; không coi một lần chạy ở trạng thái DEGRADED là bằng chứng.

Nguồn: `.planning/ROADMAP.md`, `docs/DECISIONS.md`, `.env.example`, `docker-compose.yml`

## 10. Vận hành hằng ngày

> - **Để làm gì:** Các lệnh dùng hằng ngày: xem trạng thái, nhật ký, sức khỏe, migration, bí mật, làm mới pin, ổ đĩa, đồng bộ giờ.
> - **Giải quyết vấn đề gì:** Biết một lệnh đúng cho từng việc và tránh các lệnh nguy hiểm: lệnh `config` của compose không có `-q` (in cả bí mật), xóa volume, dừng collector tùy tiện.
> - **Mức quan trọng:** **BẮT BUỘC** nắm các quy tắc an toàn (luôn `-q` khi kiểm tra cấu hình, không xóa volume, không dừng collector vì tiện; RUNBOOK). Phần còn lại là **TÙY CHỌN**, tra khi cần.

Mọi lệnh ở mục này chạy trong thư mục `/opt/trading` bằng user `trading` trên `[MÁY EC2]`, trừ khi bước nói khác.

#### Bước 10.1 Tám service của compose [ĐÃ XÂY] [CHƯA XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]`

Compose đặt tên project cố định là `trading`, nên các volume tên là `trading_pgdata` và tương tự. Dữ liệu chỉ nằm trong các volume có tên (Docker volume là một vùng lưu trữ do Docker quản lý, sống lâu hơn container): `pgdata`, `rawdata`, `backupdata`, `logs`. Mọi service ghi nhật ký kiểu json-file, xoay vòng ở 10 MB và giữ 5 tệp.

| Service | Việc của nó | Profile | `docker compose up -d` có khởi động? | Khởi động lại | Kiểm tra sức khỏe | Volume | Trạng thái |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `postgres` | cơ sở dữ liệu PostgreSQL 17, công bố chỉ trên `127.0.0.1` | không | có | unless-stopped | `pg_isready`, mỗi 10 giây | `pgdata` | `[ĐÃ XÂY]` |
| `db-upgrade` | chạy một lần `alembic upgrade head`; collector chờ nó thành công | không | có, rồi thoát | `"no"` | tắt | không | `[ĐÃ XÂY]` |
| `collector` | thu Open Interest và funding mỗi 5 phút | không | có | unless-stopped | `python -m src.data.collector --healthcheck`, mỗi 60 giây, sáu phút khởi động | `rawdata`, `logs` | `[ĐÃ XÂY]` |
| `paper` | tiến trình paper `python -m src.paper.runtime --hold-on-refusal`; một lần khởi động bị từ chối thì giữ nguyên, không ghi gì, có dấu giữ và báo không khỏe (RUNBOOK 20.1) | `paper` | không | unless-stopped (quyết định 16-DEC-RESTART-POLICY) | `python -m src.paper.runtime --healthcheck`, mỗi 60 giây, sáu phút khởi động | `logs` | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| `paper-pin` | ghim epoch một lần (`--pin-epoch`) rồi thoát 0, không chạy vòng lặp (quyết định 16-DEC-PIN-COMMAND) | `paper-pin` | không | `"no"` | tắt | `logs` | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| `live` | khung giữ chỗ chạy là thoát (Phase 24) | `live` | không | `"no"` | tắt | không | `[CHƯA XÂY]` |
| `backup` | một lần sao lưu theo lịch (`scheduled`) trong image ops | `ops` | không (được `deploy/backup.sh` gọi) | `"no"` | tắt | `rawdata` chỉ-đọc, `backupdata` | `[ĐÃ XÂY]` |
| `ops` | hộp công cụ cho `deploy/*.sh` (khôi phục, diễn tập, cutover); mặc định chỉ in trợ giúp | `ops` | không | `"no"` | tắt | `rawdata`, `backupdata`, `logs` | `[ĐÃ XÂY]` |

#### Bước 10.2 Các lệnh vòng đời [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]`

```bash
docker compose ps
```

```bash
docker compose up -d
```

```bash
docker compose stop collector
```

```bash
docker compose start collector
```

```bash
docker compose restart collector
```

```bash
docker compose --profile ops build
```

Chạy một lệnh một lần trong hộp công cụ `ops` (ví dụ liệt kê thư mục sao lưu):

```bash
docker compose --profile ops run --rm -T --no-deps ops ls /app/data/backup
```

Để chạy một stack thứ hai từ cùng một checkout (kiểm thử, diễn tập), hai biến môi trường `TRADING_ENV_FILE` (tệp env khác, mặc định `.env`) và `COMPOSE_PROJECT_NAME` (tên project) được cả compose lẫn các script deploy tôn trọng. Quy tắc cần nhớ: dừng collector làm mất vĩnh viễn các phút Open Interest; đừng dừng nó vì tiện.

#### Bước 10.3 Sức khỏe [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]`

Đầu dò của collector thoát 0 chỉ khi mọi symbol trong danh sách thu đều có mốc Open Interest mới hơn hai lần chu kỳ VÀ mốc funding mới hơn một khoảng 8 giờ cộng biên. Trên cơ sở dữ liệu mới chưa có mốc nào, nên có sáu phút khởi động. Docker không tự khởi động lại một container "unhealthy", nên đây chỉ là thông tin; bạn tự xem cột trạng thái của:

```bash
docker compose ps
```

Chạy đầu dò bằng tay (chưa từng thử trên máy thật `[CHƯA XÁC MINH]`):

```bash
docker compose exec collector /app/.venv/bin/python -m src.data.collector --healthcheck
```

#### Bước 10.4 Nhật ký [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]`

```bash
docker compose logs --tail 200 collector
```

```bash
docker compose logs --since 1h collector
```

Nhật ký json-file xoay vòng ở 10 MB với 5 tệp mỗi service; volume `logs` giữ nhật ký ứng dụng. Nhật ký của timer sao lưu nằm ở systemd:

```bash
journalctl -u trading-backup
```

Quy tắc che bí mật (D050, `src/ops/redaction.py`): việc che dựa trên GIÁ TRỊ của các biến môi trường mà tên chứa PASSWORD, SECRET, TOKEN, API_KEY, ACCESS_KEY, CRYPT hoặc PRIVATE. Vì vậy một biến bí mật mới phải giữ tên khớp quy tắc đó; đừng bao giờ đổi tên một biến bí mật thành tên không khớp.

#### Bước 10.5 Di chuyển cơ sở dữ liệu (migration) [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]`

Service `db-upgrade` chạy `alembic upgrade head` và chặn collector cho tới khi nó thành công. Để áp dụng một migration mới, dùng `docker compose up -d` (đó cũng là điều `deploy/update.sh` làm); RUNBOOK không ghi một lệnh riêng nào khác. Xem kết quả:

```bash
docker compose logs --tail 50 db-upgrade
```

Không có hạ cấp tự động. Migration `0004_persistence_integrity` (ràng buộc, bảng `execution_intents`, các trigger chỉ-thêm...) do `db-upgrade` áp dụng, không phải `deploy/migrate.sh` (script đó là cutover nhà cung cấp). Một lần quay lại mã (rollback) không chạy `alembic downgrade`; nếu mã cũ không đọc được lược đồ đã migrate, hãy khôi phục bản sao lưu trước cập nhật (mục 6.5, RUNBOOK 14.4).

#### Bước 10.6 Bí mật và `.env`; bảng xoay vòng [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]`

`.env` nằm ở `/opt/trading/.env`, quyền 0600, chủ là `trading`. Kiểm tra cấu hình bằng `-q` và chỉ bằng `-q`:

```bash
docker compose config -q
```

Lý do: lệnh `config` không có `-q` in ra môi trường đã phân giải, gồm mọi mật khẩu thật. Nếu lỡ làm vậy và đầu ra đã đi vào đâu đó, coi các bí mật đó là lộ.

| Họ bí mật | Repository ghi gì | Repository KHÔNG ghi |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | bootstrap yêu cầu ít nhất 16 ký tự và chỉ gồm chữ, số, `.`, `_`, `~`, `-` | cách đổi sau này. Đổi giá trị trong `.env` không tự đổi mật khẩu đã nằm sẵn trong volume `pgdata` đang có: đó là hành vi chung của PostgreSQL, không có trong repository `[CHƯA XÁC MINH]` |
| `BACKUP_S3_ACCESS_KEY_ID`, `BACKUP_S3_SECRET_ACCESS_KEY` | một biến thiếu thì lệnh dừng và nêu tên biến | quy trình xoay khóa ở nhà cung cấp `[CHƯA XÁC MINH]` |
| `BACKUP_CRYPT_PASSWORD`, `BACKUP_CRYPT_PASSWORD2` | giá trị là kết quả `rclone obscure`; MẤT hoặc ĐỔI cụm mật khẩu gốc thì mọi bản sao lưu cũ không đọc được | quy trình mã hóa lại sao lưu cũ; đừng đổi tùy tiện |
| Khóa Binance | khóa có quyền rút tiền tắt, giới hạn IP; tên biến tách riêng theo môi trường (OPS-06) | quy trình xoay `[CHƯA XÁC MINH]` |
| `TELEGRAM_BOT_TOKEN` | lấy từ BotFather, mỗi môi trường một bot (Q-L) | quy trình thu hồi và tạo lại `[CHƯA XÁC MINH]` |

#### Bước 10.7 Làm mới các pin (image, GitHub Actions) [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY CÓ MẠNG]` cho `--lookup`; `[MÁY PHÁT TRIỂN]` đủ cho `--list`

"Pin" là việc ghim một image hay một action vào một giá trị chính xác (thẻ cộng digest) để bản dựng tái lập được. Việc làm mới luôn có chủ ý và không bao giờ tự động (D050). Thủ tục (RUNBOOK 16.2) bằng lời thường: chạy `--lookup` để xem mục nào "MOVED"; đọc ghi chú phát hành của mọi mục đã đổi trước khi chấp nhận; sửa mọi nơi xuất hiện và các bảng của RUNBOOK mục 16 trong MỘT commit; dùng digest của chỉ mục (index digest) của thẻ, không dùng digest riêng của từng kiến trúc; chạy các kiểm thử dưới đây rồi để CI dựng và chạy job docker trước khi triển khai; sau một thay đổi lớn hoặc nhỏ của Python hay PostgreSQL, diễn tập `deploy/update.sh --ref <commit-sha>` trên một máy không phải sản xuất. Ngoại lệ duy nhất: `postgresql-client-17` trong image `ops` cố ý trôi trong phiên bản 17 vì kho PostgreSQL bỏ các bản vá cũ.

```bash
uv run pytest tests/test_deploy_docs.py tests/test_deploy_images.py tests/test_deploy_workflows.py
```

### Thẻ lệnh: deploy/refresh-pins.sh

> - **Để làm gì:** Liệt kê hoặc tra cứu các pin (image, phiên bản công cụ, GitHub Actions) xem pin nào đã đổi; chỉ đọc.
> - **Giải quyết vấn đề gì:** Giúp việc nâng pin có chủ ý (D050: không bao giờ tự động) thay vì để image hay action trôi âm thầm.
> - **Mức quan trọng:** **TÙY CHỌN**: không có lịch, chỉ khi bạn cân nhắc làm mới pin (D050).

**Mục đích:** liệt kê các image, phiên bản công cụ và GitHub Actions được ghim trong checkout này, hoặc hỏi các registry và GitHub xem pin nào đã đổi. Chỉ ĐỌC: không bao giờ sửa tệp nào.

**Khi nào chạy:** khi bạn cân nhắc làm mới các pin (bước 10.7); không có lịch.

**Chạy ở máy nào:** `--list` chạy offline ở bất kỳ máy có checkout (`[MÁY PHÁT TRIỂN]`); `--lookup` cần mạng, `curl` và `git` (`[MÁY CÓ MẠNG]`).

**Lệnh:**

```bash
deploy/refresh-pins.sh --list
```

```bash
deploy/refresh-pins.sh --lookup
```

Cờ: `--list` (offline, in một dòng `<name>:<tag>@sha256:<digest>` cho mỗi image, rồi `uv-version`, `python-version` và một dòng `<owner/repo>@<sha> <tag>` cho mỗi action), `--lookup` (online, in `unchanged` hoặc `MOVED` bên cạnh từng pin), `-h`/`--help`.

**Chạy thử:** Không áp dụng: script không có `--dry-run` vì nó vốn chỉ đọc và không đổi gì; `--list` là chế độ offline an toàn nhất.

**Dấu hiệu thành công:** `--list` in danh sách pin và thoát 0. `--lookup` in `unchanged` cho từng pin chưa đổi và thoát 0.

**Mã thoát:** 0 thành công và với `-h`. 2 khi không đưa đối số nào hoặc cờ lạ (`usage_error`). Với `--lookup`: 1 khi thiếu `curl` hay `git` (`die`), và 1 khi có ít nhất một tra cứu không trả về gì ("lookup failed").

**Khi lỗi:** `lookup failed` thường là lỗi mạng hay registry; chạy lại một lần rồi báo. Không có tùy chọn ghi đè nào.

**Không bao giờ:** sửa một tệp; tự động nâng pin; thay thế cho commit được duyệt ở bước 10.7.

#### Bước 10.8 Kéo dữ liệu nghiên cứu về máy phát triển (RUNBOOK 19.5) [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** máy sẽ nhận dữ liệu, cần cấu hình `BACKUP_*` và mạng (hôm nay `[MÁY PHÁT TRIỂN]` không có mạng, nên máy nào làm việc này là `[QUYẾT ĐỊNH CỦA BẠN]`)

Dữ liệu nghiên cứu (Parquet cùng `pg.dump` trong cùng bundle) đến máy nhận qua chuỗi sao lưu có sẵn: máy chủ đẩy một snapshot lên kho ngoài mã hóa và máy nhận kéo về, không có ssh nào từ máy nhận tới máy chủ. Máy nhận phải có cùng cấu hình `BACKUP_*` như máy chủ, nên cụm mật khẩu và một khóa truy cập bucket sẽ tồn tại ở máy thứ hai và các quy tắc giữ khóa phải áp dụng cho nó. Ít nhất một snapshot hoàn chỉnh phải có trên remote, mà bản sao lưu thật đầu tiên chờ cổng D064.

Thay `<UTC timestamp>` bằng giờ UTC hiện tại dạng `YYYYMMDDTHHMMSSZ`; đích không được tồn tại hoặc phải trống. Ba lệnh theo đúng thứ tự (kéo và kiểm; kiểm lại độc lập; chép vào thư mục dữ liệu thô không ghi đè):

```bash
docker compose --profile ops run --rm -T --no-deps ops /app/.venv/bin/python -m src.ops.backup pull --dest /app/data/backup/pull-<UTC timestamp>
```

```bash
docker compose --profile ops run --rm -T --no-deps ops /app/.venv/bin/python -m src.ops.backup verify --bundle-root /app/data/backup/pull-<UTC timestamp>
```

```bash
docker compose --profile ops run --rm -T --no-deps ops /app/.venv/bin/python -m src.ops.backup restore --bundle-root /app/data/backup/pull-<UTC timestamp> --parquet-target /app/data/raw --skip-db --force
```

Bản mới nhất hoàn chỉnh được dùng; để kéo một bản có tên, thêm `--snapshot <snapshot id>` vào lệnh đầu. Khi thành công, lệnh đầu in `pull-OK snapshot=<id> dest=...`. Lệnh thứ hai thoát 0 nghĩa là mọi tệp khớp manifest; mọi kết quả khác thì dừng, đừng chép. Lệnh thứ ba (`--skip-db` chỉ khôi phục Parquet; `--force` chỉ cần vì thư mục dữ liệu thô đã có dữ liệu và không cho ghi đè) không bao giờ ghi đè: nếu một đường dẫn đã tồn tại với nội dung khác, nó dừng với `already exists in the target with different content` và không chép gì. Đó là một phát hiện để điều tra, không phải lý do để xóa tệp đích hay đổi tùy chọn. Chỉ đưa tệp từ bundle kéo về vào thư mục dữ liệu thô bằng bước thứ ba, không bao giờ chép tay.

#### Bước 10.9 Ổ đĩa và vệ sinh volume [THỦ CÔNG]

**Chạy ở:** `[MÁY EC2]`

Cây Parquet chỉ lớn dần và không bao giờ bị xóa. Xem dung lượng bằng các lệnh chung:

```bash
df -h
```

Dọn các thư mục `restore-<timestamp>` và `drill-<timestamp>` cũ như ở bước 6.7. KHÔNG BAO GIỜ chạy lệnh `down` kèm cờ xóa volume, và không chạy lệnh dọn dẹp volume hay hệ thống của Docker: chúng xóa dữ liệu nghiên cứu không thể thay thế.

#### Bước 10.10 Đồng bộ thời gian [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]`

Bootstrap thay `systemd-timesyncd` bằng chrony và dừng nếu độ lệch vượt `--max-drift-ms` (mặc định 100 ms). Kiểm tra bất cứ lúc nào:

```bash
chronyc tracking
```

Nguồn: `docs/operations/RUNBOOK.md`, `docker-compose.yml`, `deploy/refresh-pins.sh`, `docs/operations/SECURITY_AND_OPERATIONS.md`, `src/ops/redaction.py`, `Dockerfile`, `.env.example`

## 11. Cập nhật và quay lại phiên bản cũ

> - **Để làm gì:** Cập nhật stack lên một commit đã xem lại và quay lại bản tốt cuối bằng `deploy/update.sh`.
> - **Giải quyết vấn đề gì:** Cập nhật tay dễ để lại trạng thái nửa vời; script sao lưu trước, ghi lại image tốt cuối và cho đường quay lại (quay lại không hoàn tác migration lược đồ).
> - **Mức quan trọng:** **TÙY CHỌN** cho tới khi bạn có phiên bản mới cần triển khai; từ lúc đó **NÊN LÀM** dùng script này, vì RUNBOOK không mô tả đường cập nhật nào khác.

Không có tag git nào trong repository, nên mọi ví dụ `--ref` ở đây dùng `<commit-sha>`; một tag bạn tự tạo và tự đẩy lên remote cũng dùng được.

#### Bước 11.1 Trước khi cập nhật [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]` bằng user `trading` trong `/opt/trading`

1. Cây làm việc phải sạch (cây có thay đổi chưa commit bị từ chối). Kiểm tra:

```bash
git status
```

2. Đích phải là một commit hoặc tag bạn đã xem lại, và remote phải có nó `[CHƯA XÁC MINH]`.
3. Cả hai image (`trading-alert:dev` và `trading-alert-ops:dev`, hoặc theo `IMAGE_TAG` của bạn) phải đang có trên máy: chúng là thứ mà việc quay lại sẽ trả về. Bước 4.9 đã dựng chúng.
4. Diễn tập để đọc kế hoạch:

```bash
deploy/update.sh --ref <commit-sha> --dry-run
```

#### Bước 11.2 Cập nhật [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]` bằng user `trading`

```bash
deploy/update.sh --ref <commit-sha>
```

Thứ tự theo phần đầu của script: từ chối nếu cây bẩn; ghi commit hiện tại và ID của hai image vào `.deploy/last-good.env` (bản ghi cũ giữ lại thành `last-good.env.prev`); chạy `deploy/backup.sh` (một bản sao lưu lỗi dừng cập nhật); gắn thẻ `:rollback` cho hai image; `git fetch --tags origin`; `git checkout --detach` tới ref; `docker compose --profile ops build`; `docker compose up -d`. Cờ `--skip-backup` bỏ qua bản sao lưu và là một rủi ro bạn tự nhận, đặc biệt khi cập nhật có migration.

#### Bước 11.3 Kiểm tra sau cập nhật [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]`

```bash
git rev-parse HEAD
```

```bash
docker compose ps
```

```bash
docker compose logs --tail 100 collector
```

Đối chiếu commit in ra với `<commit-sha>` bạn muốn; kiểm tra `db-upgrade` đã thoát thành công và collector lên lại (bước 10.5).

#### Bước 11.4 Quay lại phiên bản cũ [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]` bằng user `trading`

```bash
deploy/update.sh --rollback --dry-run
```

```bash
deploy/update.sh --rollback
```

#### Bước 11.5 Giới hạn cần biết (RUNBOOK 14.4) [ĐÃ XÂY]

**Chạy ở:** `[MÁY EC2]`

- Quay lại chỉ trả mã và image. Một migration lược đồ mà bản mới đã áp dụng KHÔNG được hoàn tác. Nếu mã cũ không đọc được lược đồ đã migrate, hãy khôi phục bản sao lưu trước cập nhật bằng `deploy/restore.sh` (mục 6.5) thay vì quay lại. Đó là lý do `--skip-backup` nguy hiểm khi có migration.
- Mỗi lần chạy `--ref` ghi đè `.deploy/last-good.env`. Sau một cập nhật hỏng nửa chừng, chạy `--ref` lần nữa sẽ ghi trạng thái nửa-cập-nhật đó thành "bản tốt cuối". Luôn quay lại TRƯỚC (hoặc sửa nguyên nhân), rồi mới cập nhật lại.
- `--rollback` trên một máy chưa từng cập nhật bằng `--ref` dừng với "no rollback state".
- Soak: một lần cập nhật khởi động lại tiến trình paper, là thời gian chưa bao phủ theo D063 mục 1 một khi runtime tồn tại (bước 7.9).

### Thẻ lệnh: deploy/update.sh

> - **Để làm gì:** Đưa stack đang chạy lên một commit đã xem lại, hoặc quay về đúng các image của lần chạy trước.
> - **Giải quyết vấn đề gì:** Cập nhật tay dễ bỏ sót sao lưu hoặc để trạng thái nửa vời; script từ chối cây bẩn, sao lưu trước, ghi image tốt cuối và cho đường quay lại (migration lược đồ thì không hoàn tác được).
> - **Mức quan trọng:** **NÊN LÀM** dùng nó mỗi khi triển khai phiên bản mới (RUNBOOK 14 chỉ mô tả đường này). Chưa cần nếu chưa có gì để cập nhật.

**Mục đích:** đưa stack đang chạy tới một ref git, hoặc đưa nó về đúng các image đã chạy trước đó.

**Khi nào chạy:** khi bạn muốn triển khai một phiên bản mới đã xem lại; hoặc để quay lại sau một cập nhật không ổn.

**Chạy ở máy nào:** `[MÁY EC2]` bằng user `trading` trong checkout (không dùng root).

**Lệnh:**

```bash
deploy/update.sh --ref <commit-sha> --skip-backup
```

```bash
deploy/update.sh --rollback
```

Hai chế độ. Chế độ cập nhật: `--ref REF` (bắt buộc, không được bắt đầu bằng dấu gạch), tùy chọn `--skip-backup` (chỉ dùng với `--ref`) và `--dry-run`. Chế độ quay lại: `--rollback` (kèm `--dry-run` nếu muốn), không dùng chung với `--ref` và `--skip-backup`. `-h`/`--help` in cách dùng. Các biến môi trường `COMPOSE_PROJECT_NAME`, `TRADING_ENV_FILE` và `IMAGE_TAG` (mặc định `dev`) được tôn trọng.

Tệp trạng thái: `.deploy/last-good.env` (quyền 0600, bị gitignore, được phân tích chứ không bao giờ `source`) chứa `GIT_SHA`, `APP_IMAGE_ID` và `OPS_IMAGE_ID`; bản trước là `last-good.env.prev`. Khi chạy lại một cập nhật dở (checkout đã ở REF và có bản ghi hợp lệ), script giữ nguyên bản ghi và các thẻ `:rollback` để quay lại vẫn về bản tốt cuối.

**Chạy thử:** cả hai chế độ có `--dry-run`:

```bash
deploy/update.sh --ref <commit-sha> --dry-run
```

```bash
deploy/update.sh --rollback --dry-run
```

**Dấu hiệu thành công:** cập nhật in "updated to <REF>; undo with: deploy/update.sh --rollback". Quay lại kết thúc bằng `docker compose up -d --no-build` và một cảnh báo rằng migration không bị hoàn tác.

**Mã thoát:** 0 khi thành công và với `-h`. 2 khi lỗi cờ (`usage_error`): không đưa `--ref` hay `--rollback`, dùng chung `--ref` với `--rollback`, `--skip-backup` cùng `--rollback`, hoặc ref bắt đầu bằng dấu gạch. 1 cho mọi lỗi `die`: cây làm việc có thay đổi chưa commit, hai image không tồn tại cục bộ để quay lại, không có trạng thái quay lại ("no rollback state"), tệp trạng thái hỏng, hoặc ID image không khớp với bản ghi. Một lệnh con lỗi (build, up) làm script thoát với mã của lệnh đó, suy ra từ `set -e` `[CHƯA XÁC MINH]`.

**Khi lỗi:** "the working tree has uncommitted changes": commit hoặc bỏ thay đổi. "images ... must exist locally": dựng bằng `docker compose --profile ops build` (bước 4.9). "image ... is ..., recorded was ...; refusing to roll back": thẻ `:rollback` không còn trỏ vào image đã ghi nên script dừng trước khi đổi gì; lúc này hãy khôi phục từ bản sao lưu (mục 6.5). "no rollback state ...": máy chưa từng cập nhật bằng `--ref`, không có gì để quay về.

**Không bao giờ:** hoàn tác một migration lược đồ; chạy bằng cờ `--ref` mà đầu vào là một nhánh cục bộ chưa xem lại; dùng `--skip-backup` qua một migration mà không có bản sao lưu khác; chạy lại `--ref` sau một cập nhật hỏng mà chưa quay lại.

Nguồn: `docs/operations/RUNBOOK.md`, `deploy/update.sh`, `deploy/backup.sh`, `docker-compose.yml`, `docs/DECISIONS.md`

## 12. Khẩn cấp

> - **Để làm gì:** Bảng "làm ngay" cho tình huống khẩn: SAFE_MODE, vị thế không có SL, lệnh trùng, collector dừng, máy mất, ổ đầy, S3 lỗi.
> - **Giải quyết vấn đề gì:** Lúc có sự cố không phải đi tìm cách; mục tiêu mặc định là bảo toàn vốn và tính toàn vẹn trạng thái (RUNBOOK mục 1).
> - **Mức quan trọng:** **NÊN LÀM** đọc một lần trước khi cần. Các hàng về sàn chỉ áp dụng từ DEMO; các hàng cấp máy chủ (bước 12.2) áp dụng ngay. Mức này là đánh giá của hướng dẫn này.

Mục tiêu mặc định là bảo toàn vốn và tính toàn vẹn trạng thái, không phải tiếp tục giao dịch cho nhanh (RUNBOOK mục 1). Bảng dưới trích đúng hành động của RUNBOOK các mục 2 đến 10 và 12, kèm trạng thái xây dựng và thời điểm áp dụng. Trong SHADOW không có lệnh hay vị thế nào, nên các tình huống về sàn áp dụng từ giai đoạn DEMO trở đi; các tình huống cấp máy chủ ở nửa cuối bảng áp dụng ngay bây giờ. Các hàng cấp máy chủ chỉ dùng lệnh đã có trong hướng dẫn này.

#### Bước 12.1 Tình huống về sàn và trạng thái hệ thống (từ DEMO trở đi) [CHƯA XÂY]

**Chạy ở:** `[MÁY CÓ MẠNG]` (xem trực tiếp trên sàn), `[MÁY EC2]` (cơ sở dữ liệu)

| Tình huống | Làm ngay | Trạng thái xây dựng | Áp dụng khi nào |
| --- | --- | --- | --- |
| SAFE_MODE: không đối chiếu được trạng thái, dữ liệu thị trường cũ, lệnh bảo vệ thiếu hay không chắc, nghi thực thi trùng, sàn hành xử bất thường, cơ sở dữ liệu hỏng hoặc không dùng được | 1) đặt SAFE_MODE; 2) chặn lệnh VÀO mới (lệnh bảo vệ và lệnh chỉ-giảm vẫn được phép, D034); 3) kiểm tra trực tiếp vị thế trên Binance; 4) kiểm tra lệnh thường đang mở; 5) kiểm tra lệnh algo/điều kiện đang mở; 6) kiểm tra mỗi vị thế có bảo vệ đúng không, thiếu thì sang hàng kế; 7) đối chiếu trạng thái cục bộ; 8) chỉ sau đó mới cân nhắc tiếp tục | SAFE_MODE bền qua khởi động lại và cách thoát là Phase 20 `[CHƯA XÂY]` | từ DEMO |
| Vị thế không có SL xác nhận | SAFE_MODE; báo động ngay; hỏi vị thế chuẩn trên Binance; hỏi lệnh bảo vệ/algo. Đích của D034 là tự đặt lại SL tại SL gốc sau kiểm tra rủi ro (không bao giờ rộng hơn), và nếu SL bị từ chối thì đóng vị thế bằng lệnh chỉ-giảm rồi báo động mức cao. Nhưng thang tự động đó là Phase 20 và CHƯA XÂY: cho tới lúc đó hệ thống chỉ vào SAFE_MODE và báo động, còn BẠN phải tự đặt SL hoặc đóng vị thế thủ công trên sàn. Đừng chờ hành động tự động | Phase 20 `[CHƯA XÂY]` | từ DEMO |
| Lệnh bảo vệ mồ côi (còn hoạt động khi vị thế đã bằng 0 hoặc kế hoạch đã đóng) | xác định mồ côi; xác nhận vị thế bằng 0; hủy các lệnh bảo vệ/algo liên quan; ghi nhật ký việc hủy; quét lại. Một SL đi cùng một lệnh VÀO còn chờ khớp KHÔNG phải mồ côi (F-401, D034) | quét định kỳ và theo sự kiện là Phase 20 `[CHƯA XÂY]` | từ DEMO |
| Nghi phê duyệt hay lệnh bị trùng | SAFE_MODE; không thử lại mù quáng; tra mã/băm phê duyệt; xem `clientOrderId`/`algoClientId`/trạng thái lệnh trên sàn; đối chiếu; chỉ tiếp tục khi chứng minh được ý định thực thi là duy nhất. Nguồn sự thật là PostgreSQL (D051), đọc bằng các lệnh SELECT chỉ-đọc ở dưới | các bảng `approvals` và `execution_intents` đã có từ Phase 17 (đã hoàn thành); nối vào tiến trình thật là Phase 24 `[CHƯA XÂY]` | từ DEMO |
| Telegram gửi lại cùng một callback | một callback lặp lại với cùng mã phê duyệt phải trả trạng thái hiện tại và không bao giờ tạo thêm ý định thực thi. Một callback `callback_query.id` được gửi lại không ghi thêm hàng nhật ký. Sau khi kế hoạch hết hạn, lớp callback vẫn trả "approval expired" ngay cả khi kế hoạch đã chạy: kiểm tra `execution_intents` trước khi kết luận là chưa đặt gì | lưu trữ và phát lại đã có từ Phase 17 (đã hoàn thành); thẻ xác nhận hai bước là Phase 23 `[CHƯA XÂY]` | từ SHADOW (phát lại) và từ DEMO |
| Dữ liệu thị trường cũ (thời gian hiện tại trừ nến đóng cuối vượt ngưỡng) | KHÔNG tín hiệu mới; KHÔNG lệnh vào mới; kết nối lại hoặc dựng lại; kiểm tra tính liên tục của nến; chỉ tiếp tục sau khi kiểm tra sức khỏe | phát hiện và xử lý ở Phase 20 `[CHƯA XÂY]` | từ DEMO (và với soak: khoảng trống được ghi, mục 7) |
| WebSocket ngắt | kết nối lại; làm mới giờ máy chủ nếu cần; dựng lại trạng thái tài khoản/thị trường; so với trạng thái cục bộ; khôi phục đăng ký; kiểm tra nến đóng mới nhất; rồi tiếp tục | bù REST sau đứt kết nối đã có ở supervisor (kế hoạch 16-08, mức đồ giả); dòng dữ liệu người dùng là Phase 18 `[CHƯA XÂY]` | từ SHADOW (dữ liệu công khai) |
| Cơ sở dữ liệu hỏng hoặc không dùng được | SAFE_MODE chỉ chặn lệnh VÀO mới; một sự cố cơ sở dữ liệu không được chặn hành động giảm rủi ro (D034); giữ nguyên bảo vệ phía sàn; khôi phục cơ sở dữ liệu hoặc chuyển sang giám sát chỉ-đọc; đối chiếu sau khi hồi phục. Các kho PostgreSQL thất bại theo hướng an toàn: trước khi gửi lệnh vào thì là NO_TRADE; sau khi lệnh có thể đã tồn tại thì lần ghi lỗi đầu vào SAFE_MODE với lý do `DB_FAILURE`. `UNRESOLVED_EXECUTION_INTENT` nghĩa là một lệnh vào có thể tồn tại mà hệ thống không thấy: tra ý định, hỏi Binance theo mã client, rồi hủy hoặc nhận lệnh bằng tay; đừng sửa hàng ý định | cách xử lý thất bại theo hướng an toàn đã có từ Phase 17 (đã hoàn thành); khởi động lại khôi phục và thoát SAFE_MODE thuộc Phase 20 và 24 `[CHƯA XÂY]` | từ DEMO |
| Binance suy giảm hay chậm | KHÔNG suy ra một lệnh không tồn tại chỉ vì hết thời gian chờ; truy vấn và đối chiếu TRƯỚC khi thử lại bất kỳ yêu cầu lệnh có chữ ký nào | bảng phân loại lỗi sàn là Phase 18 `[CHƯA XÂY]` | từ DEMO |
| Đóng vị thế bằng tay | việc đóng tay phải rõ ràng và được ghi là `ManualExit` với các trường `actor`, `reason`, `requested_at_utc`, `exchange_confirmation`; sau đó tiến trình đối chiếu phải hủy các lệnh bảo vệ mồ côi | ghi `ManualExit` và hủy mồ côi tự động là Phase 20 `[CHƯA XÂY]` | từ DEMO |

Ba truy vấn chỉ-đọc cho hàng "nghi phê duyệt hay lệnh bị trùng" (chép từ RUNBOOK mục 5; chạy bằng `psql` trên PostgreSQL của stack với user và cơ sở dữ liệu trong `.env`, cách chạy `psql` cụ thể trên máy chủ không được RUNBOOK nêu `[CHƯA XÁC MINH]`). KHÔNG BAO GIỜ `UPDATE` hay `DELETE` các bảng này bằng tay: các bảng nhật ký chỉ-thêm sẽ từ chối bằng lỗi "append-only".

```sql
-- the approval and its consumption state
SELECT approval_id, trade_plan_id, status, consumption_status, consumed_at_utc
  FROM approvals WHERE trade_plan_id = '<trade plan id>';

-- the write-ahead intent rows of the plan, one per role
SELECT role, intent_status, client_order_id, algo_client_id, exchange_order_id,
       outcome_recorded, outcome_is_no_trade, outcome_reason_code, intended_at_utc, sent_at_utc
  FROM execution_intents WHERE trade_plan_id = '<trade plan id>' ORDER BY role;

-- every intent that is not resolved
SELECT approval_id, role, intent_status, intended_at_utc
  FROM execution_intents WHERE intent_status IN ('INTENDED', 'SENT', 'UNKNOWN')
 ORDER BY intended_at_utc;
```

Cách đọc: `consumption_status = CONSUMED` nghĩa là phê duyệt đã tới bước đặt lệnh và có đúng một hàng ENTRY. `ACKED` là sàn đã nhận, `REJECTED` là sàn chắc chắn không nhận, còn `INTENDED`, `SENT` hoặc `UNKNOWN` là lệnh vào có thể có hoặc không trên sàn: hỏi Binance theo `client_order_id` (ENTRY) hay `algo_client_id` (chân bảo vệ) và đừng phê duyệt lại. Một phê duyệt `UNCONSUMED` chưa đặt gì.

#### Bước 12.2 Tình huống cấp máy chủ (áp dụng ngay) [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]`, và `[MÁY CÓ MẠNG]` cho AWS console và Binance

| Tình huống | Làm ngay | Trạng thái xây dựng | Áp dụng khi nào |
| --- | --- | --- | --- |
| Collector dừng | `docker compose ps` rồi `docker compose logs --tail 200 collector`; nếu chỉ dừng thì `docker compose start collector`. Các phút Open Interest đã mất là mất vĩnh viễn: ghi khoảng trống như một khoảng trống bao phủ (D059 mục 4). Heartbeat (mục 8.3) là thứ sẽ báo cho bạn biết sớm, khi bạn đã cài bộ gửi | `[ĐÃ XÂY]` | ngay |
| Máy chủ không với tới được | kiểm tra trạng thái instance trong AWS console `[THỦ CÔNG]`; sau khi máy lên lại, các service có `restart: unless-stopped` tự lên cùng Docker; kiểm tra bằng `docker compose ps`; ghi khoảng trống bao phủ. Cách khởi động lại instance không được repository mô tả | `[CHƯA XÁC MINH]` | ngay |
| Ổ đĩa đầy | `df -h` để xem; dọn thư mục `restore-` và `drill-` cũ (bước 6.7); KHÔNG xóa volume và không dùng lệnh dọn dẹp của Docker. Cây Parquet chỉ lớn dần: nếu vẫn đầy, tăng ổ là quyết định của bạn | `[ĐÃ XÂY]` | ngay |
| S3 không với tới được | bản sao lưu lỗi một cách thấy được; đọc `journalctl -u trading-backup`; dữ liệu cục bộ vẫn nguyên; chạy lại sau; nếu kéo dài, báo lại. Bảng 11.8 ở bước 6.8 phân biệt lỗi mạng với lỗi nội dung | `[ĐÃ XÂY]` | ngay |
| Địa chỉ công khai đổi (whitelist bị hỏng) | các khóa Binance giới hạn theo IP sẽ bị từ chối; dùng Elastic IP để tránh việc này; nếu địa chỉ đã đổi, cập nhật whitelist (bước 8.2) và chạy lại phép ping vùng (bước 3.7) | `[THỦ CÔNG]` | ngay (khi đã có khóa) |
| Xóa nhầm volume | khôi phục từ bản sao lưu: `deploy/restore.sh` (mục 6.5) lên máy đã bootstrap; điều kiện là cổng D064 đã qua, nếu chưa thì sao lưu thật chưa tồn tại và dữ liệu có thể không khôi phục được | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` | ngay |

Nguồn: `docs/operations/RUNBOOK.md`, `docs/DECISIONS.md`, `docker-compose.yml`, `docs/operations/SECURITY_AND_OPERATIONS.md`

## 13. Xử lý sự cố

> - **Để làm gì:** Bảng triệu chứng, nguyên nhân thường gặp và cách xử lý cho các lỗi hay gặp khi dựng và vận hành.
> - **Giải quyết vấn đề gì:** Không đoán mò khi gặp thông báo lỗi; mỗi hàng chỉ nguồn trong RUNBOOK hoặc script.
> - **Mức quan trọng:** **TÙY CHỌN**: chỉ tra khi gặp lỗi. Mức này là đánh giá của hướng dẫn này.

#### Bước 13.1 Bảng triệu chứng [ĐÃ XÂY] [CHƯA XÁC MINH]

**Chạy ở:** `[MÁY EC2]` (trừ khi cột xử lý nói khác)

| Triệu chứng | Nguyên nhân thường gặp | Cách xử lý | Nguồn |
| --- | --- | --- | --- |
| `bad interpreter` khi chạy một script `deploy/*.sh` | script có dấu xuống dòng CRLF của Windows | chép lại từ một bản checkout sạch hoặc `git archive`, không từ cây Windows cũ | RUNBOOK 13.2 |
| bootstrap dừng ở bước SSH với thông báo `lock-out guard` | tài khoản `trading` chưa có mật khẩu dùng được | trong phiên root chạy `passwd trading` rồi chạy lại đúng lệnh bootstrap | RUNBOOK 13.4, D062 |
| bootstrap từ chối hệ điều hành (`unsupported OS`) | hệ điều hành không phải Ubuntu 22.04, 24.04 hay Debian 12 | dùng một ảnh được hỗ trợ; không có gì bị đổi | `deploy/bootstrap.sh` |
| bootstrap báo tệp bí mật có `change_me` hoặc ký tự CR | `.env.example` còn giá trị mẫu, hoặc tệp lưu bằng CRLF | điền giá trị thật, bỏ hay sửa `DATABASE_URL`, lưu bằng LF | `deploy/bootstrap.sh` |
| bootstrap báo `clock drift ... exceeds` hoặc `chronyc waitsync did not report` | đồng hồ chưa đồng bộ trong giới hạn `--max-drift-ms` | đọc `chronyc tracking` và `chronyc sources`, chờ rồi chạy lại | RUNBOOK 13.4, 19.3 |
| collector báo unhealthy trong sáu phút đầu | chưa có mốc nào trên cơ sở dữ liệu mới (thời gian khởi động) | chờ hết sáu phút rồi xem `docker compose ps` | RUNBOOK 13.6 |
| `docker compose` báo `POSTGRES_USER required in .env` hoặc `POSTGRES_PASSWORD required in .env` | thiếu `.env` hoặc biến rỗng | điền biến trong `/opt/trading/.env` rồi dùng `docker compose config -q` | `docker-compose.yml` |
| không kết nối được PostgreSQL từ bên ngoài | PostgreSQL chỉ công bố trên `127.0.0.1` (chủ ý) | dùng đường hầm SSH từ máy bạn, ví dụ `ssh -L 5432:127.0.0.1:5432 trading@<elastic-ip>`; không mở cổng | `docker-compose.yml`, RUNBOOK 13.4 |
| `update.sh` từ chối vì "the working tree has uncommitted changes" | cây làm việc bẩn | commit hoặc bỏ thay đổi | `deploy/update.sh` |
| `update.sh` báo hai image "must exist locally" | chưa dựng image | chạy `docker compose --profile ops build` rồi thử lại | `deploy/update.sh` |
| quay lại dừng với "image ... is ..., recorded was ...; refusing to roll back" | thẻ `:rollback` không còn trỏ vào image đã ghi | không ép; khôi phục từ bản sao lưu (mục 6.5) | `deploy/update.sh`, RUNBOOK 14.3 |
| quay lại báo "no rollback state" | máy chưa từng cập nhật bằng `--ref` | không có gì để quay về; không cần làm gì | RUNBOOK 14.4 |
| `migrate.sh` thoát 1 | hoặc báo cáo "mất dữ liệu", hoặc một lỗi kiểm tra trước; đọc dòng `ERROR:` để phân biệt | nếu mất dữ liệu: dừng, điều tra, máy cũ còn nguyên | RUNBOOK 15.4 |
| `migrate.sh` thoát 2 | đối số sai hoặc tệp đầu vào không đọc được | sửa đối số hay tệp rồi chạy lại | `deploy/migrate.sh` |
| `migrate.sh` thoát 3 | khoảng trống Open Interest vượt `--max-gap-minutes` | đây là dữ liệu, không phải lỗi cần thử lại; quyết định khoảng trống có quan trọng hay không | RUNBOOK 15.4 |
| `migrate.sh` từ chối vì `data/backup/cutover/pg.dump` đã tồn tại | còn sót từ một lần thử trước | kiểm tra rồi tự tay xóa ở bên báo | RUNBOOK 15.3 |
| `migrate.sh` hoặc ssh báo lỗi kiểm tra khóa máy chủ | máy cũ không có trong `known_hosts` của thư mục khóa | thêm khóa máy chủ lấy từ kênh tin cậy (bước 5.4) | RUNBOOK 15.1 |
| backup báo thiếu một biến `BACKUP_...` | chưa đặt biến trong `.env` | thêm biến (bước 6.1); thông báo chỉ nêu tên | RUNBOOK 11.1 |
| `parquet push refused`, `parquet verification failed`, `manifest verification failed`, `rclone ... failed (exit N)` | các nhóm lỗi đẩy Parquet | dùng bảng ở bước 6.8 | RUNBOOK 11.8 |
| restore từ chối đích không trống | cơ sở dữ liệu hay thư mục Parquet đích đã có dữ liệu | dùng máy trống; chỉ dùng `--force` khi hiểu rõ, và nó vẫn không ghi đè | RUNBOOK 11.5 |
| diễn tập lỗi ở phép so sánh | collector vừa thêm một hàng symbol mới | chạy lại diễn tập | RUNBOOK 11.6 |
| ping vùng không trả `200` | vùng hay địa chỉ không được Binance chấp nhận | DỪNG, không cài gì, ghi lại và báo | RUNBOOK 19.2 |
| `soak_host_acceptance.py` thoát 1 | một điều kiện thiếu, chưa đầy đủ hoặc không PASS | làm điều kiện được nêu rồi cập nhật tệp | `scripts/soak_host_acceptance.py` |
| `soak_host_acceptance.py` thoát 2 | tệp không dùng được hoặc một trường trông giống bí mật | xóa thứ giống bí mật, giữ trích đoạn không nhạy cảm; xoay vòng bí mật nếu lỡ dán | `scripts/soak_host_acceptance.py` |
| tài khoản AWS bị đóng | gói Free tự đóng khoảng 2027-01-25 hoặc khi hết tín dụng | chuyển sang gói Paid trước mốc đó (điều kiện `PAID_PLAN`) | RUNBOOK 19.3, `16-DEC-O-12` |
| kiểm thử bị bỏ qua hoặc đỏ khi có `TRADING_CI_STRICT` | thiếu hạ tầng (bash, Docker, compose, shellcheck) trên máy chạy | cài hạ tầng thiếu; đó không phải lỗi mã | RUNBOOK 18 |
| Telegram im lặng | chưa rõ; có thể sai token hay mã chat, bot khác cùng polling, hoặc chưa có tiến trình nào gửi (runtime chưa xây) `[CHƯA XÁC MINH]` | kiểm tra bước 8.1; hỏi trong phiên lập kế hoạch | `.env.example` |
| không nhận được cảnh báo nào dù collector đã dừng (heartbeat im lặng) | bộ gửi chưa được cài hoặc chưa có URL ping, timer chưa bật, chu kỳ ping dài hơn chu kỳ của check, hoặc chưa được thử `[CHƯA XÁC MINH]` | đăng ký healthchecks.io rồi cài `deploy/heartbeat.sh` (`sudo deploy/heartbeat.sh --set-url`, rồi `sudo deploy/heartbeat.sh --install-timer --interval-seconds <N>`, bước 8.3), rồi làm phép thử ở bước 3.8 | RUNBOOK 11.4 |
| nhận cảnh báo thiếu tín hiệu từ dịch vụ heartbeat | collector dừng, máy không với tới được, hoặc chính bộ gửi dừng `[CHƯA XÁC MINH]` | làm theo hàng "Collector dừng" và "Máy chủ không với tới được" ở bước 12.2; ghi khoảng trống bao phủ | D042 điều kiện 1, D059 mục 4 |
| bạn tự khóa mình ngoài máy sau bootstrap | đóng phiên root trước khi thử phiên `trading` và `sudo -v` | dùng cách khôi phục của nhà cung cấp; lần sau giữ phiên root tới khi bước 4.6 xong | RUNBOOK 13.4 |
| lỡ chạy lệnh `config` của compose mà thiếu `-q` | đã in môi trường phân giải, gồm bí mật | coi các bí mật đã in là lộ và thay chúng | RUNBOOK 11.7 |

Nguồn: `docs/operations/RUNBOOK.md`, `deploy/bootstrap.sh`, `deploy/update.sh`, `deploy/migrate.sh`, `scripts/soak_host_acceptance.py`, `docker-compose.yml`

## 14. Bảng tra nhanh mọi lệnh

> - **Để làm gì:** Bảng tra mọi lệnh trong tài liệu, kèm máy chạy, mục giải thích và nhãn trạng thái.
> - **Giải quyết vấn đề gì:** Tìm lại đúng lệnh nhanh mà không đọc lại cả tài liệu, kể cả các lệnh `--dry-run`.
> - **Mức quan trọng:** **TÙY CHỌN** (tra cứu); nó không thay cho việc đọc thẻ lệnh trước lần chạy đầu tiên. Mức này là đánh giá của hướng dẫn này.

Mọi dòng bên dưới được chép từ các thẻ lệnh và các mục trước; cột "Mục" chỉ chỗ có giải thích. Nhãn trạng thái ở cột cuối: `[ĐÃ XÂY]` nghĩa là script tồn tại, `[CHƯA XÁC MINH]` nghĩa là chưa chạy trên máy thật.

### Bootstrap, cập nhật, di chuyển, refresh-pins

| Việc | Máy | Lệnh | Mục | Nhãn |
| --- | --- | --- | --- | --- |
| bootstrap, chạy thử | `[MÁY EC2]` | `sudo deploy/bootstrap.sh --dry-run --secrets-file /root/secrets.env --repo git@example.com:me/trading.git --ref <commit-sha> --authorized-keys /root/authorized_keys` | 4.3 | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| bootstrap, chạy thật với mọi cờ (`--secrets-file`, `--repo`, `--ref`, `--authorized-keys`, `--dir`, `--user`, `--deploy-key`, `--max-drift-ms`) | `[MÁY EC2]` | `sudo deploy/bootstrap.sh --secrets-file /root/secrets.env --repo git@example.com:me/trading.git --ref <commit-sha> --authorized-keys /root/authorized_keys --dir /opt/trading --user trading --deploy-key /root/deploy_key --max-drift-ms 100` | 4.4 | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| thư viện hàm dùng chung `lib.sh` (`die`, `run`, `DRY_RUN`) | không chạy | được `source` bởi các script khác, không có cờ và không bao giờ chạy trực tiếp | thẻ `deploy/bootstrap.sh` | `[ĐÃ XÂY]` |
| update, cập nhật (`--ref`, `--skip-backup`, `--dry-run`) | `[MÁY EC2]` | `deploy/update.sh --ref <commit-sha> --skip-backup --dry-run` | 11.2 | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| update, quay lại (`--rollback`) | `[MÁY EC2]` | `deploy/update.sh --rollback --dry-run` | 11.4 | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| migrate, chạy thử (`--dry-run`) | `[MÁY EC2]` | `deploy/migrate.sh --dry-run trading@old.example local` | 5.6 | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| migrate, chạy thật (`--max-gap-minutes`, `--wait-seconds`, `--key-source`) | `[MÁY EC2]` | `deploy/migrate.sh --max-gap-minutes 60 --wait-seconds 900 --key-source ~/.ssh/trading-migrate trading@old.example local` | 5.7 | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| migrate, chỉ in lại báo cáo (`--report-only`) | `[MÁY EC2]` | `deploy/migrate.sh --report-only --max-gap-minutes 30 trading@old.example local` | 5.8 | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| refresh-pins, liệt kê offline (`--list`) | `[MÁY PHÁT TRIỂN]` | `deploy/refresh-pins.sh --list` | 10.7 | `[ĐÃ XÂY]` |
| refresh-pins, tra cứu online (`--lookup`) | `[MÁY CÓ MẠNG]` | `deploy/refresh-pins.sh --lookup` | 10.7 | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| soak, chạy compose trên project `trading-soak` (script từ chối `down` kèm cờ xóa volume) | `[MÁY EC2]` | `deploy/compose-soak.sh ps` | 7.5 | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| soak, dựng image từ commit sạch và ghi lại commit cùng mã image (`--dry-run` chỉ in) | `[MÁY EC2]` | `deploy/soak-image.sh --dry-run` | 7.5 | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| diễn tập, chạy compose trên project `trading-rehearsal` (từ chối biến khóa giao dịch và soak đang chạy; `--dry-run` chỉ in) | `[MÁY EC2]` | `TRADING_ENV_FILE=/home/trading/rehearsal.env deploy/compose-rehearsal.sh --dry-run up -d db-upgrade` | 7.5 | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |

### Sao lưu, khôi phục, diễn tập, hai unit systemd

| Việc | Máy | Lệnh | Mục | Nhãn |
| --- | --- | --- | --- | --- |
| backup, khởi tạo remote (`--init-remote`) | `[MÁY EC2]` | `deploy/backup.sh --init-remote --dry-run` | 6.2 | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| backup, cài timer (`--install-timer`) | `[MÁY EC2]` | `sudo deploy/backup.sh --install-timer --dry-run` | 6.3 | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| backup, chạy một lần ngay (`--dry-run`) | `[MÁY EC2]` | `deploy/backup.sh --dry-run` | 6.4 | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| restore (`--snapshot`, `--force`, `--no-start`, `--dry-run`) | `[MÁY EC2]` | `deploy/restore.sh --snapshot 20260930T031500Z --force --no-start --dry-run` | 6.5 | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| diễn tập khôi phục (`--dry-run`) | `[MÁY EC2]` | `deploy/backup-drill.sh --dry-run` | 6.6 | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| cổng D064 trên S3 thật (`--execute`, `--evidence-dir`, `--dry-run`) | `[MÁY EC2]` | `deploy/backup-real-s3-gate.sh --execute --evidence-dir /home/trading/gate-evidence` | thẻ `deploy/backup-real-s3-gate.sh` | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| diễn tập bundle cục bộ trên Windows (`scripts/backup-drill.ps1`) | `[MÁY PHÁT TRIỂN]` hoặc `[MÁY CŨ]` Windows | `powershell -NoProfile -File scripts/backup-drill.ps1` | thẻ `scripts/backup-drill.ps1` | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| unit `trading-backup.service`: xem trạng thái | `[MÁY EC2]` | `systemctl status trading-backup` | 6.3 | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| unit `trading-backup.service`: xem nhật ký | `[MÁY EC2]` | `journalctl -u trading-backup` | 6.3 | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| unit `trading-backup.timer`: xem lịch | `[MÁY EC2]` | `systemctl list-timers trading-backup.timer` | 6.3 | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| backup của project soak, cài timer riêng (`--install-soak-timer`, `--soak-env-file`; bucket riêng) | `[MÁY EC2]` | `sudo deploy/backup.sh --install-soak-timer --soak-env-file /home/trading/soak.env --dry-run` | thẻ `deploy/systemd/trading-soak-backup.service` | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| unit `trading-soak-backup.service`: xem nhật ký | `[MÁY EC2]` | `journalctl -u trading-soak-backup` | thẻ `deploy/systemd/trading-soak-backup.service` | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| unit `trading-soak-backup.timer`: xem lịch | `[MÁY EC2]` | `systemctl list-timers trading-soak-backup.timer` | thẻ `deploy/systemd/trading-soak-backup.timer` | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |

### Heartbeat ra ngoài VPS (healthchecks.io), hai unit systemd

| Việc | Máy | Lệnh | Mục | Nhãn |
| --- | --- | --- | --- | --- |
| heartbeat, cất URL ping (`--set-url`) | `[MÁY EC2]` | `sudo deploy/heartbeat.sh --set-url` | thẻ `deploy/heartbeat.sh` | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| heartbeat, cài timer (`--install-timer`, `--interval-seconds`, `--fail-ping`, `--url-file`) | `[MÁY EC2]` | `sudo deploy/heartbeat.sh --install-timer --interval-seconds <N> --fail-ping --url-file /etc/trading/heartbeat.url --dry-run` | thẻ `deploy/heartbeat.sh` | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| heartbeat, một lần thử không gửi gì (`--dry-run`) | `[MÁY EC2]` | `deploy/heartbeat.sh --dry-run` | thẻ `deploy/heartbeat.sh` | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| unit `trading-heartbeat.service`: xem trạng thái | `[MÁY EC2]` | `systemctl status trading-heartbeat` | thẻ `deploy/systemd/trading-heartbeat.service` | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| unit `trading-heartbeat.service`: xem nhật ký | `[MÁY EC2]` | `journalctl -u trading-heartbeat` | thẻ `deploy/systemd/trading-heartbeat.service` | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| unit `trading-heartbeat.timer`: xem lịch | `[MÁY EC2]` | `systemctl list-timers trading-heartbeat.timer` | thẻ `deploy/systemd/trading-heartbeat.timer` | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| heartbeat riêng của paper, cất URL (`--target`, `--set-url`) | `[MÁY EC2]` | `sudo deploy/heartbeat.sh --target paper --set-url` | thẻ `deploy/systemd/trading-soak-paper-heartbeat.service` | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| heartbeat riêng của paper, cài timer (`--target`, `--install-timer`, `--interval-seconds`, `--soak-env-file`) | `[MÁY EC2]` | `sudo deploy/heartbeat.sh --target paper --install-timer --interval-seconds 60 --soak-env-file /home/trading/soak.env --dry-run` | thẻ `deploy/systemd/trading-soak-paper-heartbeat.service` | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| đầu dò độ sống của paper (`--liveness`) | `[MÁY EC2]` | `deploy/heartbeat.sh --target paper --dry-run` | thẻ `deploy/systemd/trading-soak-paper-heartbeat.service` | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| unit `trading-soak-paper-heartbeat.service`: xem trạng thái | `[MÁY EC2]` | `systemctl status trading-soak-paper-heartbeat` | thẻ `deploy/systemd/trading-soak-paper-heartbeat.service` | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| unit `trading-soak-paper-heartbeat.timer`: xem lịch | `[MÁY EC2]` | `systemctl list-timers trading-soak-paper-heartbeat.timer` | thẻ `deploy/systemd/trading-soak-paper-heartbeat.timer` | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |

### Nghiệm thu và kiểm tra hồ sơ

| Việc | Máy | Lệnh | Mục | Nhãn |
| --- | --- | --- | --- | --- |
| kiểm tra hồ sơ nghiệm thu (`scripts/soak_host_acceptance.py`) | máy có repository và `uv` | `uv run python scripts/soak_host_acceptance.py acceptance.json` | 3.8 | `[ĐÃ XÂY]` |
| ping Binance từ máy EC2 | `[MÁY EC2]` | `curl -sS -o /dev/null -w "%{http_code}" https://fapi.binance.com/fapi/v1/ping` | 3.7 | `[CHƯA XÁC MINH]` |
| đồng bộ thời gian | `[MÁY EC2]` | `chronyc tracking` | 10.10 | `[CHƯA XÁC MINH]` |

### Compose: vòng đời, sức khỏe, nhật ký

Tám service: `postgres`, `db-upgrade`, `collector`, `paper` (profile `paper`, tiến trình paper), `paper-pin` (profile `paper-pin`, ghim epoch một lần), `live` (profile `live`, khung giữ chỗ), `backup` (profile `ops`), `ops` (profile `ops`). Project cố định tên `trading`.

| Việc | Máy | Lệnh | Mục | Nhãn |
| --- | --- | --- | --- | --- |
| xem trạng thái | `[MÁY EC2]` | `docker compose ps` | 10.2 | `[ĐÃ XÂY]` |
| khởi động stack | `[MÁY EC2]` | `docker compose up -d` | 10.2 | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| dừng, khởi động, khởi động lại collector | `[MÁY EC2]` | `docker compose stop collector`, `docker compose start collector`, `docker compose restart collector` | 10.2 | `[ĐÃ XÂY]` |
| dựng image | `[MÁY EC2]` | `docker compose --profile ops build` | 4.9 | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| kiểm tra cấu hình (luôn có `-q`) | `[MÁY EC2]` | `docker compose config -q` | 10.6 | `[ĐÃ XÂY]` |
| nhật ký collector | `[MÁY EC2]` | `docker compose logs --tail 200 collector` | 10.4 | `[ĐÃ XÂY]` |
| đầu dò sức khỏe của collector (`--healthcheck`) | `[MÁY EC2]` | `docker compose exec collector /app/.venv/bin/python -m src.data.collector --healthcheck` | 10.3 | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| một lệnh một lần trong hộp công cụ `ops` | `[MÁY EC2]` | `docker compose --profile ops run --rm -T --no-deps ops ls /app/data/backup` | 10.2 | `[ĐÃ XÂY]` |

### Lệnh `python -m src.ops.backup` qua image ops (kéo dữ liệu nghiên cứu)

| Việc | Máy | Lệnh | Mục | Nhãn |
| --- | --- | --- | --- | --- |
| pull (kéo và kiểm) | máy nhận dữ liệu | `docker compose --profile ops run --rm -T --no-deps ops /app/.venv/bin/python -m src.ops.backup pull --dest /app/data/backup/pull-<UTC timestamp>` | 10.8 | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| verify (kiểm lại độc lập) | máy nhận dữ liệu | `docker compose --profile ops run --rm -T --no-deps ops /app/.venv/bin/python -m src.ops.backup verify --bundle-root /app/data/backup/pull-<UTC timestamp>` | 10.8 | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |
| restore, chỉ Parquet, không ghi đè | máy nhận dữ liệu | `docker compose --profile ops run --rm -T --no-deps ops /app/.venv/bin/python -m src.ops.backup restore --bundle-root /app/data/backup/pull-<UTC timestamp> --parquet-target /app/data/raw --skip-db --force` | 10.8 | `[ĐÃ XÂY]` `[CHƯA XÁC MINH]` |

### Chưa xây

| Việc | Máy | Lệnh | Mục | Nhãn |
| --- | --- | --- | --- | --- |
| điểm vào của tiến trình paper | `[MÁY EC2]` | chưa có lệnh chạy được (xem bước 7.4); tên dự kiến `python -m src.paper.runtime` | 7.4 | `[CHƯA XÂY]` |
| các giai đoạn DEMO, CANARY, LIVE | `[MÁY CÓ MẠNG]` | chưa có lệnh nào | 9 | `[CHƯA XÂY]` |

Nguồn: `deploy/bootstrap.sh`, `deploy/lib.sh`, `deploy/update.sh`, `deploy/migrate.sh`, `deploy/refresh-pins.sh`, `deploy/backup.sh`, `deploy/restore.sh`, `deploy/backup-drill.sh`, `deploy/systemd/trading-backup.service`, `deploy/systemd/trading-backup.timer`, `deploy/heartbeat.sh`, `deploy/systemd/trading-heartbeat.service`, `deploy/systemd/trading-heartbeat.timer`, `scripts/soak_host_acceptance.py`, `scripts/backup-drill.ps1`, `docker-compose.yml`, `docs/operations/RUNBOOK.md`, `deploy/compose-soak.sh`, `deploy/compose-rehearsal.sh`, `deploy/soak-image.sh`

## 15. Danh sách kiểm tra cuối cùng

> - **Để làm gì:** Danh sách tick cuối cùng, mỗi mục dẫn về mục giải thích; mục chưa làm được vì chưa xây thì để trống.
> - **Giải quyết vấn đề gì:** Thấy ở một chỗ mình còn thiếu gì trước khi tạo máy, trước khi soak và trước go-live.
> - **Mức quan trọng:** **NÊN LÀM** dùng như bản kiểm lại; mức quan trọng của từng mục là mức của mục được dẫn tới. Đánh giá của hướng dẫn này.

Mỗi mục dẫn tới phần giải thích. Các mục chưa thể làm vì chưa xây được để trống và gắn nhãn `[CHƯA XÂY]`.

### Trước khi tạo máy

- [ ] Tôi biết tài khoản AWS ở gói Free đóng khoảng 2027-01-25 và sẽ chuyển sang gói Paid trước đó (mục 2.1)
- [ ] Tôi đã tự ghi các giá trị còn thiếu của quyết định O-12 (loại máy, ổ, ngân sách, vòng đời S3, chu kỳ và ân hạn của heartbeat) theo lời của mình (mục 2.2)
- [ ] Tôi đã tạo cặp khóa SSH và khóa riêng không rời máy tôi (mục 2.3)
- [ ] Tệp `authorized_keys` có ít nhất một khóa công khai hợp lệ (mục 2.4)
- [ ] Tệp bí mật soạn ở máy có mạng: không còn `change_me`, mật khẩu PostgreSQL hợp lệ, dùng LF, không có `BINANCE_LIVE_*` (mục 2.5)
- [ ] Tôi có một commit hoặc tag cho `--ref` và đã kiểm tra remote có nó (mục 2.6)
- [ ] Cụm mật khẩu sao lưu đã được đổi sang dạng obscured và bản gốc nằm ngoài VPS (mục 2.7)

### Máy EC2

- [ ] Hệ điều hành là Ubuntu 22.04, Ubuntu 24.04 hoặc Debian 12 (mục 3.1)
- [ ] Elastic IP đã gắn vào instance (mục 3.2)
- [ ] Mã hóa EBS đã được kiểm tra và, nếu cần, bật theo quyết định của tôi (mục 3.3)
- [ ] Security group chỉ mở SSH và không có luật vào cho PostgreSQL (mục 3.4)
- [ ] Ngân sách có cảnh báo và tài khoản đã ở gói Paid (mục 3.5)
- [ ] Bucket S3 riêng tư, mã hóa mặc định, bật versioning, mới và trống (mục 3.6)
- [ ] Phép ping tới `fapi.binance.com` từ instance trả `200` trước khi cài gì (mục 3.7)
- [ ] Tôi đã đọc kế hoạch `--dry-run` của bootstrap, nhất là các dòng ufw và sshd (mục 4.3)
- [ ] Bootstrap chạy xong, tôi đã đặt `passwd trading` và thử `sudo -v` ở phiên SSH thứ hai trước khi đóng phiên root (mục 4.6)
- [ ] Tôi đã làm đủ 8 mục trong danh sách của người vận hành (mục 4.7)
- [ ] `.env` có quyền `600 trading` và tệp bí mật đã chép đã bị xóa (mục 4.8)
- [ ] `docker compose config -q` và `docker compose --profile ops build` đều qua; tôi chưa chạy `docker compose up -d` trước cutover (mục 4.9)

### Collector và di chuyển

- [ ] Tôi đã kiểm tra các điều kiện tiên quyết của máy cũ, kể cả lưu ý Docker Desktop (mục 5.3)
- [ ] Thư mục khóa di chuyển có `id_ed25519` và `known_hosts`, và ssh không tương tác thử được (mục 5.5)
- [ ] Tôi đã đọc kết quả `deploy/migrate.sh --dry-run` (mục 5.6)
- [ ] Cutover có mã thoát 0, hoặc mã 3 mà tôi đã quyết định chấp nhận (mục 5.8)
- [ ] Khoảng trống Open Interest được ghi như khoảng trống bao phủ (mục 5.9)
- [ ] Chỉ sau mã 0 tôi mới tắt máy cũ, rồi cập nhật whitelist, chuyển heartbeat, xóa thư mục khóa (mục 5.11)

### Sao lưu

- [ ] Các biến `BACKUP_*` đã nằm trong `/opt/trading/.env` (mục 6.1)
- [ ] `deploy/backup.sh --init-remote` đã chạy đúng một lần trên bucket trống (mục 6.2)
- [ ] Timer đã cài và `systemctl list-timers trading-backup.timer` liệt kê nó (mục 6.3)
- [ ] Một lần diễn tập `deploy/backup-drill.sh` đã thành công (mục 6.6)
- [ ] Cổng D064 (bằng chứng trên S3 thật) đã qua và `BACKUP_REAL_S3_GATE` là PASS `[CHƯA XÂY]` (mục 6)

### Kênh bên ngoài

- [ ] Bot Telegram riêng cho máy soak đã tạo trong BotFather và token không bị dán đi đâu (mục 8.1)
- [ ] Mỗi khóa Binance bị giới hạn ở đúng Elastic IP và quyền rút tiền tắt (mục 8.2)
- [ ] Một check healthchecks.io đã đăng ký với chu kỳ và thời gian ân hạn do tôi chọn, và URL ping được giữ bí mật (mục 8.3)
- [ ] Bộ gửi heartbeat (kế hoạch 16-50) đã được cài và phép thử `HEARTBEAT_MONITOR_ALERT_RECEIVED` đã cho cả cảnh báo lẫn thông báo phục hồi `[CHƯA XÁC MINH]` (mục 3.8)
- [ ] `acceptance.json` có đủ 16 điều kiện PASS và `soak_host_acceptance.py` thoát 0 (mục 3.8)

### Sẵn sàng cho soak Phase 16

- [ ] Cả 50 kế hoạch của Phase 16 đã xong, kể cả 16-50 bộ gửi heartbeat (đã có SUMMARY, chưa cài) `[CHƯA XÂY]` (mục 7.3)
- [ ] Tiến trình paper có điểm vào chạy được `[CHƯA XÂY]` (mục 7.4)
- [ ] Giả thuyết, lưới tham số, lệnh cho phép chạy nghiên cứu và ứng viên đã được tôi duyệt hoặc chỉ định `[CHƯA XÂY]` (mục 7.6)
- [ ] Tôi đã cho phép đúng một băm trong `PAPER_START_ALLOWLIST` `[CHƯA XÂY]` (mục 7.6)
- [ ] Trial soak 14 ngày đạt các tiêu chí đã phê chuẩn và tôi đã tuyên bố đạt `[CHƯA XÂY]` (mục 7.7)

### Cổng go-live (tất cả để trống)

- [ ] Phase 18 đến 25 đã xong và được kiểm chứng `[CHƯA XÂY]` (mục 9.2)
- [ ] Bộ kịch bản demo và soak demo ít nhất 3 tuần không có sai lệch không giải thích `[CHƯA XÂY]` (mục 9.3)
- [ ] CANARY với khóa chỉ-đọc và tài khoản phụ nhỏ không có sai lệch `[CHƯA XÂY]` (mục 9.3)
- [ ] Điều kiện của `enable()` ở Phase 26 đều đạt `[CHƯA XÂY]` (mục 9.3)
- [ ] Heartbeat ngoài VPS vẫn hoạt động cho mọi tiến trình chạy dài của máy live (D042 điều kiện 1); nó chỉ báo cho tôi, SL vẫn nằm trên sàn; bộ gửi hiện chỉ dò collector, đầu dò cho paper và live thuộc Phase 24 `[CHƯA XÂY]` (mục 8.3)

### Phụ lục: Hướng dẫn này không làm được gì

Những thứ còn chưa quyết định hoặc chưa được kiểm chứng, và hướng dẫn này không tự quyết:

- Các giá trị O-12 còn thiếu (loại máy, dung lượng ổ, ngân sách, vòng đời S3, chu kỳ và thời gian ân hạn của heartbeat; dịch vụ healthchecks.io đã chọn): `[QUYẾT ĐỊNH CỦA BẠN]`.
- Các dữ kiện gói miễn phí của healthchecks.io (20 check, 100 bản ghi log mỗi check, giới hạn ping): chỉ xác minh một phần từ trang bên thứ ba, `[CHƯA XÁC MINH]`.
- Nơi lưu bằng chứng bền vững của soak (quyết định mở O-01) và nơi ghi các khoảng trống bao phủ.
- Máy nào kéo dữ liệu nghiên cứu về (mục 10.8) và máy nào giữ `acceptance.json` (mục 3.8).
- Mô hình thực thi D055 (đặt SL trước hay sau khi vào lệnh): còn là quyết định mở.
- Cách an toàn để biết mã chat Telegram, cách thu hồi token và cách lấy phiên root trên ảnh AWS: chưa được repository ghi.
- Mọi giá cả của AWS ngoài hai mức đã nêu ở bước 3.2 và 3.5, và mọi giao diện console của AWS, Binance, Telegram.

Nguồn đã đọc ngày 2026-10-09 tại commit `97a92a6`: `docs/operations/RUNBOOK.md`, `docs/operations/SECURITY_AND_OPERATIONS.md`, `docs/DECISIONS.md`, `docker-compose.yml`, `Dockerfile`, `.env.example`, `deploy/bootstrap.sh`, `deploy/update.sh`, `deploy/migrate.sh`, `deploy/backup.sh`, `deploy/restore.sh`, `deploy/backup-drill.sh`, `deploy/refresh-pins.sh`, `deploy/lib.sh`, `scripts/soak_host_acceptance.py`, `scripts/backup-drill.ps1`, `.planning/ROADMAP.md`, `.planning/phases/16-paper-runtime-composition/16-CONTEXT.md`.

Nguồn: `docs/operations/RUNBOOK.md`, `docs/DECISIONS.md`, `.planning/ROADMAP.md`, `.planning/phases/16-paper-runtime-composition/16-CONTEXT.md`, `.env.example`
