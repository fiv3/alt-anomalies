import requests
import json
import time
from datetime import datetime

def test_binance_access(request):
    # Добавляем CORS headers для возможности вызова из браузера
    if request.method == 'OPTIONS':
        headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Max-Age': '3600'
        }
        return ('', 204, headers)

    headers = {
        'Access-Control-Allow-Origin': '*',
        'Content-Type': 'application/json',
    }

    test_results = {
        'timestamp': datetime.utcnow().isoformat(),
        'endpoints': {}
    }

    # Тестируем основные эндпоинты
    endpoints = {
        'ping': 'https://api.binance.com/api/v3/ping',
        'time': 'https://api.binance.com/api/v3/time',
        'system_status': 'https://api.binance.com/sapi/v1/system/status',
        'futures_ping': 'https://fapi.binance.com/fapi/v1/ping'
    }

    for name, url in endpoints.items():
        start_time = time.time()
        try:
            response = requests.get(url, timeout=10)
            elapsed = time.time() - start_time
            
            test_results['endpoints'][name] = {
                'status_code': response.status_code,
                'response': response.text[:200],  # First 200 chars
                'latency': round(elapsed * 1000, 2),  # Convert to ms
                'success': response.status_code == 200
            }
        except Exception as e:
            test_results['endpoints'][name] = {
                'error': str(e),
                'success': False
            }

    return (json.dumps(test_results, indent=2), 200, headers)