# NIFTY 50 ML Trading Engine & Real-Time FYERS Market Data Service

A production-grade Machine Learning service and Real-Time Market Data Engine for predicting next 30-minute return percentages (Model B Regressor) and direction (Model C Classifier) across NIFTY 50 constituents with institutional Risk Management and FYERS API v3 automatic authentication.

---

## 🚀 Key Features

1. **Automatic FYERS Token Authentication & Refresh Engine**:
   - **Server-Side Token Store**: Securely stores `access_token` and `refresh_token` in `data/live/fyers_tokens.json` (server-side only, excluded from git).
   - **Automatic Token Renewal**: Automatically refreshes expired access tokens using the official FYERS API v3 refresh-token mechanism (`grant_type="refresh_token"`) without requiring manual user logins on application restarts or runtime token expiration.
   - **Authentication State Machine**: Exposes safe statuses (`FYERS_AUTHENTICATED`, `FYERS_TOKEN_EXPIRED`, `FYERS_REAUTH_REQUIRED`, `FYERS_AUTH_ERROR`) without leaking secret keys or tokens.
2. **Indian Stock Market Hours Engine (`Asia/Kolkata`)**:
   - Timezone-aware market state calculation: `PRE_MARKET` (09:00 - 09:15 IST), `OPEN` (09:15 - 15:30 IST, Mon-Fri), `CLOSED` (After-hours / Weekends).
   - Optimizes polling/streaming intervals to prevent unnecessary API requests when the market is closed.
3. **Backend Real-Time Market Data API (`GET /api/market/nifty50`)**:
   - Serves real-time NIFTY 50 market summary (`symbol`, `price`, `change`, `change_percent`, `timestamp`, `market_status`, `auth_status`) to the frontend.
4. **4 Core Institutional Risk Management Features**:
   - **Dynamic ATR Stop-Loss & Target**: Volatility-adjusted stop loss ($1.5 \times \text{ATR}_{14}$) and Risk/Reward Guard (requires $\ge 1:1.4$ ratio, otherwise overrides to `"WAIT"`).
   - **Dynamic Position Sizing**: Capital protection allocation (🟢 100% Full, 🟡 50% Reduced Risk, 🔴 0% Do Not Trade).
   - **Key Levels & Pullback Guard**: 20-candle Support/Resistance entry zones (prevents buying near peak resistance).
   - **Volume Strength & Confluence**: Volume confirmation ($> 1.1x$) and RSI Overbought ($> 75$) / Oversold ($< 25$) alerts.
5. **Scale-Invariant Feature Engineering**: Computes ~46 normalized technical indicators, ratios, and bounded oscillators (grouped strictly by `Ticker`) to ensure zero price-scale leakage and cross-ticker generalization.
6. **30-Minute Intraday Horizons**: Configured for 15-minute candles (`interval: "15m"`) and 2-bar horizon (`horizon_candles: 2`), predicting 30-minute trend returns.
7. **Automated Self-Retraining & Champion Promotion Gate**: Periodically retrains models on accumulated dataset + live Fyers Parquet buffers (`data/live/*.parquet`), promoting candidates only if walk-forward CV metrics improve upon the current champion.

---

## 🔑 Environment Configuration (`.env`)

Create a `.env` file inside the `ml_service/` directory (or configure environment variables in your deployment system):

```bash
# ml_service/.env
FYERS_APP_ID=YOUR_APP_ID-100       # e.g., QMRW5E4JPC-100
FYERS_SECRET_KEY=YOUR_SECRET_KEY   # e.g., W8ZNTCC6FF
```

> **Security Note**: Never commit `.env` or `data/live/fyers_tokens.json` to GitHub. Ensure `.gitignore` is present. API secret keys and refresh tokens are strictly kept server-side and are NEVER sent to the frontend.

---

## 🔐 Authentication Lifecycle & Workflow

```text
                 INITIAL ONE-TIME LOGIN
                           │
                           ↓
             User opens /fyers/login once
                           │
                           ↓
              Completes FYERS OAuth login
                           │
                           ↓
         Backend exchanges auth_code for tokens
                           │
                           ↓
      Saves access_token & refresh_token server-side
                (data/live/fyers_tokens.json)
                           │
                           ↓
               SUBSEQUENT APP STARTUPS
                     (100% Auto)
                           │
                           ↓
            Backend loads server-side tokens
                           │
                 ┌─────────┴─────────┐
                 │                   │
            Token Valid        Token Expired
                 │                   │
                 │            Auto-Refresh via
                 │            FYERS API v3
                 │                   │
                 └─────────┬─────────┘
                           ↓
                Connects to FYERS &
              Streams Real-Time Data
```

---

## 🛠️ Installation & Setup

1. **Activate Python Virtual Environment & Install Dependencies**:
   ```bash
   cd ml_service
   pip install -r requirements.txt
   ```

2. **Run Comprehensive 9/9 Unit & Integration Test Suite**:
   ```bash
   python -m pytest tests/test_features.py tests/test_pipeline.py tests/test_ticker_utils.py tests/test_fyers_auth.py -v
   ```

---

## 📊 Model Architecture & Performance Metrics

| Model Component | Objective / Metric | 5-Fold Walk-Forward Champion Score |
|---|---|---|
| **Model B (Regressor)** | Avg MAE (Mean Absolute Error) | `1.51399%` |
| **Model B (Regressor)** | Avg RMSE (Root Mean Sq Error) | `2.02870%` |
| **Model B (Regressor)** | Directional Accuracy | **`54.56%`** |
| **Model C (Classifier)** | Avg Accuracy | `53.96%` |
| **Model C (Classifier)** | Avg Precision | `54.23%` |
| **Model C (Classifier)** | Avg Recall | **`70.27%`** |
| **Model C (Classifier)** | Avg F1-Score | `0.6115` |
| **Model C (Classifier)** | Avg ROC-AUC | `0.5545` |

---

## 🌐 Running the FastAPI Inference Service

Start the live FastAPI uvicorn server:

```bash
python -m uvicorn api.app:app --host 127.0.0.1 --port 8000 --reload
```

- **Live Dashboard**: Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) in your browser.
- **NIFTY 50 Real-Time Market Data**: `GET http://127.0.0.1:8000/api/market/nifty50`
- **Single Ticker Prediction & Risk Analytics**: `GET http://127.0.0.1:8000/predict/WIPRO`
- **Batch Predictions**: `GET http://127.0.0.1:8000/predict?tickers=WIPRO,RELIANCE,TCS,ADANIENT`
- **System Health & Connection Status**: `GET http://127.0.0.1:8000/health`
- **Initial 1-Click FYERS Authorization**: `GET http://127.0.0.1:8000/fyers/login`

---

## 🔄 Automated Retraining & Model Promotion

The service retrains itself unattended via `retraining/retrain_job.py`:

1. **Trigger**: Scheduled via `retraining/scheduler.py` (APScheduler running at 6:00 PM weekdays after Indian market close) or triggered via `POST /retrain`.
2. **Data Ingestion**: Merges historical dataset with accumulated Fyers live buffers (`data/live/*.parquet`).
3. **Promotion Gate**: Evaluates candidates against champion metadata. Promotes new candidates **only** if metrics improve upon champion scores.
