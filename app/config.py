"""Application constants and config (no Flask/app instance)."""
from pathlib import Path

# Paths
APP_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = APP_ROOT / "fce_trainer.db"

# Use of English / Reading
LAST_N_SHOWS = 100
TASKS_PER_SET = 5
PART4_TASKS_PER_SET = 6
LETTERS = ["A", "B", "C", "D"]
MAX_EXPLANATION_LEN = 400
MAX_WORD_FAMILY_LEN = 200
PARTS_RANGE = range(1, 8)
PART_QUESTION_COUNTS = {1: 8, 2: 8, 3: 8, 4: 6, 5: 6, 6: 6, 7: 10}

# Check result cache (server-side, avoid session cookie overflow)
CHECK_RESULT_CACHE_MAX = 20

# Writing
WRITING_MIN_WORDS = 140
WRITING_MAX_WORDS = 190
WRITING_TOTAL_MINUTES = 80
