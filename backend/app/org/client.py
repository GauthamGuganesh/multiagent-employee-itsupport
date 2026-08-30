"""Neo4j async driver singleton and query runner.

Every Cypher statement reaching this module is a named constant from
app.org.queries; values travel exclusively through `params`. Driver and
connection failures are wrapped in OrgUnavailableError so callers can fail
closed (privilege checks) or degrade (escalation targets) per DESIGN.md §10.5.
"""
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase
from neo4j.exceptions import DriverError, Neo4jError

from app.config import get_settings

_driver: AsyncDriver | None = None


class OrgUnavailableError(Exception):
    """The org graph could not be reached or the query could not be run."""


def get_driver() -> AsyncDriver:
    global _driver
    if _driver is None:
        settings = get_settings()
        if not all((settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)):
            raise OrgUnavailableError(
                "Hosted Neo4j is not configured. Set IT_NEO4J_URI, IT_NEO4J_USER, and "
                "IT_NEO4J_PASSWORD from the Neo4j portal."
            )
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
    return _driver


def set_driver_for_tests(driver: AsyncDriver | None) -> None:
    """Inject a stub driver; pass None to restore lazy creation."""
    global _driver
    _driver = driver


async def run_query(cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Execute one parameterized Cypher statement and return records as dicts."""
    try:
        driver = get_driver()
        async with driver.session(database=get_settings().neo4j_database) as session:
            result = await session.run(cypher, params or {})
            return [record.data() async for record in result]
    except (Neo4jError, DriverError, OSError) as exc:
        raise OrgUnavailableError(f"{type(exc).__name__}: {exc}") from exc


async def close_driver() -> None:
    global _driver
    if _driver is not None:
        await _driver.close()
    _driver = None
