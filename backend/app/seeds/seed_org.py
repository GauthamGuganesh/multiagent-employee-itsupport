"""Idempotent Neo4j seed for the fictional org 'GA-VoiceAI'.

60 employees (EMP-001..EMP-060) defined as deterministic literal data — no
randomness. Every node and relationship is MERGEd on its unique key, so the
seed is safe to run repeatedly. All keys come exclusively from app.org.keys
(DESIGN.md §4). Run with:

    python -m app.seeds.seed_org
"""
import asyncio
import sys
from typing import Any

from app.org import keys
from app.org.client import OrgUnavailableError, close_driver, run_query

# ---------------------------------------------------------------------------
# Literal data
# ---------------------------------------------------------------------------

_DEPARTMENTS: list[dict[str, str]] = [
    {"key": keys.DEPT_ENGINEERING, "name": "Engineering"},
    {"key": keys.DEPT_PRODUCT, "name": "Product"},
    {"key": keys.DEPT_FINANCE, "name": "Finance"},
    {"key": keys.DEPT_PEOPLE, "name": "People"},
    {"key": keys.DEPT_REVENUE, "name": "Revenue"},
    {"key": keys.DEPT_PLATFORM, "name": "Platform"},
    {"key": keys.DEPT_SECURITY, "name": "Security"},
]

_TEAMS: list[dict[str, str]] = [
    {"key": keys.TEAM_EXEC, "name": "Executive"},
    {"key": keys.TEAM_BACKEND, "name": "Backend"},
    {"key": keys.TEAM_FRONTEND, "name": "Frontend"},
    {"key": keys.TEAM_PLATFORM, "name": "Platform & IT"},
    {"key": keys.TEAM_SECURITY, "name": "Security"},
    {"key": keys.TEAM_PRODUCT, "name": "Product"},
    {"key": keys.TEAM_FINANCE, "name": "Finance"},
    {"key": keys.TEAM_HR, "name": "People Ops"},
    {"key": keys.TEAM_SALES, "name": "Sales"},
    {"key": keys.TEAM_CS, "name": "Customer Success"},
]

# Executive team spans the org and belongs to no single department.
_TEAM_DEPARTMENTS: list[dict[str, str]] = [
    {"team_key": keys.TEAM_BACKEND, "department_key": keys.DEPT_ENGINEERING},
    {"team_key": keys.TEAM_FRONTEND, "department_key": keys.DEPT_ENGINEERING},
    {"team_key": keys.TEAM_PLATFORM, "department_key": keys.DEPT_PLATFORM},
    {"team_key": keys.TEAM_SECURITY, "department_key": keys.DEPT_SECURITY},
    {"team_key": keys.TEAM_PRODUCT, "department_key": keys.DEPT_PRODUCT},
    {"team_key": keys.TEAM_FINANCE, "department_key": keys.DEPT_FINANCE},
    {"team_key": keys.TEAM_HR, "department_key": keys.DEPT_PEOPLE},
    {"team_key": keys.TEAM_SALES, "department_key": keys.DEPT_REVENUE},
    {"team_key": keys.TEAM_CS, "department_key": keys.DEPT_REVENUE},
]

_ROLES: list[dict[str, Any]] = [
    {"key": keys.ROLE_CEO, "name": "Chief Executive Officer", "level": 10},
    {"key": keys.ROLE_CTO, "name": "Chief Technology Officer", "level": 10},
    {"key": keys.ROLE_CFO, "name": "Chief Financial Officer", "level": 10},
    {"key": keys.ROLE_CPO, "name": "Chief Product Officer", "level": 10},
    {"key": keys.ROLE_CHRO, "name": "Chief People Officer", "level": 10},
    {"key": keys.ROLE_CRO, "name": "Chief Revenue Officer", "level": 10},
    {"key": keys.ROLE_ENG_MANAGER, "name": "Engineering Manager", "level": 7},
    {"key": keys.ROLE_PLATFORM_MANAGER, "name": "Platform Manager", "level": 7},
    {"key": keys.ROLE_SECURITY_LEAD, "name": "Security Lead", "level": 7},
    {"key": keys.ROLE_BACKEND_ENGINEER, "name": "Backend Engineer", "level": 3},
    {"key": keys.ROLE_SENIOR_BACKEND_ENGINEER, "name": "Senior Backend Engineer", "level": 5},
    {"key": keys.ROLE_FRONTEND_ENGINEER, "name": "Frontend Engineer", "level": 3},
    {"key": keys.ROLE_SENIOR_FRONTEND_ENGINEER, "name": "Senior Frontend Engineer", "level": 5},
    {"key": keys.ROLE_PLATFORM_ENGINEER, "name": "Platform Engineer", "level": 4},
    {"key": keys.ROLE_IT_SUPPORT_SPECIALIST, "name": "IT Support Specialist", "level": 3},
    {"key": keys.ROLE_SECURITY_ENGINEER, "name": "Security Engineer", "level": 4},
    {"key": keys.ROLE_PRODUCT_MANAGER, "name": "Product Manager", "level": 4},
    {"key": keys.ROLE_PRODUCT_DESIGNER, "name": "Product Designer", "level": 4},
    {"key": keys.ROLE_ACCOUNTANT, "name": "Accountant", "level": 3},
    {"key": keys.ROLE_FINANCE_CONTROLLER, "name": "Finance Controller", "level": 6},
    {"key": keys.ROLE_HR_PARTNER, "name": "HR Business Partner", "level": 4},
    {"key": keys.ROLE_ACCOUNT_EXECUTIVE, "name": "Account Executive", "level": 3},
    {"key": keys.ROLE_SALES_MANAGER, "name": "Sales Manager", "level": 7},
    {"key": keys.ROLE_CSM, "name": "Customer Success Manager", "level": 3},
    {"key": keys.ROLE_CS_LEAD, "name": "Customer Success Lead", "level": 6},
    {"key": keys.ROLE_CONTRACTOR, "name": "Contractor", "level": 1},
]

