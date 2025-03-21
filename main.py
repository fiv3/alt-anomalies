import functions_framework
from requests import Session
import os
import logging
import asyncio
from aiogram import Bot, types
from datetime import datetime, timedelta
from functools import wraps

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize bot
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

# Store user settings in memory
chat_settings = {}

def async_wrapper(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapped

async def get_market_data(symbol, timeframe):
    """Fetch market data from CoinMarketCap"""
    try:
        session = Session()
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

@functions_framework.http
@async_wrapper
async def main(request):
    """Cloud Function entry point"""
    try:
        if request.method == 'POST':
            try:
                update = types.Update(**request.get_json())
                
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
                        await bot.send_message(chat_id, help_text)
                        
                    elif message_text.startswith('/set_timeframe '):
                        timeframe = message_text.split()[1]
                        if timeframe in TIMEFRAMES:
                            chat_settings[chat_id] = {'timeframe': timeframe}
                            volume_threshold = THRESHOLDS['base_volume_change'] * TIMEFRAMES[timeframe]['volume_multiplier']
                            await bot.send_message(
                                chat_id, 
                                f"✅ Timeframe set to {timeframe}\nVolume threshold: {volume_threshold}%"
                            )
                        else:
                            await bot.send_message(chat_id, "❌ Invalid timeframe")
                    
                    elif message_text == '/status':
                        if chat_id in chat_settings:
                            tf = chat_settings[chat_id]['timeframe']
                            volume_threshold = THRESHOLDS['base_volume_change'] * TIMEFRAMES[tf]['volume_multiplier']
                            await bot.send_message(
                                chat_id,
                                f"Current timeframe: {tf}\nVolume threshold: {volume_threshold}%"
                            )
                        else:
                            await bot.send_message(chat_id, "Not configured. Use /set_timeframe first")
            
            except Exception as e:
                logger.error(f"Error processing telegram update: {e}")
                
        elif request.method == 'GET':
            # Process scheduled check
            symbols = ['BTC', 'ETH', 'BNB', 'SOL', 'AVAX', 'MATIC']
            for chat_id, settings in chat_settings.items():
                timeframe = settings.get('timeframe')
                if not timeframe:
                    continue
                    
                for symbol in symbols:
                    current, previous = await get_market_data(symbol, timeframe)
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
                            await bot.send_message(chat_id, alert)
                            
        return ('OK', 200)
    except Exception as e:
        logger.error(f"Error in main: {e}")
        return ('Error', 500)
