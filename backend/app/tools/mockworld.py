"""Deterministic in-memory world state powering all mock tools.

Constraints: no randomness and no wall-clock reads — per-employee variation is
derived from the numeric tail of the employee ID and all timestamps are fixed
literals, so every run and test sees identical evidence. State mutates only
through the named mutators invoked by registered tools; reads never mutate.
Notable-employee scenarios (locked account, VPN compromise, full disk) are
keyed by the canonical IDs in app.org.keys.
"""
from typing import Any, Callable

from app.org import keys

# Fixed timestamp stamped on state changes performed by tools during a demo.
_ACTION_AT = "2026-08-29T10:00:00Z"


def _seed(employee_id: str) -> int:
    try:
        return int(employee_id[-3:])
    except ValueError:
        return sum(ord(c) for c in employee_id) % 1000


def _home_ip(employee_id: str) -> str:
    n = _seed(employee_id)
    return f"10.20.{n % 250}.{10 + n % 200}"


def _home_location(employee_id: str) -> str:
    return "Bangalore, IN" if _seed(employee_id) % 2 == 0 else "Chennai, IN"


def _default_profile(employee_id: str) -> dict[str, Any]:
    n = _seed(employee_id)
    ip = _home_ip(employee_id)
    location = _home_location(employee_id)
    windows = n % 2 == 0
    gateway = "vpn-blr-1" if windows else "vpn-maa-1"
    return {
        "account": {
            "status": "active",
            "locked_reason": None,
            "mfa_enrolled": True,
            "last_password_change_days": 20 + n % 60,
            "active_sessions": 1 + n % 3,
        },
        "auth_events": [
            {
                "at": "2026-08-28T18:05:00Z",
                "event": "login",
                "ip": ip,
                "location": location,
                "success": True,
                "unusual": False,
            },
            {
                "at": "2026-08-29T08:12:00Z",
                "event": "login",
                "ip": ip,
                "location": location,
                "success": True,
                "unusual": False,
            },
            {
                "at": "2026-08-29T08:12:05Z",
                "event": "mfa_challenge",
                "ip": ip,
                "location": location,
                "success": True,
                "unusual": False,
            },
        ],
        "device": {
            "device_id": f"DEV-{employee_id[-3:]}",
            "model": "ThinkPad X1 Carbon" if windows else "MacBook Pro 14",
            "os": "Windows 11" if windows else "macOS 15",
            "os_version": "23H2" if windows else "15.3",
            "disk_used_pct": 40 + n % 25,
            "free_gb": 120 + n % 80,
            "cpu_pct": 10 + n % 20,
            "memory_pct": 35 + n % 25,
            "health_issues": [],
            "managed": True,
            "installed_software": ["Slack", "Zoom", "Chrome", "VS Code"],
            "services": {
                "mdm-agent": "running",
                "av-scanner": "running",
                "update-service": "running",
            },
        },
        "vpn": {
            "connected": True,
            "gateway": gateway,
            "drops_last_24h": 0,
            "recent_sessions": [
                {
                    "started_at": "2026-08-28T09:00:00Z",
                    "duration_min": 470,
                    "client_ip": ip,
                    "gateway": gateway,
                    "flagged": False,
                    "note": "",
                },
                {
                    "started_at": "2026-08-29T08:15:00Z",
                    "duration_min": 105,
                    "client_ip": ip,
                    "gateway": gateway,
                    "flagged": False,
                    "note": "",
                },
            ],
        },
        "network": {
            "latency_ms": 18 + n % 15,
            "packet_loss_pct": 0,
            "gateway_reachable": True,
            "dns_ok": True,
            "dns_resolver": "10.20.0.53",
            "proxy_configured": False,
            "proxy_reachable": True,
        },
        "security_events": [],
        "security_flags": [],
        "notifications": [],
    }


def _scenario_locked_out(profile: dict[str, Any]) -> None:
    account = profile["account"]
    account["status"] = "locked"
    account["locked_reason"] = "too many failed password attempts"
    ip = profile["auth_events"][0]["ip"]
    location = profile["auth_events"][0]["location"]
    profile["auth_events"].extend(
        {
            "at": f"2026-08-29T08:5{i}:00Z",
            "event": "login",
            "ip": ip,
            "location": location,
            "success": False,
            "unusual": False,
        }
        for i in range(5)
    )


