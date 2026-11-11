# mybot — trợ lý cá nhân qua Telegram

Hai phần: **theo dõi Telegram** và **soạn email theo template** (xem mục *Soạn email* bên dưới).

Phần theo dõi Telegram đọc tin nhắn trên tài khoản của bạn:

- **Báo ngay** tin quan trọng theo luật: **tin nhắn riêng** từ người **VIP**, bạn **bị nhắc tên hoặc được trả lời**, tin có **từ khóa**.
  (Người VIP nhắn trong nhóm thì không báo ngay.) Tin báo ngay chỉ gồm một dòng gọn: `Tên · (nhóm) · giờ · nội dung`, không nút.
- **Mọi tin khác bị bỏ qua**: không báo, không lưu lại. Bot không dùng AI.
- **Giờ nghỉ** hằng ngày (`/schedule`): bot im lặng hẳn, mọi tin trong giờ nghỉ bị bỏ qua (không báo ngay, không gửi bù).

Gõ lệnh không kèm gì (ví dụ `/vip`, `/schedule`, `/screen`) để hiện nút chọn: nút như *Add* sẽ hỏi bạn gõ tiếp. Vẫn gõ thẳng được, ví dụ `/vip add An`. Các lệnh có trong nút **Menu** của bot.

Mẹo: tắt tiếng (mute) mọi chat trong Telegram, chỉ để thông báo của bot này.

---

## Cài đặt lần đầu (trên máy Windows có Docker Desktop)

### 1. Chuẩn bị 3 giá trị bí mật

| Giá trị | Lấy ở đâu |
|---|---|
| `TG_API_ID`, `TG_API_HASH` | Đăng nhập https://my.telegram.org → **API development tools** → tạo app (tên gì cũng được) |
| `TG_BOT_TOKEN` | Nhắn **@BotFather** trên Telegram → `/newbot` → đặt tên → nhận token |

Sao chép `.env.example` thành `.env` rồi điền các giá trị vào. **Không chia sẻ file `.env`**.

### 2. Mở bot của bạn trên Telegram và bấm **Start**

Bot chỉ nhắn được cho bạn sau khi bạn đã bấm Start.

### 3. Đăng nhập tài khoản Telegram (một lần)

Mở PowerShell trong thư mục dự án:

```bash
docker compose build
```

```bash
docker compose run --rm bot python -m mybot login
```

Gõ số điện thoại (dạng `+84...`), mã Telegram gửi về, và mật khẩu 2 bước nếu có.
Phiên đăng nhập lưu ở `data/user.session` — **file này có toàn quyền vào tài khoản Telegram của bạn, không chia sẻ cho ai**.

### 4. Chạy bot

```bash
docker compose up -d
```

Lần đầu tiên, sau khi bot chạy, nhắn `/start` cho bot để bot "biết" bạn (chỉ cần một lần).
Từ lần khởi động sau, bot sẽ nhắn "Bot đã chạy". Docker tự chạy lại bot khi máy khởi động (nếu Docker Desktop được bật cùng Windows).

Các lệnh hữu ích:

```bash
docker compose logs -f --tail 100
```

```bash
docker compose restart
```

```bash
docker compose down
```

---

## Lệnh trong bot

| Lệnh | Tác dụng |
|---|---|
| `/vip list` · `/vip add <tên người, @username hoặc id>` · `/vip remove <số thứ tự hoặc tên>` | Tin nhắn riêng từ người VIP → báo ngay (chỉ thêm được người, không thêm nhóm) |
| `/keyword list` · `/keyword add <từ khóa>` · `/keyword remove <số thứ tự hoặc từ khóa>` (viết tắt `/kw`) | Tin có từ khóa → báo ngay |
| `/schedule` · `/schedule 17:30 08:00` · `/schedule off` | Giờ nghỉ hằng ngày: bot bỏ qua hẳn mọi tin (hết giờ nghỉ cũng không gửi bù). `off`: không có giờ nghỉ |
| `/screen status` · `/screen on` · `/screen off` | Màn hình máy Windows chạy bot (xem mục *Bật/tắt màn hình Windows*) |
| `/ultraview` (`/uv`) | Mở UltraViewer nếu chưa chạy, gửi ID và mật khẩu |
| `/help` | Danh sách lệnh |

Gõ lệnh không kèm gì thì bot hiện nút chọn:

| Lệnh | Nút |
|---|---|
| `/vip`, `/keyword` | List · Add · Remove |
| `/schedule` | Status · Set · Off |
| `/screen` | Status · On · Off |

