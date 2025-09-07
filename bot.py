import os
import asyncio
import logging
import sqlite3
import requests
from aiogram import Bot, Dispatcher, executor, types
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from playwright.async_api import async_playwright

# Load ENV
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
EARNKARO_EMAIL = os.getenv("EARNKARO_EMAIL")
EARNKARO_PASSWORD = os.getenv("EARNKARO_PASSWORD")
POST_INTERVAL_MIN = int(os.getenv("POST_INTERVAL_MIN", 30))
MAX_POSTS_PER_CYCLE = int(os.getenv("MAX_POSTS_PER_CYCLE", 10))
SOURCES = os.getenv("SOURCES", "").split(",")
LINK_MODE = os.getenv("LINK_MODE", "noop")
OWNER_IDS = [int(x) for x in os.getenv("OWNER_IDS", "").split(",") if x]

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

logging.basicConfig(level=logging.INFO)

# ---------------- DB SETUP ----------------
conn = sqlite3.connect("sources.db")
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS sources (url TEXT UNIQUE)")
conn.commit()
for src in SOURCES:
    if src.strip():
        cursor.execute("INSERT OR IGNORE INTO sources (url) VALUES (?)", (src.strip(),))
conn.commit()

# ---------------- PROFIT LINK ----------------
async def generate_profit_link(url: str) -> str:
    if LINK_MODE == "noop":
        return url
    elif LINK_MODE == "playwright":
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto("https://earnkaro.com")
                await page.click("text=Login")
                await page.fill('input[name="email"]', EARNKARO_EMAIL)
                await page.fill('input[name="password"]', EARNKARO_PASSWORD)
                await page.click("button:has-text('Login')")
                await page.wait_for_timeout(5000)
                await page.goto("https://earnkaro.com/profit-link")
                await page.fill("input[name='link']", url)
                await page.click("button:has-text('Make Profit Link')")
                await page.wait_for_selector("textarea")
                profit_link = await page.input_value("textarea")
                await browser.close()
                return profit_link
        except Exception as e:
            logging.error(f"Profit link error: {e}")
            return url
    return url

# ---------------- SCRAPER ----------------
def scrape_deals(url):
    deals = []
    try:
        html = requests.get(url, timeout=10).text
        soup = BeautifulSoup(html, "html.parser")
        for item in soup.select(".deal-card")[:MAX_POSTS_PER_CYCLE]:
            title = item.get_text(strip=True)
            link = item.find("a")["href"] if item.find("a") else url
            deals.append({"title": title, "link": link})
    except Exception as e:
        logging.error(f"Scrape error: {e}")
    return deals

# ---------------- POSTING ----------------
async def post_deals():
    cursor.execute("SELECT url FROM sources")
    srcs = [r[0] for r in cursor.fetchall()]
    for src in srcs:
        deals = scrape_deals(src)
        for deal in deals:
            plink = await generate_profit_link(deal["link"])
            text = f"🔥 {deal['title']}\n👉 {plink}"
            try:
                await bot.send_message(CHANNEL_ID, text)
                await asyncio.sleep(2)
            except Exception as e:
                logging.error(f"Post error: {e}")

# ---------------- SCHEDULER ----------------
async def scheduler():
    while True:
        logging.info("Posting deals...")
        await post_deals()
        await asyncio.sleep(POST_INTERVAL_MIN * 60)

# ---------------- COMMANDS ----------------
@dp.message_handler(commands=["ping"])
async def cmd_ping(message: types.Message):
    await message.reply("🏓 Pong")

@dp.message_handler(commands=["addsource"])
async def cmd_addsource(message: types.Message):
    if str(message.from_user.id) not in [str(x) for x in OWNER_IDS]:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("Usage: /addsource <url>")
        return
    url = parts[1]
    cursor.execute("INSERT OR IGNORE INTO sources (url) VALUES (?)", (url,))
    conn.commit()
    await message.reply(f"✅ Added source: {url}")

@dp.message_handler(commands=["postnow"])
async def cmd_postnow(message: types.Message):
    if str(message.from_user.id) not in [str(x) for x in OWNER_IDS]:
        return
    await post_deals()
    await message.reply("✅ Posted deals now!")

# ---------------- MAIN ----------------
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(scheduler())
    executor.start_polling(dp, skip_updates=True)
      
