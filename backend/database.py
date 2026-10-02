import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://root@127.0.0.1:3306/s0036_rel",
)


engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 5} if DATABASE_URL.startswith("mysql") else {},
)


class Base(DeclarativeBase):
    pass


db_session_basede26 = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


def get_db() -> Generator[Session, None, None]:
    db = db_session_basede26()

    try:
        yield db
    finally:
        db.close()
