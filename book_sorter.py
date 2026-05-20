#!/usr/bin/env python3
"""
Book Library Sorter
-------------------
Given:
  - a CSV catalog produced by book_scanner.py (columns:
    filename, file_type, file_path, category)
  - a destination parent folder

This script creates one subfolder per category inside the destination and
moves (or copies) each file there.

Safety features:
  * Defaults to DRY RUN — nothing is moved unless you pass --execute.
  * Filename collisions are resolved by appending _1, _2, ... to the stem.
  * Missing source files are logged, not fatal.
  * A CSV log of every action is written next to the CSV (move_log.csv).
  * Category names are sanitized into safe folder names.

Examples:
  Preview the plan (no changes):
      python book_sorter.py my_library.csv /storage/sorted_books

  Actually move:
      python book_sorter.py my_library.csv /storage/sorted_books --execute

  Copy instead of move:
      python book_sorter.py my_library.csv /storage/sorted_books --execute --copy

  Skip certain categories (e.g. don't move junk):
      python book_sorter.py my_library.csv /storage/sorted_books \\
          --execute --skip "Junk/Non-book" --skip "Uncategorized"
"""

import argparse
import csv
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Characters that are problematic in folder names on at least one major OS.
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_folder_name(name: str) -> str:
    """Turn a category label into a safe folder name."""
    if not name:
        return "Uncategorized"
    safe = _BAD_CHARS.sub(" - ", name)
    # Collapse repeated whitespace and trim dots/spaces from the ends
    # (Windows hates trailing dots/spaces in folder names).
    safe = re.sub(r"\s+", " ", safe).strip().strip(".")
    return safe or "Uncategorized"


def unique_destination(dest_dir: Path, filename: str, taken: set) -> Path:
    """
    Return a Path inside dest_dir that doesn't yet exist on disk *or* in `taken`.
    Appends _1, _2, ... before the extension on collision.

    `taken` is a set of resolved Paths we've already promised in this run,
    so two source files with the same name moving into the same destination
    don't both get assigned the same target path.
    """
    candidate = dest_dir / filename
    if not candidate.exists() and candidate not in taken:
        taken.add(candidate)
        return candidate

    stem = Path(filename).stem
    suffix = Path(filename).suffix
    i = 1
    while True:
        candidate = dest_dir / f"{stem}_{i}{suffix}"
        if not candidate.exists() and candidate not in taken:
            taken.add(candidate)
            return candidate
        i += 1


