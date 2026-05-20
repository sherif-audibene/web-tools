#!/usr/bin/env python3
"""
Book Library Restorer (reverse of book_sorter.py)
-------------------------------------------------
Moves files back from the per-category destination folders to the original
locations recorded in the catalog CSV.

Two ways to drive the restore:

  1. PREFERRED — from the move log produced by book_sorter.py
     (move_log.csv has exact source/destination pairs; no guessing).

         python book_restorer.py --from-log /storage/sorted_books/move_log.csv

  2. FALLBACK — from the catalog CSV + the destination folder.
     The script reconstructs the same collision-renaming the forward
     script did, so it can locate the actual current file.

         python book_restorer.py my_library.csv /storage/sorted_books

In either mode, the default is DRY RUN. Add --execute to actually move.

Examples:
  Preview a restore from the log:
      python book_restorer.py --from-log /storage/sorted_books/move_log.csv

  Actually restore using the log:
      python book_restorer.py --from-log /storage/sorted_books/move_log.csv --execute

  Restore using the catalog CSV (no log available):
      python book_restorer.py my_library.csv /storage/sorted_books --execute

  Copy back instead of moving (keep destination copies intact):
      python book_restorer.py --from-log move_log.csv --execute --copy
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
# Helpers (kept consistent with book_sorter.py so reconstruction matches)
# ---------------------------------------------------------------------------

_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_folder_name(name: str) -> str:
    if not name:
        return "Uncategorized"
    safe = _BAD_CHARS.sub(" - ", name)
    safe = re.sub(r"\s+", " ", safe).strip().strip(".")
    return safe or "Uncategorized"


def predict_destination(dest_dir: Path, filename: str, taken: set) -> Path:
    """
    Re-implement the unique_destination logic from book_sorter.py purely
    based on names already promised in this run. Used in fallback mode
    to predict where each file landed.
    """
    candidate = dest_dir / filename
    if candidate not in taken:
        taken.add(candidate)
        return candidate

    stem = Path(filename).stem
    suffix = Path(filename).suffix
    i = 1
    while True:
        candidate = dest_dir / f"{stem}_{i}{suffix}"
        if candidate not in taken:
            taken.add(candidate)
            return candidate
        i += 1


# ---------------------------------------------------------------------------
# Plan builders
# ---------------------------------------------------------------------------

def plan_from_log(log_path: Path):
    """
    Yield (current_location, original_location) pairs from move_log.csv.
    Only rows with status OK or PLANNED are considered movable.
    """
    with log_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"source", "destination", "status"}
        if not required.issubset(reader.fieldnames or []):
            raise SystemExit(
                f"Log is missing required columns. Found: {reader.fieldnames}. "
                f"Needs: {sorted(required)}"
            )
        for row in reader:
            status = (row.get("status") or "").upper()
            if status != "OK":
                # We only want files that were really moved.
                continue
            current = row["destination"]
            original = row["source"]
            if current and original:
                yield current, original


def plan_from_catalog(csv_path: Path, dest_root: Path):
    """
    Yield (current_location, original_location) pairs by re-running the
    same name-allocation order the forward script used.
    """
    promised: dict[Path, set] = defaultdict(set)
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"filename", "file_path", "category"}
        if not required.issubset(reader.fieldnames or []):
            raise SystemExit(
                f"CSV missing required columns. Found: {reader.fieldnames}. "
                f"Needs: {sorted(required)}"
            )
        for row in reader:
            original = row.get("file_path") or ""
            filename = row.get("filename") or ""
            category = (row.get("category") or "Uncategorized").strip() or "Uncategorized"
            if not original or not filename:
                continue
            cat_dir = dest_root / sanitize_folder_name(category)
            predicted = predict_destination(cat_dir, filename, promised[cat_dir])
            yield str(predicted), original


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Restore files to their original locations using the catalog CSV or the move log.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "csv_file", nargs="?",
        help="Catalog CSV (only needed when not using --from-log).",
    )
    parser.add_argument(
        "destination", nargs="?",
        help="Destination parent folder used by book_sorter.py "
             "(only needed when not using --from-log).",
    )
    parser.add_argument(
        "--from-log", metavar="MOVE_LOG_CSV",
        help="Use the move_log.csv produced by book_sorter.py. PREFERRED.",
    )
    parser.add_argument(
        "--execute", action="store_true",
        help="Actually perform the restore. Without this, runs as dry run.",
    )
    parser.add_argument(
        "--copy", action="store_true",
        help="Copy files back instead of moving them.",
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Overwrite a file at the original location if one already exists. "
             "Default is to skip and log it.",
    )
    parser.add_argument(
        "--log", default=None,
        help="Path for the restore log CSV (default: restore_log.csv next to input).",
    )
    args = parser.parse_args()

    # ----- Decide mode -----
    if args.from_log:
        log_path = Path(args.from_log).expanduser().resolve()
        if not log_path.is_file():
            sys.exit(f"Error: log file not found: {log_path}")
        plan_iter = plan_from_log(log_path)
        mode = f"FROM LOG: {log_path}"
        default_log_dir = log_path.parent
    else:
        if not args.csv_file or not args.destination:
            sys.exit(
                "Error: either pass --from-log MOVE_LOG_CSV, or provide both "
                "the catalog CSV and the destination folder.\n"
                "Run with --help for examples."
            )
        csv_path = Path(args.csv_file).expanduser().resolve()
        dest_root = Path(args.destination).expanduser().resolve()
        if not csv_path.is_file():
            sys.exit(f"Error: CSV not found: {csv_path}")
        if not dest_root.is_dir():
            sys.exit(f"Error: destination folder not found: {dest_root}")
        plan_iter = plan_from_catalog(csv_path, dest_root)
        mode = f"FROM CATALOG: {csv_path}  +  {dest_root}"
        default_log_dir = csv_path.parent

    dry_run = not args.execute
    action_word = "COPY" if args.copy else "MOVE"

    print("=" * 70)
    print(f"  Mode:         {mode}")
    print(f"  Action:       RESTORE ({action_word}){'  (DRY RUN — no changes)' if dry_run else ''}")
    print(f"  On collision: {'OVERWRITE existing original' if args.overwrite else 'SKIP'}")
    print("=" * 70)

    stats = Counter()
    log_rows = []  # (current, original, status, note)

    for current_str, original_str in plan_iter:
        current = Path(current_str)
        original = Path(original_str)

        # 1. Does the current file actually exist?
        if not current.exists():
            stats["missing"] += 1
            log_rows.append((str(current), str(original), "MISSING", "current file not found"))
            continue

        # 2. Are they already the same path?
        try:
            if current.resolve() == original.resolve():
                stats["already_in_place"] += 1
                log_rows.append((str(current), str(original), "SKIP", "already at original location"))
                continue
        except OSError:
            pass

        # 3. Something already at the original location?
        if original.exists():
            if not args.overwrite:
                stats["original_blocked"] += 1
                log_rows.append((str(current), str(original), "SKIP",
                                 "a file already exists at the original location (use --overwrite to replace)"))
                continue
            # else fall through and overwrite

        if dry_run:
            stats["planned"] += 1
            log_rows.append((str(current), str(original), "PLANNED", ""))
            continue

        # 4. Execute
        try:
            original.parent.mkdir(parents=True, exist_ok=True)
            if args.copy:
                shutil.copy2(current, original)
            else:
                # shutil.move handles cross-filesystem moves automatically.
                # If overwriting, remove the target first so move doesn't fail.
                if args.overwrite and original.exists():
                    original.unlink()
                shutil.move(str(current), str(original))
            stats["done"] += 1
            log_rows.append((str(current), str(original), "OK", ""))
        except Exception as e:
            stats["errors"] += 1
            log_rows.append((str(current), str(original), "ERROR", str(e)))

        total = stats["done"] + stats["errors"]
        if total and total % 500 == 0:
            print(f"  ... {total} files processed")

    # ----- Write restore log -----
    log_path = Path(args.log).expanduser().resolve() if args.log else (
        default_log_dir / ("restore_log.csv" if not dry_run else "restore_plan.csv")
    )
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["current_location", "original_location", "status", "note"])
            writer.writerows(log_rows)
    except Exception as e:
        print(f"  (warning: could not write restore log: {e})", file=sys.stderr)
        log_path = None

    # ----- Summary -----
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    if dry_run:
        print(f"  Planned restores:      {stats['planned']}")
    else:
        past = "Copied" if args.copy else "Restored"
        print(f"  {past} successfully:   {stats['done']}")
        if stats["errors"]:
            print(f"  Errors:                {stats['errors']}")
    if stats["missing"]:
        print(f"  Current file missing:  {stats['missing']}")
    if stats["already_in_place"]:
        print(f"  Already in place:      {stats['already_in_place']}")
    if stats["original_blocked"]:
        print(f"  Original path blocked: {stats['original_blocked']}  (use --overwrite to replace)")
    if log_path:
        print(f"  Log written to:        {log_path}")

    if dry_run:
        print("\n  This was a dry run. Re-run with --execute to actually restore files.")
    print()


if __name__ == "__main__":
    main()