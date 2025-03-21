import functions_framework
from requests import Session
import os
import json
from datetime import datetime
import asyncio
from aiogram import Bot, types

# Инициализация бота
bot = Bot(token=os.getenv('TELEGRAM_BOT_TOKEN'))

def get_cmc_data():
    session = Session()
    session.headers.update({
        'X-CMC_PRO_API_KEY': os.getenv('CMC_API_KEY'),
        'Accept': 'application/json'
    })
    
    try:
        response = session.get(
            'https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest',
            params={'limit': 100, 'convert': 'USDT'}
        )
        data = response.json()
        
        if data['status']['error_code'] == 0:
            return [{
                'symbol': coin['symbol'],
                'price': coin['quote']['USDT']['price'],
                'volume_24h': coin['quote']['USDT']['volume_24h'],
                'percent_change_24h': coin['quote']['USDT']['percent_change_24h']
            } for coin in data['data']]
        return None
    except Exception as e:
        print(f"Error fetching CMC data: {e}")
        return None

@functions_framework.http
async def main(request):
    """HTTP Cloud Function."""
    try:
        # Обработка вебхука от Telegram
        if request.method == 'POST':
            update = types.Update(**request.get_json())
            
            if update.message and update.message.text:
                chat_id = update.message.chat.id
                
                if update.message.text == '/start':
                    await bot.send_message(chat_id, "👋 Бот запущен! Используйте /price для получения цен.")
                    return ('OK', 200)
                
                elif update.message.text == '/price':
                    data = get_cmc_data()
                    if data:
                        message = "📊 Топ криптовалюты:\n\n"
                        for coin in data[:10]:  # Топ 10
                            message += f"{coin['symbol']}: ${coin['price']:.2f} ({coin['percent_change_24h']:.1f}%)\n"
                        await bot.send_message(chat_id, message)
                    else:
                        await bot.send_message(chat_id, "❌ Ошибка получения данных")
                    return ('OK', 200)
        
        # Проверка работоспособности
        return ('OK', 200)
    
    except Exception as e:
        print(f"Error: {e}")
        return ('Error', 500) 