"""Network-domain tools over the mock world (VPN and connectivity).

All five tools are read-only diagnostics — none mutate state, so none are
privileged. inspect_recent_vpn_session deliberately surfaces any flagged or
unrecognized client IP in its summary so the specialist cannot miss the
security signal and can hand off to the security domain.
"""
from typing import Any

from pydantic import BaseModel

from app.org import keys
from app.tools.mockworld import get_world
from app.tools.registry import ToolContext, ToolSpec, register


class CheckVpnStatusInput(BaseModel):
    employee_id: str


class CheckVpnStatusOutput(BaseModel):
    employee_id: str
    connected: bool
    gateway: str
    drops_last_24h: int
    summary: str


async def _check_vpn_status(inp: CheckVpnStatusInput, ctx: ToolContext) -> CheckVpnStatusOutput:
    vpn = get_world().state_for(inp.employee_id)["vpn"]
    state = "connected" if vpn["connected"] else "disconnected"
    return CheckVpnStatusOutput(
        employee_id=inp.employee_id,
        connected=vpn["connected"],
        gateway=vpn["gateway"],
        drops_last_24h=vpn["drops_last_24h"],
        summary=(
            f"VPN for {inp.employee_id} is {state} via gateway {vpn['gateway']} "
            f"with {vpn['drops_last_24h']} drop(s) in the last 24 hours."
        ),
    )


register(
    ToolSpec(
        name="check_vpn_status",
        description=(
            "Check the employee's current VPN state: connected or not, which "
            "gateway they use, and how many times the tunnel dropped in the "
            "last 24 hours. Read-only."
        ),
        domain="network",
        input_model=CheckVpnStatusInput,
        output_model=CheckVpnStatusOutput,
        handler=_check_vpn_status,
        system_key=keys.SYSTEM_VPN,
    )
)


class RunConnectivityDiagnosticsInput(BaseModel):
    employee_id: str


class RunConnectivityDiagnosticsOutput(BaseModel):
    employee_id: str
    latency_ms: int
    packet_loss_pct: int
    gateway_reachable: bool
    summary: str


async def _run_connectivity_diagnostics(
    inp: RunConnectivityDiagnosticsInput, ctx: ToolContext
) -> RunConnectivityDiagnosticsOutput:
    network = get_world().state_for(inp.employee_id)["network"]
    return RunConnectivityDiagnosticsOutput(
        employee_id=inp.employee_id,
        latency_ms=network["latency_ms"],
        packet_loss_pct=network["packet_loss_pct"],
        gateway_reachable=network["gateway_reachable"],
        summary=(
            f"Connectivity diagnostics for {inp.employee_id}: latency "
            f"{network['latency_ms']} ms, packet loss {network['packet_loss_pct']}%, "
            f"gateway {'reachable' if network['gateway_reachable'] else 'unreachable'}."
        ),
    )


register(
    ToolSpec(
        name="run_connectivity_diagnostics",
        description=(
            "Run basic connectivity diagnostics from the employee's device: "
            "latency in milliseconds, packet loss percentage, and whether the "
            "network gateway is reachable. Read-only."
        ),
        domain="network",
        input_model=RunConnectivityDiagnosticsInput,
        output_model=RunConnectivityDiagnosticsOutput,
        handler=_run_connectivity_diagnostics,
    )
)


class CheckDnsInput(BaseModel):
    employee_id: str


class CheckDnsOutput(BaseModel):
    employee_id: str
    dns_ok: bool
    resolver: str
    summary: str


async def _check_dns(inp: CheckDnsInput, ctx: ToolContext) -> CheckDnsOutput:
    network = get_world().state_for(inp.employee_id)["network"]
    return CheckDnsOutput(
        employee_id=inp.employee_id,
        dns_ok=network["dns_ok"],
        resolver=network["dns_resolver"],
        summary=(
            f"DNS resolution for {inp.employee_id} is "
            f"{'working' if network['dns_ok'] else 'failing'} via resolver "
            f"{network['dns_resolver']}."
        ),
    )


register(
    ToolSpec(
        name="check_dns",
        description=(
            "Check whether DNS resolution works from the employee's device and "
            "which resolver it is configured to use. Read-only."
        ),
        domain="network",
        input_model=CheckDnsInput,
        output_model=CheckDnsOutput,
        handler=_check_dns,
    )
)


class CheckProxyInput(BaseModel):
    employee_id: str


class CheckProxyOutput(BaseModel):
    employee_id: str
    proxy_configured: bool
    proxy_reachable: bool
    summary: str


async def _check_proxy(inp: CheckProxyInput, ctx: ToolContext) -> CheckProxyOutput:
    network = get_world().state_for(inp.employee_id)["network"]
    if not network["proxy_configured"]:
        summary = f"No proxy is configured on the device for {inp.employee_id}."
    else:
        summary = (
            f"Proxy is configured for {inp.employee_id} and is "
            f"{'reachable' if network['proxy_reachable'] else 'unreachable'}."
        )
    return CheckProxyOutput(
        employee_id=inp.employee_id,
        proxy_configured=network["proxy_configured"],
        proxy_reachable=network["proxy_reachable"],
        summary=summary,
    )


register(
    ToolSpec(
        name="check_proxy",
        description=(
            "Check whether a web proxy is configured on the employee's device "
            "and, if so, whether it is reachable. Read-only."
        ),
        domain="network",
        input_model=CheckProxyInput,
        output_model=CheckProxyOutput,
        handler=_check_proxy,
    )
)


class InspectRecentVpnSessionInput(BaseModel):
    employee_id: str


class InspectRecentVpnSessionOutput(BaseModel):
    employee_id: str
    sessions: list[dict[str, Any]]
    flagged_count: int
    summary: str


async def _inspect_recent_vpn_session(
    inp: InspectRecentVpnSessionInput, ctx: ToolContext
) -> InspectRecentVpnSessionOutput:
    sessions = [
        dict(s) for s in get_world().state_for(inp.employee_id)["vpn"]["recent_sessions"]
    ]
    flagged = [s for s in sessions if s.get("flagged")]
    if flagged:
        details = "; ".join(
            f"session at {s['started_at']} from unrecognized IP {s['client_ip']}"
            + (f" ({s['note']})" if s.get("note") else "")
            for s in flagged
        )
        summary = (
            f"Inspected {len(sessions)} recent VPN session(s) for {inp.employee_id}: "
            f"{len(flagged)} FLAGGED — {details}. This does not match the "
            "employee's usual network and warrants a security review."
        )
    else:
        summary = (
            f"Inspected {len(sessions)} recent VPN session(s) for {inp.employee_id}; "
            "none flagged — all client IPs match the employee's usual network."
        )
    return InspectRecentVpnSessionOutput(
        employee_id=inp.employee_id,
        sessions=sessions,
        flagged_count=len(flagged),
        summary=summary,
    )


register(
    ToolSpec(
        name="inspect_recent_vpn_session",
        description=(
            "Inspect the employee's recent VPN sessions: start time, duration, "
            "client IP, gateway, and a flagged marker with a note for sessions "
            "from unrecognized networks. Returns the flagged count and calls "
            "out any suspicious client IP explicitly. Read-only."
        ),
        domain="network",
        input_model=InspectRecentVpnSessionInput,
        output_model=InspectRecentVpnSessionOutput,
        handler=_inspect_recent_vpn_session,
        system_key=keys.SYSTEM_VPN,
    )
)
