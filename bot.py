import feedparser
import requests
import json
import asyncio
import os
import sys
from datetime import datetime, timedelta
from openai import OpenAI
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from dotenv import load_dotenv
from vnstock import Vnstock
import xml.etree.ElementTree as ET

load_dotenv()

# ===================== CONFIG =====================
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TOPICS_FILE = "topics.json"
SEND_HOUR_UTC = 1  # 8h sáng VN

BLUECHIP = ["VCB", "BID", "CTG", "TCB", "MBB", "VPB", "HPG", "VHM", "MSN", "VNM"]

RSS_SOURCES = {
    "VnExpress Kinh doanh":   "https://vnexpress.net/rss/kinh-doanh.rss",
    "VnExpress Thế giới":     "https://vnexpress.net/rss/the-gioi.rss",
    "VnExpress Công nghệ":    "https://vnexpress.net/rss/khoa-hoc-cong-nghe.rss",
    "Tuổi Trẻ Kinh tế":      "https://tuoitre.vn/rss/kinh-te.rss",
    "Tuổi Trẻ Thế giới":     "https://tuoitre.vn/rss/the-gioi.rss",
    "CafeF":                  "https://cafef.vn/rss/home.rss",
    "CafeF Tài chính NH":     "https://cafef.vn/tai-chinh-ngan-hang.rss",
    "Tin nhanh CK":           "https://tinnhanhchungkhoan.vn/rss/tin-moi-nhat.rss",
    "Nhịp cầu đầu tư":       "https://nhipcaudautu.vn/feed/",
    "Reuters Business":       "https://feeds.reuters.com/reuters/businessNews",
    "Reuters World":          "https://feeds.reuters.com/Reuters/worldNews",
    "BBC Business":           "http://feeds.bbci.co.uk/news/business/rss.xml",
    "BBC World":              "http://feeds.bbci.co.uk/news/world/rss.xml",
    "Bloomberg Markets":      "https://feeds.bloomberg.com/markets/news.rss",
    "Bloomberg Technology":   "https://feeds.bloomberg.com/technology/news.rss",
    "CNBC Top News":          "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "CNBC Finance":           "https://www.cnbc.com/id/10000664/device/rss/rss.html",
}

# ===================== TOPICS =====================

