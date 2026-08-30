"""Typed org-graph accessors — the only module that answers org/privilege
questions (Mem0 content never satisfies them; provenance is always Neo4j).

Degradation contract (DESIGN.md §10.5):
- has_privilege fails CLOSED when the graph is unreachable and never raises.
- get_escalation_target returns None on failure so callers degrade.
- Every other function propagates OrgUnavailableError to its caller.
"""
from typing import Any

from app.contracts.common import PrivilegeCheckResult
from app.org import keys, queries
from app.org.client import OrgUnavailableError, run_query


async def get_employee_org_context(employee_id: str) -> dict[str, Any] | None:
    rows = await run_query(queries.EMPLOYEE_ORG_CONTEXT, {"employee_id": employee_id})
    if not rows:
        return None
    row = rows[0]
    return {
        "name": row["name"],
        "email": row["email"],
        "title": row["title"],
        "location": row["location"],
        "remote": row["remote"],
        "team": {"key": row["team_key"], "name": row["team_name"]}
        if row["team_key"] is not None
        else None,
        "department": {"key": row["department_key"], "name": row["department_name"]}
        if row["department_key"] is not None
        else None,
        "roles": row["roles"],
        "manager": {"id": row["manager_id"], "name": row["manager_name"]}
        if row["manager_id"] is not None
        else None,
    }


async def get_manager(employee_id: str) -> dict[str, Any] | None:
    rows = await run_query(queries.MANAGER, {"employee_id": employee_id})
    if not rows:
        return None
    return {"id": rows[0]["id"], "name": rows[0]["name"]}


async def has_privilege(employee_id: str, privilege_key: str) -> PrivilegeCheckResult:
    """Effective-privilege check. Fails CLOSED: if the org graph cannot answer,
    access is never assumed — has_privilege=False with the error surfaced."""
    try:
        rows = await run_query(
            queries.PRIVILEGE_CHECK,
            {"employee_id": employee_id, "privilege_key": privilege_key},
        )
        granted = bool(rows and rows[0]["has_privilege"])
        eligible = bool(rows and not granted and rows[0]["eligible_with_approval"])
        approver_employee_id: str | None = None
        if eligible:
            approver = await get_required_approver(employee_id, privilege_key)
            approver_employee_id = approver["id"] if approver else None
        return PrivilegeCheckResult(
            employee_id=employee_id,
            privilege_key=privilege_key,
            has_privilege=granted,
            eligible_with_approval=eligible,
            approver_employee_id=approver_employee_id,
        )
    except Exception as exc:  # noqa: BLE001 — fail closed, never raise
        return PrivilegeCheckResult(
            employee_id=employee_id,
            privilege_key=privilege_key,
            has_privilege=False,
            eligible_with_approval=False,
            approver_employee_id=None,
            error=f"neo4j_unavailable: {exc}",
        )


async def get_system_owner(system_key: str) -> dict[str, Any] | None:
    rows = await run_query(queries.SYSTEM_OWNER, {"system_key": system_key})
    if not rows:
        return None
    return {"team_key": rows[0]["team_key"], "team_name": rows[0]["team_name"]}


async def get_support_team(system_key: str) -> dict[str, Any] | None:
    rows = await run_query(queries.SYSTEM_SUPPORT_TEAM, {"system_key": system_key})
    if not rows:
        rows = await run_query(
            queries.SUPPORT_TEAM_BY_KEY, {"support_team_key": keys.SUPPORT_IT}
        )
    if not rows:
        return None
    return {"key": rows[0]["key"], "name": rows[0]["name"]}


async def get_required_approver(employee_id: str, privilege_key: str) -> dict[str, Any] | None:
    """Nearest manager up the REPORTS_TO chain holding an APPROVAL_BY role;
    fallback: the direct manager; final fallback: None."""
    rows = await run_query(
        queries.REQUIRED_APPROVER,
        {"employee_id": employee_id, "privilege_key": privilege_key},
    )
    if rows:
        return {"id": rows[0]["id"], "name": rows[0]["name"]}
    return await get_manager(employee_id)


async def get_escalation_target(
    current_owner_id: str | None, system_key: str
) -> dict[str, Any] | None:
    """Next human up the system's escalation chain. Returns None when the chain
    is exhausted, the system is unknown, or the graph is unreachable."""
    try:
        rows = await run_query(queries.ESCALATION_CHAIN, {"system_key": system_key})
    except OrgUnavailableError:
        return None
    if not rows:
        return None
    target = rows[0]
    if current_owner_id is not None:
        for index, row in enumerate(rows):
            if row["employee_id"] == current_owner_id:
                if index + 1 >= len(rows):
                    return None
                target = rows[index + 1]
                break
    return {
        "employee_id": target["employee_id"],
        "employee_name": target["employee_name"],
        "employee_title": target["employee_title"],
        "team_key": target["team_key"],
        "team_name": target["team_name"],
        "level": target["level"],
    }


async def get_directory() -> list[dict[str, Any]]:
    rows = await run_query(queries.DIRECTORY, {})
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "title": row["title"],
            "team_key": row["team_key"],
            "team_name": row["team_name"],
        }
        for row in rows
    ]
