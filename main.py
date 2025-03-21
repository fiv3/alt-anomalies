from requests import Session
import os
import functions_framework
from datetime import datetime

def get_cmc_data():
    session = Session()
    session.headers.update({
        'X-CMC_PRO_API_KEY': os.getenv('CMC_API_KEY'),
        'Accept': 'application/json'
    })
    
    try:
        response = session.get('https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest',
            params={'limit': 100, 'convert': 'USDT'})
        data = response.json()
        
        if data['status']['error_code'] == 0:
            return {
                'timestamp': datetime.now().isoformat(),
                'data': [{
                    'symbol': coin['symbol'],
                    'price': coin['quote']['USDT']['price'],
                    'volume_24h': coin['quote']['USDT']['volume_24h'],
                    'percent_change_24h': coin['quote']['USDT']['percent_change_24h'],
                    'market_cap': coin['quote']['USDT']['market_cap']
                } for coin in data['data']]
            }
        return None
    except Exception as e:
        print(f"Error fetching CMC data: {e}")
        return None

@functions_framework.http
def main(request):
    data = get_cmc_data()
    if data:
        return {'success': True, 'data': data}
    return {'success': False, 'error': 'Failed to fetch data'}, 500 