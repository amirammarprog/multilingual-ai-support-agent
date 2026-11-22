"""Operational commands.

python -m app.cli bootstrap-db   create the database (if missing) and the application role
python -m app.cli seed           load the fictional demo shops and knowledge base (idempotent)
python -m app.cli create-staff   create an admin user for a shop
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.config import get_settings

_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def bootstrap_db() -> None:
    """Create the target database and a login role without BYPASSRLS for the application."""
    settings = get_settings()
    owner_url = make_url(settings.migration_database_url)
    app_url = make_url(settings.database_url)
    role, password, dbname = app_url.username or "", app_url.password or "", owner_url.database or ""
    if not (_IDENT.match(role) and _IDENT.match(dbname)):
        raise SystemExit("database and role names must be simple identifiers")

    admin = create_engine(owner_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        if not conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": dbname}).scalar():
            conn.execute(text(f'CREATE DATABASE "{dbname}"'))
            print(f"created database {dbname}")
        exists = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).scalar()
        # Identifiers cannot be bound parameters; the role name is validated above and the
        # password is passed through format('%L') so PostgreSQL quotes it.
        stmt = conn.execute(
            text(
                "SELECT format('ALTER ROLE %I WITH LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD %L', "
                "CAST(:r AS text), CAST(:p AS text))"
            ),
            {"r": role, "p": password},
        ).scalar_one()
        if not exists:
            conn.execute(text(f'CREATE ROLE "{role}"'))
            print(f"created role {role}")
        conn.exec_driver_sql(stmt)
    admin.dispose()

    owner = create_engine(owner_url, isolation_level="AUTOCOMMIT")
    with owner.connect() as conn:
        conn.execute(text(f'GRANT CONNECT ON DATABASE "{dbname}" TO "{role}"'))
        conn.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
    owner.dispose()
    print("bootstrap complete")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("bootstrap-db")
    seed = sub.add_parser("seed")
    seed.add_argument("--skip-knowledge", action="store_true", help="do not ingest the knowledge base")
    staff = sub.add_parser("create-staff")
    staff.add_argument("--shop", required=True)
    staff.add_argument("--email", required=True)
    staff.add_argument("--name", required=True)
    staff.add_argument("--role", default="admin", choices=["admin", "agent", "viewer"])
    args = parser.parse_args(argv)

    if args.command == "bootstrap-db":
        bootstrap_db()
    elif args.command == "seed":
        from app.seed.run import seed_all

        asyncio.run(seed_all(with_knowledge=not args.skip_knowledge))
    elif args.command == "create-staff":
        import getpass

        from app.seed.run import create_staff

        password = getpass.getpass("Password: ")
        asyncio.run(create_staff(args.shop, args.email, args.name, args.role, password))


if __name__ == "__main__":
    main(sys.argv[1:])
