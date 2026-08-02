"""
FastAPI Service for NIFTY 50 ML Trading Model.
Exposes REST API endpoints for live predictions, health checks, model retraining, and Fyers API OAuth auth flow.
"""
from __future__ import annotations

import logging
from typing import Dict, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from inference.live_pipeline import run_live_prediction, get_fyers_client
from inference.ticker_utils import NIFTY50_TICKERS, ALIAS_MAP
from models.model_utils import load_champion, list_versions
from retraining.retrain_job import run_retraining_job
from config.settings import FYERS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("api_app")

app = FastAPI(
    title="NIFTY 50 ML Trading Model API",
    description="Production-grade ML inference & self-retraining service with Fyers integration",
    version="1.0.0"
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


class TokenInput(BaseModel):
    access_token: str


@app.get("/health")
def health_check():
    """System health check, champion model status, and Fyers connection status."""
    fyers_client = get_fyers_client()
    fyers_client.reload_and_init()

    if fyers_client.is_authenticated:
        fyers_status = "connected_live"
    elif fyers_client.app_id and not fyers_client.access_token:
        fyers_status = "app_id_present_token_required"
    else:
        fyers_status = "unconfigured_mock_mode"

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
        "fyers_connection": {
            "status": fyers_status,
            "is_authenticated": fyers_client.is_authenticated,
            "app_id": fyers_client.app_id[:6] + "..." if fyers_client.app_id else "not_set",
            "has_access_token": bool(fyers_client.access_token)
        },
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
    """Redirects to Fyers OAuth 2.0 Login URL to generate an auth code."""
    client = get_fyers_client()
    try:
        auth_url = client.generate_auth_url()
        return RedirectResponse(url=auth_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/fyers/callback")
def fyers_callback(auth_code: str = Query(None), auth_code_param: str = Query(None, alias="auth_code")):
    """OAuth callback endpoint: receives auth_code, exchanges it for access_token, and saves to .env."""
    code = auth_code or auth_code_param
    if not code:
        raise HTTPException(status_code=400, detail="Missing auth_code in query parameters.")

    client = get_fyers_client()
    try:
        token = client.exchange_code_for_token(code)
        return HTMLResponse(content=f"""
        <html>
            <body style="font-family: sans-serif; background: #0f172a; color: white; padding: 40px; text-align: center;">
                <h1 style="color: #22c55e;">🟢 Fyers Live API Connected Successfully!</h1>
                <p>Access token has been generated and saved to your <code>.env</code> file.</p>
                <p><a href="/" style="color: #38bdf8; font-size: 18px; font-weight: bold;">Return to ML Trading Dashboard</a></p>
            </body>
        </html>
        """)
    except Exception as e:
        logger.error("Error exchanging Fyers auth code: %s", e)
        raise HTTPException(status_code=500, detail=f"Token exchange failed: {e}")


@app.post("/fyers/token")
def set_fyers_token(data: TokenInput):
    """Manually submits and saves FYERS_ACCESS_TOKEN into .env."""
    if not data.access_token.strip():
        raise HTTPException(status_code=400, detail="access_token cannot be empty.")

    client = get_fyers_client()
    client.save_access_token_directly(data.access_token)
    return {"message": "FYERS_ACCESS_TOKEN updated successfully.", "is_authenticated": client.is_authenticated}


@app.get("/predict/{ticker}", response_model=PredictionResponse)
def get_prediction(ticker: str):
    """Returns live ML prediction for a given NIFTY 50 ticker."""
    try:
        prediction = run_live_prediction(ticker)
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
    """Minimal local dashboard for testing predictions and managing Fyers API connection."""
    sorted_tickers = sorted(list(NIFTY50_TICKERS))
    datalist_options = "".join([f'<option value="{t}"></option>' for t in sorted_tickers])

    client = get_fyers_client()
    client.reload_and_init()

    if client.is_authenticated:
        fyers_banner = """
        <div style="background: rgba(34, 197, 94, 0.15); border: 1px solid #22c55e; color: #4ade80; padding: 12px 16px; border-radius: 8px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center;">
            <span>🟢 <strong>Fyers API Live Connected</strong> — Pulling real-time market quotes from Fyers.</span>
            <span style="font-size: 12px; background: #22c55e; color: black; padding: 2px 8px; border-radius: 12px; font-weight: bold;">LIVE ACTIVE</span>
        </div>
        """
    elif client.app_id and not client.access_token:
        fyers_banner = f"""
        <div style="background: rgba(234, 179, 8, 0.15); border: 1px solid #eab308; color: #fde047; padding: 12px 16px; border-radius: 8px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center;">
            <span>🔑 <strong>Fyers App ID Found ({client.app_id[:6]}...)</strong> — Generate Access Token to enable Live Fyers Tracking.</span>
            <a href="/fyers/login" target="_blank" style="background: #eab308; color: black; padding: 6px 14px; border-radius: 6px; text-decoration: none; font-weight: bold;">Connect Fyers Live</a>
        </div>
        """
    else:
        fyers_banner = """
        <div style="background: rgba(148, 163, 184, 0.15); border: 1px solid #64748b; color: #cbd5e1; padding: 12px 16px; border-radius: 8px; margin-bottom: 20px;">
            ℹ️ <strong>Mock Fallback Mode Active</strong> — Add <code>FYERS_APP_ID</code> and <code>FYERS_SECRET_KEY</code> to <code>ml_service/.env</code> to connect live Fyers API.
        </div>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>NIFTY 50 ML Trading Engine Dashboard</title>
        <style>
            :root {{
                --bg: #0f172a;
                --card-bg: #1e293b;
                --accent: #38bdf8;
                --text: #f8fafc;
                --text-muted: #94a3b8;
                --green: #22c55e;
                --red: #ef4444;
            }}
            body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 24px; }}
            .container {{ max-width: 1000px; margin: 0 auto; }}
            h1 {{ color: var(--accent); border-bottom: 2px solid #334155; padding-bottom: 12px; margin-bottom: 16px; }}
            .card {{ background: var(--card-bg); border-radius: 12px; padding: 20px; margin-bottom: 20px; box-shadow: 0 4px 12px rgba(0,0,0,0.3); }}
            .flex {{ display: flex; gap: 12px; align-items: center; }}
            input, button {{ padding: 10px 16px; border-radius: 6px; border: 1px solid #475569; font-size: 16px; }}
            input {{ background: #0f172a; color: white; flex-grow: 1; }}
            button {{ background: #0284c7; color: white; cursor: pointer; border: none; font-weight: bold; }}
            button:hover {{ background: #0369a1; }}
            pre {{ background: #090d16; padding: 16px; border-radius: 8px; overflow-x: auto; color: #a5f3fc; white-space: pre-wrap; }}
            .badge-up {{ background: rgba(34, 197, 94, 0.2); color: var(--green); padding: 4px 12px; border-radius: 20px; font-weight: bold; }}
            .badge-down {{ background: rgba(239, 68, 68, 0.2); color: var(--red); padding: 4px 12px; border-radius: 20px; font-weight: bold; }}
            .metrics-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-top: 16px; }}
            .metric-box {{ background: #0f172a; padding: 14px; border-radius: 8px; border: 1px solid #334155; }}
            .metric-label {{ font-size: 12px; color: var(--text-muted); text-transform: uppercase; }}
            .metric-val {{ font-size: 20px; font-weight: bold; margin-top: 4px; color: var(--accent); }}
            .error-card {{ background: rgba(239, 68, 68, 0.1); border: 1px solid var(--red); border-radius: 12px; padding: 16px; margin-bottom: 20px; display: none; color: #fca5a5; }}
            .info-text {{ font-size: 13px; color: var(--text-muted); margin-top: 6px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📈 NIFTY 50 ML Trading Engine (Live Inference & Monitoring)</h1>
            
            {fyers_banner}

            <div class="card">
                <h3>Single Ticker Live Prediction (NIFTY 50 Only)</h3>
                <div class="flex">
                    <input type="text" id="tickerInput" list="niftyTickers" value="WIPRO" placeholder="Select or type NIFTY 50 ticker (e.g. WIPRO, Tata Steel, Reliance)">
                    <datalist id="niftyTickers">
                        {datalist_options}
                    </datalist>
                    <button onclick="getPrediction()">Run ML Model</button>
                </div>
                <div class="info-text">💡 Tip: Model is trained exclusively on NIFTY 50 constituents. Typing variations like "Tata Steel" automatically resolves to "TATASTEEL".</div>
            </div>

            <div id="errorCard" class="error-card">
                <h3 style="margin-top:0; color:var(--red);">⚠️ Invalid Ticker</h3>
                <div id="errorMessage"></div>
            </div>

            <div id="resultCard" class="card" style="display:none;">
                <div class="flex" style="justify-content: space-between;">
                    <h2 id="resTicker">WIPRO</h2>
                    <span id="resDirectionBadge" class="badge-up">UP</span>
                </div>
                <div class="metrics-grid">
                    <div class="metric-box">
                        <div class="metric-label">Current Price</div>
                        <div class="metric-val" id="resCurrentPrice">₹0.00</div>
                    </div>
                    <div class="metric-box">
                        <div class="metric-label">Predicted Return %</div>
                        <div class="metric-val" id="resPredictedReturn">0.00%</div>
                    </div>
                    <div class="metric-box">
                        <div class="metric-label">Target Price</div>
                        <div class="metric-val" id="resTargetPrice">₹0.00</div>
                    </div>
                    <div class="metric-box">
                        <div class="metric-label">Confidence Score</div>
                        <div class="metric-val" id="resConfidence">0.00</div>
                    </div>
                </div>
                <h4>Raw Model Response:</h4>
                <pre id="jsonResult"></pre>
            </div>

            <div class="card">
                <div class="flex" style="justify-content: space-between;">
                    <h3>System & Champion Model Status</h3>
                    <button onclick="loadHealth()" style="background:#475569;">Refresh Health</button>
                </div>
                <pre id="healthJson">Loading system health...</pre>
            </div>
        </div>

        <script>
            async function getPrediction() {{
                const ticker = document.getElementById('tickerInput').value.trim() || 'WIPRO';
                document.getElementById('errorCard').style.display = 'none';
                document.getElementById('resultCard').style.display = 'block';
                document.getElementById('jsonResult').innerText = 'Running ML inference...';
                
                try {{
                    const res = await fetch('/predict/' + encodeURIComponent(ticker));
                    const data = await res.json();
                    
                    if (!res.ok) {{
                        document.getElementById('resultCard').style.display = 'none';
                        document.getElementById('errorCard').style.display = 'block';
                        document.getElementById('errorMessage').innerText = data.detail || 'An error occurred.';
                        return;
                    }}
                    
                    document.getElementById('jsonResult').innerText = JSON.stringify(data, null, 2);
                    document.getElementById('resTicker').innerText = data.ticker || ticker;
                    document.getElementById('resCurrentPrice').innerText = '₹' + (data.current_price || 0).toFixed(2);
                    
                    const ret = data.predicted_return_pct || 0;
                    document.getElementById('resPredictedReturn').innerText = (ret > 0 ? '+' : '') + ret.toFixed(2) + '%';
                    document.getElementById('resPredictedReturn').style.color = ret >= 0 ? '#22c55e' : '#ef4444';
                    
                    document.getElementById('resTargetPrice').innerText = '₹' + (data.predicted_price || 0).toFixed(2);
                    document.getElementById('resConfidence').innerText = ((data.confidence_score || 0) * 100).toFixed(1) + '%';
                    
                    const badge = document.getElementById('resDirectionBadge');
                    badge.innerText = data.direction || 'UP';
                    badge.className = data.direction === 'UP' ? 'badge-up' : 'badge-down';
                }} catch(e) {{
                    document.getElementById('resultCard').style.display = 'none';
                    document.getElementById('errorCard').style.display = 'block';
                    document.getElementById('errorMessage').innerText = 'Network error: ' + e;
                }}
            }}

            async function loadHealth() {{
                try {{
                    const res = await fetch('/health');
                    const data = await res.json();
                    document.getElementById('healthJson').innerText = JSON.stringify(data, null, 2);
                }} catch(e) {{
                    document.getElementById('healthJson').innerText = 'Health check error: ' + e;
                }}
            }}
            loadHealth();
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