_PRIVILEGES: list[dict[str, str]] = [
    {
        "key": keys.PRIV_SELF_ACCOUNT_UNLOCK,
        "name": "Self Account Unlock",
        "description": "Unlock one's own directory account after a lockout.",
        "risk_level": "low",
    },
    {
        "key": keys.PRIV_SELF_PASSWORD_RESET,
        "name": "Self Password Reset",
        "description": "Reset one's own account password.",
        "risk_level": "low",
    },
    {
        "key": keys.PRIV_SELF_SESSION_REVOKE,
        "name": "Self Session Revoke",
        "description": "Revoke one's own active sessions.",
        "risk_level": "low",
    },
    {
        "key": keys.PRIV_STANDARD_SOFTWARE,
        "name": "Standard Software Install",
        "description": "Install pre-approved software from the standard catalog.",
        "risk_level": "low",
    },
    {
        "key": keys.PRIV_GITHUB_ACCESS,
        "name": "GitHub Access",
        "description": "Membership in the company GitHub organization.",
        "risk_level": "medium",
    },
    {
        "key": keys.PRIV_JIRA_ACCESS,
        "name": "Jira Access",
        "description": "Access to Jira projects and boards.",
        "risk_level": "low",
    },
    {
        "key": keys.PRIV_STAGING_ACCESS,
        "name": "Staging Access",
        "description": "Deploy to and inspect the staging environment.",
        "risk_level": "medium",
    },
    {
        "key": keys.PRIV_PRODUCTION_LOGS,
        "name": "Production Logs",
        "description": "Read production application and infrastructure logs.",
        "risk_level": "high",
    },
    {
        "key": keys.PRIV_PROD_DB_ACCESS,
        "name": "Production DB Access",
        "description": "Direct query access to the production database.",
        "risk_level": "critical",
    },
    {
        "key": keys.PRIV_DEV_TOOLS_INSTALL,
        "name": "Dev Tools Install",
        "description": "Install developer tooling such as Docker Desktop.",
        "risk_level": "medium",
    },
    {
        "key": keys.PRIV_KUBERNETES_ADMIN,
        "name": "Kubernetes Admin",
        "description": "Administer the production Kubernetes clusters.",
        "risk_level": "critical",
    },
    {
        "key": keys.PRIV_PROD_INFRA_ADMIN,
        "name": "Production Infra Admin",
        "description": "Administer production cloud infrastructure.",
        "risk_level": "critical",
    },
    {
        "key": keys.PRIV_VPN_ADMIN,
        "name": "VPN Admin",
        "description": "Administer the corporate VPN service and its profiles.",
        "risk_level": "high",
    },
    {
        "key": keys.PRIV_DEVICE_ADMIN,
        "name": "Device Admin",
        "description": "Perform MDM actions on other employees' devices.",
        "risk_level": "high",
    },
    {
        "key": keys.PRIV_SECURITY_TOOLING,
        "name": "Security Tooling",
        "description": "Operate the SIEM and related security tooling.",
        "risk_level": "high",
    },
    {
        "key": keys.PRIV_AUTH_EVENT_ACCESS,
        "name": "Auth Event Access",
        "description": "Read authentication event logs for any employee.",
        "risk_level": "high",
    },
    {
        "key": keys.PRIV_SESSION_REVOKE_OTHERS,
        "name": "Session Revoke (Others)",
        "description": "Revoke active sessions belonging to other employees.",
        "risk_level": "high",
    },
    {
        "key": keys.PRIV_DEVICE_QUARANTINE,
        "name": "Device Quarantine",
        "description": "Quarantine a managed device from the network.",
        "risk_level": "critical",
    },
    {
        "key": keys.PRIV_SALESFORCE_ACCESS,
        "name": "Salesforce Access",
        "description": "Access to Salesforce CRM data.",
        "risk_level": "medium",
    },
    {
        "key": keys.PRIV_NETSUITE_ACCESS,
        "name": "NetSuite Access",
        "description": "Access to the NetSuite ERP system.",
        "risk_level": "high",
    },
    {
        "key": keys.PRIV_APPROVE_ACCESS_REQUESTS,
        "name": "Approve Access Requests",
        "description": "Approve or reject privilege grant requests.",
        "risk_level": "high",
    },
]

_SYSTEMS: list[dict[str, str]] = [
    {"key": keys.SYSTEM_VPN, "name": "Corporate VPN", "category": "network"},
    {"key": keys.SYSTEM_GITHUB, "name": "GitHub", "category": "engineering"},
    {"key": keys.SYSTEM_JIRA, "name": "Jira", "category": "engineering"},
    {"key": keys.SYSTEM_STAGING, "name": "Staging Environment", "category": "engineering"},
    {"key": keys.SYSTEM_PRODUCTION, "name": "Production Infrastructure", "category": "infrastructure"},
    {"key": keys.SYSTEM_PROD_DB, "name": "Production Database", "category": "infrastructure"},
    {"key": keys.SYSTEM_OKTA, "name": "Okta", "category": "identity"},
    {"key": keys.SYSTEM_MDM, "name": "Mobile Device Management", "category": "endpoint"},
    {"key": keys.SYSTEM_SIEM, "name": "SIEM", "category": "security"},
    {"key": keys.SYSTEM_SALESFORCE, "name": "Salesforce", "category": "business"},
    {"key": keys.SYSTEM_NETSUITE, "name": "NetSuite", "category": "business"},
]

_SUPPORT_TEAMS: list[dict[str, str]] = [
    {"key": keys.SUPPORT_IT, "name": "IT Support", "queue": keys.SUPPORT_IT},
    {"key": keys.SUPPORT_SECURITY, "name": "Security Operations", "queue": keys.SUPPORT_SECURITY},
]

