"""Roles, permissions and segregation of duties (REC-02). All role data is configuration."""

from nsrdp.rbac.models import RoleAssignment
from nsrdp.rbac.policy import (
    AccessDenied,
    RbacPolicy,
    SegregationOfDutiesViolation,
    assign_role,
    authorize,
    ensure_distinct_actors,
    has_permission,
)

__all__ = [
    "AccessDenied",
    "RbacPolicy",
    "RoleAssignment",
    "SegregationOfDutiesViolation",
    "assign_role",
    "authorize",
    "ensure_distinct_actors",
    "has_permission",
]