def _scenario_vpn_suspect(profile: dict[str, Any]) -> None:
    home_ip = profile["auth_events"][0]["ip"]
    vpn = profile["vpn"]
    gateway = vpn["gateway"]
    vpn["connected"] = False
    vpn["drops_last_24h"] = 7
    vpn["recent_sessions"] = [
        {
            "started_at": "2026-08-28T09:02:00Z",
            "duration_min": 460,
            "client_ip": home_ip,
            "gateway": gateway,
            "flagged": False,
            "note": "",
        },
        {
            "started_at": "2026-08-29T08:20:00Z",
            "duration_min": 41,
            "client_ip": home_ip,
            "gateway": gateway,
            "flagged": False,
            "note": "",
        },
        {
            "started_at": "2026-08-29T03:37:00Z",
            "duration_min": 12,
            "client_ip": "203.0.113.42",
            "gateway": gateway,
            "flagged": True,
            "note": "geo mismatch: unrecognized network",
        },
    ]
    profile["auth_events"].extend(
        [
            {
                "at": "2026-08-29T03:36:00Z",
                "event": "login",
                "ip": "203.0.113.42",
                "location": "Unknown",
                "success": True,
                "unusual": True,
            },
            {
                "at": "2026-08-29T03:39:00Z",
                "event": "mfa_enroll",
                "ip": "203.0.113.42",
                "location": "Unknown",
                "success": True,
                "unusual": True,
                "detail": "new MFA device added",
            },
        ]
    )
    profile["security_events"].extend(
        [
            {
                "at": "2026-08-29T03:40:00Z",
                "type": "impossible_travel",
                "detail": "login from 203.0.113.42 minutes after activity from the usual network",
                "severity": "high",
            },
            {
                "at": "2026-08-29T03:41:00Z",
                "type": "new_mfa_device",
                "detail": "new MFA device added from unrecognized network 203.0.113.42",
                "severity": "medium",
            },
        ]
    )


def _scenario_slow_laptop(profile: dict[str, Any]) -> None:
    device = profile["device"]
    device["disk_used_pct"] = 96
    device["free_gb"] = 9
    device["cpu_pct"] = 88
    device["health_issues"] = [
        "disk nearly full",
        "update service consuming high CPU",
    ]


_SCENARIOS: dict[str, Callable[[dict[str, Any]], None]] = {
    keys.EMP_LOCKED_OUT: _scenario_locked_out,
    keys.EMP_VPN_SUSPECT: _scenario_vpn_suspect,
    keys.EMP_SLOW_LAPTOP: _scenario_slow_laptop,
}


class MockWorld:
    """Per-employee world state, lazily materialized and mutated only by tools."""

    def __init__(self) -> None:
        self._state: dict[str, dict[str, Any]] = {}

    def state_for(self, employee_id: str) -> dict[str, Any]:
        if employee_id not in self._state:
            profile = _default_profile(employee_id)
            scenario = _SCENARIOS.get(employee_id)
            if scenario is not None:
                scenario(profile)
            self._state[employee_id] = profile
        return self._state[employee_id]

    # --- Mutators (called only by registered tools) ---

    def unlock_account(self, employee_id: str) -> None:
        account = self.state_for(employee_id)["account"]
        account["status"] = "active"
        account["locked_reason"] = None

    def reset_password(self, employee_id: str) -> None:
        state = self.state_for(employee_id)
        state["account"]["last_password_change_days"] = 0
        state["auth_events"].append(
            {
                "at": _ACTION_AT,
                "event": "password_change",
                "ip": _home_ip(employee_id),
                "location": _home_location(employee_id),
                "success": True,
                "unusual": False,
            }
        )

    def revoke_sessions(self, employee_id: str) -> int:
        account = self.state_for(employee_id)["account"]
        revoked = account["active_sessions"]
        account["active_sessions"] = 0
        return revoked

    def install_software(self, employee_id: str, name: str) -> bool:
        installed = self.state_for(employee_id)["device"]["installed_software"]
        if name in installed:
            return False
        installed.append(name)
        return True

    def restart_service(self, employee_id: str, name: str) -> str:
        services = self.state_for(employee_id)["device"]["services"]
        if name not in services:
            raise ValueError(f"unknown service on device: {name}")
        services[name] = "running"
        return services[name]

    def quarantine_device(self, employee_id: str) -> None:
        state = self.state_for(employee_id)
        state["security_flags"].append("device-quarantined")
        state["device"]["health_issues"].append("device quarantined by security policy")

    def flag_account(self, employee_id: str, reason: str) -> None:
        self.state_for(employee_id)["security_flags"].append(reason)

    def notify_security(self, employee_id: str, summary: str) -> None:
        self.state_for(employee_id)["notifications"].append(
            {"at": _ACTION_AT, "team": keys.SUPPORT_SECURITY, "summary": summary}
        )


_world: MockWorld | None = None


def get_world() -> MockWorld:
    global _world
    if _world is None:
        _world = MockWorld()
    return _world


def reset_world() -> MockWorld:
    global _world
    _world = MockWorld()
    return _world
