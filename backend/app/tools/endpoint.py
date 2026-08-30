"""Endpoint-domain tools over the mock world (MDM-managed devices).

Read-only diagnostics (device details, health check, disk space) are
unprivileged; the mutating tools (software install, managed-service restart)
are privileged and run only through the confirmation/approval workflows via
the registry gate. The registry key on install_approved_software is the
baseline default — the confirmation workflow verifies the privilege named on
the RequestedAction (e.g. dev-tools-install for Docker Desktop) against Neo4j.
"""
from typing import Any

from pydantic import BaseModel

from app.org import keys
from app.tools.mockworld import get_world
from app.tools.registry import ToolContext, ToolSpec, register


class GetDeviceDetailsInput(BaseModel):
    employee_id: str


class GetDeviceDetailsOutput(BaseModel):
    employee_id: str
    device_id: str
    model: str
    os: str
    os_version: str
    managed: bool
    installed_software: list[str]
    services: dict[str, str]
    summary: str


async def _get_device_details(
    inp: GetDeviceDetailsInput, ctx: ToolContext
) -> GetDeviceDetailsOutput:
    device = get_world().state_for(inp.employee_id)["device"]
    return GetDeviceDetailsOutput(
        employee_id=inp.employee_id,
        device_id=device["device_id"],
        model=device["model"],
        os=device["os"],
        os_version=device["os_version"],
        managed=device["managed"],
        installed_software=list(device["installed_software"]),
        services=dict(device["services"]),
        summary=(
            f"Device {device['device_id']} ({device['model']}, {device['os']} "
            f"{device['os_version']}) assigned to {inp.employee_id} is "
            f"{'managed' if device['managed'] else 'unmanaged'} with "
            f"{len(device['installed_software'])} installed application(s)."
        ),
    )


register(
    ToolSpec(
        name="get_device_details",
        description=(
            "Look up the employee's assigned device: device ID, model, OS and "
            "version, MDM-managed flag, installed software, and the state of "
            "managed services. Read-only."
        ),
        domain="endpoint",
        input_model=GetDeviceDetailsInput,
        output_model=GetDeviceDetailsOutput,
        handler=_get_device_details,
        system_key=keys.SYSTEM_MDM,
    )
)


class RunDeviceHealthCheckInput(BaseModel):
    employee_id: str


class RunDeviceHealthCheckOutput(BaseModel):
    employee_id: str
    device_id: str
    cpu_pct: int
    memory_pct: int
    disk_used_pct: int
    health_issues: list[str]
    overall: str  # healthy | degraded | critical
    summary: str


async def _run_device_health_check(
    inp: RunDeviceHealthCheckInput, ctx: ToolContext
) -> RunDeviceHealthCheckOutput:
    device = get_world().state_for(inp.employee_id)["device"]
    issues = list(device["health_issues"])
    if device["disk_used_pct"] >= 95 or len(issues) > 2:
        overall = "critical"
    elif issues:
        overall = "degraded"
    else:
        overall = "healthy"
    if issues:
        summary = (
            f"Health check on {device['device_id']} for {inp.employee_id}: "
            f"{overall} — CPU {device['cpu_pct']}%, memory {device['memory_pct']}%, "
            f"disk {device['disk_used_pct']}% used; issues: {'; '.join(issues)}."
        )
    else:
        summary = (
            f"Health check on {device['device_id']} for {inp.employee_id}: "
            f"healthy — CPU {device['cpu_pct']}%, memory {device['memory_pct']}%, "
            f"disk {device['disk_used_pct']}% used; no issues found."
        )
    return RunDeviceHealthCheckOutput(
        employee_id=inp.employee_id,
        device_id=device["device_id"],
        cpu_pct=device["cpu_pct"],
        memory_pct=device["memory_pct"],
        disk_used_pct=device["disk_used_pct"],
        health_issues=issues,
        overall=overall,
        summary=summary,
    )


register(
    ToolSpec(
        name="run_device_health_check",
        description=(
            "Run a full health check on the employee's device: CPU, memory, and "
            "disk utilization plus any detected health issues, with an overall "
            "verdict of healthy, degraded, or critical. Read-only."
        ),
        domain="endpoint",
        input_model=RunDeviceHealthCheckInput,
        output_model=RunDeviceHealthCheckOutput,
        handler=_run_device_health_check,
        system_key=keys.SYSTEM_MDM,
    )
)


