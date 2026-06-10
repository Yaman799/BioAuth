"""Encrypted event-file write adapter for logger captures."""
from __future__ import annotations

from collections.abc import Iterable, Sequence

from security import append_encrypted_rows, rotate_encrypted, write_encrypted


def seed_file(path: str, header: str) -> None:
    write_encrypted(path, [], header)


def append_rows(path: str, rows: Iterable[Sequence[object]], header: str, max_size: int) -> None:
    rotate_encrypted(path, header, max_size)
    append_encrypted_rows(path, list(rows), header)