# Roster: (id, name, title, team_key, role_key, manager_id, location, remote).
# Distribution: exec 2, engineering 18 (EMP-007 + 12 backend + 5 frontend),
# platform 8, security 4, product 7, finance 6, people 5, sales/cs 10 = 60.
_ROSTER: list[tuple[str, str, str, str, str, str | None, str, bool]] = [
    (keys.EMP_CEO, "Margaret Okafor", "Chief Executive Officer", keys.TEAM_EXEC, keys.ROLE_CEO, None, "San Francisco, US", False),
    (keys.EMP_CTO, "Daniel Chen", "Chief Technology Officer", keys.TEAM_EXEC, keys.ROLE_CTO, keys.EMP_CEO, "San Francisco, US", False),
    (keys.EMP_CPO, "Priya Raghavan", "Chief Product Officer", keys.TEAM_PRODUCT, keys.ROLE_CPO, keys.EMP_CEO, "San Francisco, US", False),
    (keys.EMP_CFO, "Tomasz Kowalski", "Chief Financial Officer", keys.TEAM_FINANCE, keys.ROLE_CFO, keys.EMP_CEO, "New York, US", False),
    (keys.EMP_CHRO, "Alicia Fernandez", "Chief People Officer", keys.TEAM_HR, keys.ROLE_CHRO, keys.EMP_CEO, "Austin, US", False),
    (keys.EMP_CRO, "Robert Ellison", "Chief Revenue Officer", keys.TEAM_SALES, keys.ROLE_CRO, keys.EMP_CEO, "Chicago, US", False),
    (keys.EMP_ENG_MANAGER, "Sofia Martins", "Engineering Manager", keys.TEAM_BACKEND, keys.ROLE_ENG_MANAGER, keys.EMP_CTO, "Lisbon, PT", False),
    (keys.EMP_PLATFORM_MANAGER, "Marcus Webb", "Platform & IT Manager", keys.TEAM_PLATFORM, keys.ROLE_PLATFORM_MANAGER, keys.EMP_CTO, "Denver, US", False),
    (keys.EMP_SECURITY_LEAD, "Yuki Tanaka", "Security Lead", keys.TEAM_SECURITY, keys.ROLE_SECURITY_LEAD, keys.EMP_CTO, "Toronto, CA", False),
    (keys.EMP_BACKEND_LEAD, "Aisha Bello", "Backend Team Lead", keys.TEAM_BACKEND, keys.ROLE_SENIOR_BACKEND_ENGINEER, keys.EMP_ENG_MANAGER, "London, UK", False),
    ("EMP-011", "Lars Nielsen", "Senior Backend Engineer", keys.TEAM_BACKEND, keys.ROLE_SENIOR_BACKEND_ENGINEER, keys.EMP_BACKEND_LEAD, "Copenhagen, DK", True),
    ("EMP-012", "Elena Petrova", "Backend Engineer", keys.TEAM_BACKEND, keys.ROLE_BACKEND_ENGINEER, keys.EMP_BACKEND_LEAD, "Berlin, DE", False),
    ("EMP-013", "James O'Connor", "Backend Engineer", keys.TEAM_BACKEND, keys.ROLE_BACKEND_ENGINEER, keys.EMP_BACKEND_LEAD, "Dublin, IE", False),
    (keys.EMP_VPN_SUSPECT, "Nadia Haddad", "Backend Engineer", keys.TEAM_BACKEND, keys.ROLE_BACKEND_ENGINEER, keys.EMP_BACKEND_LEAD, "Amsterdam, NL", False),
    ("EMP-015", "Victor Osei", "Backend Engineer", keys.TEAM_BACKEND, keys.ROLE_BACKEND_ENGINEER, keys.EMP_BACKEND_LEAD, "London, UK", False),
    ("EMP-016", "Hannah Lindqvist", "Backend Engineer", keys.TEAM_BACKEND, keys.ROLE_BACKEND_ENGINEER, keys.EMP_BACKEND_LEAD, "Stockholm, SE", True),
    (keys.EMP_017_BACKEND, "Mateo Silva", "Backend Engineer", keys.TEAM_BACKEND, keys.ROLE_BACKEND_ENGINEER, keys.EMP_BACKEND_LEAD, "Sao Paulo, BR", False),
    ("EMP-018", "Grace Kim", "Backend Engineer", keys.TEAM_BACKEND, keys.ROLE_BACKEND_ENGINEER, keys.EMP_BACKEND_LEAD, "Seattle, US", False),
    ("EMP-019", "Omar Farouk", "Backend Engineer", keys.TEAM_BACKEND, keys.ROLE_BACKEND_ENGINEER, keys.EMP_BACKEND_LEAD, "Cairo, EG", True),
    ("EMP-020", "Isabelle Moreau", "Backend Engineer", keys.TEAM_BACKEND, keys.ROLE_BACKEND_ENGINEER, keys.EMP_BACKEND_LEAD, "Paris, FR", False),
    ("EMP-021", "Dmitri Ivanov", "Backend Engineer", keys.TEAM_BACKEND, keys.ROLE_BACKEND_ENGINEER, keys.EMP_BACKEND_LEAD, "Belgrade, RS", False),
    ("EMP-022", "Sarah Whitfield", "Platform Engineer", keys.TEAM_PLATFORM, keys.ROLE_PLATFORM_ENGINEER, keys.EMP_PLATFORM_MANAGER, "Denver, US", False),
    ("EMP-023", "Rajesh Nair", "Platform Engineer", keys.TEAM_PLATFORM, keys.ROLE_PLATFORM_ENGINEER, keys.EMP_PLATFORM_MANAGER, "Bangalore, IN", False),
    ("EMP-024", "Emily Zhang", "Platform Engineer", keys.TEAM_PLATFORM, keys.ROLE_PLATFORM_ENGINEER, keys.EMP_PLATFORM_MANAGER, "Vancouver, CA", True),
    (keys.EMP_IT_SUPPORT_1, "Carlos Mendoza", "IT Support Specialist", keys.TEAM_PLATFORM, keys.ROLE_IT_SUPPORT_SPECIALIST, keys.EMP_PLATFORM_MANAGER, "Austin, US", False),
    (keys.EMP_IT_SUPPORT_2, "Fatima Al-Rashid", "IT Support Specialist", keys.TEAM_PLATFORM, keys.ROLE_IT_SUPPORT_SPECIALIST, keys.EMP_PLATFORM_MANAGER, "Dubai, AE", False),
    ("EMP-027", "Ben Carter", "Platform Engineer", keys.TEAM_PLATFORM, keys.ROLE_PLATFORM_ENGINEER, keys.EMP_PLATFORM_MANAGER, "Denver, US", False),
    (keys.EMP_PLATFORM_ENG, "Ingrid Johansson", "Platform Engineer", keys.TEAM_PLATFORM, keys.ROLE_PLATFORM_ENGINEER, keys.EMP_PLATFORM_MANAGER, "Oslo, NO", False),
    ("EMP-029", "Wei Liu", "Senior Frontend Engineer", keys.TEAM_FRONTEND, keys.ROLE_SENIOR_FRONTEND_ENGINEER, keys.EMP_ENG_MANAGER, "Singapore, SG", False),
    ("EMP-030", "Amara Diallo", "Frontend Engineer", keys.TEAM_FRONTEND, keys.ROLE_FRONTEND_ENGINEER, "EMP-029", "Dakar, SN", True),
    ("EMP-031", "Jonas Weber", "Frontend Engineer", keys.TEAM_FRONTEND, keys.ROLE_FRONTEND_ENGINEER, "EMP-029", "Munich, DE", False),
    (keys.EMP_FRONTEND_ENG, "Chloe Bennett", "Frontend Engineer", keys.TEAM_FRONTEND, keys.ROLE_FRONTEND_ENGINEER, "EMP-029", "Melbourne, AU", False),
    ("EMP-033", "Ravi Patel", "Frontend Engineer", keys.TEAM_FRONTEND, keys.ROLE_FRONTEND_ENGINEER, "EMP-029", "Bangalore, IN", False),
    (keys.EMP_LOCKED_OUT, "Tyler Brooks", "Account Executive", keys.TEAM_SALES, keys.ROLE_ACCOUNT_EXECUTIVE, "EMP-035", "Chicago, US", False),
    ("EMP-035", "Monica Alvarez", "Sales Manager", keys.TEAM_SALES, keys.ROLE_SALES_MANAGER, keys.EMP_CRO, "Chicago, US", False),
    ("EMP-036", "David Nkemelu", "Account Executive", keys.TEAM_SALES, keys.ROLE_ACCOUNT_EXECUTIVE, "EMP-035", "Atlanta, US", False),
    ("EMP-037", "Jessica Tran", "Account Executive", keys.TEAM_SALES, keys.ROLE_ACCOUNT_EXECUTIVE, "EMP-035", "San Diego, US", True),
    ("EMP-038", "Ahmed Yusuf", "Account Executive", keys.TEAM_SALES, keys.ROLE_ACCOUNT_EXECUTIVE, "EMP-035", "London, UK", False),
    ("EMP-039", "Rachel Goldberg", "Customer Success Lead", keys.TEAM_CS, keys.ROLE_CS_LEAD, keys.EMP_CRO, "Boston, US", False),
    ("EMP-040", "Kwame Asante", "Customer Success Manager", keys.TEAM_CS, keys.ROLE_CSM, "EMP-039", "Accra, GH", True),
    (keys.EMP_SLOW_LAPTOP, "Laura Jimenez", "Customer Success Manager", keys.TEAM_CS, keys.ROLE_CSM, "EMP-039", "Madrid, ES", False),
    ("EMP-042", "Steven Park", "Customer Success Manager", keys.TEAM_CS, keys.ROLE_CSM, "EMP-039", "Seoul, KR", False),
    ("EMP-043", "Anita Desai", "Product Manager", keys.TEAM_PRODUCT, keys.ROLE_PRODUCT_MANAGER, keys.EMP_CPO, "San Francisco, US", False),
    ("EMP-044", "Felix Braun", "Product Designer", keys.TEAM_PRODUCT, keys.ROLE_PRODUCT_DESIGNER, keys.EMP_CPO, "Berlin, DE", True),
    ("EMP-045", "Olivia Hughes", "Product Manager", keys.TEAM_PRODUCT, keys.ROLE_PRODUCT_MANAGER, keys.EMP_CPO, "London, UK", False),
    (keys.EMP_EXCEPTION_GRANT, "Marco Rossi", "Product Manager", keys.TEAM_PRODUCT, keys.ROLE_PRODUCT_MANAGER, keys.EMP_CPO, "Milan, IT", False),
    ("EMP-047", "Zainab Hussain", "Product Designer", keys.TEAM_PRODUCT, keys.ROLE_PRODUCT_DESIGNER, keys.EMP_CPO, "Manchester, UK", False),
    ("EMP-048", "Ethan Wright", "Product Manager", keys.TEAM_PRODUCT, keys.ROLE_PRODUCT_MANAGER, keys.EMP_CPO, "New York, US", False),
    ("EMP-049", "Katherine Doyle", "Finance Controller", keys.TEAM_FINANCE, keys.ROLE_FINANCE_CONTROLLER, keys.EMP_CFO, "New York, US", False),
    ("EMP-050", "Samuel Adeboye", "Accountant", keys.TEAM_FINANCE, keys.ROLE_ACCOUNTANT, keys.EMP_CFO, "Lagos, NG", False),
    ("EMP-051", "Mei Lin Wong", "Accountant", keys.TEAM_FINANCE, keys.ROLE_ACCOUNTANT, keys.EMP_CFO, "Hong Kong, HK", False),
    (keys.EMP_CONTRACTOR, "Piotr Zielinski", "Finance Systems Contractor", keys.TEAM_FINANCE, keys.ROLE_CONTRACTOR, keys.EMP_CFO, "Warsaw, PL", True),
    ("EMP-053", "Rebecca Stone", "Accountant", keys.TEAM_FINANCE, keys.ROLE_ACCOUNTANT, keys.EMP_CFO, "New York, US", False),
    ("EMP-054", "Gabriel Santos", "HR Business Partner", keys.TEAM_HR, keys.ROLE_HR_PARTNER, keys.EMP_CHRO, "Austin, US", False),
    ("EMP-055", "Leila Nasser", "HR Business Partner", keys.TEAM_HR, keys.ROLE_HR_PARTNER, keys.EMP_CHRO, "Berlin, DE", False),
    ("EMP-056", "Thomas Muller", "HR Business Partner", keys.TEAM_HR, keys.ROLE_HR_PARTNER, keys.EMP_CHRO, "Frankfurt, DE", True),
    ("EMP-057", "Naomi Cohen", "HR Business Partner", keys.TEAM_HR, keys.ROLE_HR_PARTNER, keys.EMP_CHRO, "Tel Aviv, IL", False),
    ("EMP-058", "Andre Bishop", "Security Engineer", keys.TEAM_SECURITY, keys.ROLE_SECURITY_ENGINEER, keys.EMP_SECURITY_LEAD, "Toronto, CA", False),
    ("EMP-059", "Sanjana Iyer", "Security Engineer", keys.TEAM_SECURITY, keys.ROLE_SECURITY_ENGINEER, keys.EMP_SECURITY_LEAD, "Bangalore, IN", False),
    ("EMP-060", "Lucas Ferreira", "Security Engineer", keys.TEAM_SECURITY, keys.ROLE_SECURITY_ENGINEER, keys.EMP_SECURITY_LEAD, "Lisbon, PT", True),
]


