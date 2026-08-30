import pytest
from fastapi import HTTPException

from app.api.routes_voice import create_bridge_token, resolve_bridge_token


def test_voice_bridge_token_resolves_authenticated_employee():
    token = create_bridge_token("EMP-032")

    assert resolve_bridge_token(token) == "EMP-032"


def test_voice_bridge_token_rejects_tampering():
    token = create_bridge_token("EMP-032")

    with pytest.raises(HTTPException, match="invalid or expired voice bridge token"):
        resolve_bridge_token(f"{token}tampered")
