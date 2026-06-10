"""Writes encrypted keyboard/mouse events into the current live session dir."""
from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .encrypted_event_writer import append_rows, seed_file

KB_HEADER = "key,event,timestamp"
MS_HEADER = "x,y,event,timestamp"


@dataclass(frozen=True)
class LiveSessionWriter:
    live_session_dir: str
    max_size: int

    @property
    def keyboard_file(self) -> str:
        return os.path.join(self.live_session_dir, "keyboard_log.csv")

    @property
    def mouse_file(self) -> str:
        return os.path.join(self.live_session_dir, "mouse_log.csv")

    def seed(self) -> None:
        os.makedirs(self.live_session_dir, exist_ok=True)
        seed_file(self.keyboard_file, KB_HEADER)
        seed_file(self.mouse_file, MS_HEADER)

    def append_keyboard(self, rows: Iterable[Sequence[object]]) -> None:
        append_rows(self.keyboard_file, rows, KB_HEADER, self.max_size)

    def append_mouse(self, rows: Iterable[Sequence[object]]) -> None:
        append_rows(self.mouse_file, rows, MS_HEADER, self.max_size)