def read_csv(csv_path: Path):
    """Yield rows from the catalog CSV, skipping blanks."""
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"filename", "file_type", "file_path", "category"}
        if not required.issubset(reader.fieldnames or []):
            missing = required - set(reader.fieldnames or [])
            raise SystemExit(
                f"CSV is missing required columns: {sorted(missing)}.\n"
                f"Expected columns: {sorted(required)}"
            )
        for row in reader:
            if row.get("file_path"):
                yield row


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Move (or copy) files into per-category subfolders based on a catalog CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("csv_file", help="Catalog CSV from book_scanner.py")
    parser.add_argument("destination", help="Parent folder where category subfolders will live")
    parser.add_argument(
        "--execute", action="store_true",
        help="Actually perform the operation. Without this, runs as dry run.",
    )
    parser.add_argument(
        "--copy", action="store_true",
        help="Copy files instead of moving them (default: move).",
    )
    parser.add_argument(
        "--skip", action="append", default=[], metavar="CATEGORY",
        help="Category to exclude from the move (can be passed multiple times).",
    )
    parser.add_argument(
        "--only", action="append", default=[], metavar="CATEGORY",
        help="If given, ONLY these categories are moved (can be passed multiple times).",
    )
    parser.add_argument(
        "--log", default=None,
        help="Path for the action log CSV (default: <destination>/move_log.csv).",
    )
    args = parser.parse_args()

    csv_path = Path(args.csv_file).expanduser().resolve()
    if not csv_path.is_file():
        sys.exit(f"Error: CSV not found: {csv_path}")

    dest_root = Path(args.destination).expanduser().resolve()

    skip_set = {s.strip() for s in args.skip}
    only_set = {s.strip() for s in args.only}

    dry_run = not args.execute
    action_word = "COPY" if args.copy else "MOVE"

    print("=" * 70)
    print(f"  Catalog:      {csv_path}")
    print(f"  Destination:  {dest_root}")
    print(f"  Action:       {action_word}{'  (DRY RUN — no changes will be made)' if dry_run else ''}")
    if skip_set:
        print(f"  Skipping:     {', '.join(sorted(skip_set))}")
    if only_set:
        print(f"  Only:         {', '.join(sorted(only_set))}")
    print("=" * 70)

    # Create destination root if executing.
    if not dry_run:
        dest_root.mkdir(parents=True, exist_ok=True)

    # Track which target Paths we've promised, per destination folder.
    promised_by_dir: dict[Path, set] = defaultdict(set)

    # Counters and logs.
    stats = Counter()
    per_category = Counter()
    log_rows = []  # each: (source, destination_or_blank, status, note)

    for row in read_csv(csv_path):
        src = Path(row["file_path"])
        category = (row.get("category") or "Uncategorized").strip() or "Uncategorized"

        # Filter logic
        if only_set and category not in only_set:
            stats["skipped_filter"] += 1
            continue
        if category in skip_set:
            stats["skipped_filter"] += 1
            continue

        folder_name = sanitize_folder_name(category)
        cat_dir = dest_root / folder_name

        # Choose target path (handle collisions)
        target = unique_destination(cat_dir, src.name, promised_by_dir[cat_dir])

        # Validate source
        if not src.exists():
            stats["missing"] += 1
            log_rows.append((str(src), "", "MISSING", "source file not found"))
            continue

        # Skip if source IS already the target (running twice into same place)
        try:
            if src.resolve() == target.resolve():
                stats["already_in_place"] += 1
                log_rows.append((str(src), str(target), "SKIP", "already in destination"))
                continue
        except OSError:
            pass

        if dry_run:
            stats["planned"] += 1
            per_category[category] += 1
            log_rows.append((str(src), str(target), "PLANNED", ""))
            continue

        # Real execution
        try:
            cat_dir.mkdir(parents=True, exist_ok=True)
            if args.copy:
                shutil.copy2(src, target)
            else:
                shutil.move(str(src), str(target))
            stats["done"] += 1
            per_category[category] += 1
            log_rows.append((str(src), str(target), "OK", ""))
        except Exception as e:
            stats["errors"] += 1
            log_rows.append((str(src), str(target), "ERROR", str(e)))

        # Progress ping every 500 files
        total_handled = stats["done"] + stats["errors"]
        if total_handled and total_handled % 500 == 0:
            print(f"  ... {total_handled} files processed")

    # ----- Write log -----
    log_path = Path(args.log).expanduser().resolve() if args.log else (
        dest_root / "move_log.csv" if not dry_run else csv_path.parent / "move_plan.csv"
    )
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["source", "destination", "status", "note"])
            writer.writerows(log_rows)
    except Exception as e:
        print(f"  (warning: could not write log to {log_path}: {e})", file=sys.stderr)
        log_path = None

    # ----- Summary -----
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    if dry_run:
        print(f"  Planned {action_word.lower()}s:    {stats['planned']}")
    else:
        past = "Copied" if args.copy else "Moved"
        print(f"  {past} successfully:  {stats['done']}")
        if stats["errors"]:
            print(f"  Errors:           {stats['errors']}")
    if stats["missing"]:
        print(f"  Source missing:   {stats['missing']}")
    if stats["already_in_place"]:
        print(f"  Already in place: {stats['already_in_place']}")
    if stats["skipped_filter"]:
        print(f"  Skipped (filters): {stats['skipped_filter']}")
    if log_path:
        print(f"  Log written to:   {log_path}")

    if per_category:
        print("\n  Per-category counts:")
        for cat, n in per_category.most_common():
            print(f"    {n:6d}  {cat}")

    if dry_run:
        print("\n  This was a dry run. Re-run with --execute to actually move files.")
    print()


if __name__ == "__main__":
    main()