import ccxt

exchange = ccxt.binanceusdm({
    'apiKey': 'LuYr36BAvOZ3UxGlO00wWGpE1gwFvhjd1zMqEMXvfXy4qOkOtIh20jjDLDolVe7E',
    'secret': 'XIgYJx1fz5RWRH6JvTcQeQzMP4RmfMaVU78GeZDFvzsEuAxZMzZ7KV8FpDCmM0vT',
    'enableRateLimit': True,
})

try:
    markets = exchange.load_markets()
    print(f"Loaded markets: {len(markets)}")
    for k, m in list(markets.items())[:5]:
        print(k, m)
except Exception as e:
    print(f"Error: {e}")
