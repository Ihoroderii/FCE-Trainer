"""Restore the tracked portable_state snapshot into runtime locations."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from portable_state_sync import restore_portable_state_if_needed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing runtime files from the portable_state snapshot.",
    )
    args = parser.parse_args()
    result = restore_portable_state_if_needed(force=args.force)
    print(
        "portable_state restored: "
        f"db={'yes' if result['db_restored'] else 'no'}, "
        f"listening_files={result['listening_files']}, "
        f"transcript_files={result['transcript_files']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