def _email(name: str) -> str:
    local = name.lower().replace("'", "").replace(" ", ".")
    return f"{local}@gavoiceai.com"


_EMPLOYEES: list[dict[str, Any]] = [
    {
        "id": emp_id,
        "name": name,
        "email": _email(name),
        "title": title,
        "location": location,
        "remote": remote,
    }
    for emp_id, name, title, _team, _role, _manager, location, remote in _ROSTER
]

_MEMBER_OF: list[dict[str, str]] = [
    {"employee_id": emp_id, "team_key": team}
    for emp_id, _name, _title, team, _role, _manager, _loc, _remote in _ROSTER
]

_HAS_ROLE: list[dict[str, str]] = [
    {"employee_id": emp_id, "role_key": role}
    for emp_id, _name, _title, _team, role, _manager, _loc, _remote in _ROSTER
]

_REPORTS_TO: list[dict[str, str]] = [
    {"employee_id": emp_id, "manager_id": manager}
    for emp_id, _name, _title, _team, _role, manager, _loc, _remote in _ROSTER
    if manager is not None
]

# Role GRANTS ladders (DESIGN.md §4). Contractors get self-service only —
# no standard-software-install.
_SELF_BASELINE: list[str] = [
    keys.PRIV_SELF_ACCOUNT_UNLOCK,
    keys.PRIV_SELF_PASSWORD_RESET,
    keys.PRIV_SELF_SESSION_REVOKE,
]
_BASELINE: list[str] = [*_SELF_BASELINE, keys.PRIV_STANDARD_SOFTWARE]
_ENGINEER_CORE: list[str] = [
    keys.PRIV_GITHUB_ACCESS,
    keys.PRIV_JIRA_ACCESS,
    keys.PRIV_STAGING_ACCESS,
]
_PLATFORM_ADMIN: list[str] = [
    keys.PRIV_DEV_TOOLS_INSTALL,
    keys.PRIV_KUBERNETES_ADMIN,
    keys.PRIV_PROD_INFRA_ADMIN,
    keys.PRIV_VPN_ADMIN,
    keys.PRIV_DEVICE_ADMIN,
]
_SECURITY_CORE: list[str] = [
    keys.PRIV_SECURITY_TOOLING,
    keys.PRIV_AUTH_EVENT_ACCESS,
    keys.PRIV_SESSION_REVOKE_OTHERS,
    keys.PRIV_DEVICE_QUARANTINE,
]

