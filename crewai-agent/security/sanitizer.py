import os
import re
import html
import logging
import bleach
from functools import wraps
from flask import session, redirect, url_for, request, abort


SENSITIVE_PATTERNS = re.compile(
    r'(password|passwd|secret|api_key|apikey|token|auth|credential|bearer|private_key|'
    r'access_key|secret_key|client_secret|private|ssn|credit.?card)',
    re.IGNORECASE
)

PROMPT_INJECTION_PATTERNS = re.compile(
    r'(ignore\s+previous|disregard\s+(all|the|your)|forget\s+(everything|all|your)|'
    r'you\s+are\s+now|act\s+as\s+if|pretend\s+(you\s+are|to\s+be)|jailbreak|'
    r'do\s+anything\s+now|DAN\s+mode|bypass\s+(your|the)\s+restrict|'
    r'system\s*:\s*you\s+are|<\s*system\s*>|<\s*\/system\s*>)',
    re.IGNORECASE
)

ALLOWED_TAGS: list = []
ALLOWED_ATTRS: dict = {}


def sanitize_input(text: str, max_length: int = 4096) -> str:
    if not isinstance(text, str):
        text = str(text)

    text = text[:max_length]

    text = bleach.clean(text, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)

    text = html.escape(text)

    if PROMPT_INJECTION_PATTERNS.search(text):
        raise ValueError("Input contains potentially malicious prompt injection content.")

    return text.strip()


def mask_secrets(text: str) -> str:
    if not isinstance(text, str):
        text = str(text)

    env_vars_to_mask = [
        "GROQ_API_KEY", "GEMINI_API_KEY", "DASHBOARD_PASSWORD",
        "FLASK_SECRET_KEY", "ADZUNA_APP_KEY", "ADZUNA_APP_ID",
        "SENDER_PASSWORD", "SMTP_SERVER", "SENDER_EMAIL",
    ]
    for key in env_vars_to_mask:
        value = os.getenv(key, "")
        if value and len(value) > 4:
            text = text.replace(value, f"[MASKED:{key}]")

    text = re.sub(
        r'((?:api[_-]?key|secret|token|password|bearer)["\s:=]+)[A-Za-z0-9\-_\.]{8,}',
        r'\1[REDACTED]',
        text,
        flags=re.IGNORECASE
    )

    if SENSITIVE_PATTERNS.search(text):
        text = re.sub(
            r'((?:' + SENSITIVE_PATTERNS.pattern + r')["\s:=]+)[^\s\'"&,;]{4,}',
            r'\1[MASKED]',
            text,
            flags=re.IGNORECASE
        )

    return text


class SecureLogger(logging.Logger):
    def _log_masked(self, level: int, msg: object, *args, **kwargs):
        safe_msg = mask_secrets(str(msg))
        safe_args = tuple(mask_secrets(str(a)) for a in args) if args else args
        super().log(level, safe_msg, *safe_args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self._log_masked(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self._log_masked(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self._log_masked(logging.ERROR, msg, *args, **kwargs)

    def debug(self, msg, *args, **kwargs):
        self._log_masked(logging.DEBUG, msg, *args, **kwargs)


def get_secure_logger(name: str) -> SecureLogger:
    logging.setLoggerClass(SecureLogger)
    logger = logging.getLogger(name)
    logging.setLoggerClass(logging.Logger)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger  # type: ignore[return-value]


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login", next=request.url))
        return f(*args, **kwargs)
    return decorated


def validate_auth_token(token: str) -> bool:
    expected = os.getenv("DASHBOARD_PASSWORD", "")
    if not expected:
        return False
    return token == expected
