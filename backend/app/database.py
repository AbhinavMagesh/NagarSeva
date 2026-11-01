from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as db:
        yield db


def initialize_database() -> None:
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
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
