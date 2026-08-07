"""Regenerate `data/problems.json` from upstream NeetCode sources.

You do not need to run this to use the nagger — `data/problems.json` is
committed. Run it only if you want to refresh the lists:

    python tools/build_problem_data.py

Sources:
  - neetcode-gh/leetcode `.problemSiteData.json` — authoritative `blind75`
    and `neetcode150` membership flags, patterns, difficulty, LeetCode slugs.
  - ascherj/neetcode-250-guide `neetcode_250_complete.json` — a scrape of the
    NeetCode 250 roadmap, used for the 100 problems beyond the 150 and for
    the roadmap's category ordering.

The script cross-checks that 75 ⊂ 150 ⊂ 250 and fails loudly if not.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

PSD_URL = "https://raw.githubusercontent.com/neetcode-gh/leetcode/main/.problemSiteData.json"
NC250_URL = "https://raw.githubusercontent.com/ascherj/neetcode-250-guide/main/neetcode_250_complete.json"

OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "problems.json"

# Both upstreams title-case their names off the URL slug, which gives you
# "Kth Smallest Element In a Bst". Undo the worst of it.
LOWER_WORDS = {
    "a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "into",
    "nor", "of", "on", "or", "per", "the", "to", "vs", "with", "without",
}
UPPER_WORDS = {
    "bst", "lru", "lfu", "api", "url", "ip", "cpu", "gcd", "xor", "ascii",
    "bfs", "dfs", "lca", "sql", "ii", "iii", "iv",
}


def pretty_name(name: str) -> str:
    words = name.split()
    out = []
    for i, word in enumerate(words):
        low = word.lower()
        if low in UPPER_WORDS:
            out.append(low.upper())
        elif low in LOWER_WORDS and 0 < i < len(words) - 1:
            out.append(low)
        else:
            out.append(word)
    return " ".join(out)


def fetch_json(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": "leetcode-nagger/2.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    psd = fetch_json(PSD_URL)
    nc250 = fetch_json(NC250_URL)

    problems_250 = nc250["problems"]
    categories = nc250["categories"]

    by_name = {p["problem"]: p for p in psd}
    in_75 = {p["problem"] for p in psd if p.get("blind75")}
    in_150 = {p["problem"] for p in psd if p.get("neetcode150")}

    names_250 = {p["name"] for p in problems_250}
    missing = (in_75 | in_150) - names_250
    if missing:
        sys.exit(f"Upstream drift: {len(missing)} problem(s) in 75/150 but not 250: {sorted(missing)}")
    if not in_75 <= in_150:
        sys.exit("Upstream drift: blind75 is not a subset of neetcode150.")
    if len(problems_250) != 250:
        sys.exit(f"Expected 250 problems, got {len(problems_250)}.")

    # Roadmap order: category order from the 250 scrape, original order within.
    order = {c: i for i, c in enumerate(categories)}
    problems_250.sort(key=lambda p: order.get(p["category"], len(order)))

    out = []
    for p in problems_250:
        name = p["name"]
        official = by_name.get(name, {})
        lists = ["neetcode250"]
        if name in in_150:
            lists.insert(0, "neetcode150")
        if name in in_75:
            lists.insert(0, "blind75")
        leetcode_slug = (official.get("link") or p["slug"]).strip("/")
        out.append({
            "name": pretty_name(name),
            "pattern": official.get("pattern") or p["category"],
            "difficulty": official.get("difficulty") or p["difficulty"],
            "leetcode_slug": leetcode_slug,
            "neetcode_slug": p["neetcode_url"].split("?")[0].rsplit("/", 1)[-1],
            "premium": bool(official.get("premium", False)),
            "lists": lists,
        })

    counts = {name: sum(1 for p in out if name in p["lists"])
              for name in ("blind75", "neetcode150", "neetcode250")}
    if counts != {"blind75": 75, "neetcode150": 150, "neetcode250": 250}:
        sys.exit(f"Unexpected list sizes: {counts}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump({"categories": categories, "problems": out}, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote {OUT_PATH} — {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
