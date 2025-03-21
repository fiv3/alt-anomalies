import functions_framework
from requests import Session
import os
import logging
from aiogram import Bot, types
from datetime import datetime, timedelta
import asyncio
from flask import jsonify
import aiohttp

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize bot with persistent session
bot = Bot(token=os.getenv('TELEGRAM_BOT_TOKEN'))

# Timeframe settings with volume multipliers
TIMEFRAMES = {
    '5m': {'minutes': 5, 'volume_multiplier': 20},
    '15m': {'minutes': 15, 'volume_multiplier': 20},
    '1h': {'minutes': 60, 'volume_multiplier': 4},
    '4h': {'minutes': 240, 'volume_multiplier': 4},
    '1d': {'minutes': 1440, 'volume_multiplier': 1},
    '1w': {'minutes': 10080, 'volume_multiplier': 1}
}

# Alert thresholds
THRESHOLDS = {
    'price_change': 2.0,    # 2% price change
    'base_volume_change': 25.0,  # 25% base volume change
    'open_interest_change': 50.0,  # 50% open interest change
    'volatility_change': 50.0  # 50% volatility change
}

# Store user settings in memory (consider using Firestore for persistence)
chat_settings = {}

def get_market_data(symbol, timeframe):
    """Fetch market data from CoinMarketCap"""
    try:
        with Session() as session:  # Using context manager for better resource cleanup
            session.headers.update({
                'X-CMC_PRO_API_KEY': os.getenv('CMC_API_KEY'),
                'Accept': 'application/json'
            })

            # Get current data
            current_response = session.get(
                'https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest',
                params={'symbol': symbol, 'convert': 'USDT'}
            )
            
            if current_response.status_code != 200:
                logger.error(f"Error fetching current data: {current_response.text}")
                return None, None

            current_data = current_response.json()
            current_quote = current_data['data'][symbol]['quote']['USDT']
            
            # Calculate time for previous period
            now = datetime.now()
            tf_minutes = TIMEFRAMES[timeframe]['minutes']
            previous_time = now - timedelta(minutes=tf_minutes)
            
            # Get historical data
            historical_response = session.get(
                'https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/historical',
                params={
                    'symbol': symbol,
                    'time_start': previous_time.isoformat(),
                    'convert': 'USDT'
                }
            )
            
            if historical_response.status_code != 200:
                logger.error(f"Error fetching historical data: {historical_response.text}")
                return None, None

            historical_data = historical_response.json()
            previous_quote = historical_data['data'][symbol]['quotes'][0]['quote']['USDT']

            # Clear responses to free memory
            del current_response
            del historical_response
            del current_data
            del historical_data

            return {
                'price': current_quote['price'],
                'volume': current_quote['volume_24h'],
                'open_interest': current_quote.get('open_interest', 0),
                'volatility': (current_quote['high_24h'] - current_quote['low_24h']) / current_quote['low_24h'] * 100
            }, {
                'price': previous_quote['price'],
                'volume': previous_quote['volume_24h'],
                'open_interest': previous_quote.get('open_interest', 0),
                'volatility': (previous_quote['high_24h'] - previous_quote['low_24h']) / previous_quote['low_24h'] * 100
            }

    except Exception as e:
        logger.error(f"Error in get_market_data: {e}")
        return None, None

async def send_telegram_message(chat_id, text, retry_count=3):
    """Helper function to send telegram messages with retries"""
    for attempt in range(retry_count):
        try:
            async with bot:  # Properly initialize bot session
                await asyncio.sleep(0.1)  # Small delay to prevent rate limiting
                await bot.send_message(chat_id, text)
                return True
        except Exception as e:
            if attempt == retry_count - 1:  # Last attempt
                logger.error(f"Failed to send message after {retry_count} attempts: {e}")
                return False
            await asyncio.sleep(1)  # Wait before retry