def load_topics():
    if os.path.exists(TOPICS_FILE):
        with open(TOPICS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_topics(topics):
    with open(TOPICS_FILE, "w", encoding="utf-8") as f:
        json.dump(topics, f, ensure_ascii=False, indent=2)

# ===================== WATCHLIST =====================

def load_watchlist():
    raw = os.getenv("WATCHLIST", "VCB,TCB,MBB,HPG,VHM")
    return [s.strip() for s in raw.split(",") if s.strip()]

def save_watchlist(symbols):
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    with open(env_path, "r") as f:
        lines = f.readlines()
    new_line = f"WATCHLIST={','.join(symbols)}\n"
    updated = False
    for i, line in enumerate(lines):
        if line.startswith("WATCHLIST="):
            lines[i] = new_line
            updated = True
            break
    if not updated:
        lines.append(new_line)
    with open(env_path, "w") as f:
        f.writelines(lines)
    os.environ["WATCHLIST"] = ",".join(symbols)

# ===================== DATA FETCHERS =====================

def get_exchange_rate():
    try:
        url = "https://portal.vietcombank.com.vn/Usercontrols/TVPortal.TyGia/pXML.aspx?b=10"
        r = requests.get(url, timeout=10)
        root = ET.fromstring(r.content)
        for item in root.findall('.//Exrate'):
            if item.get('CurrencyCode') == 'USD':
                return {"buy": item.get('Buy', 'N/A'), "sell": item.get('Sell', 'N/A')}
    except:
        return {"buy": "N/A", "sell": "N/A"}

def get_gold_price():
    try:
        url = "https://sjc.com.vn/GoldPrice/Index/GetGoldPriceList"
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        data = r.json()
        for item in data:
            if "SJC" in str(item.get("kieu", "")):
                return {"buy": item.get("mua", "N/A"), "sell": item.get("ban", "N/A")}
    except:
        return {"buy": "N/A", "sell": "N/A"}

def get_stock_data():
    watchlist = load_watchlist()
    all_symbols = list(set(BLUECHIP + watchlist))
    results = []
    end_date = datetime.today().strftime("%Y-%m-%d")
    start_date = (datetime.today() - timedelta(days=5)).strftime("%Y-%m-%d")

    for symbol in all_symbols:
        try:
            stock = Vnstock().stock(symbol=symbol, source="TCBS")
            df = stock.quote.history(start=start_date, end=end_date, interval="1D")
            if df is None or len(df) < 2:
                continue
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            price = latest["close"]
            change_pct = ((price - prev["close"]) / prev["close"]) * 100
            results.append({
                "symbol": symbol,
                "price": price,
                "change_pct": round(change_pct, 2),
                "volume": latest["volume"],
                "in_watchlist": symbol in watchlist
            })
        except:
            continue

    results.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
    return results

# ===================== NEWS =====================

def fetch_all_articles(max_per_feed=10, days_back=1):
    from email.utils import parsedate_to_datetime
    import time

    cutoff = datetime.now() - timedelta(days=days_back)
    all_articles = []

    for source_name, url in RSS_SOURCES.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_per_feed]:
                # Thử lấy ngày đăng
                pub_date = None
                if hasattr(entry, "published"):
                    try:
                        pub_date = parsedate_to_datetime(entry.published)
                        # Bỏ timezone để so sánh
                        pub_date = pub_date.replace(tzinfo=None)
                    except:
                        pass

                # Nếu không có ngày thì bỏ qua
                if pub_date is None:
                    continue

                # Chỉ lấy bài trong khoảng days_back ngày
                if pub_date < cutoff:
                    continue

                all_articles.append({
                    "source": source_name,
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", "")[:400],
                    "link": entry.get("link", ""),
                    "published": pub_date.strftime("%d/%m %H:%M")
                })
        except:
            continue

    return all_articles

# ===================== DEEPSEEK =====================

def summarize_topic(topic, articles):
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
    if not articles:
        return None

    # Gửi tất cả bài, để AI tự lọc và tóm tắt — xử lý được cả tiếng Anh lẫn tiếng Việt
    content = "\n".join([
        f"[{a['source']}] {a['title']}: {a['summary']} (Link: {a['link']})"
        for a in articles
    ])
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Bạn là trợ lý tóm tắt tin tức chuyên nghiệp bằng tiếng Việt. "
                        "Trả lời ngắn gọn, súc tích, dễ đọc trên Telegram. "
                        "Với mỗi điểm tin quan trọng, thêm link bài gốc ở cuối dòng đó. "
                        "Bài có thể bằng tiếng Anh hoặc tiếng Việt — hãy tóm tắt tất cả bằng tiếng Việt."
                    )
                },
                {
                    "role": "user",
                    "content": (
                        f"Từ danh sách bài báo dưới đây, hãy chọn ra các bài liên quan đến chủ đề '{topic}' "
                        f"(bao gồm cả bài tiếng Anh và tiếng Việt), rồi tóm tắt thành 4-5 điểm chính. "
                        f"Mỗi điểm 1-2 câu bằng tiếng Việt, kèm link bài gốc. "
                        f"Nếu không có bài nào liên quan, hãy nói rõ.\n\n{content}"
                    )
                }
            ],
            max_tokens=800
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Lỗi khi tóm tắt: {str(e)}"

def analyze_market(stock_data, usd_rate, gold_price):
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
    top_movers = stock_data[:5]
    movers_text = "\n".join([
        f"- {s['symbol']}: {s['change_pct']:+.2f}% | Giá: {s['price']:,.0f} | Vol: {s['volume']:,.0f}"
        for s in top_movers
    ])
    watchlist_text = "\n".join([
        f"- {s['symbol']}: {s['change_pct']:+.2f}% | Giá: {s['price']:,.0f}"
        for s in stock_data if s["in_watchlist"]
    ])
    prompt = f"""Hôm nay là {datetime.today().strftime('%d/%m/%Y')}.

TOP CỔ PHIẾU BIẾN ĐỘNG MẠNH:
{movers_text}

WATCHLIST CÁ NHÂN:
{watchlist_text}

Tỷ giá USD/VND: Mua {usd_rate['buy']} | Bán {usd_rate['sell']}
Giá vàng SJC: Mua {gold_price['buy']} | Bán {gold_price['sell']}

Hãy:
1. Nhận xét ngắn xu hướng thị trường hôm nay (2-3 câu)
2. Giải thích lý do biến động TOP 3 mã mạnh nhất
3. Nhận xét watchlist cá nhân
4. Một câu lưu ý ngắn

Trả lời tiếng Việt, ngắn gọn, dùng emoji, format Markdown cho Telegram."""

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1000
    )
    return response.choices[0].message.content

