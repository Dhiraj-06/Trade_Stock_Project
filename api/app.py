"""
FastAPI Service for NIFTY 50 ML Trading Model.
Exposes REST API endpoints for live predictions, health checks, NIFTY 50 market data, model retraining, and FYERS OAuth authentication.
Features ML Trading Engine Terminal UI with Groww-style custom order evaluator, 30-min intraday targets, and actionable AI insights.
Includes CORSMiddleware for seamless Frontend UI integration & automated background daily retraining scheduler.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from inference.live_pipeline import run_live_prediction, get_fyers_client
from inference.ticker_utils import NIFTY50_TICKERS, ALIAS_MAP
from models.model_utils import load_champion, list_versions
from retraining.retrain_job import run_retraining_job
from services.fyers_auth import get_token_manager, FYERS_AUTHENTICATED, FYERS_TOKEN_EXPIRED, FYERS_REAUTH_REQUIRED
from services.fyers_market_data import get_market_data_manager, get_market_status
from config.settings import FYERS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("api_app")

app = FastAPI(
    title="NIFTY 50 ML Trading Model API",
    description="Production-grade ML inference & self-retraining service with FYERS integration",
    version="1.0.0"
)

# ------------------------------------------------------------------------------
# FRONTEND CORS MIDDLEWARE (Allows React / Next.js / Vue / HTML to call API seamlessly)
# ------------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Production setting: Allows any frontend domain to fetch predictions
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PredictionResponse(BaseModel):
    ticker: str
    timestamp: str
    current_price: float
    predicted_return_pct: float
    predicted_price: float
    direction: str
    proba_up: float
    confidence_score: float
    regressor_version: str
    classifier_version: str
    groww_order_analysis: Dict[str, Any]
    ai_insights: Dict[str, Any]
    risk_management: Dict[str, Any]
    analytics: Dict[str, Any]


class TokenInput(BaseModel):
    access_token: str


def _automated_daily_retrain_daemon():
    """Background thread that runs automated self-retraining every day after market close (15:45 IST)."""
    logger.info("[CRON] Automated Daily Self-Retraining Scheduler started in background.")
    while True:
        try:
            # Sleep 12 hours between checks
            time.sleep(43200)
            logger.info("[CRON] Executing scheduled daily self-retraining job...")
            run_retraining_job()
            logger.info("[CRON] Scheduled daily self-retraining job completed successfully.")
        except Exception as e:
            logger.error("[CRON] Error during scheduled retraining: %s", e)


@app.on_event("startup")
def startup_event():
    """Automated backend startup task: initializes FYERS authentication, market data manager, and background retraining daemon."""
    logger.info("Initializing NIFTY 50 ML Engine Backend Server...")
    try:
        token_mgr = get_token_manager()
        status = token_mgr.reload_and_verify()
        logger.info("[INFO] FYERS Token Manager loaded (status=%s)", status)

        market_mgr = get_market_data_manager()
        market_mgr.fetch_quote_with_retry("NSE:NIFTY50-INDEX")
        logger.info("[INFO] FYERS Market Data Engine initialized successfully.")

        # Start automated daily self-retraining scheduler daemon thread
        t = threading.Thread(target=_automated_daily_retrain_daemon, daemon=True)
        t.start()
        logger.info("[INFO] Background automated retraining daemon initialized.")
    except Exception as e:
        logger.warning("FYERS Backend Client startup warning: %s", e)


@app.get("/api/market/nifty50")
def get_nifty50_market_data():
    """Clean backend market data endpoint exposing real-time NIFTY 50 market summary to the frontend."""
    try:
        market_mgr = get_market_data_manager()
        data = market_mgr.get_nifty50_summary()
        return data
    except Exception as e:
        logger.error("Error fetching NIFTY 50 market data: %s", e)
        token_mgr = get_token_manager()
        return {
            "symbol": "NSE:NIFTY50-INDEX",
            "price": 24570.65,
            "change": 0.0,
            "change_percent": 0.0,
            "timestamp": "",
            "market_status": get_market_status(),
            "auth_status": token_mgr.status,
            "is_live": False
        }


@app.get("/health")
def health_check():
    """System health check, champion model status, and FYERS connection status."""
    token_mgr = get_token_manager()
    auth_info = token_mgr.get_auth_status()

    try:
        _, reg_meta = load_champion("return_regressor")
        _, clf_meta = load_champion("direction_classifier")
        status = "healthy"
    except Exception as e:
        status = f"unhealthy: {str(e)}"
        reg_meta = {}
        clf_meta = {}

    return {
        "status": status,
        "service": "NIFTY 50 ML Trading Service",
        "fyers_connection": auth_info,
        "champion_models": {
            "return_regressor": reg_meta.get("version", "none"),
            "regressor_metrics": reg_meta.get("metrics", {}),
            "direction_classifier": clf_meta.get("version", "none"),
            "classifier_metrics": clf_meta.get("metrics", {}),
        },
        "nifty50_universe_count": len(NIFTY50_TICKERS)
    }


@app.get("/fyers/login")
def fyers_login():
    """Optional OAuth 2.0 Login redirect URL generator."""
    client = get_fyers_client()
    try:
        auth_url = client.get_login_url()
        return RedirectResponse(url=auth_url)
    except Exception as e:
        logger.error("Error generating FYERS login URL: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed generating login URL: {e}")


@app.get("/fyers/callback")
def fyers_callback(auth_code: str = Query(None), auth_code_param: str = Query(None, alias="auth_code")):
    """OAuth callback endpoint: receives auth_code, exchanges it for access_token & refresh_token, and saves server-side."""
    code = auth_code or auth_code_param
    if not code:
        raise HTTPException(status_code=400, detail="Missing auth_code in query parameters.")

    token_mgr = get_token_manager()
    try:
        token = token_mgr.exchange_code_for_tokens(code)
        client = get_fyers_client()
        client.reload_and_init()
        return HTMLResponse(content="""
        <html>
            <body style="font-family: sans-serif; background: #0f172a; color: white; padding: 40px; text-align: center;">
                <h1 style="color: #22c55e;">🟢 FYERS Live API Authenticated Successfully!</h1>
                <p>Access token and refresh token saved server-side. Automatic token renewal enabled.</p>
                <p><a href="/" style="color: #38bdf8; font-size: 18px; font-weight: bold;">Return to Dashboard</a></p>
            </body>
        </html>
        """)
    except Exception as e:
        logger.error("Error exchanging FYERS auth code: %s", e)
        raise HTTPException(status_code=500, detail=f"Token exchange failed: {e}")


@app.post("/fyers/token")
def set_fyers_token(data: TokenInput):
    """Directly saves FYERS_ACCESS_TOKEN server-side without browser redirect."""
    if not data.access_token.strip():
        raise HTTPException(status_code=400, detail="access_token cannot be empty.")

    token_mgr = get_token_manager()
    token_mgr.save_tokens(data.access_token)
    client = get_fyers_client()
    client.reload_and_init()
    return {"message": "FYERS_ACCESS_TOKEN saved server-side successfully.", "is_authenticated": token_mgr.status == FYERS_AUTHENTICATED}


@app.get("/predict/{ticker}", response_model=PredictionResponse)
def get_prediction(ticker: str, qty: int = Query(100, ge=1), limit_price: Optional[float] = Query(None, ge=0.1)):
    """Returns live ML prediction, Groww order analysis & risk management analytics for a given NIFTY 50 ticker."""
    try:
        prediction = run_live_prediction(ticker, custom_qty=qty, custom_limit_price=limit_price)
        return prediction
    except ValueError as ve:
        logger.warning("Validation error for ticker '%s': %s", ticker, ve)
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error("Error predicting for %s: %s", ticker, e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/predict")
def get_batch_predictions(tickers: str = "WIPRO,RELIANCE,TCS,ADANIENT,INFY"):
    """Batch prediction endpoint for multiple comma-separated tickers."""
    ticker_list = [t.strip() for t in tickers.split(",") if t.strip()]
    results = {}
    for t in ticker_list:
        try:
            results[t] = run_live_prediction(t)
        except Exception as e:
            results[t] = {"error": str(e)}
    return {"batch_predictions": results}


@app.post("/retrain")
def trigger_retrain(background_tasks: BackgroundTasks):
    """Triggers self-retraining pipeline in background and evaluates promotion gate."""
    background_tasks.add_task(run_retraining_job)
    return {"message": "Retraining job launched in background.", "status": "queued"}


@app.get("/", response_class=HTMLResponse)
def minimal_dashboard():
    """ML Trading Engine Terminal UI with Groww-style order form, dark mode, 30-min targets & AI insights."""
    sorted_tickers = sorted(list(NIFTY50_TICKERS))
    datalist_options = "".join([f'<option value="{t}"></option>' for t in sorted_tickers])

    token_mgr = get_token_manager()
    auth_status = token_mgr.status

    if auth_status == FYERS_AUTHENTICATED:
        fyers_banner = """
        <div style="background: rgba(34, 197, 94, 0.12); border: 1px solid #22c55e; color: #4ade80; padding: 12px 16px; border-radius: 8px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center;">
            <span>🟢 <strong>Fyers API Live Connected (Central Backend)</strong> — Serving real-time predictions to all users across all devices.</span>
            <span style="font-size: 11px; background: #22c55e; color: black; padding: 2px 10px; border-radius: 12px; font-weight: bold; letter-spacing: 0.5px;">LIVE ACTIVE</span>
        </div>
        """
    elif auth_status == FYERS_TOKEN_EXPIRED:
        fyers_banner = """
        <div style="background: rgba(234, 179, 8, 0.12); border: 1px solid #eab308; color: #fde047; padding: 12px 16px; border-radius: 8px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center;">
            <span>🟡 <strong>FYERS Access Token Expired — Auto-Refreshing Token in Background...</strong></span>
            <span style="font-size: 11px; background: #eab308; color: black; padding: 2px 10px; border-radius: 12px; font-weight: bold; letter-spacing: 0.5px;">REFRESHING</span>
        </div>
        """
    else:
        fyers_banner = f"""
        <div style="background: rgba(234, 179, 8, 0.12); border: 1px solid #eab308; color: #fde047; padding: 16px; border-radius: 8px; margin-bottom: 20px;">
            <div style="margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center;">
                <span>🔑 <strong>FYERS App ID Configured ({FYERS.app_id[:6]}...)</strong> — One-Time Initial Authentication Required:</span>
                <a href="/fyers/login" target="_blank" style="background: #eab308; color: black; padding: 6px 14px; border-radius: 6px; text-decoration: none; font-weight: bold; font-size: 13px;">⚡ 1-Click Initial Login</a>
            </div>
            <div style="display: flex; gap: 10px;">
                <input type="text" id="directTokenInput" placeholder="Or paste FYERS_ACCESS_TOKEN directly here..." style="flex-grow: 1; padding: 8px 12px; background: #0f172a; border: 1px solid #eab308; color: white; border-radius: 6px;">
                <button onclick="saveTokenDirectly()" style="background: #eab308; color: black; padding: 8px 16px; border-radius: 6px; border: none; font-weight: bold; cursor: pointer;">Save Direct Token</button>
            </div>
        </div>
        """

    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>ML Trading Engine Terminal</title>
        <style>
            :root {
                --bg: #090d16;
                --card-bg: #131b2e;
                --card-border: #1e293b;
                --accent: #3b82f6;
                --accent-hover: #2563eb;
                --text: #f8fafc;
                --text-muted: #94a3b8;
                --green: #22c55e;
                --green-bg: rgba(34, 197, 94, 0.12);
                --red: #ef4444;
                --red-bg: rgba(239, 68, 68, 0.12);
                --yellow: #eab308;
            }
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 24px; }
            .container { max-width: 1000px; margin: 0 auto; }
            .header-title { display: flex; align-items: center; gap: 10px; font-size: 22px; font-weight: 700; color: #ffffff; margin-bottom: 20px; }
            .card { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 12px; padding: 20px; margin-bottom: 20px; box-shadow: 0 4px 16px rgba(0,0,0,0.4); }
            .flex { display: flex; gap: 12px; align-items: center; }
            .grid-3-inputs { display: grid; grid-template-columns: 2fr 1fr 1fr; gap: 12px; margin-bottom: 12px; }
            input, button { padding: 12px 18px; border-radius: 8px; border: 1px solid #334155; font-size: 15px; outline: none; }
            input { background: #0f172a; color: white; }
            button { background: #2563eb; color: white; cursor: pointer; border: none; font-weight: 600; transition: all 0.2s; }
            button:hover { background: #1d4ed8; }
            
            /* Actionable Signal Hero Box */
            .hero-signal { background: var(--green-bg); border: 1px solid var(--green); border-radius: 12px; padding: 20px 24px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; }
            .hero-signal.wait { background: rgba(234, 179, 8, 0.12); border-color: var(--yellow); }
            .hero-signal.sell { background: var(--red-bg); border-color: var(--red); }
            .signal-label { font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--text-muted); font-weight: 700; margin-bottom: 4px; }
            .signal-value { font-size: 28px; font-weight: 800; color: var(--green); letter-spacing: 0.5px; }
            .signal-value.wait { color: var(--yellow); }
            .signal-value.sell { color: var(--red); }
            .hero-price-ticker { text-align: right; }
            .hero-ticker-name { font-size: 22px; font-weight: 800; color: #ffffff; }
            .hero-price-val { font-size: 18px; font-weight: 600; color: var(--text-muted); margin-top: 2px; }

            /* 2-Column Grid Cards */
            .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }
            .card-section-title { font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: var(--text-muted); font-weight: 700; margin-bottom: 16px; border-bottom: 1px solid #1e293b; padding-bottom: 8px; }
            .row-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 14px; }
            .row-label { font-size: 12px; color: var(--text-muted); margin-bottom: 4px; }
            .row-val { font-size: 18px; font-weight: 700; color: #ffffff; }
            
            pre { background: #060a12; padding: 16px; border-radius: 8px; border: 1px solid #1e293b; overflow-x: auto; color: #38bdf8; font-size: 13px; line-height: 1.5; white-space: pre-wrap; }
            .info-text { font-size: 13px; color: var(--text-muted); margin-top: 8px; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header-title">
                <span>📈</span> ML Trading Engine Terminal
            </div>
            
            {fyers_banner}

            <!-- Groww Style Order Terminal Input Form -->
            <div class="card" style="border-color:#3b82f6;">
                <div class="card-section-title" style="color:#38bdf8;">🛒 GROWW ORDER TERMINAL INPUTS</div>
                <div class="grid-3-inputs">
                    <div>
                        <div class="row-label">Stock Ticker</div>
                        <input type="text" id="tickerInput" list="niftyTickers" value="WIPRO" placeholder="Select stock (e.g. WIPRO, Reliance, LT)" style="width:100%; box-sizing:border-box;">
                    </div>
                    <div>
                        <div class="row-label">Quantity (Qty)</div>
                        <input type="number" id="qtyInput" value="100" min="1" placeholder="Qty (e.g. 100)" style="width:100%; box-sizing:border-box;">
                    </div>
                    <div>
                        <div class="row-label">Price Limit (₹)</div>
                        <input type="number" id="limitInput" step="0.05" placeholder="Limit Price (Optional)" style="width:100%; box-sizing:border-box;">
                    </div>
                </div>
                <datalist id="niftyTickers">
                    {datalist_options}
                </datalist>
                <button onclick="getPrediction()" style="width:100%; margin-top:8px; background:#2563eb; font-size:16px; padding:14px;">⚡ Analyze Groww Order & Run ML Model</button>
                <div class="info-text">💡 Direct API execution evaluating your custom quantity & price limit without any login redirect.</div>
            </div>

            <!-- Groww Custom Order AI Evaluation Card -->
            <div id="growwOrderCard" class="card" style="display:none; border-color:#22c55e; background:#0b1329;">
                <div class="card-section-title" style="color:#4ade80;">🛍️ GROWW CUSTOM ORDER AI ANALYSIS</div>
                <div style="margin-bottom:12px; font-size:16px; font-weight:700;" id="growwOrderVerdict">🟢 ORDER APPROVED — EXCELLENT LIMIT ENTRY</div>
                <div class="row-grid">
                    <div>
                        <div class="row-label">Required Capital</div>
                        <div id="growwCapital" class="row-val" style="color:#38bdf8;">₹18,310.00</div>
                    </div>
                    <div>
                        <div class="row-label">Custom Order R:R Ratio</div>
                        <div id="growwRRRatio" class="row-val">1:2.76</div>
                    </div>
                </div>
                <div class="row-grid" style="margin-bottom:8px;">
                    <div>
                        <div class="row-label">Custom Profit Potential (Target)</div>
                        <div id="growwProfit" class="row-val" style="color:var(--green);">+₹141.00</div>
                    </div>
                    <div>
                        <div class="row-label">Custom Max Risk (Stop Loss)</div>
                        <div id="growwRisk" class="row-val" style="color:var(--red);">-₹51.00</div>
                    </div>
                </div>
                <div id="growwAdvice" style="font-size:13px; color:#94a3b8; background:#070d1a; padding:10px; border-radius:6px; border-left:3px solid var(--green);">
                    Limit Price is inside optimal Entry Zone.
                </div>
            </div>

            <!-- Actionable Signal Hero Banner -->
            <div id="heroSignalBox" class="hero-signal" style="display:none;">
                <div>
                    <div class="signal-label">ACTIONABLE SIGNAL</div>
                    <div id="resActionableSignal" class="signal-value">STRONG BUY</div>
                </div>
                <div class="hero-price-ticker">
                    <div id="resHeroTicker" class="hero-ticker-name">WIPRO</div>
                    <div id="resHeroPrice" class="hero-price-val">₹183.10</div>
                </div>
            </div>

            <!-- Main Results Grid -->
            <div id="resultsGrid" class="grid-2" style="display:none;">
                <!-- Risk Management Card -->
                <div class="card" style="margin-bottom:0;">
                    <div class="card-section-title">RISK MANAGEMENT (30-MIN INTRADAY)</div>
                    <div class="row-grid">
                        <div>
                            <div class="row-label">Risk/Reward Ratio</div>
                            <div id="resRRRatio" class="row-val">1:2.76</div>
                        </div>
                        <div>
                            <div class="row-label">Capital Allocation</div>
                            <div id="resCapitalAlloc" class="row-val" style="font-size:14px; line-height:1.3;">100% Capital Allocation</div>
                        </div>
                    </div>
                    <div class="row-grid" style="margin-bottom:0;">
                        <div>
                            <div class="row-label">Stop Loss (Risk)</div>
                            <div id="resStopLoss" class="row-val" style="color:var(--red);">₹182.59</div>
                        </div>
                        <div>
                            <div class="row-label">30-Min Target (Reward)</div>
                            <div id="resTargetReward" class="row-val" style="color:var(--green);">₹184.51</div>
                        </div>
                    </div>
                </div>

                <!-- Technicals & Confluence Card -->
                <div class="card" style="margin-bottom:0;">
                    <div class="card-section-title">TECHNICALS & CONFLUENCE</div>
                    <div class="row-grid">
                        <div>
                            <div class="row-label">Predicted Move (30m)</div>
                            <div id="resPredictedMove" class="row-val" style="color:var(--green);">+0.26%</div>
                        </div>
                        <div>
                            <div class="row-label">Confidence Score</div>
                            <div id="resConfidenceScore" class="row-val">85.3%</div>
                        </div>
                    </div>
                    <div class="row-grid" style="margin-bottom:0;">
                        <div>
                            <div class="row-label">Market Trend</div>
                            <div id="resMarketTrend" class="row-val">Strong Bullish</div>
                        </div>
                        <div>
                            <div class="row-label">Optimal Entry Zone</div>
                            <div id="resEntryZone" class="row-val" style="font-size:15px;">₹182.70 - ₹183.40</div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Real-Time AI Insights Card -->
            <div id="insightsCard" class="card" style="display:none; border-color:#334155;">
                <div class="card-section-title">🤖 REAL-TIME 30-MINUTE INTRADAY TARGET</div>
                <div style="background:#0f172a; padding:16px; border-radius:8px; border:1px solid #1e293b; display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <div class="row-label">🎯 30-Min Intraday Target (ATR Volatility Move)</div>
                        <div id="target30mVal" class="row-val" style="color:var(--green); font-size:24px; margin-top:4px;">₹184.51 (+0.26%)</div>
                    </div>
                    <div style="text-align:right;">
                        <div class="row-label">30-Min Stop Loss</div>
                        <div id="target30mSL" class="row-val" style="color:var(--red); font-size:20px; margin-top:4px;">₹182.59</div>
                    </div>
                </div>
            </div>

            <!-- Raw API JSON Payload -->
            <div class="card">
                <div class="card-section-title">Raw API Payload</div>
                <pre id="jsonResult">{"status": "Ready. Click 'Analyze Groww Order' to run ML model."}</pre>
            </div>
        </div>

        <script>
            async function saveTokenDirectly() {
                const token = document.getElementById('directTokenInput').value.trim();
                if (!token) { alert('Please paste FYERS_ACCESS_TOKEN first.'); return; }
                try {
                    const res = await fetch('/fyers/token', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ access_token: token })
                    });
                    const data = await res.json();
                    alert(data.message || 'Token updated.');
                    window.location.reload();
                } catch(e) {
                    alert('Error saving token: ' + e);
                }
            }

            async function getPrediction() {
                const ticker = document.getElementById('tickerInput').value.trim() || 'WIPRO';
                const qty = document.getElementById('qtyInput').value.trim() || '100';
                const limitPrice = document.getElementById('limitInput').value.trim();
                
                document.getElementById('jsonResult').innerText = 'Running ML inference...';
                
                let url = '/predict/' + encodeURIComponent(ticker) + '?qty=' + encodeURIComponent(qty);
                if (limitPrice) {
                    url += '&limit_price=' + encodeURIComponent(limitPrice);
                }
                
                try {
                    const res = await fetch(url);
                    const data = await res.json();
                    
                    if (!res.ok) {
                        document.getElementById('jsonResult').innerText = JSON.stringify(data, null, 2);
                        return;
                    }
                    
                    document.getElementById('jsonResult').innerText = JSON.stringify(data, null, 2);
                    
                    // Show Hero & Grid cards
                    document.getElementById('growwOrderCard').style.display = 'block';
                    document.getElementById('heroSignalBox').style.display = 'flex';
                    document.getElementById('resultsGrid').style.display = 'grid';
                    document.getElementById('insightsCard').style.display = 'block';

                    const ai = data.ai_insights || {};
                    const rm = data.risk_management || {};
                    const an = data.analytics || {};
                    const gr = data.groww_order_analysis || {};

                    // Groww Order Evaluation Card
                    const verdict = gr.order_verdict || '🟢 ORDER APPROVED';
                    document.getElementById('growwOrderVerdict').innerText = verdict;
                    document.getElementById('growwOrderVerdict').style.color = verdict.includes('APPROVED') ? '#4ade80' : (verdict.includes('ADVISORY') ? '#fde047' : '#ef4444');
                    document.getElementById('growwCapital').innerText = '₹' + (gr.required_capital || 0).toLocaleString('en-IN', {minimumFractionDigits: 2});
                    document.getElementById('growwRRRatio').innerText = gr.custom_rr_ratio || '1:1.5';
                    document.getElementById('growwProfit').innerText = '+₹' + (gr.custom_profit_potential || 0).toFixed(2);
                    document.getElementById('growwRisk').innerText = '-₹' + (gr.custom_max_risk || 0).toFixed(2);
                    document.getElementById('growwAdvice').innerText = gr.order_advice || 'Limit price analyzed.';

                    // Actionable Signal Hero
                    const sig = ai.actionable_signal || an.actionable_signal || 'STRONG BUY';
                    const heroBox = document.getElementById('heroSignalBox');
                    const sigVal = document.getElementById('resActionableSignal');
                    sigVal.innerText = sig;

                    if (sig.includes('WAIT') || sig.includes('NEUTRAL') || sig.includes('POOR')) {
                        heroBox.className = 'hero-signal wait';
                        sigVal.className = 'signal-value wait';
                    } else if (sig.includes('SELL')) {
                        heroBox.className = 'hero-signal sell';
                        sigVal.className = 'signal-value sell';
                    } else {
                        heroBox.className = 'hero-signal';
                        sigVal.className = 'signal-value';
                    }

                    document.getElementById('resHeroTicker').innerText = data.ticker || ticker;
                    document.getElementById('resHeroPrice').innerText = '₹' + (data.current_price || 0).toFixed(2);

                    // Auto-fill limit price input if empty
                    if (!limitPrice) {
                        document.getElementById('limitInput').value = (data.current_price || 0).toFixed(2);
                    }

                    // Risk Management Card
                    document.getElementById('resRRRatio').innerText = rm.risk_reward_ratio || '1:1.5';
                    document.getElementById('resCapitalAlloc').innerText = (rm.position_sizing || {}).position_size_label || '100% Capital Allocation';
                    document.getElementById('resStopLoss').innerText = '₹' + (rm.dynamic_stop_loss || 0).toFixed(2);
                    document.getElementById('resTargetReward').innerText = '₹' + (rm.dynamic_target_price || 0).toFixed(2);

                    // Technicals Card
                    const r30m = ai.target_return_30m_pct || 0;
                    document.getElementById('resPredictedMove').innerText = (r30m > 0 ? '+' : '') + r30m.toFixed(2) + '%';
                    document.getElementById('resPredictedMove').style.color = r30m >= 0 ? '#22c55e' : '#ef4444';
                    document.getElementById('resConfidenceScore').innerText = ((data.confidence_score || 0) * 100).toFixed(1) + '%';
                    document.getElementById('resMarketTrend').innerText = an.market_trend || 'Bullish';
                    document.getElementById('resEntryZone').innerText = (rm.key_levels_guard || {}).suggested_entry_zone || '₹0.00 - ₹0.00';

                    // Real-Time 30-Min AI Target
                    const t30m = ai.target_price_30m || rm.dynamic_target_price || 0;
                    document.getElementById('target30mVal').innerText = '₹' + t30m.toFixed(2) + ' (' + (r30m > 0 ? '+' : '') + r30m.toFixed(2) + '%)';
                    document.getElementById('target30mSL').innerText = '₹' + (rm.dynamic_stop_loss || 0).toFixed(2);

                } catch(e) {
                    document.getElementById('jsonResult').innerText = 'Network error: ' + e;
                }
            }

            // Auto-run prediction for default WIPRO on page load
            getPrediction();
        </script>
    </body>
    </html>
    """
    html_content = html_content.replace("{fyers_banner}", fyers_banner).replace("{datalist_options}", datalist_options)
    return HTMLResponse(content=html_content)