async def process_telegram_update(update_data):
    """Process Telegram update"""
    try:
        update = types.Update.model_validate(update_data)
        
        if update.message and update.message.text:
            chat_id = update.message.chat.id
            message_text = update.message.text.lower()
            
            if message_text == '/start':
                help_text = """
🤖 Market Scanner Bot

Commands:
/set_timeframe <tf> - Set monitoring timeframe
Available timeframes: 5m, 15m, 1h, 4h, 1d, 1w

Alert Triggers:
- Price change > 2%
- Volume change > 25-500% (based on timeframe)
- Open Interest change > 50%
- Volatility change > 50%
"""
                await send_telegram_message(chat_id, help_text)
                
            elif message_text.startswith('/set_timeframe'):
                # Извлекаем таймфрейм, убирая возможные пробелы
                parts = message_text.replace('/set_timeframe', '').strip()
                timeframe = parts if parts else None
                
                if timeframe and timeframe in TIMEFRAMES:
                    chat_settings[chat_id] = {'timeframe': timeframe}
                    volume_threshold = THRESHOLDS['base_volume_change'] * TIMEFRAMES[timeframe]['volume_multiplier']
                    await send_telegram_message(
                        chat_id, 
                        f"✅ Timeframe set to {timeframe}\nVolume threshold: {volume_threshold}%"
                    )
                else:
                    available_timeframes = ', '.join(TIMEFRAMES.keys())
                    await send_telegram_message(
                        chat_id, 
                        f"❌ Invalid timeframe. Available options: {available_timeframes}"
                    )
            
            elif message_text == '/status':
                if chat_id in chat_settings:
                    tf = chat_settings[chat_id]['timeframe']
                    volume_threshold = THRESHOLDS['base_volume_change'] * TIMEFRAMES[tf]['volume_multiplier']
                    await send_telegram_message(
                        chat_id,
                        f"Current timeframe: {tf}\nVolume threshold: {volume_threshold}%"
                    )
                else:
                    await send_telegram_message(chat_id, "Not configured. Use /set_timeframe first")
    
    except Exception as e:
        logger.error(f"Error processing telegram update: {e}")
        logger.exception("Full traceback:")  # Добавляем полный traceback для отладки

async def process_market_check():
    """Process market data check"""
    try:
        symbols = ['BTC', 'ETH', 'BNB', 'SOL', 'AVAX', 'MATIC']
        for chat_id, settings in chat_settings.items():
            timeframe = settings.get('timeframe')
            if not timeframe:
                continue
                
            for symbol in symbols:
                await asyncio.sleep(0.1)  # Add small delay between checks
                current, previous = get_market_data(symbol, timeframe)
                if current and previous:
                    # Calculate changes
                    price_change = ((current['price'] - previous['price']) / previous['price']) * 100
                    volume_change = ((current['volume'] - previous['volume']) / previous['volume']) * 100
                    oi_change = ((current['open_interest'] - previous['open_interest']) / previous['open_interest']) * 100
                    volatility_change = ((current['volatility'] - previous['volatility']) / previous['volatility']) * 100
                    
                    # Check thresholds
                    volume_threshold = THRESHOLDS['base_volume_change'] * TIMEFRAMES[timeframe]['volume_multiplier']
                    if (abs(price_change) > THRESHOLDS['price_change'] and 
                        abs(volume_change) > volume_threshold and
                        abs(oi_change) > THRESHOLDS['open_interest_change'] and
                        abs(volatility_change) > THRESHOLDS['volatility_change']):
                        
                        alert = f"""
🚨 Alert for {symbol} ({timeframe})
💰 Price: ${current['price']:.2f} ({price_change:+.2f}%)
📊 Volume: ${current['volume']:,.0f} ({volume_change:+.2f}%)
📈 Open Interest: ${current['open_interest']:,.0f} ({oi_change:+.2f}%)
⚡ Volatility: {current['volatility']:.2f}% ({volatility_change:+.2f}%)
"""
                        await send_telegram_message(chat_id, alert)
    
    except Exception as e:
        logger.error(f"Error in process_market_check: {e}")

@functions_framework.http
def main(request):
    """HTTP Function entry point"""
    async def async_wrapper():
        try:
            if request.method == "POST":
                await process_telegram_update(request.get_json())
            elif request.method == "GET":
                await process_market_check()
            return jsonify({"status": "ok"})
        except Exception as e:
            logger.error(f"Error in async_wrapper: {e}")
            return jsonify({"error": str(e)}), 500

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(async_wrapper())
    finally:
        loop.close()