_ROLE_GRANTS: dict[str, list[str]] = {
    keys.ROLE_CEO: _BASELINE,
    keys.ROLE_CTO: _BASELINE,
    keys.ROLE_CFO: [*_BASELINE, keys.PRIV_NETSUITE_ACCESS, keys.PRIV_APPROVE_ACCESS_REQUESTS],
    keys.ROLE_CPO: [*_BASELINE, keys.PRIV_JIRA_ACCESS],
    keys.ROLE_CHRO: _BASELINE,
    keys.ROLE_CRO: [*_BASELINE, keys.PRIV_SALESFORCE_ACCESS],
    keys.ROLE_ENG_MANAGER: [*_BASELINE, *_ENGINEER_CORE, keys.PRIV_APPROVE_ACCESS_REQUESTS],
    keys.ROLE_PLATFORM_MANAGER: [*_BASELINE, *_PLATFORM_ADMIN, keys.PRIV_APPROVE_ACCESS_REQUESTS],
    keys.ROLE_SECURITY_LEAD: [*_BASELINE, *_SECURITY_CORE, keys.PRIV_APPROVE_ACCESS_REQUESTS],
    keys.ROLE_BACKEND_ENGINEER: [*_BASELINE, *_ENGINEER_CORE],
    keys.ROLE_SENIOR_BACKEND_ENGINEER: [*_BASELINE, *_ENGINEER_CORE, keys.PRIV_PRODUCTION_LOGS],
    keys.ROLE_FRONTEND_ENGINEER: [*_BASELINE, *_ENGINEER_CORE],
    keys.ROLE_SENIOR_FRONTEND_ENGINEER: [*_BASELINE, *_ENGINEER_CORE],
    keys.ROLE_PLATFORM_ENGINEER: [*_BASELINE, *_PLATFORM_ADMIN],
    keys.ROLE_IT_SUPPORT_SPECIALIST: [*_BASELINE, keys.PRIV_JIRA_ACCESS, keys.PRIV_DEVICE_ADMIN],
    keys.ROLE_SECURITY_ENGINEER: [*_BASELINE, *_SECURITY_CORE],
    keys.ROLE_PRODUCT_MANAGER: [*_BASELINE, keys.PRIV_JIRA_ACCESS],
    keys.ROLE_PRODUCT_DESIGNER: [*_BASELINE, keys.PRIV_JIRA_ACCESS],
    keys.ROLE_ACCOUNTANT: [*_BASELINE, keys.PRIV_NETSUITE_ACCESS],
    keys.ROLE_FINANCE_CONTROLLER: [*_BASELINE, keys.PRIV_NETSUITE_ACCESS],
    keys.ROLE_HR_PARTNER: _BASELINE,
    keys.ROLE_ACCOUNT_EXECUTIVE: [*_BASELINE, keys.PRIV_SALESFORCE_ACCESS],
    keys.ROLE_SALES_MANAGER: [*_BASELINE, keys.PRIV_SALESFORCE_ACCESS, keys.PRIV_APPROVE_ACCESS_REQUESTS],
    keys.ROLE_CSM: [*_BASELINE, keys.PRIV_SALESFORCE_ACCESS],
    keys.ROLE_CS_LEAD: [*_BASELINE, keys.PRIV_SALESFORCE_ACCESS],
    keys.ROLE_CONTRACTOR: _SELF_BASELINE,
}

