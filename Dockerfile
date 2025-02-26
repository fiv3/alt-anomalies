# Use official Python image
FROM python:3.10

# Set working directory inside the container
WORKDIR /app

# Copy project files into the container
COPY . .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8080

# Pass environment variables explicitly
ENV BINANCE_API_KEY=$BINANCE_API_KEY
ENV BINANCE_SECRET_KEY=$BINANCE_SECRET_KEY
ENV TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN

# Run the bot
CMD ["python", "alt-anomalies.py"]
