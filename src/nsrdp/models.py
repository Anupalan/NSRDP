"""Import every ORM model so metadata (and Alembic) see all tables."""


def import_all_models() -> None:
    import nsrdp.rbac.models  # noqa: F401
    import nsrdp.rules.models  # noqa: F401
    import nsrdp.rules.service  # noqa: F401  (registers immutability listeners)
    import nsrdp.tenancy.models  # noqa: F401
