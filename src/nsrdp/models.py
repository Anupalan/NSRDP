"""Import every ORM model so metadata (and Alembic) see all tables."""


def import_all_models() -> None:
    import nsrdp.events.models  # noqa: F401
    import nsrdp.events.store  # noqa: F401  (registers append-only listeners)
    import nsrdp.rbac.models  # noqa: F401
    import nsrdp.registry.models  # noqa: F401
    import nsrdp.rules.models  # noqa: F401
    import nsrdp.rules.service  # noqa: F401  (registers immutability listeners)
    import nsrdp.tenancy.models  # noqa: F401
