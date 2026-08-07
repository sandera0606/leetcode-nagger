"""Generate a blank tracker spreadsheet for a problem list.

    python tools/make_template.py --list blind75
    python tools/make_template.py --list neetcode150 --out my-tracker.xlsx
    python tools/make_template.py --all

Writes an .xlsx (and a plain .csv alongside it) into `templates/` by default.
Upload the .xlsx to Google Drive and it opens as a Google Sheet with the
dashboard formulas intact.

Only needed if you want to regenerate the templates — they are committed.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

try:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation
except ImportError:
    sys.exit("openpyxl is required to build templates: pip install openpyxl")

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "problems.json"
DEFAULT_OUT_DIR = ROOT / "templates"

LIST_TITLES = {
    "blind75": "Blind 75",
    "neetcode150": "NeetCode 150",
    "neetcode250": "NeetCode 250",
}

# Column order. The nagger only requires Problem, Diff, Cold ✓ (date),
# 1wk Review and 3wk Review — the rest are for you, not the bot.
HEADERS = [
    "#", "Pattern", "Problem", "Diff", "Time Budget", "Link",
    "Cold ✓ (date)", "1wk Review", "3wk Review",
    "Key Insight + Pitfall", "Confidence",
]
COL = {name: i + 1 for i, name in enumerate(HEADERS)}
HEADER_ROW = 7
FIRST_DATA_ROW = HEADER_ROW + 1

TIME_BUDGETS = {
    "Easy": "~45min first / ~5min review",
    "Medium": "~60min first / ~8min review",
    "Hard": "~75min first / ~12min review",
}

CONFIDENCE_LEVELS = ["Shaky", "OK", "Strong"]

INK = "1F2933"
MUTED = "6B7280"
ACCENT_FILL = "1F2933"
BAND_FILL = "F4F6F8"
DASH_FILL = "EEF2F7"

DIFF_FILL = {"Easy": "E3F5E9", "Medium": "FDF3DC", "Hard": "FBE4E4"}
DIFF_INK = {"Easy": "1E6F42", "Medium": "8A6100", "Hard": "9B1C1C"}

METHOD_NOTE = (
    "4-pass method per problem: (1) cold attempt, timeboxed — no hints. "
    "(2) read the editorial/video. (3) re-solve from scratch. "
    "(4) write the key insight + the pitfall that got you, in your own words."
)
REPETITION_NOTE = (
    "Spaced repetition: re-solve each problem ~1 week and ~3 weeks after the "
    "cold attempt. Log the date you actually did it in the review columns — "
    "those blanks are what the nagger yells at you about."
)


def load_problems(list_name: str) -> list[dict]:
    with DATA_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return [p for p in data["problems"] if list_name in p["lists"]]


def thin_border(color: str = "D8DEE6") -> Border:
    side = Side(style="thin", color=color)
    return Border(left=side, right=side, top=side, bottom=side)


def build_workbook(list_name: str, problems: list[dict]):
    pretty = LIST_TITLES[list_name]
    last_row = FIRST_DATA_ROW + len(problems) - 1
    cold_range = f"$G${FIRST_DATA_ROW}:$G${last_row}"
    wk1_range = f"$H${FIRST_DATA_ROW}:$H${last_row}"
    wk3_range = f"$I${FIRST_DATA_ROW}:$I${last_row}"
    conf_range = f"$K${FIRST_DATA_ROW}:$K${last_row}"

    wb = Workbook()
    ws = wb.active
    ws.title = "Tracker"

    # ---- title + dashboard ---------------------------------------------
    ws.cell(row=1, column=1, value=f"{pretty} — Tracker").font = Font(
        size=16, bold=True, color=INK)
    ws.cell(row=2, column=1, value="DASHBOARD").font = Font(
        size=9, bold=True, color=MUTED)

    stats = [
        ("Total problems", f"={len(problems)}"),
        ("Cold ✓", f"=COUNTA({cold_range})"),
        ("1wk done", f"=COUNTA({wk1_range})"),
        ("3wk done", f"=COUNTA({wk3_range})"),
        ("Shaky", f'=COUNTIF({conf_range},"Shaky")'),
        ("OK", f'=COUNTIF({conf_range},"OK")'),
        ("Strong", f'=COUNTIF({conf_range},"Strong")'),
        ("% Strong", f'=IF(COUNTA({conf_range})=0,0,'
                     f'COUNTIF({conf_range},"Strong")/{len(problems)})'),
    ]
    for i, (label, formula) in enumerate(stats, start=1):
        label_cell = ws.cell(row=3, column=i, value=label)
        label_cell.font = Font(size=9, bold=True, color=MUTED)
        label_cell.alignment = Alignment(horizontal="center")
        label_cell.fill = PatternFill("solid", fgColor=DASH_FILL)
        value_cell = ws.cell(row=4, column=i, value=formula)
        value_cell.font = Font(size=14, bold=True, color=INK)
        value_cell.alignment = Alignment(horizontal="center")
        value_cell.fill = PatternFill("solid", fgColor=DASH_FILL)
        if label == "% Strong":
            value_cell.number_format = "0%"

    for row, note in ((5, METHOD_NOTE), (6, REPETITION_NOTE)):
        cell = ws.cell(row=row, column=1, value=note)
        cell.font = Font(size=9, italic=True, color=MUTED)
        cell.alignment = Alignment(vertical="center")

    # ---- header row ------------------------------------------------------
    for name in HEADERS:
        cell = ws.cell(row=HEADER_ROW, column=COL[name], value=name)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=ACCENT_FILL)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        cell.border = thin_border("1F2933")
    ws.row_dimensions[HEADER_ROW].height = 30

    # ---- problem rows ----------------------------------------------------
    border = thin_border()
    for i, p in enumerate(problems):
        row = FIRST_DATA_ROW + i
        banded = i % 2 == 1
        values = {
            "#": i + 1,
            "Pattern": p["pattern"],
            "Problem": p["name"],
            "Diff": p["difficulty"],
            "Time Budget": TIME_BUDGETS.get(p["difficulty"], ""),
            "Link": "Open →",
            "Cold ✓ (date)": None,
            "1wk Review": None,
            "3wk Review": None,
            "Key Insight + Pitfall": None,
            "Confidence": None,
        }
        for name, value in values.items():
            cell = ws.cell(row=row, column=COL[name], value=value)
            cell.border = border
            cell.alignment = Alignment(vertical="center", wrap_text=name in (
                "Time Budget", "Key Insight + Pitfall"))
            if banded:
                cell.fill = PatternFill("solid", fgColor=BAND_FILL)

        ws.cell(row=row, column=COL["Problem"]).font = Font(bold=True, color=INK)

        diff_cell = ws.cell(row=row, column=COL["Diff"])
        diff_cell.font = Font(bold=True, color=DIFF_INK.get(p["difficulty"], INK))
        diff_cell.fill = PatternFill(
            "solid", fgColor=DIFF_FILL.get(p["difficulty"], "FFFFFF"))
        diff_cell.alignment = Alignment(horizontal="center", vertical="center")

        link_cell = ws.cell(row=row, column=COL["Link"])
        link_cell.hyperlink = f"https://neetcode.io/problems/{p['neetcode_slug']}"
        link_cell.font = Font(color="1A56DB", underline="single")
        link_cell.alignment = Alignment(horizontal="center", vertical="center")

        for name in ("Cold ✓ (date)", "1wk Review", "3wk Review"):
            ws.cell(row=row, column=COL[name]).number_format = "yyyy-mm-dd"

        if p["premium"]:
            ws.cell(row=row, column=COL["Problem"]).comment = None
            note_cell = ws.cell(row=row, column=COL["Time Budget"])
            note_cell.value = f"{note_cell.value}  (LeetCode Premium — use the NeetCode link)"

    # ---- validation, widths, freeze --------------------------------------
    dv = DataValidation(
        type="list",
        formula1='"' + ",".join(CONFIDENCE_LEVELS) + '"',
        allow_blank=True,
        showDropDown=False,
    )
    ws.add_data_validation(dv)
    dv.add(f"K{FIRST_DATA_ROW}:K{last_row}")

    widths = {
        "#": 5, "Pattern": 22, "Problem": 34, "Diff": 10, "Time Budget": 30,
        "Link": 10, "Cold ✓ (date)": 14, "1wk Review": 13, "3wk Review": 13,
        "Key Insight + Pitfall": 46, "Confidence": 12,
    }
    for name, width in widths.items():
        ws.column_dimensions[get_column_letter(COL[name])].width = width

    ws.freeze_panes = ws.cell(row=FIRST_DATA_ROW, column=1)
    ws.auto_filter.ref = f"A{HEADER_ROW}:K{last_row}"
    ws.sheet_view.showGridLines = False
    return wb


def write_csv(path: Path, problems: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(HEADERS)
        for i, p in enumerate(problems, start=1):
            writer.writerow([
                i, p["pattern"], p["name"], p["difficulty"],
                TIME_BUDGETS.get(p["difficulty"], ""),
                f"https://neetcode.io/problems/{p['neetcode_slug']}",
                "", "", "", "", "",
            ])


def build(list_name: str, out: Path) -> None:
    problems = load_problems(list_name)
    if not problems:
        sys.exit(f"No problems found for list '{list_name}'.")
    out.parent.mkdir(parents=True, exist_ok=True)
    build_workbook(list_name, problems).save(out)
    csv_path = out.with_suffix(".csv")
    write_csv(csv_path, problems)
    print(f"Wrote {out} and {csv_path} ({len(problems)} problems)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", choices=sorted(LIST_TITLES), default="blind75")
    parser.add_argument("--out", type=Path, help="output .xlsx path")
    parser.add_argument("--all", action="store_true", help="build every list")
    args = parser.parse_args()

    if args.all:
        for name in ("blind75", "neetcode150", "neetcode250"):
            build(name, DEFAULT_OUT_DIR / f"{name}-tracker.xlsx")
        return 0
    build(args.list, args.out or DEFAULT_OUT_DIR / f"{args.list}-tracker.xlsx")
    return 0


if __name__ == "__main__":
    sys.exit(main())
