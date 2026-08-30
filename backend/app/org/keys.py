"""Canonical organizational keys — the single vocabulary shared by the Neo4j
seed, mock tools, workflows, and tests. Postgres stores these as logical
references; Neo4j is authoritative for what they mean."""

# --- Departments ---
DEPT_ENGINEERING = "engineering"
DEPT_PRODUCT = "product"
DEPT_FINANCE = "finance"
DEPT_PEOPLE = "people"
DEPT_REVENUE = "revenue"
DEPT_PLATFORM = "platform"
DEPT_SECURITY = "security"

# --- Teams ---
TEAM_EXEC = "exec"
TEAM_BACKEND = "backend"
TEAM_FRONTEND = "frontend"
TEAM_PLATFORM = "platform-it"
TEAM_SECURITY = "security"
TEAM_PRODUCT = "product"
TEAM_FINANCE = "finance"
TEAM_HR = "people-ops"
TEAM_SALES = "sales"
TEAM_CS = "customer-success"

# --- Support teams ---
SUPPORT_IT = "it-support"          # first-line IT (staffed by platform-it)
SUPPORT_SECURITY = "security-ops"  # security operations

# --- Roles ---
ROLE_CEO = "ceo"
ROLE_CTO = "cto"
ROLE_CFO = "cfo"
ROLE_CPO = "cpo"                    # head of product
ROLE_CHRO = "chro"                  # head of people
ROLE_CRO = "cro"                    # head of revenue
ROLE_ENG_MANAGER = "eng-manager"
ROLE_PLATFORM_MANAGER = "platform-manager"
ROLE_SECURITY_LEAD = "security-lead"
ROLE_BACKEND_ENGINEER = "backend-engineer"
ROLE_SENIOR_BACKEND_ENGINEER = "senior-backend-engineer"
ROLE_FRONTEND_ENGINEER = "frontend-engineer"
ROLE_SENIOR_FRONTEND_ENGINEER = "senior-frontend-engineer"
ROLE_PLATFORM_ENGINEER = "platform-engineer"
ROLE_IT_SUPPORT_SPECIALIST = "it-support-specialist"
ROLE_SECURITY_ENGINEER = "security-engineer"
ROLE_PRODUCT_MANAGER = "product-manager"
ROLE_PRODUCT_DESIGNER = "product-designer"
ROLE_ACCOUNTANT = "accountant"
ROLE_FINANCE_CONTROLLER = "finance-controller"
ROLE_HR_PARTNER = "hr-partner"
ROLE_ACCOUNT_EXECUTIVE = "account-executive"
ROLE_SALES_MANAGER = "sales-manager"
ROLE_CSM = "customer-success-manager"
ROLE_CS_LEAD = "customer-success-lead"
ROLE_CONTRACTOR = "contractor"

# --- Systems ---
SYSTEM_VPN = "vpn"
SYSTEM_GITHUB = "github"
SYSTEM_JIRA = "jira"
SYSTEM_STAGING = "staging-env"
SYSTEM_PRODUCTION = "production-infra"
SYSTEM_PROD_DB = "production-db"
SYSTEM_OKTA = "okta"                # identity provider
SYSTEM_MDM = "mdm"                  # managed devices
SYSTEM_SIEM = "siem"                # security tooling
SYSTEM_SALESFORCE = "salesforce"
SYSTEM_NETSUITE = "netsuite"

# --- Privileges ---
# Baseline (granted to every employee via their role)
PRIV_SELF_ACCOUNT_UNLOCK = "self-account-unlock"
PRIV_SELF_PASSWORD_RESET = "self-password-reset"
PRIV_SELF_SESSION_REVOKE = "self-session-revoke"
PRIV_STANDARD_SOFTWARE = "standard-software-install"
# Engineering
PRIV_GITHUB_ACCESS = "github-access"
PRIV_JIRA_ACCESS = "jira-access"
PRIV_STAGING_ACCESS = "staging-access"
PRIV_PRODUCTION_LOGS = "production-logs"
PRIV_PROD_DB_ACCESS = "production-db-access"
PRIV_DEV_TOOLS_INSTALL = "dev-tools-install"      # e.g. Docker Desktop
# Platform / IT
PRIV_KUBERNETES_ADMIN = "kubernetes-admin"
PRIV_PROD_INFRA_ADMIN = "production-infra-admin"
PRIV_VPN_ADMIN = "vpn-admin"
PRIV_DEVICE_ADMIN = "device-admin"                # MDM actions on others' devices
# Security
PRIV_SECURITY_TOOLING = "security-tooling"
PRIV_AUTH_EVENT_ACCESS = "auth-event-access"
PRIV_SESSION_REVOKE_OTHERS = "session-revoke-others"
PRIV_DEVICE_QUARANTINE = "device-quarantine"
# Business systems
PRIV_SALESFORCE_ACCESS = "salesforce-access"
PRIV_NETSUITE_ACCESS = "netsuite-access"
# Approval capability
PRIV_APPROVE_ACCESS_REQUESTS = "approve-access-requests"

# --- Notable employees (fixed IDs the scenarios and mockworld rely on) ---
EMP_CEO = "EMP-001"
EMP_CTO = "EMP-002"
EMP_CPO = "EMP-003"
EMP_CFO = "EMP-004"
EMP_CHRO = "EMP-005"
EMP_CRO = "EMP-006"
EMP_ENG_MANAGER = "EMP-007"       # approves engineering access requests
EMP_PLATFORM_MANAGER = "EMP-008"  # VPN escalation level 2
EMP_SECURITY_LEAD = "EMP-009"     # security escalation target
EMP_BACKEND_LEAD = "EMP-010"      # senior backend (production logs)
EMP_017_BACKEND = "EMP-017"       # 'who manages EMP-017' demo (reports to EMP-010)
EMP_IT_SUPPORT_1 = "EMP-025"      # first-line IT support specialist
EMP_IT_SUPPORT_2 = "EMP-026"
EMP_PLATFORM_ENG = "EMP-028"      # HAS dev-tools-install (scenario 3)
EMP_FRONTEND_ENG = "EMP-032"      # eligible for dev-tools-install, not granted (scenario 4)
EMP_LOCKED_OUT = "EMP-034"        # mockworld: account locked (scenario 1)
EMP_VPN_SUSPECT = "EMP-014"       # mockworld: VPN drops + unknown-IP auth (scenario 2)
EMP_SLOW_LAPTOP = "EMP-041"       # mockworld: disk 96% full (scenario 5)
EMP_EXCEPTION_GRANT = "EMP-046"   # direct HAS_PRIVILEGE exception (prod logs w/o senior role)
EMP_CONTRACTOR = "EMP-052"        # contractor, minimal privileges
