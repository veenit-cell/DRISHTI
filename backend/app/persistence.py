from pathlib import Path
from time import sleep

import psycopg

MIGRATION_ATTEMPTS = 10
MIGRATION_RETRY_DELAY_SECONDS = 1


def database_ready(database_url: str) -> bool:
    try:
        with psycopg.connect(database_url, connect_timeout=1) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                if cursor.fetchone() != (1,):
                    return False
                cursor.execute("SELECT PostGIS_Version()")
                return bool(cursor.fetchone())
    except psycopg.Error:
        return False


def apply_foundation_migration(
    database_url: str,
    attempts: int = MIGRATION_ATTEMPTS,
    retry_delay_seconds: float = MIGRATION_RETRY_DELAY_SECONDS,
) -> None:
    migrations_dir = Path(__file__).parents[1] / "migrations"
    sql = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(migrations_dir.glob("*.sql"))
    )
    for attempt in range(1, attempts + 1):
        try:
            with psycopg.connect(database_url, connect_timeout=2) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(sql)
            return
        except psycopg.OperationalError:
            if attempt == attempts:
                raise
            sleep(retry_delay_seconds)


if __name__ == "__main__":
    from app.core.config import get_settings

    apply_foundation_migration(get_settings().database_url)
    print("Applied database migrations")
