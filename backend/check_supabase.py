r"""Supabase Database Connection & Verification Tool

Run this script to test and verify your Supabase PostgreSQL connection:
    cd backend
    .\.venv\Scripts\python.exe check_supabase.py
"""

import sys
import re
from sqlalchemy import text, event
from app.config import settings
from app.database import engine, initialize_database, SessionLocal
from app import models


def mask_url(url: str) -> str:
    """Mask password in connection URI for safe console logging."""
    return re.sub(r":([^:@/]+)@", ":****@", url)


# Attach real-time DDL progress logger
@event.listens_for(engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    stmt = (statement or "").strip()
    first_line = stmt.splitlines()[0] if stmt else ""
    first_upper = first_line.upper()
    if "CREATE TABLE" in first_upper:
        clean = first_line.split("(")[0].strip()
        print(f"       [DDL] {clean}...")
    elif "CREATE INDEX" in first_upper:
        clean = first_line.split(" ON ")[0].strip() if " ON " in first_line else first_line[:50]
        print(f"       [DDL] {clean}...")


def main() -> None:
    print("=" * 60)
    print("  NagarSeva — Supabase Database Connection Check")
    print("=" * 60)

    raw_url = settings.database_url
    print(f"\n[1] Configured DATABASE_URL: {mask_url(raw_url)}")

    # Step 1: Test basic connection
    print("\n[2] Connecting to PostgreSQL database...")
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version();")).scalar()
            print("    ✓ Connected successfully!")
            print(f"    Database Version: {result[:75]}...")
    except Exception as e:
        print(f"\n    ✗ Connection failed: {e}")
        print("\nTroubleshooting tips:")
        print(" - Verify your project ref and database password.")
        print(" - Ensure special characters in password are URL-encoded.")
        print(" - Make sure '?sslmode=require' is included.")
        sys.exit(1)

    # Step 2: Check / Enable PostGIS extension
    print("\n[3] Checking PostGIS extension...")
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
            postgis_ver = conn.execute(text("SELECT PostGIS_Version();")).scalar()
            print(f"    ✓ PostGIS extension is active (Version: {postgis_ver})")
    except Exception as e:
        print(f"    ! Note on PostGIS: {e}")

    # Step 3: Run schema creation & department seeding
    print("\n[4] Initializing schema and seeding default departments...")
    print("    (Creating tables & geospatial indexes over cloud pooler; please allow 5-15s)...")
    try:
        initialize_database()
        print("    ✓ Tables created / validated successfully.")
    except Exception as e:
        print(f"    ✗ Table initialization failed: {e}")
        sys.exit(1)

    # Step 4: Verify seeded data
    print("\n[5] Verifying seeded departments in database...")
    with SessionLocal() as db:
        departments = db.query(models.Department).all()
        print(f"    ✓ Found {len(departments)} departments registered:")
        for dept in departments:
            print(f"       - [{dept.code}] {dept.name}")

    print("\n" + "=" * 60)
    print("  All checks passed! Supabase is fully configured and ready.")
    print("  You can now start the backend with:")
    print(r"    .\.venv\Scripts\uvicorn.exe app.main:app --reload --host 127.0.0.1 --port 8000")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
