"""Named, parameterized Cypher constants — the only Cypher in the codebase.

Values are passed exclusively through query parameters ($name); no string
interpolation of values, ever. No LLM-generated Cypher in V1 (DESIGN.md §4).
"""

# Full org context for one employee: profile, team, department, roles, manager.
EMPLOYEE_ORG_CONTEXT = """
MATCH (e:Employee {id: $employee_id})
OPTIONAL MATCH (e)-[:MEMBER_OF]->(t:Team)
OPTIONAL MATCH (t)-[:PART_OF]->(d:Department)
OPTIONAL MATCH (e)-[:HAS_ROLE]->(r:Role)
OPTIONAL MATCH (e)-[:REPORTS_TO]->(m:Employee)
RETURN e.name AS name, e.email AS email, e.title AS title,
       e.location AS location, e.remote AS remote,
       t.key AS team_key, t.name AS team_name,
       d.key AS department_key, d.name AS department_name,
       collect(DISTINCT r.key) AS roles,
       m.id AS manager_id, m.name AS manager_name
"""

# Direct manager via REPORTS_TO.
MANAGER = """
MATCH (:Employee {id: $employee_id})-[:REPORTS_TO]->(m:Employee)
RETURN m.id AS id, m.name AS name
"""

# Effective privilege (direct grant OR role GRANTS) and approval eligibility
# (role ELIGIBLE_FOR) in one round trip.
PRIVILEGE_CHECK = """
MATCH (e:Employee {id: $employee_id})
RETURN
  EXISTS { (e)-[:HAS_PRIVILEGE]->(:Privilege {key: $privilege_key}) }
    OR EXISTS { (e)-[:HAS_ROLE]->(:Role)-[:GRANTS]->(:Privilege {key: $privilege_key}) }
    AS has_privilege,
  EXISTS { (e)-[:HAS_ROLE]->(:Role)-[:ELIGIBLE_FOR]->(:Privilege {key: $privilege_key}) }
    AS eligible_with_approval
"""

# Team that owns a system.
SYSTEM_OWNER = """
MATCH (t:Team)-[:OWNS]->(:System {key: $system_key})
RETURN t.key AS team_key, t.name AS team_name
"""

# Support team responsible for a system.
SYSTEM_SUPPORT_TEAM = """
MATCH (:System {key: $system_key})-[:SUPPORTED_BY]->(st:SupportTeam)
RETURN st.key AS key, st.name AS name
"""

# Support team looked up directly by key (fallback when the system is unknown).
SUPPORT_TEAM_BY_KEY = """
MATCH (st:SupportTeam {key: $support_team_key})
RETURN st.key AS key, st.name AS name
"""

# Nearest manager up the requester's REPORTS_TO chain (1..6 hops) holding a
# role designated by (privilege)-[:APPROVAL_BY]->(role).
REQUIRED_APPROVER = """
MATCH path = (:Employee {id: $employee_id})-[:REPORTS_TO*1..6]->(m:Employee)
MATCH (:Privilege {key: $privilege_key})-[:APPROVAL_BY]->(:Role)<-[:HAS_ROLE]-(m)
RETURN m.id AS id, m.name AS name, length(path) AS distance
ORDER BY distance ASC
LIMIT 1
"""

# Escalation chain for a system's support team, ordered by level.
ESCALATION_CHAIN = """
MATCH (:System {key: $system_key})-[:SUPPORTED_BY]->(st:SupportTeam)
MATCH (st)-[esc:ESCALATES_TO]->(target:Employee)
RETURN st.key AS team_key, st.name AS team_name, esc.level AS level,
       target.id AS employee_id, target.name AS employee_name, target.title AS employee_title
ORDER BY esc.level ASC
"""

# Demo sign-in picker: every employee with team, ordered by id.
DIRECTORY = """
MATCH (e:Employee)
OPTIONAL MATCH (e)-[:MEMBER_OF]->(t:Team)
RETURN e.id AS id, e.name AS name, e.title AS title,
       t.key AS team_key, t.name AS team_name
ORDER BY e.id ASC
"""
