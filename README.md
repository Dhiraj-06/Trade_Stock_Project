# NIFTY 50 ML Trading Model Service (Fyers Live Integration + Scheduled Self-Retraining)

A production-grade Machine Learning service for predicting next-day return percentages (Model B Regressor) and direction (Model C Classifier) across NIFTY 50 constituents. Features zero-leakage walk-forward validation, scale-invariant feature engineering, Fyers API v3 integration, FastAPI serving, and metric-gated automated self-retraining.

---

## 🚀 Key Features

1. **Scale-Invariant Feature Engineering**: Computes ~46 normalized technical indicators, ratios, and bounded oscillators (grouped strictly by `Ticker`) to ensure zero price-scale leakage and cross-ticker generalization.
2. **Shared Training & Live Logic**: Single source of truth (`features/build_features.py`) guarantees identical feature calculation for both offline historical training and live Fyers inference.
3. **Walk-Forward Validation**: 5-fold `TimeSeriesSplit` cross-validation guarantees time-ordered evaluation without future-to-past data leakage.
4. **Fyers API v3 Integration**: Live quote fetching and historical candle buffer management (`data/live/`) with built-in mock fallback for dry-run/offline testing.
5. **Automated Self-Retraining & Champion Promotion Gate**: Periodically retrains models on accumulated data, compares walk-forward metrics against current champion metadata, and **only promotes** new candidates if performance equals or improves upon the champion.
6. **FastAPI Inference Server**: Serving endpoints (`/predict/{ticker}`, `/predict`, `/health`, `/retrain`) and an embedded minimal test dashboard (`/`).

---

## 🔑 Where to Add Fyers API Keys

Create a `.env` file inside the `ml_service/` directory (or export environment variables directly in your terminal/deployment environment):

```bash
# ml_service/.env
FYERS_APP_ID=YOUR_APP_ID-100       # e.g., XXYYZZ1234-100
FYERS_SECRET_KEY=YOUR_SECRET_KEY
FYERS_ACCESS_TOKEN=YOUR_ACCESS_TOKEN
FYERS_PIN=YOUR_4_DIGIT_PIN         # Optional for automated OAuth flow
FYERS_TOTP_KEY=YOUR_TOTP_SECRET    # Optional for automated OAuth flow
```

*Note: If these environment variables are absent, the system automatically runs in **Mock/Dry-Run mode** using synthetic live quotes so you can test the API and pipeline offline.*

---

## 🛠️ Installation & Setup

1. **Activate Python Virtual Environment & Install Dependencies**:
   ```bash
   cd ml_service
   pip install -r requirements.txt
   ```

2. **Run Unit & Integration Tests**:
   ```bash
   python -m pytest tests/test_features.py tests/test_pipeline.py -v
   ```

---

## 📊 Running Model Training

Run the one-shot training script to ingest `data/raw/NIFTY50_Preprocessed.csv`, compute scale-invariant features, evaluate 5-fold walk-forward metrics, and save initial champion models to `models/registry/`:

```bash
python scripts/run_training.py
```

### Baseline Performance Metrics (NIFTY 50 Dataset — 41,494 rows, 50 tickers)

| Model | Metric | Walk-Forward 5-Fold Score |
|---|---|---|
| **Model B (Regressor)** | Avg MAE | `1.05436%` |
| **Model B (Regressor)** | Avg RMSE | `1.44808%` |
| **Model B (Regressor)** | Directional Accuracy | `52.76%` |
| **Model C (Classifier)** | Avg Accuracy | `53.56%` |
| **Model C (Classifier)** | Avg Precision | `54.21%` |
| **Model C (Classifier)** | Avg Recall | `58.56%` |
| **Model C (Classifier)** | Avg F1-Score | `0.5604` |
| **Model C (Classifier)** | Avg ROC-AUC | `0.5417` |

---

## 🌐 Running the FastAPI Inference Service

Start the live FastAPI uvicorn server:

```bash
uvicorn api.app:app --host 0.0.0.0 --port 8000 --reload
```

- **Live Test Dashboard**: Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) in your browser.
- **Health & Champion Status**: `GET http://127.0.0.1:8000/health`
- **Single Ticker Prediction**: `GET http://127.0.0.1:8000/predict/WIPRO`
- **Batch Predictions**: `GET http://127.0.0.1:8000/predict?tickers=WIPRO,RELIANCE,TCS,ADANIENT`
- **Manual Retrain Trigger**: `POST http://127.0.0.1:8000/retrain`

---

## 🔄 Automated Retraining & Model Promotion

The service retrains itself unattended via `retraining/retrain_job.py`:

1. **Trigger**: Scheduled via `retraining/scheduler.py` (APScheduler running at 6:00 PM weekdays after Indian market close) or triggered via `POST /retrain`.
2. **Data Ingestion**: Combines historical dataset with accumulated Fyers live buffers (`data/live/*.parquet`).
3. **Validation & Promotion Gate**: Candidate regressor and classifier are trained with 5-fold walk-forward CV. Candidate metrics are compared against champion `metadata.json`.
4. **Promotion**: Candidate is promoted to active champion **only** if metrics meet or exceed the champion by `min_score_improvement` (0.5%). Otherwise, candidate is saved to registry and candidate is rejected.
5. **Rollback**: To rollback a bad model version:
   ```python
   from models.model_utils import rollback
   rollback("return_regressor")  # Rolls back to previous champion version
   ```

---

## 🐳 Deployment Guide

### Option 1: Docker Container Deployment (Recommended)

1. **Build Docker Image**:
   ```bash
   docker build -t nifty50-ml-service .
   ```

2. **Run Container with Environment File**:
   ```bash
   docker run -d \
     --name ml_service \
     -p 8000:8000 \
     --env-file .env \
     -v $(pwd)/models/registry:/app/models/registry \
     -v $(pwd)/data/live:/app/data/live \
     nifty50-ml-service
   ```

### Option 2: Linux Cloud VM (AWS EC2 / DigitalOcean / Render)

1. Provision Linux VM (Ubuntu 22.04 LTS).
2. Clone repository & install python 3.10.
3. Configure `.env` with Fyers credentials.
4. Run `scripts/run_training.py` once to populate registry champions.
5. Set up systemd service or Docker compose to keep Uvicorn running persistently:
   ```ini
   [Unit]
   Description=NIFTY 50 ML Service
   After=network.target

   [Service]
   User=ubuntu
   WorkingDirectory=/home/ubuntu/ml_service
   ExecStart=/home/ubuntu/ml_service/venv/bin/uvicorn api.app:app --host 0.0.0.0 --port 8000
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```
