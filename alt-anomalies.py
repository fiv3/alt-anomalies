import os
import ccxt
import pandas as pd
import logging
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command
from dotenv import load_dotenv
from collections import deque
import time

# === Set up logging ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === Fix Windows Async Event Loop ===
import sys
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# === Load environment variables ===
load_dotenv()
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not BINANCE_API_KEY or not BINANCE_SECRET_KEY or not TELEGRAM_BOT_TOKEN:
    raise ValueError("❌ ERROR: Missing API keys or bot token! Check your .env file.")

# === Initialize Telegram Bot ===
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# === Connect to Binance API ===
binance = ccxt.binance({
    'apiKey': BINANCE_API_KEY,
    'secret': BINANCE_SECRET_KEY,
    'options': {'defaultType': 'future'}
})

# === Fetch active Binance Futures trading pairs ===
def get_futures_symbols():
    try:
        logger.info("📡 Fetching available Binance Futures trading pairs...")
        markets = binance.load_markets()
        futures_symbols = [
            market.replace("/", "").split(":")[0]  # Format symbols correctly
            for market in markets.keys()
            if "USDT" in market and markets[market].get("contract") and markets[market].get("linear") and markets[market]["active"]
        ]
        logger.info(f"✅ Found {len(futures_symbols)} active Binance Futures pairs.")
        return futures_symbols
    except Exception as e:
        logger.error(f"❌ Binance API Error: {e}")
        return []

# === Load available symbols ===
SYMBOLS = get_futures_symbols()
if not SYMBOLS:
    logger.warning("⚠️ No active Binance Futures symbols found. Exiting...")
    exit(1)

# === Define timeframes ===
TIMEFRAMES = {'5m': 5, '15m': 15, '1h': 60, '4h': 240, '1d': 1440, '1w': 10080}

# === Store chat settings ===
chat_settings = {}  # {chat_id: {"timeframe": "5m"}}

# === Command: /start - Register chat ID ===
@dp.message(Command("start"))
async def start_command(message: Message):
    chat_id = message.chat.id
    chat_settings[chat_id] = {"timeframe": "5m"}  # Default timeframe
    await message.answer("👋 Binance Futures Bot is running! Use /set_timeframe to configure.")

# === Command: /set_timeframe <timeframe> ===
@dp.message(Command("set_timeframe"))
async def set_timeframe(message: Message):
    chat_id = message.chat.id
    args = message.text.split()
    if len(args) < 2 or args[1] not in TIMEFRAMES:
        await message.answer("⚠️ Usage: /set_timeframe <5m|15m|1h|4h|1d|1w>")
        return
    chat_settings[chat_id] = {"timeframe": args[1]}
    await message.answer(f"✅ Timeframe set to {args[1]} for this group.")

# === Fetch market data ===
async def fetch_market_data(symbol, timeframe, chat_id):
    try:
        ohlcv = binance.fetch_ohlcv(symbol, timeframe, limit=2)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        latest = df.iloc[-1]
        previous = df.iloc[-2]
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "price": float(latest['close']),
            "prev_price": float(previous['close']),
            "volume": float(latest['volume']),
            "prev_volume": float(previous['volume']),
            "chat_id": chat_id
        }
    except Exception as e:
        logger.error(f"⚠️ Binance API Error for {symbol}: {e}")
        return None

# === Monitor market ===
async def monitor_market():
    while True:
        tasks = []
        for chat_id, settings in chat_settings.items():
            timeframe = settings.get("timeframe", "5m")
            for symbol in SYMBOLS:
                tasks.append(fetch_market_data(symbol, timeframe, chat_id))
        results = await asyncio.gather(*tasks)
        for data in results:
            if data:
                await process_market_data(data)
        await asyncio.sleep(30)

# === Process and send alerts ===
async def process_market_data(data):
    price_change = (data['price'] - data['prev_price']) / data['prev_price'] * 100
    volume_change = max((data['volume'] - data['prev_volume']) / data['prev_volume'] * 100, 0)
    if abs(price_change) > 2 and volume_change > 25:
        message = (
            f"📢 {data['symbol']} ({data['timeframe']})\n"
            f"💰 Price: {data['price']:.2f} ({'🔼' if price_change > 0 else '🔽'} {price_change:.2f}%)"
        )
        await bot.send_message(chat_id=data["chat_id"], text=message)

# === Start the bot ===
async def main():
    asyncio.create_task(monitor_market())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