_ROLE_ELIGIBLE: dict[str, list[str]] = {
    keys.ROLE_BACKEND_ENGINEER: [keys.PRIV_DEV_TOOLS_INSTALL, keys.PRIV_PRODUCTION_LOGS],
    keys.ROLE_SENIOR_BACKEND_ENGINEER: [keys.PRIV_DEV_TOOLS_INSTALL, keys.PRIV_PROD_DB_ACCESS],
    keys.ROLE_FRONTEND_ENGINEER: [keys.PRIV_DEV_TOOLS_INSTALL],
    keys.ROLE_SENIOR_FRONTEND_ENGINEER: [keys.PRIV_DEV_TOOLS_INSTALL],
    keys.ROLE_ENG_MANAGER: [keys.PRIV_DEV_TOOLS_INSTALL, keys.PRIV_PRODUCTION_LOGS],
}

_GRANTS_ROWS: list[dict[str, str]] = [
    {"role_key": role, "privilege_key": privilege}
    for role, privileges in _ROLE_GRANTS.items()
    for privilege in privileges
]

_ELIGIBLE_ROWS: list[dict[str, str]] = [
    {"role_key": role, "privilege_key": privilege}
    for role, privileges in _ROLE_ELIGIBLE.items()
    for privilege in privileges
]

_APPROVAL_BY: list[dict[str, str]] = [
    {"privilege_key": keys.PRIV_DEV_TOOLS_INSTALL, "role_key": keys.ROLE_ENG_MANAGER},
    {"privilege_key": keys.PRIV_PRODUCTION_LOGS, "role_key": keys.ROLE_ENG_MANAGER},
    {"privilege_key": keys.PRIV_PROD_DB_ACCESS, "role_key": keys.ROLE_PLATFORM_MANAGER},
    {"privilege_key": keys.PRIV_KUBERNETES_ADMIN, "role_key": keys.ROLE_PLATFORM_MANAGER},
    {"privilege_key": keys.PRIV_VPN_ADMIN, "role_key": keys.ROLE_PLATFORM_MANAGER},
    {"privilege_key": keys.PRIV_SALESFORCE_ACCESS, "role_key": keys.ROLE_SALES_MANAGER},
    {"privilege_key": keys.PRIV_NETSUITE_ACCESS, "role_key": keys.ROLE_CFO},
    {"privilege_key": keys.PRIV_GITHUB_ACCESS, "role_key": keys.ROLE_ENG_MANAGER},
]

# Direct exception grant: EMP-046 holds production-logs without a senior role.
_DIRECT_PRIVILEGES: list[dict[str, str]] = [
    {"employee_id": keys.EMP_EXCEPTION_GRANT, "privilege_key": keys.PRIV_PRODUCTION_LOGS},
]

_OWNS: list[dict[str, str]] = [
    {"team_key": keys.TEAM_PLATFORM, "system_key": keys.SYSTEM_VPN},
    {"team_key": keys.TEAM_PLATFORM, "system_key": keys.SYSTEM_OKTA},
    {"team_key": keys.TEAM_PLATFORM, "system_key": keys.SYSTEM_MDM},
    {"team_key": keys.TEAM_PLATFORM, "system_key": keys.SYSTEM_GITHUB},
    {"team_key": keys.TEAM_PLATFORM, "system_key": keys.SYSTEM_JIRA},
    {"team_key": keys.TEAM_BACKEND, "system_key": keys.SYSTEM_STAGING},
    {"team_key": keys.TEAM_PLATFORM, "system_key": keys.SYSTEM_PRODUCTION},
    {"team_key": keys.TEAM_PLATFORM, "system_key": keys.SYSTEM_PROD_DB},
    {"team_key": keys.TEAM_SECURITY, "system_key": keys.SYSTEM_SIEM},
    {"team_key": keys.TEAM_SALES, "system_key": keys.SYSTEM_SALESFORCE},
    {"team_key": keys.TEAM_FINANCE, "system_key": keys.SYSTEM_NETSUITE},
]