class CheckDiskSpaceInput(BaseModel):
    employee_id: str


class CheckDiskSpaceOutput(BaseModel):
    employee_id: str
    device_id: str
    disk_used_pct: int
    free_gb: int
    summary: str


async def _check_disk_space(inp: CheckDiskSpaceInput, ctx: ToolContext) -> CheckDiskSpaceOutput:
    device = get_world().state_for(inp.employee_id)["device"]
    return CheckDiskSpaceOutput(
        employee_id=inp.employee_id,
        device_id=device["device_id"],
        disk_used_pct=device["disk_used_pct"],
        free_gb=device["free_gb"],
        summary=(
            f"Disk on {device['device_id']} for {inp.employee_id} is "
            f"{device['disk_used_pct']}% used with {device['free_gb']} GB free."
        ),
    )


register(
    ToolSpec(
        name="check_disk_space",
        description=(
            "Check disk usage on the employee's device: percentage used and "
            "gigabytes free. Read-only."
        ),
        domain="endpoint",
        input_model=CheckDiskSpaceInput,
        output_model=CheckDiskSpaceOutput,
        handler=_check_disk_space,
        system_key=keys.SYSTEM_MDM,
    )
)


class InstallApprovedSoftwareInput(BaseModel):
    employee_id: str
    software_name: str


class InstallApprovedSoftwareOutput(BaseModel):
    employee_id: str
    software_name: str
    installed: bool
    already_installed: bool
    summary: str


async def _install_approved_software(
    inp: InstallApprovedSoftwareInput, ctx: ToolContext
) -> InstallApprovedSoftwareOutput:
    installed = get_world().install_software(inp.employee_id, inp.software_name)
    if installed:
        summary = f"Installed {inp.software_name} on the device for {inp.employee_id}."
    else:
        summary = (
            f"{inp.software_name} is already installed on the device for "
            f"{inp.employee_id}; nothing changed."
        )
    return InstallApprovedSoftwareOutput(
        employee_id=inp.employee_id,
        software_name=inp.software_name,
        installed=installed,
        already_installed=not installed,
        summary=summary,
    )


register(
    ToolSpec(
        name="install_approved_software",
        description=(
            "Install a named application on the employee's managed device via "
            "MDM. No-op if it is already installed. The required privilege "
            "depends on the software (standard vs dev tools) and is verified by "
            "the confirmation workflow against Neo4j."
        ),
        domain="endpoint",
        input_model=InstallApprovedSoftwareInput,
        output_model=InstallApprovedSoftwareOutput,
        handler=_install_approved_software,
        privileged=True,
        privilege_key=keys.PRIV_STANDARD_SOFTWARE,
        system_key=keys.SYSTEM_MDM,
        risk_level="medium",
    )
)


class RestartManagedServiceInput(BaseModel):
    employee_id: str
    service_name: str


class RestartManagedServiceOutput(BaseModel):
    employee_id: str
    service_name: str
    service_status: str
    summary: str


async def _restart_managed_service(
    inp: RestartManagedServiceInput, ctx: ToolContext
) -> RestartManagedServiceOutput:
    status = get_world().restart_service(inp.employee_id, inp.service_name)
    return RestartManagedServiceOutput(
        employee_id=inp.employee_id,
        service_name=inp.service_name,
        service_status=status,
        summary=(
            f"Restarted managed service {inp.service_name} on the device for "
            f"{inp.employee_id}; status is now {status}."
        ),
    )


register(
    ToolSpec(
        name="restart_managed_service",
        description=(
            "Restart a named managed service (e.g. mdm-agent, av-scanner, "
            "update-service) on the employee's device. Fails if the service "
            "does not exist on the device."
        ),
        domain="endpoint",
        input_model=RestartManagedServiceInput,
        output_model=RestartManagedServiceOutput,
        handler=_restart_managed_service,
        privileged=True,
        privilege_key=keys.PRIV_STANDARD_SOFTWARE,
        system_key=keys.SYSTEM_MDM,
        risk_level="low",
    )
)