# ===================== SEND MESSAGES =====================

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": chunk,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        })

async def send_daily_news(context: ContextTypes.DEFAULT_TYPE = None):
    """Gửi bản tin tức theo chủ đề"""
    topics = load_topics()
    if not topics:
        send_telegram_message("⚠️ Bạn chưa có chủ đề nào. Nhắn /addtopic <chủ đề> để thêm.")
        return

    now = datetime.now().strftime("%d/%m/%Y")
    send_telegram_message(f"🗞 *Bản tin buổi sáng - {now}*\n\nĐang tổng hợp tin tức...")

    articles = fetch_all_articles()
    for topic in topics:
        summary = summarize_topic(topic, articles)
        if summary:
            send_telegram_message(f"📌 *{topic.upper()}*\n\n{summary}")

    send_telegram_message("✅ *Hết bản tin. Chúc bạn ngày làm việc hiệu quả!*")

async def send_market_briefing():
    """Gửi briefing thị trường"""
    send_telegram_message("⏳ Đang lấy dữ liệu thị trường...")
    usd_rate = get_exchange_rate()
    gold_price = get_gold_price()
    stock_data = get_stock_data()
    analysis = analyze_market(stock_data, usd_rate, gold_price)

    today = datetime.today().strftime("%d/%m/%Y")
    top_lines = []
    for s in stock_data[:5]:
        arrow = "📈" if s["change_pct"] > 0 else "📉"
        top_lines.append(f"{arrow} *{s['symbol']}*: {s['change_pct']:+.2f}%")

    watchlist_lines = []
    for s in stock_data:
        if s["in_watchlist"]:
            dot = "🟢" if s["change_pct"] > 0 else "🔴" if s["change_pct"] < 0 else "⚪"
            watchlist_lines.append(f"{dot} *{s['symbol']}*: {s['price']:,.0f} ({s['change_pct']:+.2f}%)")

    message = f"""🌅 *DAILY BRIEFING — {today}*
━━━━━━━━━━━━━━━━━━
💵 *Tỷ giá USD/VND*
Mua: {usd_rate['buy']} | Bán: {usd_rate['sell']}

🏆 *Giá vàng SJC*
Mua: {gold_price['buy']} | Bán: {gold_price['sell']}

━━━━━━━━━━━━━━━━━━
📊 *TOP BIẾN ĐỘNG*
{chr(10).join(top_lines)}

👀 *WATCHLIST*
{chr(10).join(watchlist_lines)}

━━━━━━━━━━━━━━━━━━
🤖 *PHÂN TÍCH AI*
{analysis}"""

    send_telegram_message(message)

# ===================== TELEGRAM COMMANDS =====================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 Xin chào! Tôi là bot tin tức & thị trường của bạn.\n\n"
        "📰 *Lệnh tin tức:*\n"
        "/addtopic <chủ đề> — Thêm chủ đề theo dõi\n"
        "/removetopic <chủ đề> — Xóa chủ đề\n"
        "/list — Xem danh sách chủ đề\n"
        "/news — Lấy tin ngay bây giờ\n\n"
        "📊 *Lệnh thị trường:*\n"
        "/watchlist — Xem danh sách cổ phiếu\n"
        "/addstock <mã> — Thêm mã cổ phiếu\n"
        "/removestock <mã> — Xóa mã cổ phiếu\n"
        "/briefing — Xem briefing thị trường ngay\n\n"
        "💡 *Ví dụ:*\n"
        "/addtopic tài chính ngân hàng\n"
        "/addstock VPB"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# --- News commands ---
