FROM python:3.10-slim

WORKDIR /app

COPY . .
RUN pip install --no-cache-dir -r requirements.txt

# Expose Cloud Run port
ENV PORT=8080
EXPOSE 8080

CMD ["python", "altcoin_screener.py"]