## Cryptanalytics for Predicting Alternative Anomalies
### Hosted in Google Cloud Platform (GCP)

This guide provides step-by-step instructions to deploy **altcoin-screener** on **Google Cloud Run**.

### **1️⃣ Enable Required GCP Services**

```sh
gcloud services enable run.googleapis.com
gcloud projects create altcoin-screener --set-as-default
git clone https://github.com/fiv3/alt-anomalies.git

cd alt-anomalies

gcloud auth configure-docker
gcloud config set project altcoin-screener
gcloud config get-value project
gcloud services enable cloudbuild.googleapis.com artifactregistry.googleapis.com

gcloud projects add-iam-policy-binding $(gcloud config get-value project) \
    --member=serviceAccount:$(gcloud projects describe $(gcloud config get-value project) --format="value(projectNumber)")@cloudbuild.gserviceaccount.com \
    --role=roles/storage.admin

gcloud projects add-iam-policy-binding altcoin-screener \
    --member=user:varimathrasfiv3@gmail.com \
    --role=roles/owner

gcloud builds submit --tag gcr.io/$(gcloud config get-value project)/altcoin-screener .

gcloud run deploy altcoin-screener \
    --image gcr.io/altcoin-screener/altcoin-screener \
    --platform managed \
    --region asia-east1 \
    --allow-unauthenticated

gcloud run deploy altcoin-screener \
  --image gcr.io/$(gcloud config get-value project)/altcoin-screener \
  --region asia-east1 \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars "BINANCE_API_KEY=LuYr36BAvOZ3UxGlO00wWGpE1gwFvhjd1zMqEMXvfXy4qOkOtIh20jjDLDolVe7E" \
  --set-env-vars "BINANCE_SECRET_KEY=XIgYJx1fz5RWRH6JvTcQeQzMP4RmfMaVU78GeZDFvzsEuAxZMzZ7KV8FpDCmM0vT" \
  --set-env-vars "TELEGRAM_BOT_TOKEN=7279536567:AAEBxZUuAvPmGSU2soqhXXFOr7WU7kVmG5I" \
  --set-env-vars "SERVICE_URL=https://altcoin-screener-256702831943.asia-east1.run.app" \
  --set-env-vars "PORT=8080" \
  --timeout=900s

gcloud run services update altcoin-screener-bot \
  --set-env-vars="SERVICE_URL=https://altcoin-screener-256702831943.asia-east1.run.app/"

curl "https://api.telegram.org/bot7279536567:AAEBxZUuAvPmGSU2soqhXXFOr7WU7kVmG5I/setWebhook?url=YOUR_SERVICE_URL/webhook"


gcloud run services describe altcoin-screener --region us-central1
gcloud run services list
```

### Ensure that env.yaml is correctly formatted before deploying.

### If issues arise with permissions, verify IAM roles using gcloud projects get-iam-policy altcoin-screener.

### Logs can be accessed via Cloud Run Logs: gcloud logs read --limit 50.

### 🚀 Your altcoin-screener cryptanalytics tool is now running on Google Cloud Run!

gcloud builds submit --tag gcr.io/$(gcloud config get-value project)/altcoin-screener .
gcloud run deploy altcoin-screener --image gcr.io/$(gcloud config get-value project)/altcoin-screener --region us-central1 --platform managed --allow-unauthenticated --set-env-vars "BINANCE_API_KEY=your_key" --set-env-vars "BINANCE_SECRET_KEY=your_key" --set-env-vars "TELEGRAM_BOT_TOKEN=your_key" --timeout=300s
