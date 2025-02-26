import os
import ccxt
import pandas as pd
import logging
import asyncio
import threading
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command
from dotenv import load_dotenv
from flask import Flask

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
PORT = int(os.getenv("PORT", 8080))  # Default port for Cloud Run

if not BINANCE_API_KEY or not BINANCE_SECRET_KEY or not TELEGRAM_BOT_TOKEN:
    raise ValueError("❌ ERROR: Missing API keys or bot token! Check your environment variables.")
else:
    print(f"✅ Environment variables loaded successfully! Server will run on port {PORT}")

# === Initialize Flask Web Server ===
app = Flask(__name__)

@app.route("/")
def home():
    return "Altcoin Screener Bot is running!"

# Start Flask in a separate thread
# Run Flask in a separate thread
def run_server():
    app.run(host="0.0.0.0", port=8080)  # Ensure it listens on 8080

if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()  # Start Flask server
    asyncio.run(main())  # Run Telegram bot

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
            market.replace("/", "").split(":")[0]
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

# === Define timeframes and volume thresholds ===
TIMEFRAMES = {
    '5m': {'minutes': 5, 'volume_threshold': 500},
    '15m': {'minutes': 15, 'volume_threshold': 500},
    '1h': {'minutes': 60, 'volume_threshold': 100},
    '4h': {'minutes': 240, 'volume_threshold': 100},
    '1d': {'minutes': 1440, 'volume_threshold': 25},
    '1w': {'minutes': 10080, 'volume_threshold': 25}
}

# === Store chat settings ===
chat_settings = {}  # {chat_id: {"timeframe": "5m"}}

# === Command: /start - Register chat ID ===
@dp.message(Command("start"))
async def start_command(message: Message):
    chat_id = message.chat.id
    chat_settings[chat_id] = {"timeframe": "5m"}  # Default timeframe
    await message.answer("👋 Altcoin Screener Bot is running! Use /set_timeframe to configure.")

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

        # Fetch Open Interest (OI)
        oi_data = binance.fapiPublicGetOpenInterest({'symbol': symbol})
        open_interest = float(oi_data['openInterest'])

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "price": float(latest['close']),
            "prev_price": float(previous['close']),
            "volume": float(latest['volume']),
            "prev_volume": float(previous['volume']),
            "volatility": (float(latest['high']) - float(latest['low'])) / float(latest['low']) * 100,
            "prev_volatility": (float(previous['high']) - float(previous['low'])) / float(previous['low']) * 100,
            "open_interest": open_interest,
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
    timeframe = data['timeframe']
    volume_threshold = TIMEFRAMES[timeframe]['volume_threshold']

    price_change = (data['price'] - data['prev_price']) / data['prev_price'] * 100
    volume_change = max((data['volume'] - data['prev_volume']) / data['prev_volume'] * 100, 0)
    volatility_change = (data['volatility'] - data['prev_volatility']) / max(data['prev_volatility'], 1) * 100
    oi_change = (data['open_interest'] - data['open_interest']) / max(data['open_interest'], 1) * 100

    oi_direction = "🟢🔺" if oi_change > 0 else "🔴🔻"
    price_direction = "🟢🔼" if price_change > 0 else "🔴🔽"

    # Apply timeframe-specific volume threshold
    if abs(price_change) > 2 and volume_change > volume_threshold and abs(volatility_change) > 50 and abs(oi_change) > 50:
        message = (
            f"📢 {data['symbol']} ({data['timeframe']})\n"
            f"💰 Price: {data['price']:.6f} {price_direction} ({price_change:.2f}%)\n"
            f"📊 Volume: {data['volume']:.2f} ({volume_change:.2f}%)\n"
            f"⚡ Volatility: {volatility_change:.2f}%\n"
            f"📉 Open Interest: {oi_direction} {oi_change:.2f}%"
        )
        await bot.send_message(chat_id=data["chat_id"], text=message)

# === Start the bot and Flask server ===
if __name__ == "__main__":
    threading.Thread(target=run_server).start()  # Start Flask server
    asyncio.run(main())  # Start Telegram bot