Nút Add / Set / Remove hỏi bạn gõ tiếp (Remove in danh sách trước để biết số thứ tự). Đang được hỏi mà gõ lệnh khác thì bỏ câu hỏi.
Các lệnh cũng nằm trong nút **Menu** của bot trên Telegram (bot tự cập nhật mỗi lần khởi động),
và trên bàn phím nút nhanh dưới ô nhập: Help · VIP · Screen · Mail / Keyword · Schedule · UltraView
(hiện sau tin "Bot đã chạy" hoặc khi gõ /help; bấm nút giống như gõ lệnh).

`/vip add` tìm theo tên trong danh sách chat của bạn; nếu nhiều kết quả, bot hiện nút để chọn.
Ngoài VIP và từ khóa, tin **nhắc tên bạn hoặc trả lời tin của bạn** luôn được báo ngay.

## Soạn email

### Bật lần đầu
1. Bật **xác minh 2 bước** cho tài khoản Google: https://myaccount.google.com/signinoptions/twosv
2. Tạo **App Password**: https://myaccount.google.com/apppasswords → đặt tên `mybot` → Google hiện mật khẩu 16 ký tự.
3. Thêm vào `.env`:
   ```
   GMAIL_ADDRESS=ban@gmail.com
   GMAIL_APP_PASSWORD=abcd efgh ijkl mnop
   ```
4. `docker compose up -d --build`. Bot báo "Bot đã chạy (theo dõi Telegram, soạn email)".

App Password có **toàn quyền vào hộp thư** — không chia sẻ. Bị lộ thì vào lại trang ở bước 2 để xóa.

### Template
Mỗi file `.md` trong `data/templates/` là một template (lần đầu bot tạo sẵn `mau-bao-gia.md` để làm theo):

```
---
to: khach@abc.com
cc: sep@gmail.com
subject: Báo giá dự án {Tên dự án}
---
Kính gửi {Tên khách},
...
```

- Chỗ cần điền viết trong `{...}`; bot hỏi lần lượt theo thứ tự xuất hiện (tiêu đề trước).
- Cùng một `{...}` xuất hiện nhiều chỗ (ví dụ cả tiêu đề và nội dung) thì bot chỉ hỏi một lần.
- **Ô ngày** viết `{Tên:ngày}`, ví dụ `{Ngày nghỉ:ngày}`: bot hỏi ngày bắt đầu (gõ `24/10`, bot tự thêm năm)
  rồi ngày kết thúc (bấm *Chỉ nghỉ 1 ngày* nếu nghỉ 1 ngày). Kết quả: `24/10/2026` · `24,25,26/10/2026` ·
  qua tháng `30/10 - 02/11/2026`.
- **Ô lựa chọn** viết `{Tên|Lựa chọn 1|Lựa chọn 2}`, ví dụ `{Hình thức nghỉ phép|Không hưởng lương|Nghỉ phép}`:
  bot hiện nút để bấm chọn.
- `to:` / `cc:` là **người nhận mặc định**. Mỗi lần soạn, bot hiện danh sách kèm 3 nút:
  **Giữ nguyên** · **Thêm** (nhập email để thêm vào) · **Xóa hết** (xóa rồi nhập email mới).
  Để trống thì bot hỏi bạn nhập email (CC có nút *Không CC*). Nhiều địa chỉ cách nhau bằng dấu phẩy.
- Ở bước xem trước, nút **Sửa** có cả mục *Gửi tới* và *CC*.
- Tên file (bỏ `.md`) là tên template trong danh sách.
- Lưu file bằng mã hóa **UTF-8** (Notepad mặc định đã là UTF-8).

### Dùng trong bot
1. Gõ `/mail` → bấm chọn template.
2. Trả lời lần lượt từng câu hỏi (`/cancel` để hủy).
3. Xem trước → **Gửi** · **Sửa** (chọn chỗ cần sửa) · **Lưu nháp** (vào Nháp của Gmail) · **Hủy**.

Email **chỉ được gửi khi bạn bấm Gửi**.

## Cấu hình `config.yaml`

Múi giờ, từ khóa mặc định (chỉ nạp lần chạy đầu), tên người gửi email (`mail.from_name`).
Sửa xong chạy `docker compose restart`.

## Cấu trúc code

```
mybot/
├── core/              dùng chung: cấu hình, cơ sở dữ liệu (VIP, từ khóa, cài đặt), luật lọc, giờ nghỉ
├── control/           bot điều khiển: gửi tin, định tuyến lệnh / nút / tin nhắn chữ
├── sources/telegram/  theo dõi tin Telegram, báo tin khớp luật
├── skills/mail/       soạn và gửi email theo template
└── skills/screen/     lệnh /screen (gọi host/screen_agent.py trên Windows)
```

Thêm tính năng mới: tạo thư mục trong `skills/` (hoặc `sources/` nếu là nguồn tin), viết hàm
`setup(cfg, controller)` đăng ký lệnh qua `controller.add_command(...)`, rồi gọi nó trong `app.py`.

## Quyền riêng tư

