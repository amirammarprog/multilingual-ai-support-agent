"""Drop and recreate the schema of the configured database (development only), then migrate.

python scripts/reset_db.py && python -m app.cli seed
"""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.cli import bootstrap_db
from app.config import get_settings

settings = get_settings()
if settings.app_env == "production":
    raise SystemExit("refusing to reset a production database")
bootstrap_db()
role = make_url(settings.database_url).username
engine = create_engine(settings.migration_database_url, isolation_level="AUTOCOMMIT")
with engine.connect() as conn:
    conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
    conn.execute(text("CREATE SCHEMA public"))
    conn.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
engine.dispose()
command.upgrade(Config("alembic.ini"), "head")
print("database reset and migrated")
