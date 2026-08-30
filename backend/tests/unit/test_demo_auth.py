"""Tests for the documented portfolio-demo credential policy."""

import pytest
from fastapi import HTTPException, Response

from app.api.deps import is_valid_demo_password
from app.api.routes_auth import LoginRequest, login


def test_demo_password_matches_employee_suffix():
    assert is_valid_demo_password("EMP-032", "gavoiceai-032")


def test_demo_password_rejects_wrong_employee_or_secret():
    assert not is_valid_demo_password("EMP-032", "gavoiceai-031")
    assert not is_valid_demo_password("EMP-032", "incorrect")
    assert not is_valid_demo_password("EMP-32", "gavoiceai-032")


@pytest.mark.asyncio
async def test_login_accepts_documented_credentials_and_sets_session(monkeypatch):
    async def profile(_: str):
        return {"id": "EMP-032", "name": "Chloe Bennett"}

    monkeypatch.setattr("app.api.routes_auth.org.get_employee_org_context", profile)
    response = Response()
    result = await login(LoginRequest(employee_id="emp-032", password="gavoiceai-032"), response)

    assert result["employee_id"] == "EMP-032"
    assert "it_session=" in response.headers["set-cookie"]


@pytest.mark.asyncio
async def test_login_rejects_incorrect_password():
    with pytest.raises(HTTPException, match="invalid employee ID or password"):
        await login(LoginRequest(employee_id="EMP-032", password="wrong"), Response())


@pytest.mark.asyncio
async def test_landing_login_accepts_administrator_without_employee_id_validation():
    response = Response()

    result = await login(LoginRequest(employee_id="admin", password="ga-voiceai-admin"), response)

    assert result == {"username": "admin", "role": "administrator"}
    assert "it_session=" in response.headers["set-cookie"]
