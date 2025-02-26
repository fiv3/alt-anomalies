# Use Python 3.10 as base image
FROM python:3.10

WORKDIR /app

COPY . .
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

RUN pip install --no-cache-dir -r requirements.txt
ENV BINANCE_API_KEY=${BINANCE_API_KEY}
ENV BINANCE_SECRET_KEY=${BINANCE_SECRET_KEY}
ENV TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}

# Run entrypoint first, then the app
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "alt-anomalies.py"]
