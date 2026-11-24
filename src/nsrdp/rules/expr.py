"""A small, safe expression language for rule logic (JSON-Logic style).

Rules are data (D2), so their logic must be data too. An expression is either a literal or
a one-key object ``{"<op>": [args...]}``. Nothing is ``eval``-ed; unknown operators are
rejected when a rule is drafted.

Example: ``{"and": [{">=": [{"var": "vessel.ldt"}, 0]}, {"in": [{"var": "state"}, ["GJ"]]}]}``
"""

from __future__ import annotations

import operator
from collections.abc import Callable
from typing import Any

_MISSING = object()


class RuleExpressionError(ValueError):
    pass


def _var(data: dict[str, Any], path: str, default: Any = None) -> Any:
    cur: Any = data
    for part in str(path).split(".") if path != "" else []:
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return default
    return cur


def _cmp(fn: Callable[[Any, Any], bool]) -> Callable[..., bool]:
    def run(a: Any, b: Any, c: Any = _MISSING) -> bool:
        if c is _MISSING:
            return fn(a, b)
        return fn(a, b) and fn(b, c)  # between: {"<=": [lo, x, hi]}

    return run


_STRICT: dict[str, Callable[..., Any]] = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "<": _cmp(operator.lt),
    "<=": _cmp(operator.le),
    ">": _cmp(operator.gt),
    ">=": _cmp(operator.ge),
    "!": lambda a: not a,
    "in": lambda a, b: a in b if b is not None else False,
    "+": lambda *a: sum(a),
    "-": lambda a, b=_MISSING: -a if b is _MISSING else a - b,
    "*": lambda *a: _product(a),
    "/": lambda a, b: a / b,
    "min": lambda *a: min(a),
    "max": lambda *a: max(a),
    "cat": lambda *a: "".join(str(x) for x in a),
}

_LAZY = {"var", "and", "or", "if", "missing"}
OPERATORS = frozenset(_STRICT) | _LAZY


def _product(values: tuple[Any, ...]) -> Any:
    out: Any = 1
    for v in values:
        out *= v
    return out


def _args(node: dict[str, Any]) -> tuple[str, list[Any]]:
    ((op, args),) = node.items()
    if not isinstance(args, list):
        args = [args]
    return op, args


def validate(expr: Any) -> None:
    if isinstance(expr, list):
        for e in expr:
            validate(e)
        return
    if not isinstance(expr, dict):
        return
    if len(expr) != 1:
        raise RuleExpressionError(f"operator object must have exactly one key: {expr}")
    op, args = _args(expr)
    if op not in OPERATORS:
        raise RuleExpressionError(f"unknown operator {op!r}")
    for a in args:
        validate(a)


def evaluate(expr: Any, data: dict[str, Any]) -> Any:
    if isinstance(expr, list):
        return [evaluate(e, data) for e in expr]
    if not isinstance(expr, dict):
        return expr
    op, args = _args(expr)
    if op == "var":
        path = evaluate(args[0], data) if args else ""
        default = evaluate(args[1], data) if len(args) > 1 else None
        return _var(data, path, default)
    if op == "and":
        result: Any = True
        for a in args:
            result = evaluate(a, data)
            if not result:
                return result
        return result
    if op == "or":
        result = False
        for a in args:
            result = evaluate(a, data)
            if result:
                return result
        return result
    if op == "if":
        i = 0
        while i + 1 < len(args):
            if evaluate(args[i], data):
                return evaluate(args[i + 1], data)
            i += 2
        return evaluate(args[i], data) if i < len(args) else None
    if op == "missing":
        return [p for p in (evaluate(a, data) for a in args) if _var(data, p, _MISSING) is _MISSING]
    fn = _STRICT.get(op)
    if fn is None:
        raise RuleExpressionError(f"unknown operator {op!r}")
    try:
        return fn(*[evaluate(a, data) for a in args])
    except TypeError as exc:
        raise RuleExpressionError(f"{op}: {exc}") from exc
