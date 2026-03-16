"""Gamification engine — XP, levels, streaks, combos, achievements."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from flask import session

from app.config import (
    ACHIEVEMENTS,
    COMBO_BONUSES,
    COMBO_THRESHOLDS,
    LEVELS,
    PARTS_RANGE,
    XP_PER_CORRECT,
    XP_PERFECT_BONUS,
    XP_STREAK_MULTIPLIER,
)
from app.db import db_connection


# ── Helpers ──────────────────────────────────────────────────────────────────

def _today() -> str:
    return date.today().isoformat()


def _level_for_xp(xp: int) -> tuple[int, str, int, int]:
    """Return (level_index, level_name, xp_floor, xp_next_floor)."""
    for i in range(len(LEVELS) - 1, -1, -1):
        if xp >= LEVELS[i][0]:
            floor = LEVELS[i][0]
            ceiling = LEVELS[i + 1][0] if i + 1 < len(LEVELS) else floor
            return i, LEVELS[i][1], floor, ceiling
    return 0, LEVELS[0][1], 0, LEVELS[1][0] if len(LEVELS) > 1 else 0


# ── Core game state ─────────────────────────────────────────────────────────

def get_game_stats(user_id: int | None = None) -> dict:
    """Full game profile for the current user."""
    if user_id is None:
        user_id = session.get("user_id")
    if user_id is None:
        return _empty_game_stats()

    with db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM user_game_stats WHERE user_id = ?", (user_id,)
        ).fetchone()

    if not row:
        return _empty_game_stats()

    xp = row["xp"]
    level_idx, level_name, xp_floor, xp_next = _level_for_xp(xp)
    xp_in_level = xp - xp_floor
    xp_needed = max(xp_next - xp_floor, 1)

    return {
        "xp": xp,
        "level": level_idx,
        "level_name": level_name,
        "xp_in_level": xp_in_level,
        "xp_needed": xp_needed,
        "xp_progress_pct": min(round(100 * xp_in_level / xp_needed, 1), 100),
        "streak_days": row["streak_days"],
        "best_streak": row["best_streak"],
        "total_perfect": row["total_perfect"],
        "best_combo": row["best_combo"],
        "last_practice_date": row["last_practice_date"],
        "achievements": _get_achievements(user_id),
    }


def _empty_game_stats() -> dict:
    return {
        "xp": 0,
        "level": 0,
        "level_name": LEVELS[0][1],
        "xp_in_level": 0,
        "xp_needed": LEVELS[1][0] if len(LEVELS) > 1 else 1,
        "xp_progress_pct": 0,
        "streak_days": 0,
        "best_streak": 0,
        "total_perfect": 0,
        "best_combo": 0,
        "last_practice_date": None,
        "achievements": [],
    }


def _get_achievements(user_id: int) -> list[dict]:
    with db_connection() as conn:
        rows = conn.execute(
            "SELECT achievement_key, unlocked_at FROM user_achievements WHERE user_id = ? ORDER BY unlocked_at DESC",
            (user_id,),
        ).fetchall()
    out = []
    for r in rows:
        key = r["achievement_key"]
        meta = ACHIEVEMENTS.get(key, {})
        raw = r["unlocked_at"]
        try:
            dt = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
            display = dt.strftime("%d %b %Y")
        except (ValueError, TypeError):
            display = raw[:10] if raw else ""
        out.append({
            "key": key,
            "name": meta.get("name", key),
            "desc": meta.get("desc", ""),
            "icon": meta.get("icon", "🏅"),
            "unlocked_at": raw,
            "unlocked_display": display,
        })
    return out


# ── Award XP after a check ──────────────────────────────────────────────────

def award_xp(user_id: int, score: int, total: int, part: int) -> dict:
    """Calculate and persist XP gain, update streak, check achievements.

    Returns a reward summary dict for the frontend toast/animation.
    """
    if user_id is None or total <= 0:
        return {"xp_gained": 0, "new_achievements": [], "level_up": False}

    today = _today()

    with db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM user_game_stats WHERE user_id = ?", (user_id,)
        ).fetchone()

        if row:
            old_xp = row["xp"]
            streak = row["streak_days"]
            best_streak = row["best_streak"]
            total_perfect = row["total_perfect"]
            best_combo = row["best_combo"]
            last_date = row["last_practice_date"]
        else:
            old_xp = 0
            streak = 0
            best_streak = 0
            total_perfect = 0
            best_combo = 0
            last_date = None
            conn.execute(
                "INSERT INTO user_game_stats (user_id) VALUES (?)", (user_id,)
            )

        # ── Streak logic ──
        if last_date == today:
            pass  # already practiced today
        elif last_date:
            try:
                last_dt = datetime.strptime(last_date, "%Y-%m-%d").date()
                delta = (date.today() - last_dt).days
                if delta == 1:
                    streak += 1
                elif delta > 1:
                    streak = 1  # reset
            except ValueError:
                streak = 1
        else:
            streak = 1  # first ever practice

        if streak > best_streak:
            best_streak = streak

        # ── XP calculation ──
        base_xp = score * XP_PER_CORRECT

        # Perfect score bonus
        is_perfect = score == total
        if is_perfect:
            base_xp += XP_PERFECT_BONUS
            total_perfect += 1

        # Streak multiplier
        streak_bonus = int(base_xp * streak * XP_STREAK_MULTIPLIER)
        xp_gained = base_xp + streak_bonus

        # Combo bonus (consecutive correct = score here since it's per-set)
        combo = score  # consecutive correct in this set
        combo_xp = 0
        for threshold, bonus in zip(COMBO_THRESHOLDS, COMBO_BONUSES):
            if combo >= threshold:
                combo_xp = bonus
        xp_gained += combo_xp

        if combo > best_combo:
            best_combo = combo

        new_xp = old_xp + xp_gained

        # ── Persist ──
        conn.execute(
            """UPDATE user_game_stats
               SET xp = ?, streak_days = ?, best_streak = ?,
                   total_perfect = ?, best_combo = ?,
                   last_practice_date = ?, updated_at = datetime('now')
               WHERE user_id = ?""",
            (new_xp, streak, best_streak, total_perfect, best_combo, today, user_id),
        )
        conn.commit()

    # ── Level-up check ──
    old_level = _level_for_xp(old_xp)[0]
    new_level_idx, new_level_name, _, _ = _level_for_xp(new_xp)
    level_up = new_level_idx > old_level

    # ── Achievements ──
    new_achievements = _check_achievements(user_id, new_xp, streak, total_perfect, best_combo, is_perfect)

    return {
        "xp_gained": xp_gained,
        "xp_total": new_xp,
        "streak": streak,
        "combo": combo,
        "combo_xp": combo_xp,
        "streak_bonus": streak_bonus,
        "is_perfect": is_perfect,
        "level_up": level_up,
        "new_level": new_level_name if level_up else None,
        "new_achievements": new_achievements,
    }


def _check_achievements(user_id: int, xp: int, streak: int, total_perfect: int, best_combo: int, is_perfect: bool) -> list[dict]:
    """Check and unlock any new achievements. Returns list of newly unlocked."""
    candidates = []

    # First check
    candidates.append("first_check")

    # Streak milestones
    if streak >= 3:
        candidates.append("streak_3")
    if streak >= 7:
        candidates.append("streak_7")
    if streak >= 30:
        candidates.append("streak_30")

    # Perfect score
    if is_perfect:
        candidates.append("perfect_score")

    # XP milestones
    if xp >= 500:
        candidates.append("xp_500")
    if xp >= 2000:
        candidates.append("xp_2000")
    if xp >= 5000:
        candidates.append("xp_5000")

    # Combo
    if best_combo >= 10:
        candidates.append("combo_10")

    # All parts practiced
    with db_connection() as conn:
        cur = conn.execute(
            "SELECT COUNT(DISTINCT part) AS n FROM check_history WHERE user_id = ? AND part BETWEEN 1 AND 7",
            (user_id,),
        )
        row = cur.fetchone()
        if row and row["n"] >= 7:
            candidates.append("all_parts")

        # Total attempts
        cur = conn.execute(
            "SELECT COUNT(*) AS n FROM check_history WHERE user_id = ?", (user_id,)
        )
        row = cur.fetchone()
        attempt_count = row["n"] if row else 0
        if attempt_count >= 50:
            candidates.append("attempts_50")
        if attempt_count >= 200:
            candidates.append("attempts_200")

    # Try to unlock — only insert if not already unlocked
    newly_unlocked = []
    with db_connection() as conn:
        for key in candidates:
            if key not in ACHIEVEMENTS:
                continue
            cur = conn.execute(
                "SELECT 1 FROM user_achievements WHERE user_id = ? AND achievement_key = ?",
                (user_id, key),
            )
            if cur.fetchone():
                continue
            conn.execute(
                "INSERT INTO user_achievements (user_id, achievement_key) VALUES (?, ?)",
                (user_id, key),
            )
            meta = ACHIEVEMENTS[key]
            newly_unlocked.append({
                "key": key,
                "name": meta["name"],
                "desc": meta["desc"],
                "icon": meta["icon"],
            })
        conn.commit()

    return newly_unlocked
