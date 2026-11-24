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


@pytest.mark.skipif(not PG.startswith("postgresql"), reason="needs PostgreSQL")
def test_migrated_event_table_is_append_only():
    from sqlalchemy import text

    engine = create_engine(PG)
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
    cfg = Config("alembic.ini")
    cfg.attributes["url"] = PG
    command.upgrade(cfg, "head")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "INSERT INTO tenants (id, level, code, name, tenant_path, created_at) "
                "VALUES ('t', 'platform', 'P', 'P', '/t/', now())"
            )
            conn.exec_driver_sql(
                "INSERT INTO events (id, tenant_id, tenant_path, stream_type, stream_id, seq, "
                "event_type, evidence, actor, occurred_at, recorded_at, hash) VALUES "
                "('e', 't', '/t/', 's', '1', 1, 'x', '[]', 'a', now(), now(), 'h')"
            )
        with pytest.raises(Exception, match="append-only"), engine.begin() as conn:
            conn.execute(text("UPDATE events SET actor = 'b'"))
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql("DROP TRIGGER IF EXISTS events_append_only ON events")
        command.downgrade(cfg, "base")
        engine.dispose()
