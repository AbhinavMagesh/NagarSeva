import logging
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

logger = logging.getLogger("nagarseva.database")


def normalize_database_url(url: str) -> str:
    cleaned = (url or "").strip()
    # Handle accidental "DATABASE_URL=" prefix or quotes
    while cleaned.startswith("DATABASE_URL="):
        cleaned = cleaned[len("DATABASE_URL=") :].strip()
    if (cleaned.startswith('"') and cleaned.endswith('"')) or (cleaned.startswith("'") and cleaned.endswith("'")):
        cleaned = cleaned[1:-1].strip()

    if cleaned.startswith("postgres://"):
        cleaned = "postgresql+psycopg://" + cleaned[len("postgres://") :]
    elif cleaned.startswith("postgresql://"):
        cleaned = "postgresql+psycopg://" + cleaned[len("postgresql://") :]

    # Supabase and other managed cloud Postgres instances require SSL
    if ("supabase.co" in cleaned or "pooler.supabase.com" in cleaned) and "sslmode=" not in cleaned:
        sep = "&" if "?" in cleaned else "?"
        cleaned = f"{cleaned}{sep}sslmode=require"

    return cleaned


engine = create_engine(normalize_database_url(settings.database_url), pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as db:
        yield db


def initialize_database() -> None:
    with engine.begin() as connection:
        try:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        except Exception as exc:
            logger.warning("Notice on postgis extension creation (it may already be enabled): %s", exc)
    from app import models

    Base.metadata.create_all(bind=engine)
    with SessionLocal.begin() as db:
        for code, name in (
            ("PWD", "Public Works Department"),
            ("WATER", "Water Board"),
            ("SANITATION", "Municipal Sanitation"),
            ("ELECTRICITY", "Electricity Board"),
            ("ENV", "Pollution Control Board"),
            ("MUNICIPAL", "Municipal Corporation"),
        ):
            if not db.query(models.Department).filter_by(code=code).first():
                db.add(models.Department(code=code, name=name, jurisdiction="DISTRICT"))
