# mybot — trợ lý cá nhân qua Telegram

Hai phần: **theo dõi Telegram** và **soạn email theo template** (xem mục *Soạn email* bên dưới).

Phần theo dõi Telegram đọc tin nhắn trên tài khoản của bạn:

- **Báo ngay** tin quan trọng theo luật: người/nhóm **VIP**, bạn **bị nhắc tên hoặc được trả lời**, tin có **từ khóa**.
- Mọi tin khác được gom lại, **15 phút một lần** (đổi bằng `/interval`) gửi Claude Haiku 5.5 tóm tắt theo đầu mục. Mỗi đầu mục có nhãn ⭐ quan trọng / ▫️ không quan trọng và nút Đúng / Sai nhãn.
- Bấm Sai nhãn → bot **đề xuất một bài học** → bạn bấm **Đồng ý** thì mới ghi. Bài học là ghi chú cho AI (ghi vào `data/lessons.md`) hoặc thêm từ khóa/VIP.
- **Giờ nghỉ** hằng ngày: không tóm tắt 15 phút, đến cuối giờ nghỉ gửi một bản tóm tắt toàn bộ.

Mẹo: tắt tiếng (mute) mọi chat trong Telegram, chỉ để thông báo của bot này.

---

## Cài đặt lần đầu (trên máy Windows có Docker Desktop)

### 1. Chuẩn bị 4 giá trị bí mật

| Giá trị | Lấy ở đâu |
|---|---|
| `TG_API_ID`, `TG_API_HASH` | Đăng nhập https://my.telegram.org → **API development tools** → tạo app (tên gì cũng được) |
| `TG_BOT_TOKEN` | Nhắn **@BotFather** trên Telegram → `/newbot` → đặt tên → nhận token |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com → **API Keys** → tạo key (cần nạp ít tiền) |

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
| `/vip list` · `/vip add <tên, @username hoặc id>` · `/vip remove <số>` | Tin từ người/nhóm VIP → báo ngay |
| `/keyword list` · `/keyword add <từ>` · `/keyword remove <số>` (viết tắt `/kw`) | Tin có từ khóa → báo ngay |
| `/ignore list` · `/ignore add <tên chat>` · `/ignore remove <số>` | Bỏ qua hẳn chat: không đọc, không tóm tắt, không gửi AI |
| `/interval` · `/interval 30` | Xem / đổi chu kỳ tóm tắt (5–720 phút, mặc định 15) |
| `/schedule` · `/schedule 17:30 08:00 hold` · `/schedule off` | Giờ nghỉ hằng ngày. `notify`: tin quan trọng vẫn báo ngay; `hold`: giữ tới cuối giờ nghỉ |
| `/lessons` · `/lessons remove <số>` | Xem / xóa bài học |
| `/status` | Số tin hôm nay, chi phí AI ước tính |
| `/help` | Danh sách lệnh |

`/vip add` và `/ignore add` tìm theo tên trong danh sách chat của bạn; nếu nhiều kết quả, bot hiện nút để chọn.

## File bài học `data/lessons.md`

Mỗi dòng bắt đầu bằng `- ` là một bài học AI dùng khi gán nhãn. Bạn mở file bằng Notepad để sửa/xóa
trực tiếp; thay đổi có hiệu lực từ bản tóm tắt kế tiếp. Bài học dạng *thêm từ khóa / VIP* không nằm
trong file này mà vào danh sách `/keyword`, `/vip`.

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

Múi giờ, chu kỳ tóm tắt (mặc định 15 phút), số ngày giữ lịch sử, đoạn mô tả về bạn (`about_me`) để AI
hiểu điều gì quan trọng, model AI, tên người gửi email (`mail.from_name`). Sửa xong chạy `docker compose restart`.

## Cấu trúc code

```
mybot/
├── core/              dùng chung: cấu hình, cơ sở dữ liệu, AI, luật lọc, giờ nghỉ, bài học
├── control/           bot điều khiển: gửi tin, định tuyến lệnh / nút / tin nhắn chữ
├── sources/telegram/  theo dõi và tóm tắt tin Telegram
└── skills/mail/       soạn và gửi email theo template
```

Thêm tính năng mới: tạo thư mục trong `skills/` (hoặc `sources/` nếu là nguồn tin), viết hàm
`setup(cfg, controller)` đăng ký lệnh qua `controller.add_command(...)`, rồi gọi nó trong `app.py`.

## Quyền riêng tư

- Nội dung mọi chat không nằm trong `/ignore` được gửi lên Anthropic để tóm tắt.
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
