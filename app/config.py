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
# Get phrases (study mode): separate part id for check_history / stats
GET_PHRASE_PART = 8

# Listening
LISTENING_PARTS_RANGE = range(1, 5)
LISTENING_QUESTION_COUNTS = {1: 8, 2: 10, 3: 5, 4: 7}
# Part numbers used in check_history for listening (101-104)
LISTENING_HISTORY_PARTS = {1: 101, 2: 102, 3: 103, 4: 104}

# Check result cache (server-side, avoid session cookie overflow)
CHECK_RESULT_CACHE_MAX = 20

# Writing
WRITING_MIN_WORDS = 140
WRITING_MAX_WORDS = 190
WRITING_TOTAL_MINUTES = 80

# Gamification
GAMIFICATION_ENABLED = False  # Set to True to re-enable XP, levels, streaks, achievements
XP_PER_CORRECT = 10          # base XP per correct answer
XP_PERFECT_BONUS = 25        # bonus XP for a perfect score (all correct)
XP_STREAK_MULTIPLIER = 0.1   # extra % per day of streak (e.g. 5-day streak = +50%)
COMBO_THRESHOLDS = [3, 5, 10]  # consecutive correct answers for combo bonuses
COMBO_BONUSES = [5, 15, 30]    # bonus XP at each combo threshold
LEVELS = [
    (0,    "Beginner"),
    (100,  "Elementary"),
    (300,  "Pre-Intermediate"),
    (600,  "Intermediate"),
    (1000, "Upper-Intermediate"),
    (1500, "Advanced"),
    (2500, "Proficient"),
    (4000, "Expert"),
    (6000, "Master"),
    (9000, "Cambridge Legend"),
]
ACHIEVEMENTS = {
    "first_check":    {"name": "First Steps",     "desc": "Check your first set of answers",    "icon": "🎯"},
    "streak_3":       {"name": "On a Roll",        "desc": "3-day practice streak",              "icon": "🔥"},
    "streak_7":       {"name": "Week Warrior",     "desc": "7-day practice streak",              "icon": "⚡"},
    "streak_30":      {"name": "Monthly Master",   "desc": "30-day practice streak",             "icon": "🏆"},
    "perfect_score":  {"name": "Perfectionist",    "desc": "Get 100% on any task",               "icon": "💯"},
    "all_parts":      {"name": "Well-Rounded",     "desc": "Practice all 7 parts",               "icon": "🌟"},
    "xp_500":         {"name": "Scholar",           "desc": "Earn 500 XP total",                 "icon": "📚"},
    "xp_2000":        {"name": "Dedicated",         "desc": "Earn 2,000 XP total",               "icon": "🎓"},
    "xp_5000":        {"name": "Grandmaster",       "desc": "Earn 5,000 XP total",               "icon": "👑"},
    "attempts_50":    {"name": "Persistent",        "desc": "Complete 50 practice sets",          "icon": "💪"},
    "attempts_200":   {"name": "Unstoppable",       "desc": "Complete 200 practice sets",         "icon": "🚀"},
    "combo_10":       {"name": "Combo King",        "desc": "Get 10 correct answers in a row",   "icon": "🎮"},
}
