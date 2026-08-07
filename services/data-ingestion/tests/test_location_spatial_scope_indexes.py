import re
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = SERVICE_ROOT / "migrations" / "location_spatial_scope_indexes.cypher"

EXPECTED_STATEMENTS = (
    """CREATE RANGE INDEX location_country_scope_derivation IF NOT EXISTS
FOR (l:Location) ON (l.country_scope_key, l.spatial_derivation_revision)""",
    """CREATE RANGE INDEX location_admin1_scope_derivation IF NOT EXISTS
FOR (l:Location) ON (l.admin1_scope_key, l.spatial_derivation_revision)""",
    """CREATE RANGE INDEX location_admin2_scope_derivation IF NOT EXISTS
FOR (l:Location) ON (l.admin2_scope_key, l.spatial_derivation_revision)""",
    """CREATE POINT INDEX location_geo IF NOT EXISTS
FOR (l:Location) ON (l.geo)""",
)


def _statements(text: str) -> tuple[str, ...]:
    return tuple(statement.strip() for statement in text.split(";") if statement.strip())


def test_spatial_scope_migration_has_exact_deterministic_index_contract() -> None:
    assert _statements(MIGRATION.read_text()) == EXPECTED_STATEMENTS


def test_spatial_scope_migration_is_additive_and_idempotent() -> None:
    text = MIGRATION.read_text()
    assert text.count("IF NOT EXISTS") == 4
    assert re.search(r"\b(DROP|DELETE|DETACH|REMOVE|SET|MERGE|CREATE \()\b", text) is None


def test_location_geo_point_index_is_declared_exactly_once_across_migrations() -> None:
    declarations = []
    for path in sorted(SERVICE_ROOT.glob("**/migrations/*.cypher")):
        declarations.extend(
            (path, match.group(0))
            for match in re.finditer(
                r"CREATE\s+POINT\s+INDEX\s+location_geo\s+IF\s+NOT\s+EXISTS",
                path.read_text(),
                re.IGNORECASE,
            )
        )

    assert declarations == [
        (MIGRATION, "CREATE POINT INDEX location_geo IF NOT EXISTS")
    ]
