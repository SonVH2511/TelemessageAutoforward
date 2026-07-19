### Auto forward tele message

Tự động forward tất cả tin nhắn Telegram vào một group đích, mỗi nguồn tạo topic riêng.

### Features

- Auto-forward tin nhắn vào forum topic theo tên group/channel nguồn
- Theo dõi edit & delete tin nhắn, gửi thông báo tương ứng
- Blacklist theo tên, username, chat ID hoặc folder Telegram
- FloodWait retry, single instance protection
- Message map phân theo ngày, tự cleanup khi vượt ngưỡng

### Usage

1. Cài Python 3.10+ và thư viện: `pip install telethon`
2. Copy `config.example.json` thành `config.json` và điền `api_id`, `api_hash`
3. Tạo group Telegram, bật `create topic`, điền tên group vào `recv_group` trong `config.json`
4. Chạy lần đầu: `python Telethon.py` (nhập số điện thoại + OTP)
5. Sau đó chạy ngầm: sửa đường dẫn trong `auto_run.bat` và đặt vào Startup

### Config

Tất cả cấu hình nằm trong `config.json`:

```json
{
    "api_id": 12345678,
    "api_hash": "your_api_hash_here",
    "session_name": "my_session",
    "recv_group": "recv_autoforwarding",
    "max_message_map_entries": 150000,
    "blacklist": [],
    "blacklist_folders": [],
    "folder_refresh_interval": 3600
}
```

| Field | Mô tả |
|---|---|
| `api_id` / `api_hash` | Lấy từ https://my.telegram.org |
| `recv_group` | Tên hoặc ID group đích (cần bật forum/topic) |
| `blacklist` | Danh sách tên, username hoặc chat ID cần bỏ qua |
| `blacklist_folders` | Tên folder Telegram cần bỏ qua toàn bộ |
| `folder_refresh_interval` | Chu kỳ refresh folder blacklist (giây) |

### Startup

Sửa đường dẫn Python trong `auto_run.bat`, rồi đặt shortcut vào:
```
C:\Users\<user>\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup
```
