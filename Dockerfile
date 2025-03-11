FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY . .

# Expose Cloud Run port
ENV PORT=8080
EXPOSE 8080

# Set environment variables for production
ENV PYTHONUNBUFFERED=1

# Start the application
CMD ["python", "altcoin_screener.py"]
