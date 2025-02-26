#!/bin/sh
echo "🔍 Checking environment variables..."
echo "BINANCE_API_KEY: $BINANCE_API_KEY"
echo "BINANCE_SECRET_KEY: $BINANCE_SECRET_KEY"
echo "TELEGRAM_BOT_TOKEN: $TELEGRAM_BOT_TOKEN"

exec "$@"
