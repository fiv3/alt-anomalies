# Use Python 3.10 as base image
FROM python:3.10

# Set working directory
WORKDIR /app

# Copy application files
COPY . .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Explicitly set environment variables (THIS IS THE FIX)
ARG BINANCE_API_KEY
ARG BINANCE_SECRET_KEY
ARG TELEGRAM_BOT_TOKEN

ENV BINANCE_API_KEY=$BINANCE_API_KEY
ENV BINANCE_SECRET_KEY=$BINANCE_SECRET_KEY
ENV TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN

# Run the application
CMD ["python", "alt-anomalies.py"]