- Không gửi nội dung tin nhắn ra dịch vụ bên ngoài nào và không lưu tin nhắn: bot chỉ xét luật rồi báo hoặc bỏ qua.
- Tin từ tài khoản hệ thống Telegram (mã đăng nhập) không bao giờ được đọc.
- Bot chỉ trả lời đúng tài khoản Telegram đã đăng nhập.
- Thư mục `data/` và file `.env` đã được loại khỏi git.

## Chuyển lên VPS

Trên VPS (Linux có Docker): `git clone` repo, chép `.env` và cả thư mục `data/` từ máy này lên
(để khỏi đăng nhập lại), rồi `docker compose up -d`. **Tắt bot trên máy này trước** để không chạy hai nơi cùng lúc.

## Phát triển

```bash
pip install -r requirements.txt pytest
```

```bash
python -m pytest tests
```


---

## Bật/tắt màn hình Windows (`/screen`)

Bot chạy trong Docker nên không tự điều khiển được màn hình. Cần chạy thêm một script nhỏ trên Windows
(`host/screen_agent.py`, chỉ dùng thư viện chuẩn của Python, không cần cài gì):

1. Trong `.env` đặt `SCREEN_TOKEN=` một chuỗi bí mật bất kỳ (>= 16 ký tự), rồi build lại bot
   (nếu `docker compose up -d --build` báo lỗi `--allow=fs.read=Dockerfile`, dùng
   `docker build -t mybot-bot .` rồi `docker compose up -d --no-build`).
2. Cho script tự chạy mỗi khi đăng nhập Windows (chạy một lần trong PowerShell, tại thư mục dự án):
   ```powershell
   $py = (Get-Command python).Source -replace 'python\.exe$','pythonw.exe'
   $action = New-ScheduledTaskAction -Execute $py -Argument "`"$PWD\host\screen_agent.py`"" -WorkingDirectory $PWD
   $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
   $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable
   Register-ScheduledTask -TaskName 'mybot-screen-agent' -Action $action -Trigger $trigger -Settings $settings -Force
   Start-ScheduledTask -TaskName 'mybot-screen-agent'
   ```
   Sửa script xong thì dừng tiến trình `pythonw` đang chạy nó rồi `Start-ScheduledTask -TaskName 'mybot-screen-agent'`.
3. Nhắn bot `/screen` để thấy nút Status · On · Off.

| Lệnh | Tác dụng |
|---|---|
| `/screen status` | Màn hình đang bật / tắt, có đang khóa chuột và bàn phím không |
| `/screen off` | Tắt màn hình **và khóa chuột, bàn phím** |
| `/screen on` | Mở khóa và bật màn hình |

Khi khóa: mọi phím, di chuyển, click, cuộn chuột đều bị chặn. Windows vẫn đánh thức màn hình khi có người
chạm chuột/phím (không chặn được), nhưng script tắt lại ngay, nên chỉ thấy chớp sáng. Mở khóa:

- **Ctrl+Shift+N** tại máy (vừa mở khóa vừa bật màn hình), hoặc `/screen on` từ Telegram.
- Ctrl+Alt+Del luôn dùng được (Windows không cho chặn); đăng xuất / khởi động lại thì script dừng, hết khóa.

Lưu ý:
- "Bật" hoạt động bằng cách giả lập chuột nhúc nhích và phím Shift. Nếu Windows đang ở màn hình khóa
  (lock screen), màn hình sáng lên nhưng vẫn phải đăng nhập.
- Script chạy quyền thường: nếu lúc khóa đang chọn một cửa sổ chạy quyền admin (ví dụ Task Manager),
  phím có thể vẫn lọt vào cửa sổ đó.
- Script chỉ nghe ở `127.0.0.1:8765` và chỉ nhận yêu cầu kèm đúng token. Tắt máy thì `/screen` báo
  "không kết nối được" cho tới khi bạn đăng nhập lại.

## UltraViewer (`/ultraview`, viết tắt `/uv`)

Dùng chung script `host/screen_agent.py` và `SCREEN_TOKEN` với `/screen`. Bot mở UltraViewer nếu chưa chạy,
chờ tới khi có ID (tối đa khoảng 45 giây), rồi gửi **ID** và **mật khẩu** (bấm vào để sao chép).
ID và mật khẩu được đọc thẳng từ cửa sổ UltraViewer, kể cả khi đang thu nhỏ xuống khay hệ thống.
UltraViewer cài ở chỗ khác `C:\Program Files (x86)\UltraViewer` thì đặt `ULTRAVIEWER_EXE=` (đường dẫn tới
`UltraViewer_Desktop.exe`) trong `.env` rồi khởi động lại script.

Mật khẩu UltraViewer cho phép điều khiển máy từ xa: tin nhắn chứa nó nằm trong chat với bot, nên giữ kín tài khoản Telegram.