_SUPPORTED_BY: list[dict[str, str]] = [
    {"system_key": keys.SYSTEM_VPN, "support_team_key": keys.SUPPORT_IT},
    {"system_key": keys.SYSTEM_OKTA, "support_team_key": keys.SUPPORT_IT},
    {"system_key": keys.SYSTEM_MDM, "support_team_key": keys.SUPPORT_IT},
    {"system_key": keys.SYSTEM_GITHUB, "support_team_key": keys.SUPPORT_IT},
    {"system_key": keys.SYSTEM_JIRA, "support_team_key": keys.SUPPORT_IT},
    {"system_key": keys.SYSTEM_STAGING, "support_team_key": keys.SUPPORT_IT},
    {"system_key": keys.SYSTEM_PRODUCTION, "support_team_key": keys.SUPPORT_IT},
    {"system_key": keys.SYSTEM_PROD_DB, "support_team_key": keys.SUPPORT_IT},
    {"system_key": keys.SYSTEM_SIEM, "support_team_key": keys.SUPPORT_SECURITY},
    {"system_key": keys.SYSTEM_SALESFORCE, "support_team_key": keys.SUPPORT_IT},
    {"system_key": keys.SYSTEM_NETSUITE, "support_team_key": keys.SUPPORT_IT},
]

# First-line IT: the two specialists, plus two platform engineers as
# second-line staff. Security ops is staffed by the security engineers.
_ON_SUPPORT_TEAM: list[dict[str, str]] = [
    {"employee_id": keys.EMP_IT_SUPPORT_1, "support_team_key": keys.SUPPORT_IT},
    {"employee_id": keys.EMP_IT_SUPPORT_2, "support_team_key": keys.SUPPORT_IT},
    {"employee_id": "EMP-022", "support_team_key": keys.SUPPORT_IT},
    {"employee_id": "EMP-023", "support_team_key": keys.SUPPORT_IT},
    {"employee_id": "EMP-058", "support_team_key": keys.SUPPORT_SECURITY},
    {"employee_id": "EMP-059", "support_team_key": keys.SUPPORT_SECURITY},
    {"employee_id": "EMP-060", "support_team_key": keys.SUPPORT_SECURITY},
]

_ESCALATES_TO: list[dict[str, Any]] = [
    {"support_team_key": keys.SUPPORT_IT, "level": 1, "employee_id": keys.EMP_IT_SUPPORT_1},
    {"support_team_key": keys.SUPPORT_IT, "level": 2, "employee_id": keys.EMP_PLATFORM_MANAGER},
    {"support_team_key": keys.SUPPORT_IT, "level": 3, "employee_id": keys.EMP_CTO},
    {"support_team_key": keys.SUPPORT_SECURITY, "level": 1, "employee_id": keys.EMP_SECURITY_LEAD},
    {"support_team_key": keys.SUPPORT_SECURITY, "level": 2, "employee_id": keys.EMP_CTO},
]

# ---------------------------------------------------------------------------
# Cypher (parameterized; MERGE-only, idempotent)
# ---------------------------------------------------------------------------

_CONSTRAINTS: list[str] = [
    "CREATE CONSTRAINT employee_id IF NOT EXISTS FOR (e:Employee) REQUIRE e.id IS UNIQUE",
    "CREATE CONSTRAINT team_key IF NOT EXISTS FOR (t:Team) REQUIRE t.key IS UNIQUE",
    "CREATE CONSTRAINT department_key IF NOT EXISTS FOR (d:Department) REQUIRE d.key IS UNIQUE",
    "CREATE CONSTRAINT role_key IF NOT EXISTS FOR (r:Role) REQUIRE r.key IS UNIQUE",
    "CREATE CONSTRAINT privilege_key IF NOT EXISTS FOR (p:Privilege) REQUIRE p.key IS UNIQUE",
    "CREATE CONSTRAINT system_key IF NOT EXISTS FOR (s:System) REQUIRE s.key IS UNIQUE",
    "CREATE CONSTRAINT support_team_key IF NOT EXISTS FOR (st:SupportTeam) REQUIRE st.key IS UNIQUE",
]

_MERGE_DEPARTMENTS = """
UNWIND $rows AS row
MERGE (d:Department {key: row.key})
SET d.name = row.name
"""

_MERGE_TEAMS = """
UNWIND $rows AS row
MERGE (t:Team {key: row.key})
SET t.name = row.name
"""

_MERGE_ROLES = """
UNWIND $rows AS row
MERGE (r:Role {key: row.key})
SET r.name = row.name, r.level = row.level
"""

_MERGE_PRIVILEGES = """
UNWIND $rows AS row
MERGE (p:Privilege {key: row.key})
SET p.name = row.name, p.description = row.description, p.risk_level = row.risk_level
"""

_MERGE_SYSTEMS = """
UNWIND $rows AS row
MERGE (s:System {key: row.key})
SET s.name = row.name, s.category = row.category
"""

_MERGE_SUPPORT_TEAMS = """
UNWIND $rows AS row
MERGE (st:SupportTeam {key: row.key})
SET st.name = row.name, st.queue = row.queue
"""

_MERGE_EMPLOYEES = """
UNWIND $rows AS row
MERGE (e:Employee {id: row.id})
SET e.name = row.name, e.email = row.email, e.title = row.title,
    e.location = row.location, e.remote = row.remote
"""

_MERGE_PART_OF = """
UNWIND $rows AS row
MATCH (t:Team {key: row.team_key})
MATCH (d:Department {key: row.department_key})
MERGE (t)-[:PART_OF]->(d)
"""

_MERGE_MEMBER_OF = """
UNWIND $rows AS row
MATCH (e:Employee {id: row.employee_id})
MATCH (t:Team {key: row.team_key})
MERGE (e)-[:MEMBER_OF]->(t)
"""

_MERGE_HAS_ROLE = """
UNWIND $rows AS row
MATCH (e:Employee {id: row.employee_id})
MATCH (r:Role {key: row.role_key})
MERGE (e)-[:HAS_ROLE]->(r)
"""

