import os
import jwt
import httpx
from functools import wraps
from flask import request, jsonify, g
from security.sanitizer import get_secure_logger

logger = get_secure_logger(__name__)

CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY", "")
CLERK_JWKS_URL = "https://api.clerk.com/v1/jwks"

_jwks_client = None

def get_jwks_client():
    global _jwks_client
    if _jwks_client is None:
        from jwt import PyJWKClient
        _jwks_client = PyJWKClient(CLERK_JWKS_URL)
    return _jwks_client

def verify_clerk_token(token: str) -> dict | None:
    """Verify a Clerk JWT token and return the payload."""
    if not CLERK_SECRET_KEY:
        logger.error("CLERK_SECRET_KEY not set.")
        return None
    try:
        client = get_jwks_client()
        signing_key = client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_exp": True},
        )
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("Clerk token expired.")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Clerk token invalid: {e}")
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
        g.user_id = user.get("sub", "")
        g.user_email = user.get("email", "")
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
