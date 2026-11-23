from alembic import context

from nsrdp.config import get_settings
from nsrdp.db import Base, make_engine
from nsrdp.models import import_all_models

import_all_models()
target_metadata = Base.metadata


def run() -> None:
    url = context.config.attributes.get("url") or get_settings().database_url
    engine = make_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run()
