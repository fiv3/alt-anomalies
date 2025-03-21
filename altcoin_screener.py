import os, ccxt, logging, asyncio, time, logging.handlers, signal, sys, pandas
from requests import Session
from requests.exceptions import RequestException

from aiogram import Bot, Dispatcher, BaseMiddleware
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web
from dotenv import load_dotenv
from functools import lru_cache
from datetime import datetime, timedelta
from prometheus_client import Counter, Histogram, start_http_server

logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            'bot.log',
            maxBytes=10485760,  # 10MB
            backupCount=5
        )
    ]
)

class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, limit=1):
        super().__init__()
        self.rate_limit = limit
        self.users = {}
        self.lock = asyncio.Lock()  # Add lock for thread safety

    async def __call__(self, handler, event, data):
        user_id = event.from_user.id if event.from_user else None
        if not user_id:
            return await handler(event, data)
            
        async with self.lock:
            if user_id in self.users:
                await asyncio.sleep(self.rate_limit)
            self.users[user_id] = True
            
        try:
            return await handler(event, data)
        finally:
            async with self.lock:
                if user_id in self.users:
                    del self.users[user_id]

logger = logging.getLogger(__name__)

load_dotenv()
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
print(f"Token value: {TELEGRAM_BOT_TOKEN}")  # Добавьте эту строку для отладки
PORT = int(os.getenv("PORT", 8080))

if not TELEGRAM_BOT_TOKEN:
    logger.error("❌ TELEGRAM_BOT_TOKEN is required!")
    sys.exit(1)

if not BINANCE_API_KEY or not BINANCE_SECRET_KEY:
    logger.warning("⚠️ Binance API keys are missing - some features will be limited")

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}{WEBHOOK_PATH}"

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
    # Инициализация CoinMarketCap клиента
    cmc_session = Session()
    cmc_session.headers.update({
        'X-CMC_PRO_API_KEY': os.getenv('CMC_API_KEY'),
        'Accept': 'application/json'
    })
    
    def get_futures_symbols():
        try:
            # Получаем топ 100 криптовалют
            response = cmc_session.get('https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest', 
                params={'limit': 100, 'convert': 'USDT'})
            data = response.json()
            
            if data['status']['error_code'] == 0:
                return [f"{coin['symbol']}/USDT" for coin in data['data']]
            return []
        except Exception as e:
            logger.error(f"Error fetching CMC symbols: {e}")
            return []

    async def fetch_market_data(symbol, timeframe, semaphore):
        async with semaphore:
            try:
                # Получаем актуальные данные по монете
                symbol_clean = symbol.split('/')[0]
                response = cmc_session.get(
                    'https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest',
                    params={'symbol': symbol_clean, 'convert': 'USDT'}
                )
                data = response.json()
                
                if data['status']['error_code'] == 0:
                    quote = data['data'][symbol_clean]['quote']['USDT']
                    return {
                        'symbol': symbol,
                        'price': quote['price'],
                        'volume_24h': quote['volume_24h'],
                        'percent_change_1h': quote['percent_change_1h'],
                        'percent_change_24h': quote['percent_change_24h'],
                        'market_cap': quote['market_cap']
                    }
                return None
            except Exception as e:
                logger.error(f"Error fetching CMC data for {symbol}: {e}")
                return None

    logger.info("✅ CoinMarketCap API initialized")
except Exception as e:
    logger.error(f"Failed to initialize CoinMarketCap API: {e}")

API_REQUESTS = Counter('api_requests_total', 'Total API requests made')
PROCESSING_TIME = Histogram('processing_time_seconds', 'Time spent processing market data')
ERROR_COUNTER = Counter('error_total', 'Total number of errors')

@lru_cache(maxsize=100)
def get_cached_symbols():
    return get_futures_symbols()

SYMBOLS = get_futures_symbols()

if exchange:
    for market, data in exchange.markets.items():
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
    try:
        # Setup health check endpoint first
        async def health_check(request):
            try:
                # Простая проверка, что сервис работает
                return web.Response(text="healthy", status=200)
            except Exception as e:
                logger.error(f"Health check error: {e}")
                return web.Response(text="unhealthy", status=500)
        
        app.router.add_get("/health", health_check)
        
        # Start web server
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", PORT)
        await site.start()
        
        logger.info(f"Web server started on port {PORT}")
        
        # Инициализация бота и вебхука
        try:
            webhook_url = f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}{WEBHOOK_PATH}"
            await bot.delete_webhook(drop_pending_updates=True)
            await bot.set_webhook(webhook_url)
            logger.info(f"Webhook set to {webhook_url}")
        except Exception as e:
            logger.error(f"Webhook setup error: {e}")
            # Продолжаем работу, так как это не критично
        
        # Start Prometheus metrics server
        try:
            start_http_server(8000)
            logger.info("Prometheus metrics server started")
        except Exception as e:
            logger.error(f"Prometheus server error: {e}")
            # Продолжаем работу без метрик
        
        logger.info("Bot startup complete")
        
        # Держим приложение запущенным
        await asyncio.Event().wait()
        
    except Exception as e:
        logger.error(f"Startup error: {e}")
        raise

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

# === Monitor market ===
async def monitor_market():
    while True:
        try:
            start_time = time.time()
            tasks = []
            semaphore = asyncio.Semaphore(10)  # Limit concurrent API calls
            
            for chat_id, settings in chat_settings.items():
                timeframe = settings.get("timeframe", "5m")
                symbols = get_cached_symbols()  # Use cached symbols
                
                for symbol in symbols:
                    task = asyncio.create_task(fetch_market_data(symbol, timeframe, semaphore))
                    tasks.append(task)
                    
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    ERROR_COUNTER.inc()
                    logger.error(f"Error in market monitoring: {result}")
                    
            PROCESSING_TIME.observe(time.time() - start_time)
            
            # Dynamic sleep based on processing time
            processing_time = time.time() - start_time
            sleep_time = max(1, 60 - processing_time)  # Ensure at least 1 second sleep
            await asyncio.sleep(sleep_time)
            
        except Exception as e:
            ERROR_COUNTER.inc()
            logger.error(f"Critical error in market monitoring: {e}")
            await asyncio.sleep(5)  # Wait before retrying

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
        if exchange:
            for market, data in exchange.markets.items():
                print(f"{market}: {data}")
            exchange.fetch_ticker("BTC/USDT")
            logger.info("✅ Binance connection test successful")
    except Exception as e:
        logger.error(f"❌ Error during startup: {e}")

def handle_shutdown(signum, frame):
    logger.info("Received shutdown signal")
    if monitoring_task:
        monitoring_task.cancel()
    loop = asyncio.get_event_loop()
    loop.stop()
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT, handle_shutdown)

if __name__ == "__main__":
    try:
        asyncio.run(start())
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
