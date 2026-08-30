"""Offline demo provider (IT_LLM_PROVIDER=scripted).

Deterministic, keyword-routed structured decisions so the full platform runs
without an API key: every guard, workflow, privilege check, and persistence
path is real — only the judgment inside the supervisor/specialists is canned.
Not used by tests (they script FakeProvider explicitly).
"""
import re
from typing import Any

from pydantic import BaseModel

from app.llm.provider import StructuredAttempt
from app.org import keys

_TICKET_RE = re.compile(r"\bIT-\d{3,6}\b", re.IGNORECASE)


def _text_of(messages: list[tuple[str, str]]) -> str:
    return " ".join(content for _, content in messages).lower()


def _employee_text(messages: list[tuple[str, str]]) -> str:
    """Only what the employee actually said — triage keywords must never match
    the system prompt or specialist result dumps."""
    joined = "\n".join(content for role, content in messages if role == "user")
    parts: list[str] = []
    m = re.search(r"Original request: (.+)", joined)
    if m:
        parts.append(m.group(1))
    parts.extend(re.findall(r"\[employee\] (.+)", joined))
    return " ".join(parts).lower() if parts else joined.lower()


def _obs_text(messages: list[tuple[str, str]]) -> str:
    """Only this run's tool observations — evidence checks must never match
    mission prompts or conversation text."""
    joined = "\n".join(content for role, content in messages if role == "user")
    marker = "Your tool observations this run:"
    idx = joined.find(marker)
    return joined[idx + len(marker):].lower() if idx >= 0 else ""


def _employee_of(messages: list[tuple[str, str]]) -> str:
    m = re.search(r"Employee:\s*(EMP-\d{3})", " ".join(c for _, c in messages))
    return m.group(1) if m else "EMP-000"


