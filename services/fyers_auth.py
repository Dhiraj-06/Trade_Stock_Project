"""
Official FYERS API v3 Token Authentication Manager & State Machine.
Handles token persistence, automatic refresh-token renewal, and safe auth state reporting.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Dict, Any

from config.settings import FYERS, BASE_DIR

logger = logging.getLogger(__name__)

# Authentication States
FYERS_AUTHENTICATED = "FYERS_AUTHENTICATED"
FYERS_TOKEN_EXPIRED = "FYERS_TOKEN_EXPIRED"
FYERS_REAUTH_REQUIRED = "FYERS_REAUTH_REQUIRED"
FYERS_AUTH_ERROR = "FYERS_AUTH_ERROR"


def _update_env_file(updates: Dict[str, str]):
    """Helper to safely update key=value pairs in ml_service/.env without corrupting existing lines."""
    env_path = BASE_DIR / ".env"
    lines = []
    if env_path.exists():
        with open(env_path, "r") as f:
            lines = f.readlines()

    updated_keys = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        matched_key = None
        for key in updates:
            if stripped.startswith(f"{key}="):
                matched_key = key
                break

        if matched_key:
            updated_keys.add(matched_key)
            val = updates[matched_key].strip()
            if val:
                new_lines.append(f"{matched_key}={val}\n")
        else:
            new_lines.append(line)

    for key, val in updates.items():
        if key not in updated_keys and val.strip():
            new_lines.append(f"{key}={val.strip()}\n")

    with open(env_path, "w") as f:
        f.writelines(new_lines)


class FyersTokenManager:
    """Manages the server-side lifecycle of FYERS access and refresh tokens."""

    def __init__(self):
        self.token_store_path = FYERS.token_store_path
        self.token_store_path.parent.mkdir(parents=True, exist_ok=True)

        self.access_token: str = ""
        self.refresh_token: str = ""
        self.expires_at: float = 0.0
        self.status: str = FYERS_REAUTH_REQUIRED
        self.last_error: str = ""

        self.reload_and_verify()

    def load_tokens(self) -> bool:
        """Loads stored tokens from server-side JSON store or environment variables."""
        FYERS.reload()
        # 1. Check local JSON store
        if self.token_store_path.exists():
            try:
                with open(self.token_store_path, "r") as f:
                    data = json.load(f)
                    self.access_token = data.get("access_token", "").strip()
                    self.refresh_token = data.get("refresh_token", "").strip()
                    self.expires_at = float(data.get("expires_at", 0.0))
            except Exception as e:
                logger.warning("Error reading server-side token store: %s", e)

        # 2. Fallback to .env if JSON store empty
        if not self.access_token and FYERS.access_token:
            self.access_token = FYERS.access_token
        if not self.refresh_token and FYERS.refresh_token:
            self.refresh_token = FYERS.refresh_token

        return bool(self.access_token or self.refresh_token)

    def save_tokens(self, access_token: str, refresh_token: str = "", expires_in: int = 86400):
        """Persists access token and refresh token server-side and updates environment file."""
        self.access_token = access_token.strip()
        if refresh_token.strip():
            self.refresh_token = refresh_token.strip()

        self.expires_at = time.time() + float(expires_in)

        # Save to server-side JSON file (excluded from git/frontend)
        token_data = {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "updated_at": time.time()
        }
        with open(self.token_store_path, "w") as f:
            json.dump(token_data, f, indent=2)

        # Sync to .env for fallback
        env_updates = {"FYERS_ACCESS_TOKEN": self.access_token}
        if self.refresh_token:
            env_updates["FYERS_REFRESH_TOKEN"] = self.refresh_token
        _update_env_file(env_updates)
        FYERS.reload()

        self.status = FYERS_AUTHENTICATED
        logger.info("[INFO] FYERS authentication loaded & tokens securely saved server-side.")

    def is_access_token_valid(self) -> bool:
        """Returns True if access token is present and not expired (with 5-minute safety buffer)."""
        if not self.access_token:
            return False
        if self.expires_at > 0 and time.time() >= (self.expires_at - 300):
            return False
        return True

    def refresh_access_token(self) -> bool:
        """Attempts automatic access token renewal using stored refresh token via official FYERS API."""
        if not FYERS.app_id or not FYERS.secret_key:
            self.status = FYERS_REAUTH_REQUIRED
            self.last_error = "Missing FYERS_APP_ID or FYERS_SECRET_KEY in environment."
            logger.warning("[WARNING] Cannot refresh FYERS token: missing App ID or Secret Key.")
            return False

        if not self.refresh_token:
            self.status = FYERS_REAUTH_REQUIRED
            self.last_error = "No refresh token available server-side."
            logger.info("[INFO] Refresh token not present server-side. Re-authentication required.")
            return False

        try:
            logger.info("[INFO] Access token expired. Refreshing FYERS access token automatically...")
            from fyers_apiv3 import fyersModel
            import hashlib

            app_id_hash = hashlib.sha256(f"{FYERS.app_id}:{FYERS.secret_key}".encode()).hexdigest()
            session = fyersModel.SessionModel(
                client_id=FYERS.app_id,
                secret_key=FYERS.secret_key,
                redirect_uri=FYERS.redirect_url,
                response_type="code",
                grant_type="refresh_token"
            )
            session.set_token(self.refresh_token)
            response = session.generate_token()

            if isinstance(response, dict) and response.get("s") == "ok" and response.get("access_token"):
                new_access_token = response["access_token"]
                new_refresh_token = response.get("refresh_token", self.refresh_token)
                expires_in = response.get("expires_in", 86400)
                self.save_tokens(new_access_token, new_refresh_token, expires_in=expires_in)
                logger.info("[INFO] FYERS access token refreshed successfully!")
                return True
            else:
                error_msg = response.get("message", str(response)) if isinstance(response, dict) else str(response)
                logger.info("[INFO] FYERS refresh token expired or invalid (%s). Cleared tokens for clean offline fallback mode.", error_msg)
                self.access_token = ""
                self.refresh_token = ""
                self.status = FYERS_REAUTH_REQUIRED
                self.last_error = f"Re-authentication required: {error_msg}"
                _save_env_updates({"FYERS_ACCESS_TOKEN": "", "FYERS_REFRESH_TOKEN": ""})
                return False
        except Exception as e:
            logger.error("[ERROR] Token refresh failed: %s", e)
            self.status = FYERS_AUTH_ERROR
            self.last_error = str(e)
            return False

    def exchange_code_for_tokens(self, auth_code: str) -> str:
        """Exchanges initial auth_code for access_token and refresh_token, saving them server-side."""
        if not FYERS.app_id or not FYERS.secret_key:
            raise ValueError("FYERS_APP_ID and FYERS_SECRET_KEY must be set in environment.")

        from fyers_apiv3 import fyersModel

        session = fyersModel.SessionModel(
            client_id=FYERS.app_id,
            secret_key=FYERS.secret_key,
            redirect_uri=FYERS.redirect_url,
            response_type="code",
            grant_type="authorization_code"
        )
        session.set_token(auth_code)
        response = session.generate_token()

        if isinstance(response, dict) and response.get("s") == "ok" and response.get("access_token"):
            access_token = response["access_token"]
            refresh_token = response.get("refresh_token", "")
            expires_in = response.get("expires_in", 86400)
            self.save_tokens(access_token, refresh_token, expires_in=expires_in)
            return access_token
        else:
            msg = response.get("message", str(response)) if isinstance(response, dict) else str(response)
            self.status = FYERS_AUTH_ERROR
            self.last_error = msg
            raise RuntimeError(f"FYERS token generation failed: {msg}")

    def reload_and_verify(self) -> str:
        """Startup check: loads stored tokens, validates access token, or automatically refreshes token."""
        self.load_tokens()

        if not FYERS.app_id:
            self.status = FYERS_REAUTH_REQUIRED
            self.last_error = "FYERS_APP_ID not configured."
            return self.status

        if self.is_access_token_valid():
            self.status = FYERS_AUTHENTICATED
            logger.info("[INFO] FYERS access token is valid and active.")
            return self.status

        # Access token missing or expired -> attempt refresh if refresh token present
        if self.refresh_token:
            if self.refresh_access_token():
                return self.status

        self.status = FYERS_REAUTH_REQUIRED
        self.last_error = "Re-authentication required. Access token expired and no valid refresh token."
        logger.info("[INFO] FYERS authentication status: %s", self.status)
        return self.status

    def get_auth_status(self) -> Dict[str, Any]:
        """Returns safe user-friendly authentication status dict for backend API responses without leaking secrets/tokens."""
        return {
            "status": self.status,
            "is_authenticated": (self.status == FYERS_AUTHENTICATED),
            "app_id_configured": bool(FYERS.app_id),
            "has_access_token": bool(self.access_token),
            "has_refresh_token": bool(self.refresh_token),
            "last_error": self.last_error if self.status != FYERS_AUTHENTICATED else ""
        }


# Global Singleton Manager Instance
_token_manager_instance: FyersTokenManager | None = None

def get_token_manager() -> FyersTokenManager:
    global _token_manager_instance
    if _token_manager_instance is None:
        _token_manager_instance = FyersTokenManager()
    return _token_manager_instance
