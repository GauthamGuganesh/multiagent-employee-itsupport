"""Demo-grade authentication: sign-in-as-employee with a signed cookie.

This is intentionally not production auth (documented in README) — the point
of the platform is what happens AFTER authentication. Voice confirms intent,
never identity: identity comes only from this session cookie.
"""
import hmac
import re

from fastapi import Cookie, HTTPException
from itsdangerous import BadSignature, URLSafeSerializer

from app.config import get_settings

COOKIE_NAME = "it_session"
_EMP_RE = re.compile(r"^EMP-\d{3}$")


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().session_secret, salt="it-support-session")


def make_session_cookie(employee_id: str) -> str:
    return _serializer().dumps({"employee_id": employee_id})


def make_admin_session_cookie(username: str) -> str:
    return _serializer().dumps({"principal_type": "administrator", "username": username})


def is_valid_employee_id(employee_id: str) -> bool:
    return bool(_EMP_RE.match(employee_id))


def is_valid_demo_password(employee_id: str, password: str) -> bool:
    """Validate the documented, deterministic credentials for this portfolio demo.

    This deliberately is not a production password scheme. It lets every
    seeded employee use ``gavoiceai-<three digit employee number>`` without
    storing a password or exposing one in session state.
    """
    if not is_valid_employee_id(employee_id):
        return False
    suffix = employee_id.rsplit("-", maxsplit=1)[-1]
    expected = f"{get_settings().demo_password_prefix}{suffix}"
    return hmac.compare_digest(password, expected)


def is_valid_admin_credentials(username: str, password: str) -> bool:
    """Validate the documented, dedicated Command Center demo credential."""
    settings = get_settings()
    return hmac.compare_digest(username, settings.admin_username) and hmac.compare_digest(
        password, settings.admin_password
    )


def _session_data(it_session: str | None) -> dict[str, object]:
    if not it_session:
        raise HTTPException(status_code=401, detail="not signed in")
    try:
        data = _serializer().loads(it_session)
    except BadSignature as exc:
        raise HTTPException(status_code=401, detail="invalid session") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=401, detail="invalid session")
    return data


def get_current_employee(it_session: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> str:
    data = _session_data(it_session)
    if data.get("principal_type") == "administrator":
        raise HTTPException(status_code=401, detail="employee session required")
    employee_id = data.get("employee_id", "")
    if not isinstance(employee_id, str) or not is_valid_employee_id(employee_id):
        raise HTTPException(status_code=401, detail="invalid session")
    return employee_id


def get_current_administrator(it_session: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> str:
    data = _session_data(it_session)
    username = data.get("username", "")
    if data.get("principal_type") != "administrator" or not isinstance(username, str):
        raise HTTPException(status_code=401, detail="administrator session required")
    if not hmac.compare_digest(username, get_settings().admin_username):
        raise HTTPException(status_code=401, detail="invalid session")
    return username