class ScriptedProvider:
    """Routes by dominant keyword; specialists follow a fixed evidence-first
    tool sequence and finish from what the tools actually observed."""

    async def complete(self, messages: list[tuple[str, str]]) -> str:
        return "Employee support conversation summary (scripted demo mode)."

    async def structured(
        self, schema: type[BaseModel], messages: list[tuple[str, str]]
    ) -> StructuredAttempt:
        name = schema.__name__
        if name == "SupervisorDecision":
            payload = self._supervisor(messages)
        elif name == "SpecialistStep":
            payload = self._specialist(messages)
        else:
            return StructuredAttempt(
                parsed=None, error=f"scripted provider has no script for {name}", raw_text=""
            )
        try:
            return StructuredAttempt(
                parsed=schema.model_validate(payload), error=None, raw_text=str(payload)
            )
        except Exception as exc:
            return StructuredAttempt(parsed=None, error=str(exc), raw_text=str(payload))

    # --- supervisor -----------------------------------------------------------

    def _supervisor(self, messages: list[tuple[str, str]]) -> dict[str, Any]:
        text = _text_of(messages)

        def decision(**kw: Any) -> dict[str, Any]:
            base = {
                "decision": "route_to_specialist",
                "target_specialist": None,
                "workflow": None,
                "category": "other",
                "intent": "employee support request",
                "risk_level": "low",
                "autonomy_level": "confirm_required",
                "question_for_employee": None,
                "message_to_employee": None,
                "reason": "scripted demo decision",
                "confidence": 0.9,
            }
            base.update(kw)
            return base

        declined = "declined the proposed action" in text
        if declined:
            return decision(
                decision="close_session",
                message_to_employee=(
                    "No problem — I haven't made any changes. If you'd like to revisit "
                    "this later, just start a new conversation."
                ),
                reason="employee declined the action; closing gracefully",
            )

        has_action = "pending requested_action" in text
        security_escalated = '"agent": "security"' in text and '"outcome": "escalation_required"' in text
        any_result = '"outcome":' in text
        handoff_to_security = '"outcome": "handoff_recommended"' in text and '"target_agent": "security"' in text
        needs_information = '"outcome": "need_more_information"' in text
        resolved = '"outcome": "resolved"' in text
        unable = '"outcome": "unable_to_resolve"' in text

        if security_escalated:
            return decision(
                decision="run_workflow", workflow="escalation", category="security",
                risk_level="high", autonomy_level="human_only",
                intent="suspicious account activity",
                reason="security specialist requires human intervention",
            )
        if has_action:
            return decision(
                decision="run_workflow", workflow="confirmation",
                category="endpoint" if "install" in text else "identity",
                risk_level="medium",
                intent="privileged action pending employee confirmation",
                reason="a concrete action is recommended; verifying privilege and asking for confirmation",
            )
        if handoff_to_security:
            return decision(
                target_specialist="security", category="security", risk_level="high",
                autonomy_level="human_only",
                intent="suspicious activity found during network diagnostics",
                reason="honoring the network specialist's handoff recommendation",
            )
        if needs_information:
            employee_text = _employee_text(messages)
            if "phishing-report" in text:
                has_phishing_detail = any(
                    phrase in employee_text
                    for phrase in ("clicked", "opened", "sender", "subject", "link", "attachment")
                )
                if has_phishing_detail:
                    return decision(
                        target_specialist="security", category="security", risk_level="high",
                        autonomy_level="human_only", intent="possible phishing exposure",
                        reason="employee supplied the phishing details requested by security",
                    )
                return decision(
                    decision="ask_employee", category="security", risk_level="high",
                    autonomy_level="human_only", intent="possible phishing exposure",
                    question_for_employee=(
                        "Thanks for flagging this. Please don't open any links or attachments. "
                        "Did you click or open anything, and can you share the sender or subject line?"
                    ),
                    reason="security needs the employee's exposure details before continuing",
                )
            if '"agent": "network"' in text:
                has_network_detail = any(
                    phrase in employee_text
                    for phrase in (
                        "disconnect", "drop", "cannot connect", "can't connect", "unable to connect",
                        "error", "timeout", "connected but", "internal site", "internal service",
                    )
                )
                if has_network_detail:
                    return decision(
                        target_specialist="network", category="network", risk_level="medium",
                        intent="VPN connectivity diagnosis",
                        reason="the employee supplied the connection symptom needed for diagnostics",
                    )
                return decision(
                    decision="ask_employee", category="network", risk_level="medium",
                    intent="VPN connectivity diagnosis",
                    question_for_employee=(
                        "Sorry you're blocked. Is the VPN failing to connect, dropping after it "
                        "connects, or connected but unable to reach an internal service? Please "
                        "share any error text you see."
                    ),
                    reason="network diagnostics need the connection failure mode",
                )
            return decision(
                decision="ask_employee",
                question_for_employee="Could you share the missing detail so I can continue investigating?",
                reason="the specialist needs one more employee detail",
            )
        if resolved:
            return decision(
                decision="run_workflow", workflow="resolution",
                # Preserve the category selected by the active specialist. A
                # follow-up may mention a laptop or a previous symptom without
                # changing the domain that actually resolved the request.
                category="other",
                intent="issue diagnosed and resolved",
                reason="specialist resolved the issue; closing out",
            )
        if unable or '"failure_type"' in text:
            return decision(
                decision="run_workflow", workflow="escalation",
                intent="automated investigation exhausted",
                reason="no autonomous path remains; escalating to a human",
            )
        if any_result:
            return decision(
                decision="run_workflow", workflow="escalation",
                reason="investigation complete without autonomous resolution; escalating",
            )

        # --- initial triage (employee text only) ---
        text = _employee_text(messages)
        if _TICKET_RE.search(text) or "ticket" in text or "status of" in text or "still pending" in text:
            return decision(
                decision="run_workflow", workflow="ticket_status", category="ticketing",
                intent="ticket status inquiry", autonomy_level="auto_resolve",
                reason="the employee is asking about an existing request",
            )
        if "phishing" in text or "suspicious" in text or "hacked" in text or "compromise" in text or "malware" in text:
            return decision(
                target_specialist="security", category="security", risk_level="high",
                autonomy_level="human_only", intent="possible security incident",
                reason="possible security incident reported by the employee",
            )
        if "vpn" in text or "wifi" in text or "wi-fi" in text or "internet" in text or "network" in text:
            return decision(
                target_specialist="network", category="network", risk_level="medium",
                intent="connectivity problem",
                reason="dominant symptom is network connectivity",
            )
        if "locked" in text or "lock" in text or "password" in text or "sign in" in text or "log in" in text or "mfa" in text:
            return decision(
                target_specialist="identity", category="identity", risk_level="medium",
                intent="account access problem",
                reason="dominant symptom is account access",
            )
        if "install" in text or "docker" in text or "software" in text:
            return decision(
                target_specialist="endpoint", category="endpoint", risk_level="medium",
                intent="software installation request",
                reason="software installation is an endpoint action",
            )
        if "slow" in text or "disk" in text or "laptop" in text or "device" in text or "crash" in text or "screen" in text or "display" in text:
            return decision(
                target_specialist="endpoint", category="endpoint", risk_level="low",
                intent="device performance problem",
                reason="dominant symptom is device health",
            )
        return decision(
            decision="ask_employee", category="other",
            question_for_employee=(
                "Could you tell me a bit more about what's not working — is it your "
                "account, your device, the network, or something else?"
            ),
            reason="the request is too ambiguous to route safely",
        )

    # --- specialists ----------------------------------------------------------

    def _specialist(self, messages: list[tuple[str, str]]) -> dict[str, Any]:
        text = _text_of(messages)
        employee = _employee_of(messages)

        def call(tool: str, **params: Any) -> dict[str, Any]:
            return {"action": "call_tool", "tool_call": {"tool_name": tool, "params": params}, "result": None}

        def finish(**kw: Any) -> dict[str, Any]:
            base = {
                "action": "finish",
                "tool_call": None,
                "result": {
                    "agent": "identity",
                    "outcome": "resolved",
                    "findings": [],
                    "tools_used": [],
                    "confidence": 0.88,
                    "reasoning_summary": "scripted demo result",
                    "question_for_employee": None,
                    "handoff": None,
                    "requested_action": None,
                    "escalation_reason": None,
                    "resolution_summary": None,
                },
            }
            base["result"].update(kw)
            return base

        agent = "identity"
        m = re.search(r'agent must be "(\w+)"', " ".join(c for _, c in messages))
        if m:
            agent = m.group(1)

        observed = "your tool observations this run" in text

        if agent == "network":
            employee_text = _employee_text(messages)
            observations = _obs_text(messages)
            has_network_detail = any(
                phrase in employee_text
                for phrase in (
                    "disconnect", "drop", "cannot connect", "can't connect", "unable to connect",
                    "error", "timeout", "connected but", "internal site", "internal service",
                )
            )
            if not has_network_detail:
                return finish(
                    agent="network",
                    outcome="need_more_information",
                    findings=[{
                        "agent": "network",
                        "summary": "Employee reported that VPN access is not working, but the connection failure mode is not yet known",
                        "severity": "low",
                        "tags": ["vpn"],
                        "detail": "",
                    }],
                    question_for_employee=(
                        "Sorry you're blocked. Is the VPN failing to connect, dropping after it "
                        "connects, or connected but unable to reach an internal service? Please "
                        "share any error text you see."
                    ),
                    reasoning_summary=(
                        "The reported VPN problem needs one discriminating symptom before "
                        "diagnostics can distinguish connection, stability, and access paths."
                    ),
                )
            if "[check_vpn_status]" not in text:
                return call("check_vpn_status")
            if "[inspect_recent_vpn_session]" not in text:
                return call("inspect_recent_vpn_session")
            if "flagged" in observations and (
                "203.0.113.42" in observations or "unrecognized" in observations
            ):
                return finish(
                    agent="network",
                    outcome="handoff_recommended",
                    findings=[
                        {"agent": "network", "summary": "VPN has dropped repeatedly in the last 24 hours", "severity": "medium", "tags": ["vpn"], "detail": ""},
                        {"agent": "network", "summary": "A recent VPN session originated from an unrecognized IP with a geo mismatch", "severity": "high", "tags": ["vpn", "suspicious-auth"], "detail": ""},
                    ],
                    handoff={
                        "outcome": "handoff",
                        "target_agent": "security",
                        "reason": "Suspicious authentication activity discovered during VPN diagnostics",
                        "findings": [
                            "VPN disconnects repeatedly",
                            "Unrecognized IP observed in a recent VPN session (geo mismatch)",
                        ],
                        "confidence": 0.87,
                    },
                    reasoning_summary="Diagnostics show instability plus a flagged session from an unknown network; this needs a security review.",
                )
            return finish(
                agent="network",
                outcome="resolved",
                findings=[{"agent": "network", "summary": "VPN and connectivity diagnostics do not show an active fault at the time of the check", "severity": "low", "tags": ["vpn"], "detail": ""}],
                resolution_summary=(
                    "I couldn't reproduce a VPN fault during this check, although that doesn't "
                    "invalidate what you experienced. If it happens again, note the time and any "
                    "error message, then reconnect once and send those details so we can compare them."
                ),
                reasoning_summary="Diagnostics did not reproduce the reported issue, so the next step preserves the employee's symptom for targeted follow-up.",
            )

        if agent == "security":
            employee_text = _employee_text(messages)
            reported_phishing = any(
                phrase in employee_text
                for phrase in ("phishing", "suspicious mail", "suspicious email", "weird email")
            )
            supplied_phishing_detail = any(
                phrase in employee_text
                for phrase in ("clicked", "opened", "sender", "subject", "link", "attachment")
            )
            if reported_phishing and not supplied_phishing_detail:
                return finish(
                    agent="security",
                    outcome="need_more_information",
                    findings=[{
                        "agent": "security",
                        "summary": "Employee reported a suspicious email; interaction with it has not yet been confirmed",
                        "severity": "medium",
                        "tags": ["phishing-report"],
                        "detail": "",
                    }],
                    question_for_employee=(
                        "Thanks for flagging this. Please don't open any links or attachments. "
                        "Did you click or open anything, and can you share the sender or subject line?"
                    ),
                    reasoning_summary=(
                        "A phishing report needs immediate safe handling and a small amount of "
                        "context before assessing possible exposure."
                    ),
                )
            if "[get_recent_security_events]" not in text:
                return call("get_recent_security_events")
            if "[notify_security_team]" not in text:
                return call("notify_security_team", summary=f"Security review requested after suspicious activity reported by {employee}")
            has_high_events = "highest severity is high" in text or "highest severity is critical" in text
            return finish(
                agent="security",
                outcome="escalation_required",
                findings=[
                    {
                        "agent": "security",
                        "summary": (
                            "Security events include high-severity account indicators"
                            if has_high_events
                            else "Employee-reported suspicious activity has been passed to the security team for review"
                        ),
                        "severity": "high" if has_high_events else "medium",
                        "tags": ["security-review"],
                        "detail": "",
                    },
                ],
                escalation_reason=(
                    "Reported suspicious activity requires human security review"
                    if not has_high_events
                    else "High-severity account indicators require human security review"
                ),
                confidence=0.9,
                reasoning_summary=(
                    "The security team was notified so it can assess the report and decide whether containment is needed."
                    if not has_high_events
                    else "High-severity indicators need human containment decisions."
                ),
            )

        if agent == "endpoint":
            asked = _employee_text(messages)
            physical_damage = any(
                phrase in asked
                for phrase in ("screen", "display", "damaged", "damage", "cracked", "replacement")
            )
            unable_to_work = any(
                phrase in asked
                for phrase in ("cannot work", "can't work", "unable to work", "not able to work")
            )
            if physical_damage:
                impact = " and is preventing normal work" if unable_to_work else ""
                return finish(
                    agent="endpoint",
                    outcome="escalation_required",
                    findings=[{
                        "agent": "endpoint",
                        "summary": f"Employee reports physical display damage{impact}",
                        "severity": "medium",
                        "tags": ["hardware", "display"],
                        "detail": "",
                    }],
                    escalation_reason=(
                        "Physical device damage needs an IT hardware assessment before a repair or replacement can be arranged"
                    ),
                    reasoning_summary=(
                        "Remote diagnostics cannot safely assess physical display damage; a hardware owner must determine the repair or replacement path."
                    ),
                )
            wants_install = "install" in asked or "docker" in asked
            if wants_install:
                software = "Docker Desktop" if "docker" in asked else "the requested software"
                privilege = keys.PRIV_DEV_TOOLS_INSTALL if "docker" in asked else keys.PRIV_STANDARD_SOFTWARE
                return finish(
                    agent="endpoint",
                    outcome="approval_required",
                    findings=[{"agent": "endpoint", "summary": f"Employee requested installation of {software} on their managed device", "severity": "low", "tags": ["software"], "detail": ""}],
                    requested_action={
                        "action_key": "install_approved_software",
                        "summary": f"Install {software} on {employee}'s managed laptop.",
                        "privilege_key": privilege,
                        "system_key": keys.SYSTEM_MDM,
                        "params": {"software_name": software},
                        "risk_level": "medium",
                    },
                    reasoning_summary="Installation is a privileged device action; the platform will verify entitlement and confirm before executing.",
                )
            if "[run_device_health_check]" not in text:
                return call("run_device_health_check")
            if "[check_disk_space]" not in text and ("disk" in text or "96" in text or "critical" in text or "degraded" in text):
                return call("check_disk_space")
            if "96" in text or "disk nearly full" in text:
                return finish(
                    agent="endpoint",
                    outcome="resolved",
                    findings=[{"agent": "endpoint", "summary": "Disk is 96% full, which explains the slowdown", "severity": "medium", "tags": ["disk"], "detail": ""}],
                    resolution_summary=(
                        "Your disk is 96% full, which is why the laptop feels slow. Free up space "
                        "by emptying Downloads and old screen recordings, then restart. If you "
                        "need more room, we can request an upgrade."
                    ),
                    reasoning_summary="Health check attributes the slowdown to disk pressure; safe self-service guidance resolves it.",
                )
            return finish(
                agent="endpoint",
                outcome="resolved",
                findings=[{"agent": "endpoint", "summary": "Device health check shows no critical issues", "severity": "low", "tags": [], "detail": ""}],
                resolution_summary=(
                    "Your device checks out healthy. A restart clears most lingering slowness; "
                    "reach out again if it doesn't."
                ),
                reasoning_summary="No fault found; providing safe guidance.",
            )

        # identity (default)
        employee_text = _employee_text(messages)
        observations = _obs_text(messages)
        account_is_locked = "locked" in employee_text or "account for" in observations and " is locked" in observations
        if "[get_account_status]" not in text:
            return call("get_account_status")
        if account_is_locked:
            if "[get_recent_auth_events]" not in text:
                return call("get_recent_auth_events")
            if "flagged as unusual" in observations and not "0 flagged as unusual" in observations and (
                "impossible" in observations or "203.0.113.42" in observations
            ):
                return finish(
                    agent="identity",
                    outcome="handoff_recommended",
                    findings=[{"agent": "identity", "summary": "Lockout coincides with unusual authentication activity", "severity": "high", "tags": ["auth"], "detail": ""}],
                    handoff={
                        "outcome": "handoff",
                        "target_agent": "security",
                        "reason": "Unusual authentication activity around the lockout",
                        "findings": ["Account locked", "Unusual auth events observed"],
                        "confidence": 0.8,
                    },
                    reasoning_summary="The lockout pattern looks anomalous; security should review before unlocking.",
                )
            return finish(
                agent="identity",
                outcome="approval_required",
                findings=[{"agent": "identity", "summary": "Account is locked after repeated failed password attempts from the employee's usual location", "severity": "medium", "tags": ["lockout"], "detail": ""}],
                requested_action={
                    "action_key": "unlock_account",
                    "summary": f"Unlock the account for {employee}.",
                    "privilege_key": keys.PRIV_SELF_ACCOUNT_UNLOCK,
                    "system_key": keys.SYSTEM_OKTA,
                    "params": {},
                    "risk_level": "medium",
                },
                reasoning_summary="Failed attempts came from the usual location, so a self-service unlock with explicit confirmation is appropriate.",
            )
        if observed:
            return finish(
                agent="identity",
                outcome="resolved",
                findings=[{"agent": "identity", "summary": "Account is active with no unusual activity", "severity": "low", "tags": [], "detail": ""}],
                resolution_summary=(
                    "Your account looks healthy — active, no lockouts, and no unusual sign-in "
                    "activity. If you still can't get in, tell me exactly what error you see."
                ),
                reasoning_summary="Status check found nothing wrong.",
            )
        return call("get_account_status")
