"""Problem name → neetcode.io URL, from the same data the templates use.

`data/problems.json` is the file `tools/build_problem_data.py` generates and
`tools/make_template.py` builds the tracker's Link column from, so a name that
came out of a shipped template always resolves. Names are matched loosely
because they've been round-tripped through a spreadsheet a user can edit.

Links are a nicety. Every failure here degrades to "no link" rather than
taking down a nag.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "problems.json"
NEETCODE_URL = "https://neetcode.io/problems/{slug}"


def _key(name: str) -> str:
    """Fold away the differences a spreadsheet introduces: case, punctuation,
    stray whitespace. 'Two Sum II' and 'two-sum-ii' land on the same key."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


@lru_cache(maxsize=1)
def _index() -> dict[str, str]:
    try:
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    index: dict[str, str] = {}
    for problem in data.get("problems", []) or []:
        slug = (problem.get("neetcode_slug") or "").strip()
        name = problem.get("name") or ""
        if slug and name:
            index.setdefault(_key(name), NEETCODE_URL.format(slug=slug))
    return index


def url_for(name: str) -> str:
    """The neetcode.io URL for a problem, or '' if it isn't one we know."""
    return _index().get(_key(name), "")
