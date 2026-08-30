"""Demo employee-ID/password sign-in and seeded-directory access."""
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from app.api.deps import (
    COOKIE_NAME,
    get_current_administrator,
    get_current_employee,
    is_valid_admin_credentials,
    is_valid_demo_password,
    is_valid_employee_id,
    make_admin_session_cookie,
    make_session_cookie,
)
from app.org import service as org
from app.org.client import OrgUnavailableError

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    employee_id: str
    password: str = Field(min_length=1, max_length=128)


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=128)


@router.post("/login")
async def login(body: LoginRequest, response: Response):
    employee_id = body.employee_id.strip().upper()
    if not is_valid_employee_id(employee_id):
        raise HTTPException(status_code=400, detail="employee id must look like EMP-001")
    if not is_valid_demo_password(employee_id, body.password):
        raise HTTPException(status_code=401, detail="invalid employee ID or password")
    profile = None
    try:
        profile = await org.get_employee_org_context(employee_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="unknown employee")
    except OrgUnavailableError:
        profile = None  # directory down: allow demo login, profile resolves later
    response.set_cookie(
        COOKIE_NAME, make_session_cookie(employee_id),
        httponly=True, samesite="lax", max_age=60 * 60 * 12,
    )
    return {"employee_id": employee_id, "profile": profile}


@router.post("/admin/login")
async def admin_login(body: AdminLoginRequest, response: Response):
    username = body.username.strip()
    if not is_valid_admin_credentials(username, body.password):
        raise HTTPException(status_code=401, detail="invalid administrator credentials")
    response.set_cookie(
        COOKIE_NAME,
        make_admin_session_cookie(username),
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 12,
    )
    return {"username": username, "role": "administrator"}


@router.get("/admin/me")
async def admin_me(username: str = Depends(get_current_administrator)):
    return {"username": username, "role": "administrator"}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@router.get("/me")
async def me(employee_id: str = Depends(get_current_employee)):
    try:
        profile = await org.get_employee_org_context(employee_id)
    except OrgUnavailableError:
        profile = None
    return {"employee_id": employee_id, "profile": profile}


@router.get("/directory")
async def directory():
    try:
        return {"employees": await org.get_directory()}
    except OrgUnavailableError:
        return {"employees": []}
