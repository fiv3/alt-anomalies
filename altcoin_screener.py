import os
import ccxt
import logging
import asyncio
import pandas as pd
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from dotenv import load_dotenv
from aiohttp import web
from aiogram.fsm.storage.memory import MemoryStorage

# === Set up logging ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === Load environment variables ===
load_dotenv()
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SERVICE_URL = os.getenv("SERVICE_URL")
PORT = int(os.getenv("PORT", 8080))

if not BINANCE_API_KEY or not BINANCE_SECRET_KEY or not TELEGRAM_BOT_TOKEN or not SERVICE_URL:
    raise ValueError("❌ ERROR: Missing API keys, bot token, or service URL!")

# === Set up Telegram Webhook ===
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{SERVICE_URL}{WEBHOOK_PATH}"

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# === Aiohttp Webhook Setup ===
app = web.Application()
webhook_requests = SimpleRequestHandler(dispatcher=dp, bot=bot)
webhook_requests.register(app, path=WEBHOOK_PATH)

async def home(request):
    return web.Response(text="Altcoin Screener Bot is running!")

app.router.add_get("/", home)

# === Initialize Binance API ===
binance = ccxt.binance({
    'apiKey': BINANCE_API_KEY,
    'secret': BINANCE_SECRET_KEY,
    'options': {'defaultType': 'future'}
})

binance.load_markets()

# === Fetch active Binance Futures trading pairs ===
def get_futures_symbols():
    try:
        futures_symbols = [
            market.replace("/", "").split(":")[0]
            for market in binance.markets.keys()
            if "USDT" in market and binance.markets[market].get("contract") and binance.markets[market].get("linear") and binance.markets[market]["active"]
        ]
        logger.info(f"✅ Found {len(futures_symbols)} active Binance Futures pairs.")
        return futures_symbols
    except Exception as e:
        logger.error(f"❌ Binance API Error: {e}")
        return []

SYMBOLS = get_futures_symbols()
if not SYMBOLS:
    logger.warning("⚠️ No active Binance Futures symbols found.")
    SYMBOLS = []

# === Define timeframes and volume thresholds ===
TIMEFRAMES = {
    '5m': {'minutes': 5, 'volume_threshold': 500},  # x20
    '15m': {'minutes': 15, 'volume_threshold': 500},  # x20
    '1h': {'minutes': 60, 'volume_threshold': 100},  # x4
    '4h': {'minutes': 240, 'volume_threshold': 100},  # x4
    '1d': {'minutes': 1440, 'volume_threshold': 25},  # оставить как есть
    '1w': {'minutes': 10080, 'volume_threshold': 25}  # оставить как есть
}

# === Store chat settings ===
chat_settings = {}  # {chat_id: {"timeframe": "5m"}}
monitoring_lock = asyncio.Lock()
monitoring_started = False
monitoring_task = None

async def start_monitoring():
    global monitoring_started
    global monitoring_task
    async with monitoring_lock:
        if not monitoring_started and chat_settings:
            monitoring_started = True
            monitoring_task = asyncio.create_task(monitor_market())
            logger.info("🔍 Market monitoring started")

# === Command: /start - Register chat ID ===
@dp.message(Command("start"))
async def start_command(message: Message):
    chat_id = message.chat.id
    if chat_id not in chat_settings:
        chat_settings[chat_id] = {"timeframe": "5m"}  
    await message.answer("👋 Altcoin Screener Bot is running! Use /set_timeframe to configure.\n\nAvailable commands:\n/set_timeframe - Set monitoring timeframe\n/help - Show help\n/status - Show current status")
    await start_monitoring()

@dp.message(Command("set_timeframe"))
async def set_timeframe(message: Message):
    chat_id = message.chat.id
    args = message.text.split()
    if len(args) < 2 or args[1] not in TIMEFRAMES:
        await message.answer("⚠️ Usage: /set_timeframe <5m|15m|1h|4h|1d|1w>")
        return
    
    if chat_id not in chat_settings:
        chat_settings[chat_id] = {}
        
    chat_settings[chat_id]["timeframe"] = args[1]
    await message.answer(f"✅ Timeframe set to {args[1]} for this chat.")
    await start_monitoring()

@dp.message(Command("help"))
async def help_command(message: Message):
    help_text = (
        "🤖 *Altcoin Screener Bot* 🤖\n\n"
        "This bot monitors Binance Futures markets and alerts on significant market movements.\n\n"
        "*Commands:*\n"
        "/start - Start the bot\n"
        "/set_timeframe <tf> - Set timeframe (5m, 15m, 1h, 4h, 1d, 1w)\n"
        "/status - Check current status\n"
        "/help - Show this help message\n\n"
        "*Alert Criteria:*\n"
        "- Price change > 2%\n"
        "- Volume change above threshold (varies by timeframe)\n"
        "- Volatility change > 50%\n"
        "- Open Interest change > 50%"
    )
    await message.answer(help_text)

