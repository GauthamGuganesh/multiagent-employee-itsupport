"""Server-side mapping from internal events to employee-friendly progress copy.

The employee UI never sees node names, cycles, or tool traces — only these
strings. Returning None means the event is internal and not shown to the
employee at all.
"""
from typing import Any

AGENT_COPY = {
    "identity": "Checking your account…",
    "endpoint": "Looking at your device…",
    "network": "Running network diagnostics…",
    "security": "Reviewing security signals…",
    "supervisor": None,  # routing itself is invisible
}

TOOL_COPY = {
    "get_account_status": "Checking your account status…",
    "get_recent_auth_events": "Reviewing recent sign-in activity…",
    "unlock_account": "Unlocking your account…",
    "reset_password": "Preparing a password reset…",
    "revoke_sessions": "Signing out your active sessions…",
    "get_device_details": "Looking up your device…",
    "run_device_health_check": "Running a device health check…",
    "check_disk_space": "Checking disk space…",
    "install_approved_software": "Installing the software…",
    "restart_managed_service": "Restarting the service…",
    "check_vpn_status": "Checking VPN status…",
    "run_connectivity_diagnostics": "Running connectivity diagnostics…",
    "check_dns": "Checking DNS…",
    "check_proxy": "Checking proxy settings…",
    "inspect_recent_vpn_session": "Reviewing recent VPN sessions…",
    "get_recent_security_events": "Reviewing security events…",
    "revoke_active_sessions": "Signing out your active sessions…",
    "quarantine_device": "Isolating the device…",
    "flag_account_for_security_review": "Flagging for security review…",
    "notify_security_team": "Notifying the security team…",
    "create_ticket": "Creating your ticket…",
    "get_ticket_status": "Looking up your ticket…",
    "update_ticket": "Updating your ticket…",
}


def friendly_copy(event: dict[str, Any]) -> str | None:
    etype = event.get("event_type")
    payload = event.get("payload") or {}
    if etype == "SUPERVISOR_DECISION":
        return "Understanding your request…" if payload.get("cycle") == 1 else None
    if etype == "AGENT_STARTED":
        return AGENT_COPY.get(event.get("actor") or "")
    if etype == "TOOL_CALLED":
        return TOOL_COPY.get(payload.get("tool") or "")
    if etype == "APPROVAL_REQUESTED":
        return "Preparing an approval request…"
    if etype == "ESCALATION_TRIGGERED":
        return "Bringing in the right people…"
    if etype == "USER_CONFIRMATION_REQUESTED":
        return "Verifying access…"
    if etype == "MEMORY_RETRIEVED":
        return "Checking past conversations…"
    return None
