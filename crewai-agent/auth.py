import os
import jwt
from jwt import PyJWKClient
from functools import wraps
from flask import request, jsonify, g
from security.sanitizer import get_secure_logger

logger = get_secure_logger(__name__)

CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY", "")
CLERK_JWKS_URL = os.getenv(
    "CLERK_JWKS_URL",
    "https://faithful-oryx-81.clerk.accounts.dev/.well-known/jwks.json"
)

_jwks_client = None

def get_jwks_client():
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(CLERK_JWKS_URL, cache_keys=True)
    return _jwks_client

def verify_clerk_token(token: str) -> dict | None:
    if not token:
        return None
    try:
        client = get_jwks_client()
        signing_key = client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={
                "verify_exp": True,
                "verify_aud": False,
            },
        )
        logger.info(f"Token verified for sub: {payload.get('sub')}")
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("Token expired.")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Token invalid: {e}")
        return None
    except Exception as e:
        logger.error(f"JWKS error: {type(e).__name__}: {e}")
        return None

def get_user_from_request() -> dict | None:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ", 1)[1].strip()
    if not token or token == "null":
        return None
    return verify_clerk_token(token)

def api_login_required(f):
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
