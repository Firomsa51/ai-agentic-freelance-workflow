import os
import httpx
from functools import wraps
from flask import request, jsonify, g
from security.sanitizer import get_secure_logger

logger = get_secure_logger(__name__)

CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY", "")
CLERK_API_BASE = "https://api.clerk.com/v1"


def verify_clerk_token(token: str) -> dict | None:
    """Verify a Clerk session token and return user data."""
    if not CLERK_SECRET_KEY:
        logger.error("CLERK_SECRET_KEY not set.")
        return None
    try:
        resp = httpx.get(
            f"{CLERK_API_BASE}/sessions/{token}/verify",
            headers={
                "Authorization": f"Bearer {CLERK_SECRET_KEY}",
                "Content-Type": "application/json",
            },
            timeout=5,
        )
        if resp.status_code == 200:
            return resp.json()
        logger.warning(f"Clerk token verification failed: {resp.status_code}")
        return None
    except Exception as e:
        logger.error(f"Clerk verification error: {e}")
        return None


def get_user_from_request() -> dict | None:
    """Extract and verify user from Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        return None
    return verify_clerk_token(token)


def api_login_required(f):
    """Decorator for API routes — returns JSON errors, not redirects."""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_user_from_request()
        if not user:
            return jsonify({
                "error": "Unauthorized",
                "message": "Valid Bearer token required."
            }), 401
        # Store user in Flask g for use in route
        g.user_id = user.get("user_id") or user.get("id", "")
        g.user_email = user.get("email_addresses", [{}])[0].get(
            "email_address", ""
        ) if isinstance(user.get("email_addresses"), list) else ""
        return f(*args, **kwargs)
    return decorated


def ensure_user_exists(user_id: str, email: str) -> None:
    """Create user record in DB if not already present."""
    from database import get_conn
    from datetime import datetime
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (id, email, created_at, tier, is_active)
                    VALUES (%s, %s, %s, 'free', true)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (user_id, email, datetime.utcnow().isoformat())
                )
    except Exception as e:
        logger.error(f"ensure_user_exists failed: {e}")
