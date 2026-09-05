from pathlib import Path

MIGRATION = Path(__file__).parents[1] / "migrations" / "0001_registry_foundation.sql"


def test_foundation_migration_owns_required_state() -> None:
    sql = MIGRATION.read_text()

    for table in (
        "agents",
        "releases",
        "access_grants",
        "access_grant_audit",
        "publication_audit",
        "run_specifications",
        "idempotency_records",
    ):
        assert f"CREATE TABLE {table}" in sql


def test_release_content_and_audit_are_database_protected() -> None:
    sql = MIGRATION.read_text()

    assert "CREATE TRIGGER releases_immutable_content" in sql
    assert "CREATE TRIGGER publication_audit_append_only" in sql
    assert "CREATE TRIGGER access_grant_audit_append_only" in sql
    assert "CREATE TRIGGER run_specifications_immutable" in sql
    assert "a deprecated release cannot be republished" in sql
    assert "status = 'deprecated' AND deprecated_by IS NOT NULL" in sql
