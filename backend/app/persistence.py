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
    migration = Path(__file__).parents[1] / "migrations" / "0001_foundation.sql"
    sql = migration.read_text(encoding="utf-8")
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql)


if __name__ == "__main__":
    from app.core.config import get_settings

    apply_foundation_migration(get_settings().database_url)
    print("Applied foundation migration 0001_foundation.sql")