@dp.message(Command("status"))
async def status_command(message: Message):
    chat_id = message.chat.id
    if chat_id not in chat_settings:
        await message.answer("⚠️ Bot is not configured for this chat. Use /start first.")
        return
    
    tf = chat_settings[chat_id].get("timeframe", "not set")
    active = "Yes" if monitoring_started else "No"
    symbols_count = len(SYMBOLS)
    
    status_text = (
        f"📊 *Bot Status*\n\n"
        f"Active: {active}\n"
        f"Current timeframe: {tf}\n"
        f"Monitoring symbols: {symbols_count}\n"
        f"Volume threshold: {TIMEFRAMES.get(tf, {}).get('volume_threshold', 'N/A')}%"
    )
    await message.answer(status_text)

# === Fetch market data ===
async def fetch_market_data(symbol, timeframe, semaphore):
    async with semaphore:
        try:
            ohlcv = binance.fetch_ohlcv(symbol, timeframe, limit=2)
            if not ohlcv or len(ohlcv) < 2:
                return None

            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            latest = df.iloc[-1]
            previous = df.iloc[-2]

            try:
                oi_data = binance.fetch_open_interest(symbol)
                open_interest = float(oi_data.get("openInterest", 0)) if oi_data else 0
                
                # Get previous OI (simplified approach - in real scenario, store this in a database)
                previous_oi = open_interest * 0.95  # Dummy value, just for demonstration
            except Exception:
                open_interest = 0
                previous_oi = 0

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
                "prev_open_interest": previous_oi
            }
        except Exception as e:
            logger.error(f"⚠️ Binance API Error for {symbol}: {e}")
            return None

# === Monitor market ===
async def monitor_market():
    semaphore = asyncio.Semaphore(10)
    while True:
        if not chat_settings:
            await asyncio.sleep(30)
            continue

        for chat_id, settings in chat_settings.items():
            timeframe = settings.get("timeframe", "5m")
            
            tasks = [fetch_market_data(symbol, timeframe, semaphore) for symbol in SYMBOLS]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            valid_results = []
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Error fetching data: {result}")
                elif result is not None:
                    valid_results.append(result)
            
            for data in valid_results:
                await process_market_data(data, chat_id)

        await asyncio.sleep(30)

# === Process and send alerts ===
async def process_market_data(data, chat_id):
    timeframe = data['timeframe']
    volume_threshold = TIMEFRAMES[timeframe]['volume_threshold']

    price_change = (data['price'] - data['prev_price']) / data['prev_price'] * 100
    volume_change = max((data['volume'] - data['prev_volume']) / data['prev_volume'] * 100, 0)
    volatility_change = (data['volatility'] - data['prev_volatility']) / max(data['prev_volatility'], 1) * 100
    
    # Calculate OI change
    if 'prev_open_interest' in data and data['prev_open_interest'] > 0:
        oi_change = (data['open_interest'] - data['prev_open_interest']) / data['prev_open_interest'] * 100
    else:
        oi_change = 0
    
    # Get price and OI direction
    price_direction = "📈" if price_change > 0 else "📉"
    oi_direction = "📈" if oi_change > 0 else "📉"

    # Check alert conditions
    if abs(price_change) > 2 and volume_change > volume_threshold and abs(volatility_change) > 50 and abs(oi_change) > 50:
        message = (
            f"📢 {data['symbol']} ({data['timeframe']})\n"
            f"💰 Price: {data['price']:.6f} {price_direction} ({price_change:.2f}%)\n"
            f"📊 Volume: {data['volume']:.2f} ({volume_change:.2f}%)\n"
            f"⚡ Volatility: {volatility_change:.2f}%\n"
            f"📉 Open Interest: {oi_direction} {oi_change:.2f}%"
        )
        try:
            await bot.send_message(chat_id=chat_id, text=message)
            logger.info(f"✅ Alert sent for {data['symbol']} in timeframe {data['timeframe']}")
        except Exception as e:
            logger.error(f"❌ Error sending message: {e}")

async def on_startup():
    await bot.set_webhook(WEBHOOK_URL)
    logger.info(f"✅ Webhook set to {WEBHOOK_URL}")
    
    # Check Binance connection
    try:
        binance.fetch_ticker("BTC/USDT:USDT")
        logger.info("✅ Binance connection test successful")
    except Exception as e:
        logger.error(f"❌ Binance connection test failed: {e}")

async def main():
    await on_startup()
    # Don't start monitoring here, it will be started by the /start command
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"✅ Web server started on port {PORT}")
    
    # Endless task to keep the event loop running
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
