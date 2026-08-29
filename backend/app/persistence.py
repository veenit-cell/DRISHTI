from pathlib import Path

import psycopg


def database_ready(database_url: str) -> bool:
    try:
        with psycopg.connect(database_url, connect_timeout=1) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                return cursor.fetchone() == (1,)
    except psycopg.Error:
        return False


def apply_foundation_migration(database_url: str) -> None:
    migrations_dir = Path(__file__).parents[1] / "migrations"
    sql = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(migrations_dir.glob("*.sql"))
    )
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql)


if __name__ == "__main__":
    from app.core.config import get_settings

    apply_foundation_migration(get_settings().database_url)
    print("Applied foundation migration 0001_foundation.sql")
