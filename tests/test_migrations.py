"""Migrations must produce exactly the schema the ORM models describe."""

import os

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from nsrdp.db import Base

PG = os.environ.get("NSRDP_TEST_DATABASE_URL", "")


@pytest.mark.skipif(not PG.startswith("postgresql"), reason="needs PostgreSQL")
def test_migrations_match_models():
    engine = create_engine(PG)
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
    cfg = Config("alembic.ini")
    cfg.attributes["url"] = PG
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    command.downgrade(cfg, "base")
    engine.dispose()
    assert diff == []