_MERGE_REPORTS_TO = """
UNWIND $rows AS row
MATCH (e:Employee {id: row.employee_id})
MATCH (m:Employee {id: row.manager_id})
MERGE (e)-[:REPORTS_TO]->(m)
"""

_MERGE_GRANTS = """
UNWIND $rows AS row
MATCH (r:Role {key: row.role_key})
MATCH (p:Privilege {key: row.privilege_key})
MERGE (r)-[:GRANTS]->(p)
"""

_MERGE_ELIGIBLE_FOR = """
UNWIND $rows AS row
MATCH (r:Role {key: row.role_key})
MATCH (p:Privilege {key: row.privilege_key})
MERGE (r)-[:ELIGIBLE_FOR]->(p)
"""

_MERGE_APPROVAL_BY = """
UNWIND $rows AS row
MATCH (p:Privilege {key: row.privilege_key})
MATCH (r:Role {key: row.role_key})
MERGE (p)-[:APPROVAL_BY]->(r)
"""

_MERGE_HAS_PRIVILEGE = """
UNWIND $rows AS row
MATCH (e:Employee {id: row.employee_id})
MATCH (p:Privilege {key: row.privilege_key})
MERGE (e)-[:HAS_PRIVILEGE]->(p)
"""

_MERGE_OWNS = """
UNWIND $rows AS row
MATCH (t:Team {key: row.team_key})
MATCH (s:System {key: row.system_key})
MERGE (t)-[:OWNS]->(s)
"""

_MERGE_SUPPORTED_BY = """
UNWIND $rows AS row
MATCH (s:System {key: row.system_key})
MATCH (st:SupportTeam {key: row.support_team_key})
MERGE (s)-[:SUPPORTED_BY]->(st)
"""

_MERGE_ON_SUPPORT_TEAM = """
UNWIND $rows AS row
MATCH (e:Employee {id: row.employee_id})
MATCH (st:SupportTeam {key: row.support_team_key})
MERGE (e)-[:ON_SUPPORT_TEAM]->(st)
"""

_MERGE_ESCALATES_TO = """
UNWIND $rows AS row
MATCH (st:SupportTeam {key: row.support_team_key})
MATCH (e:Employee {id: row.employee_id})
MERGE (st)-[:ESCALATES_TO {level: row.level}]->(e)
"""

_NODE_COUNTS = """
MATCH (n)
UNWIND labels(n) AS label
RETURN label, count(*) AS count
ORDER BY label
"""

_REL_COUNTS = """
MATCH ()-[r]->()
RETURN type(r) AS type, count(r) AS count
ORDER BY type
"""

# ---------------------------------------------------------------------------
# Seed runner
# ---------------------------------------------------------------------------

_STEPS: list[tuple[str, str, list[dict[str, Any]]]] = [
    ("Department nodes", _MERGE_DEPARTMENTS, _DEPARTMENTS),
    ("Team nodes", _MERGE_TEAMS, _TEAMS),
    ("Role nodes", _MERGE_ROLES, _ROLES),
    ("Privilege nodes", _MERGE_PRIVILEGES, _PRIVILEGES),
    ("System nodes", _MERGE_SYSTEMS, _SYSTEMS),
    ("SupportTeam nodes", _MERGE_SUPPORT_TEAMS, _SUPPORT_TEAMS),
    ("Employee nodes", _MERGE_EMPLOYEES, _EMPLOYEES),
    ("PART_OF", _MERGE_PART_OF, _TEAM_DEPARTMENTS),
    ("MEMBER_OF", _MERGE_MEMBER_OF, _MEMBER_OF),
    ("HAS_ROLE", _MERGE_HAS_ROLE, _HAS_ROLE),
    ("REPORTS_TO", _MERGE_REPORTS_TO, _REPORTS_TO),
    ("GRANTS", _MERGE_GRANTS, _GRANTS_ROWS),
    ("ELIGIBLE_FOR", _MERGE_ELIGIBLE_FOR, _ELIGIBLE_ROWS),
    ("APPROVAL_BY", _MERGE_APPROVAL_BY, _APPROVAL_BY),
    ("HAS_PRIVILEGE (exceptions)", _MERGE_HAS_PRIVILEGE, _DIRECT_PRIVILEGES),
    ("OWNS", _MERGE_OWNS, _OWNS),
    ("SUPPORTED_BY", _MERGE_SUPPORTED_BY, _SUPPORTED_BY),
    ("ON_SUPPORT_TEAM", _MERGE_ON_SUPPORT_TEAM, _ON_SUPPORT_TEAM),
    ("ESCALATES_TO", _MERGE_ESCALATES_TO, _ESCALATES_TO),
]


async def seed() -> None:
    for statement in _CONSTRAINTS:
        await run_query(statement)
    print(f"Constraints ensured: {len(_CONSTRAINTS)}")

    for label, statement, rows in _STEPS:
        await run_query(statement, {"rows": rows})
        print(f"Merged {label}: {len(rows)} rows")

    print("\nGraph totals (queried back from Neo4j):")
    for row in await run_query(_NODE_COUNTS):
        print(f"  (:{row['label']}) {row['count']}")
    for row in await run_query(_REL_COUNTS):
        print(f"  [:{row['type']}] {row['count']}")


async def main() -> int:
    try:
        await seed()
    except OrgUnavailableError as exc:
        print(f"Neo4j unavailable: {exc}", file=sys.stderr)
        print(
            "Could not reach the org graph — is docker compose up? "
            "Neo4j must be listening at the configured IT_NEO4J_URI "
            "(the hosted URI provided by the Neo4j portal).",
            file=sys.stderr,
        )
        return 1
    finally:
        await close_driver()
    print("\nSeed complete: GA-VoiceAI (60 employees, EMP-001..EMP-060)")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(asyncio.run(main()))
