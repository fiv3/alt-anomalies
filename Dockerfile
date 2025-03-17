FROM python:3.10-slim AS builder

WORKDIR /app
COPY requirements.txt .

# Install build dependencies and compile requirements
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc python3-dev && \
    pip install --user --no-cache-dir -r requirements.txt && \
    rm -rf /var/lib/apt/lists/*

FROM python:3.10-slim
WORKDIR /app

# Copy only necessary files
COPY --from=builder /root/.local /root/.local
COPY altcoin_screener.py .

# Set PATH and environment variables
ENV PATH=/root/.local/bin:$PATH \
    PORT=8080 \
    PYTHONUNBUFFERED=1 \
    TZ=UTC \
    SERVICE_URL=https://altcoin-screener-altcoin-screener.run.app/

# Cloud Run will provide the port as an env variable
EXPOSE ${PORT}

CMD exec python altcoin_screener.py
