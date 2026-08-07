"""Tiny JSON file that stops the bot repeating itself.

Tracks the last day a nag went out (at most one per day, even if the workflow
runs more than once) and which milestones have already been celebrated. The
GitHub Action commits it back to the repo after each run.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "state.json"


class State:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_PATH
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            self.data = data if isinstance(data, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError):
            self.data = {}

    def save(self) -> None:
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, sort_keys=True)
            f.write("\n")

    # ---- nag dedup ------------------------------------------------------

    def nagged_today(self, today: date) -> bool:
        return self.data.get("last_nag_date") == today.isoformat()

    def mark_nagged(self, today: date) -> None:
        self.data["last_nag_date"] = today.isoformat()

    # ---- celebrations ---------------------------------------------------

    def _celebrated(self) -> list[str]:
        value = self.data.get("celebrated")
        return value if isinstance(value, list) else []

    def has_celebrated(self, key: str) -> bool:
        return key in self._celebrated()

    def mark_celebrated(self, key: str) -> None:
        done = self._celebrated()
        if key not in done:
            done.append(key)
        self.data["celebrated"] = sorted(done)
