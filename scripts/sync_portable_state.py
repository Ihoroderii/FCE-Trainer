"""Copy runtime app state into the tracked portable_state snapshot."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from portable_state_sync import sync_portable_state


def main() -> int:
    result = sync_portable_state()
    print(
        "portable_state synced: "
        f"db={'yes' if result['db_copied'] else 'no'}, "
        f"listening_files={result['listening_files']}, "
        f"transcript_files={result['transcript_files']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
