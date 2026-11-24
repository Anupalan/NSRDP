"""National identifier scheme (REG-01..04). Format is configuration (TBC)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


class InvalidIdentifier(ValueError):
    pass


def _to_digits(s: str) -> str:
    return "".join(str(int(c, 36)) for c in s.upper())


def mod97_check(body: str) -> str:
    """ISO 7064 MOD 97-10 check digits over an alphanumeric body."""
    return f"{98 - (int(_to_digits(body) + '00') % 97):02d}"


def mod97_valid(body: str, check: str) -> bool:
    return int(_to_digits(body) + check) % 97 == 1


@dataclass(frozen=True)
class IdScheme:
    prefix: str
    sequence_width: int
    separator: str
    kind_codes: dict[str, str]

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> IdScheme:
        scheme = cfg["id_scheme"]
        if scheme.get("check") != "iso7064_mod97_10":
            raise ValueError(f"unsupported check scheme {scheme.get('check')!r}")
        codes = {k: v["code"] for k, v in cfg["kinds"].items()}
        if len(set(codes.values())) != len(codes):
            raise ValueError("kind codes must be unique")
        for token in [scheme["prefix"], *codes.values()]:
            if not re.fullmatch(r"[A-Z0-9]+", token):
                raise ValueError(f"id tokens must be A-Z0-9: {token!r}")
        return cls(scheme["prefix"], int(scheme["sequence_width"]), scheme["separator"], codes)

    def format(self, kind: str, seq: int) -> str:
        code = self.kind_codes[kind]
        number = f"{seq:0{self.sequence_width}d}"
        check = mod97_check(f"{self.prefix}{code}{number}")
        return self.separator.join([self.prefix, code, number, check])

    def parse(self, value: str) -> tuple[str, int]:
        parts = value.split(self.separator)
        if len(parts) != 4:
            raise InvalidIdentifier(value)
        prefix, code, number, check = parts
        if prefix != self.prefix or not number.isdigit():
            raise InvalidIdentifier(value)
        kind = next((k for k, c in self.kind_codes.items() if c == code), None)
        if kind is None or not mod97_valid(prefix + code + number, check):
            raise InvalidIdentifier(value)
        return kind, int(number)


def imo_valid(value: str) -> bool:
    """IMO ship identification number: 7 digits, last is a weighted check digit."""
    digits = value.upper().removeprefix("IMO").strip()
    if not re.fullmatch(r"\d{7}", digits):
        return False
    total = sum(int(d) * w for d, w in zip(digits[:6], range(7, 1, -1), strict=True))
    return total % 10 == int(digits[6])
