# News Bot Telegram

Bot tự động tổng hợp tin tức và theo dõi thị trường chứng khoán, gửi thẳng vào Telegram.

## Tính năng

- Tự động gửi bản tin tức buổi sáng theo chủ đề bạn chọn
- Theo dõi giá cổ phiếu, tỷ giá USD/VND, giá vàng SJC
- Phân tích thị trường bằng AI (DeepSeek)
- Gửi briefing thị trường theo lệnh hoặc tự động hàng ngày

---

## Lệnh Telegram

### Tin tức

| Lệnh | Mô tả | Ví dụ |
|---|---|---|
| `/start` | Xem hướng dẫn sử dụng bot | `/start` |
| `/addtopic` | Thêm chủ đề tin tức muốn theo dõi | `/addtopic tài chính ngân hàng` |
| `/removetopic` | Xóa chủ đề | `/removetopic tài chính ngân hàng` |
| `/list` | Xem danh sách chủ đề đang theo dõi | `/list` |
| `/news` | Lấy bản tin ngay lập tức | `/news` |

### Thị trường chứng khoán

| Lệnh | Mô tả | Ví dụ |
|---|---|---|
| `/watchlist` | Xem danh sách cổ phiếu đang theo dõi | `/watchlist` |
| `/addstock` | Thêm mã cổ phiếu vào watchlist | `/addstock VPB` |
| `/removestock` | Xóa mã cổ phiếu khỏi watchlist | `/removestock VPB` |
| `/briefing` | Xem briefing thị trường ngay lập tức | `/briefing` |

---

## Lịch tự động

- **8h sáng hàng ngày** — Bot tự gửi bản tin tức theo các chủ đề đã cài đặt

---

## Cấu hình (.env)

Tạo file `.env` từ `.env.example` và điền thông tin thật:

```
DEEPSEEK_API_KEY=    # API key từ platform.deepseek.com
TELEGRAM_TOKEN=      # Token bot từ @BotFather
CHAT_ID=             # ID chat Telegram nhận tin
WATCHLIST=VCB,TCB,MBB,HPG,VHM   # Danh sách mã cổ phiếu mặc định
```

---

## Cài đặt & Chạy (trên VPS)

```bash
# Clone repo
git clone https://github.com/ngocnguyen128/news-bot.git
cd news-bot

# Tạo môi trường ảo và cài thư viện
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Tạo file .env
cp .env.example .env
nano .env

# Chạy bot
python bot.py
```

### Chạy tự động với systemd

```bash
sudo systemctl start news-bot
sudo systemctl stop news-bot
sudo systemctl restart news-bot
sudo systemctl status news-bot
```

---

## Cập nhật code

Push code lên GitHub, VPS sẽ tự động pull và restart bot trong vòng 5 phút.

Hoặc cập nhật thủ công ngay:

```bash
cd ~/news-bot
git pull origin main
systemctl restart news-bot
```
