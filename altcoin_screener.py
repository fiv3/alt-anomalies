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
from aiogram import BaseMiddleware

class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, limit=1):
        super().__init__()
        self.rate_limit = limit
        self.users = {}

    async def __call__(self, handler, event, data):
        user_id = event.from_user.id if event.from_user else None
        if not user_id:
            return await handler(event, data)
        if user_id in self.users:
            await asyncio.sleep(self.rate_limit)
        self.users[user_id] = True
        await asyncio.sleep(self.rate_limit)
        if user_id in self.users:
            del self.users[user_id]
        return await handler(event, data)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SERVICE_URL = os.getenv("SERVICE_URL")
PORT = int(os.getenv("PORT", 8080))

if not BINANCE_API_KEY or not BINANCE_SECRET_KEY or not TELEGRAM_BOT_TOKEN or not SERVICE_URL:
    logger.warning("⚠️ Missing API keys, bot token, or service URL!")

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{SERVICE_URL}{WEBHOOK_PATH}"

bot = Bot(token=TELEGRAM_BOT_TOKEN, timeout=30)
dp = Dispatcher(storage=MemoryStorage())

app = web.Application()
webhook_requests = SimpleRequestHandler(dispatcher=dp, bot=bot)
webhook_requests.register(app, path=WEBHOOK_PATH)

async def home(request):
    return web.Response(text="Altcoin Screener Bot is running!")
app.router.add_get("/", home)

dp.message.middleware(ThrottlingMiddleware(limit=1))

try:
    binance = ccxt.binanceusdm({
        'apiKey': BINANCE_API_KEY,
        'secret': BINANCE_SECRET_KEY,
        'enableRateLimit': True,
    })
    binance.load_markets(reload=True)
    logger.info(f"✅ Reloaded markets: {len(binance.markets)}")
except Exception as e:
    logger.error(f"Failed to initialize Binance USDM API: {e}")
    binance = None

def get_futures_symbols():
    if not binance:
        return []
    try:
        return [
            market for market, data in binance.markets.items()
            if data.get("active") and data.get("type") == "swap" and ":USDT" in market
        ]
    except Exception as e:
        logger.error(f"Error fetching futures symbols: {e}")
        return []

SYMBOLS = get_futures_symbols()

if binance:
    for market, data in binance.markets.items():
        print(f"{market}: {data}")

TIMEFRAMES = {
    '5m': {'minutes': 5, 'volume_threshold': 500},
    '15m': {'minutes': 15, 'volume_threshold': 500},
    '1h': {'minutes': 60, 'volume_threshold': 100},
    '4h': {'minutes': 240, 'volume_threshold': 100},
    '1d': {'minutes': 1440, 'volume_threshold': 25},
    '1w': {'minutes': 10080, 'volume_threshold': 25}
}

chat_settings = {}
monitoring_lock = asyncio.Lock()
monitoring_started = False
monitoring_task = None

async def start_monitoring():
    global monitoring_started, monitoring_task
    async with monitoring_lock:
        if not monitoring_started and chat_settings:
            monitoring_started = True
            monitoring_task = asyncio.create_task(monitor_market())
            logger.info("🔍 Market monitoring started")

# === Command: /symbols - Show active futures pairs ===
@dp.message(Command("symbols"))
async def symbols_command(message: Message):
    if SYMBOLS:
        symbols_list = "\n".join(SYMBOLS)
        await message.answer(f"Active Futures Pairs:\n{symbols_list}")
    else:
        await message.answer("No active futures pairs found.")

@dp.message(Command("refresh"))
async def refresh_symbols(message: Message):
    global SYMBOLS
    SYMBOLS = get_futures_symbols()
    await message.answer(f"🔄 Updated! Found {len(SYMBOLS)} pairs.")

@dp.message(Command("start"))
async def start_command(message: Message):
    chat_settings[message.chat.id] = {"timeframe": "5m"}
    await message.answer("👋 Bot started. Use /set_timeframe to configure.")
    await start_monitoring()

async def start():
    await bot.set_webhook(WEBHOOK_URL)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

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
    await message.answer(help_text, parse_mode="Markdown")

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
    await message.answer(status_text, parse_mode="Markdown")

# === Fetch market data ===
async def fetch_market_data(symbol, timeframe, semaphore):
    async with semaphore:
        try:
            if not binance:
                return None
            # Use the full market symbol directly, e.g., "BTC/USDT:USDT" or similar
            ohlcv = binance.fetch_ohlcv(symbol, timeframe, limit=2)
            if not ohlcv or len(ohlcv) < 2:
                return None
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            latest = df.iloc[-1]
            previous = df.iloc[-2]
            try:
                oi_data = binance.fetch_open_interest(symbol)
                open_interest = float(oi_data.get("openInterest", 0)) if oi_data else 0
                previous_oi = open_interest * 0.95  # Dummy previous OI for demo
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
        try:
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
        except Exception as e:
            logger.error(f"Error in monitor_market: {e}")
            await asyncio.sleep(60)

# === Process and send alerts ===
async def process_market_data(data, chat_id):
    try:
        timeframe = data['timeframe']
        volume_threshold = TIMEFRAMES[timeframe]['volume_threshold']
        price_change = (data['price'] - data['prev_price']) / data['prev_price'] * 100
        volume_change = 0
        if data['prev_volume'] > 0:
            volume_change = max((data['volume'] - data['prev_volume']) / data['prev_volume'] * 100, 0)
        volatility_change = 0
        if data['prev_volatility'] > 0:
            volatility_change = (data['volatility'] - data['prev_volatility']) / max(data['prev_volatility'], 1) * 100
        oi_change = 0
        if 'prev_open_interest' in data and data['prev_open_interest'] > 0:
            oi_change = (data['open_interest'] - data['prev_open_interest']) / data['prev_open_interest'] * 100
        price_direction = "📈" if price_change > 0 else "📉"
        oi_direction = "📈" if oi_change > 0 else "📉"
        if abs(price_change) > 2 and volume_change > volume_threshold and abs(volatility_change) > 50 and abs(oi_change) > 5:
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
    except Exception as e:
        logger.error(f"Error processing market data: {e}")

async def on_startup():
    try:
        await bot.set_webhook(WEBHOOK_URL)
        logger.info(f"✅ Webhook set to {WEBHOOK_URL}")
        if binance:
            for market, data in binance.markets.items():
                print(f"{market}: {data}")
            binance.fetch_ticker("BTC/USDT")
            logger.info("✅ Binance connection test successful")
    except Exception as e:
        logger.error(f"❌ Error during startup: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(start())
    except RuntimeError:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(start())

