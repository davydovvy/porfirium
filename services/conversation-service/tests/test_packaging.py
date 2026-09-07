from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]


def test_container_image_includes_database_migrations() -> None:
    dockerfile = (SERVICE_ROOT / "Dockerfile").read_text()

    assert "COPY migrations migrations" in dockerfile
    assert list((SERVICE_ROOT / "migrations").glob("*.sql"))
