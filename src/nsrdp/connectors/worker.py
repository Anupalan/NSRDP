"""Outbox dispatcher process: ``python -m nsrdp.connectors.worker``.

Runs from the same image as the API. Poll interval comes from NSRDP_DISPATCH_INTERVAL_SECONDS.
"""

from __future__ import annotations

import logging
import os
import time

from nsrdp.config import get_settings
from nsrdp.connectors.hub import ConnectorHub
from nsrdp.connectors.outbox import dispatch_due
from nsrdp.db import make_engine, make_session_factory
from nsrdp.models import import_all_models

log = logging.getLogger("nsrdp.worker")


def run_once(session_factory, hub: ConnectorHub) -> None:
    with session_factory() as session:
        result = dispatch_due(session, hub)
        session.commit()
    if result.delivered or result.retrying or result.dead:
        log.info(
            "delivered=%d retrying=%d dead=%d",
            len(result.delivered),
            len(result.retrying),
            len(result.dead),
        )


def main() -> None:
    logging.basicConfig(level=os.environ.get("NSRDP_LOG_LEVEL", "INFO"))
    import_all_models()
    settings = get_settings()
    session_factory = make_session_factory(make_engine(settings.database_url))
    hub = ConnectorHub.from_contracts_dir()
    interval = float(os.environ.get("NSRDP_DISPATCH_INTERVAL_SECONDS", "10"))
    while True:
        try:
            run_once(session_factory, hub)
        except Exception:
            log.exception("dispatch cycle failed")
        time.sleep(interval)


if __name__ == "__main__":
    main()