async def cmd_addtopic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Ví dụ: /addtopic tài chính ngân hàng")
        return
    topic = " ".join(context.args).strip().lower()
    topics = load_topics()
    if topic in topics:
        await update.message.reply_text(f"⚠️ Chủ đề *{topic}* đã tồn tại!", parse_mode="Markdown")
        return
    topics.append(topic)
    save_topics(topics)
    await update.message.reply_text(f"✅ Đã thêm chủ đề: *{topic}*", parse_mode="Markdown")

async def cmd_removetopic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Ví dụ: /removetopic tài chính ngân hàng")
        return
    topic = " ".join(context.args).strip().lower()
    topics = load_topics()
    if topic not in topics:
        await update.message.reply_text(f"⚠️ Không tìm thấy chủ đề *{topic}*", parse_mode="Markdown")
        return
    topics.remove(topic)
    save_topics(topics)
    await update.message.reply_text(f"🗑 Đã xóa chủ đề: *{topic}*", parse_mode="Markdown")

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topics = load_topics()
    if not topics:
        await update.message.reply_text("📋 Chưa có chủ đề nào. Dùng /addtopic để thêm!")
        return
    msg = "📋 *Chủ đề đang theo dõi:*\n\n" + "\n".join([f"• {t}" for t in topics])
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Đang tổng hợp tin tức, chờ mình tí...")
    await send_daily_news()

# --- Stock commands ---
async def cmd_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbols = load_watchlist()
    text = "👀 *Watchlist hiện tại:*\n" + "\n".join(f"• {s}" for s in symbols)
    text += "\n\n➕ Thêm: `/addstock VPB`\n➖ Bớt: `/removestock VPB`"
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_addstock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Ví dụ: /addstock VPB", parse_mode="Markdown")
        return
    symbol = context.args[0].upper()
    symbols = load_watchlist()
    if symbol in symbols:
        await update.message.reply_text(f"⚠️ *{symbol}* đã có trong watchlist rồi!", parse_mode="Markdown")
        return
    symbols.append(symbol)
    save_watchlist(symbols)
    await update.message.reply_text(
        f"✅ Đã thêm *{symbol}*\nWatchlist: {', '.join(symbols)}",
        parse_mode="Markdown"
    )

async def cmd_removestock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Ví dụ: /removestock VPB", parse_mode="Markdown")
        return
    symbol = context.args[0].upper()
    symbols = load_watchlist()
    if symbol not in symbols:
        await update.message.reply_text(f"⚠️ *{symbol}* không có trong watchlist!", parse_mode="Markdown")
        return
    symbols.remove(symbol)
    save_watchlist(symbols)
    await update.message.reply_text(
        f"✅ Đã xóa *{symbol}*\nWatchlist: {', '.join(symbols)}",
        parse_mode="Markdown"
    )

async def cmd_briefing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Đang lấy dữ liệu thị trường, chờ mình tí...")
    await send_market_briefing()

# ===================== MAIN =====================

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # News handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("addtopic", cmd_addtopic))
    app.add_handler(CommandHandler("removetopic", cmd_removetopic))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("news", cmd_news))

    # Stock handlers
    app.add_handler(CommandHandler("watchlist", cmd_watchlist))
    app.add_handler(CommandHandler("addstock", cmd_addstock))
    app.add_handler(CommandHandler("removestock", cmd_removestock))
    app.add_handler(CommandHandler("briefing", cmd_briefing))

    # Job tự động 8h sáng VN gửi tin tức
    job_queue = app.job_queue
    job_queue.run_daily(
        send_daily_news,
        time=datetime.strptime(f"{SEND_HOUR_UTC}:00", "%H:%M").time(),
        days=(0, 1, 2, 3, 4, 5, 6)
    )

    print("🤖 Bot đang chạy...")
    app.run_polling()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "briefing":
        # Cron gọi: python daily_briefing.py briefing
        asyncio.run(send_market_briefing())
    elif len(sys.argv) > 1 and sys.argv[1] == "news":
        # Cron gọi: python daily_briefing.py news
        asyncio.run(send_daily_news())
    else:
        main()