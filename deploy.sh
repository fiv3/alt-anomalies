#!/bin/bash

# Список регионов для тестирования
REGIONS=(
    "us-central1"
    "us-east1"
    "us-east4"
    "us-west1"
    "europe-west1"
    "europe-west2"
    "asia-east1"
    "asia-northeast1"
    "asia-southeast1"
)

# Создаем функцию в каждом регионе
for region in "${REGIONS[@]}"; do
    echo "Deploying to ${region}..."
    gcloud functions deploy "test-binance-${region}" \
        --runtime python39 \
        --trigger-http \
        --allow-unauthenticated \
        --region ${region} \
        --entry-point test_binance_access \
        --memory 128MB \
        --timeout 30s
done

# Создаем файл с URLs всех функций
echo "Generating URLs file..."
echo "# Binance API Test Functions" > function_urls.md
echo "Generated at: $(date)" >> function_urls.md
echo "" >> function_urls.md

for region in "${REGIONS[@]}"; do
    url=$(gcloud functions describe "test-binance-${region}" --region ${region} --format='value(httpsTrigger.url)')
    echo "- ${region}: ${url}" >> function_urls.md
done