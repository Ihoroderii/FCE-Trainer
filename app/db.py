"""Database connection, schema, seed, and task/shows helpers. No Flask or OpenAI."""
import contextlib
import json
import re
import sqlite3

from app.config import DB_PATH, LAST_N_SHOWS

# --- Connection ---


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextlib.contextmanager
def db_connection():
    conn = get_db()
    try:
        yield conn
    finally:
        conn.close()


def _get_excluded_ids(shows_table: str):
    with db_connection() as conn:
        cur = conn.execute(
            f"SELECT DISTINCT task_id FROM {shows_table} ORDER BY id DESC LIMIT ?",
            (LAST_N_SHOWS,),
        )
        return [r["task_id"] for r in cur.fetchall()]


def _pick_one_task_id(tasks_table: str, shows_table: str, exclude_current=None):
    excluded = list(_get_excluded_ids(shows_table))
    if exclude_current is not None and exclude_current not in excluded:
        excluded.append(exclude_current)
    with db_connection() as conn:
        if excluded:
            ph = ",".join("?" * len(excluded))
            cur = conn.execute(
                f"SELECT id FROM {tasks_table} WHERE id NOT IN ({ph}) ORDER BY RANDOM() LIMIT 1",
                excluded,
            )
        else:
            cur = conn.execute(f"SELECT id FROM {tasks_table} ORDER BY RANDOM() LIMIT 1")
        row = cur.fetchone()
        return row["id"] if row else None


def _record_show(shows_table: str, task_id: int):
    with db_connection() as conn:
        conn.execute(
            f"INSERT INTO {shows_table} (task_id, shown_at) VALUES (?, datetime('now'))",
            (task_id,),
        )
        conn.commit()


# --- Schema & migrations ---


def init_db():
    with db_connection() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS uoe_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sentence1 TEXT NOT NULL,
            keyword TEXT NOT NULL,
            sentence2 TEXT NOT NULL,
            answer TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS uoe_task_shows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL REFERENCES uoe_tasks(id),
            shown_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_shows_task_id ON uoe_task_shows(task_id);
        CREATE INDEX IF NOT EXISTS idx_shows_shown_at ON uoe_task_shows(shown_at);
        CREATE TABLE IF NOT EXISTS part1_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            gaps_json TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS part1_task_shows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL REFERENCES part1_tasks(id),
            shown_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_part1_shows_task_id ON part1_task_shows(task_id);
        CREATE TABLE IF NOT EXISTS part3_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            items_json TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS part3_task_shows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL REFERENCES part3_tasks(id),
            shown_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_part3_shows_task_id ON part3_task_shows(task_id);
        CREATE INDEX IF NOT EXISTS idx_part3_shows_shown_at ON part3_task_shows(shown_at);
        CREATE TABLE IF NOT EXISTS part2_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            answers_json TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS part2_task_shows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL REFERENCES part2_tasks(id),
            shown_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_part2_shows_task_id ON part2_task_shows(task_id);
        CREATE INDEX IF NOT EXISTS idx_part2_shows_shown_at ON part2_task_shows(shown_at);
        CREATE TABLE IF NOT EXISTS part5_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            text TEXT NOT NULL,
            questions_json TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS part5_task_shows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL REFERENCES part5_tasks(id),
            shown_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_part5_shows_task_id ON part5_task_shows(task_id);
        CREATE INDEX IF NOT EXISTS idx_part5_shows_shown_at ON part5_task_shows(shown_at);
        CREATE TABLE IF NOT EXISTS part6_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paragraphs_json TEXT NOT NULL,
            sentences_json TEXT NOT NULL,
            answers_json TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS part6_task_shows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL REFERENCES part6_tasks(id),
            shown_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_part6_shows_task_id ON part6_task_shows(task_id);
        CREATE INDEX IF NOT EXISTS idx_part6_shows_shown_at ON part6_task_shows(shown_at);
        CREATE TABLE IF NOT EXISTS part7_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sections_json TEXT NOT NULL,
            questions_json TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS part7_task_shows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL REFERENCES part7_tasks(id),
            shown_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_part7_shows_task_id ON part7_task_shows(task_id);
        CREATE INDEX IF NOT EXISTS idx_part7_shows_shown_at ON part7_task_shows(shown_at);
        CREATE TABLE IF NOT EXISTS check_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            part INTEGER NOT NULL,
            score INTEGER NOT NULL,
            total INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_check_history_part ON check_history(part);
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            google_id TEXT UNIQUE NOT NULL,
            email TEXT,
            name TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id);
    """)
        conn.commit()


def _ensure_uoe_grammar_topic_column():
    with db_connection() as conn:
        cur = conn.execute("PRAGMA table_info(uoe_tasks)")
        cols = [r["name"] for r in cur.fetchall()]
        if "grammar_topic" in cols:
            return
        conn.execute("ALTER TABLE uoe_tasks ADD COLUMN grammar_topic TEXT")
        conn.commit()


def _ensure_check_history_user_id():
    with db_connection() as conn:
        cur = conn.execute("PRAGMA table_info(check_history)")
        cols = [r["name"] for r in cur.fetchall()]
        if "user_id" in cols:
            return
        conn.execute("ALTER TABLE check_history ADD COLUMN user_id INTEGER REFERENCES users(id)")
        conn.commit()


def seed_db():
    from data import (
        UOE_SEED_TASKS,
        PART_1_DATA,
        PART_2_DATA,
        PART_3_DATA,
        PART_5_DATA,
        PART_6_DATA,
        PART_7_DATA,
    )
    conn = get_db()
    cur = conn.execute("SELECT COUNT(*) as n FROM uoe_tasks")
    if cur.fetchone()["n"] == 0:
        for t in UOE_SEED_TASKS:
            conn.execute(
                "INSERT INTO uoe_tasks (sentence1, keyword, sentence2, answer, source) VALUES (?, ?, ?, ?, ?)",
                (t["sentence1"], t["keyword"], t["sentence2"], t["answer"], "manual"),
            )
    cur = conn.execute("SELECT COUNT(*) as n FROM part1_tasks")
    if cur.fetchone()["n"] == 0 and PART_1_DATA:
        for t in PART_1_DATA:
            conn.execute(
                "INSERT INTO part1_tasks (text, gaps_json, source) VALUES (?, ?, ?)",
                (t["text"], json.dumps(t["gaps"]), "manual"),
            )
    cur = conn.execute("SELECT COUNT(*) as n FROM part3_tasks")
    if cur.fetchone()["n"] == 0 and PART_3_DATA:
        for set_items in PART_3_DATA:
            conn.execute(
                "INSERT INTO part3_tasks (items_json, source) VALUES (?, ?)",
                (json.dumps(set_items), "manual"),
            )
    cur = conn.execute("SELECT COUNT(*) as n FROM part2_tasks")
    if cur.fetchone()["n"] == 0 and PART_2_DATA:
        for t in PART_2_DATA:
            conn.execute(
                "INSERT INTO part2_tasks (text, answers_json, source) VALUES (?, ?, ?)",
                (t["text"], json.dumps(t["answers"]), "manual"),
            )
    cur = conn.execute("SELECT COUNT(*) as n FROM part5_tasks")
    if cur.fetchone()["n"] == 0 and PART_5_DATA:
        for t in PART_5_DATA:
            conn.execute(
                "INSERT INTO part5_tasks (title, text, questions_json, source) VALUES (?, ?, ?, ?)",
                (t["title"], t["text"], json.dumps(t["questions"]), "manual"),
            )
    cur = conn.execute("SELECT COUNT(*) as n FROM part6_tasks")
    if cur.fetchone()["n"] == 0 and PART_6_DATA:
        for t in PART_6_DATA:
            sentences_raw = t.get("sentences", [])
            sentences_clean = [re.sub(r"^[A-G]\)\s*", "", s).strip() for s in sentences_raw]
            conn.execute(
                "INSERT INTO part6_tasks (paragraphs_json, sentences_json, answers_json, source) VALUES (?, ?, ?, ?)",
                (json.dumps(t["paragraphs"]), json.dumps(sentences_clean), json.dumps(t["answers"]), "manual"),
            )
    cur = conn.execute("SELECT COUNT(*) as n FROM part7_tasks")
    if cur.fetchone()["n"] == 0 and PART_7_DATA:
        for t in PART_7_DATA:
            sections = t.get("sections", [])
            questions = [{"text": q.get("text"), "correct": q.get("correct")} for q in t.get("questions", [])]
            conn.execute(
                "INSERT INTO part7_tasks (sections_json, questions_json, source) VALUES (?, ?, ?)",
                (json.dumps(sections), json.dumps(questions), "manual"),
            )
    conn.commit()
    conn.close()


# --- Part schema (generic task loaders) ---


def _parse_part3_row(row):
    data = json.loads(row["items_json"])
    if isinstance(data, dict) and "text" in data:
        return {
            "id": row["id"],
            "text": data["text"],
            "stems": data.get("stems", []),
            "answers": data.get("answers", []),
            "source": row["source"],
        }
    return {"id": row["id"], "items": data, "source": row["source"]}


_PART_DB_SCHEMA = {
    1: {
        "table": "part1_tasks",
        "shows": "part1_task_shows",
        "select": "SELECT id, text, gaps_json, source FROM part1_tasks WHERE id = ?",
        "parse": lambda row: {"id": row["id"], "text": row["text"], "gaps": json.loads(row["gaps_json"])},
    },
    3: {
        "table": "part3_tasks",
        "shows": "part3_task_shows",
        "select": "SELECT id, items_json, source FROM part3_tasks WHERE id = ?",
        "parse": lambda row: _parse_part3_row(row),
    },
    2: {
        "table": "part2_tasks",
        "shows": "part2_task_shows",
        "select": "SELECT id, text, answers_json FROM part2_tasks WHERE id = ?",
        "parse": lambda row: {"id": row["id"], "text": row["text"], "answers": json.loads(row["answers_json"])},
    },
    5: {
        "table": "part5_tasks",
        "shows": "part5_task_shows",
        "select": "SELECT id, title, text, questions_json FROM part5_tasks WHERE id = ?",
        "parse": lambda row: {
            "id": row["id"],
            "title": row["title"],
            "text": row["text"],
            "questions": json.loads(row["questions_json"]),
        },
    },
    6: {
        "table": "part6_tasks",
        "shows": "part6_task_shows",
        "select": "SELECT id, paragraphs_json, sentences_json, answers_json FROM part6_tasks WHERE id = ?",
        "parse": lambda row: {
            "id": row["id"],
            "paragraphs": json.loads(row["paragraphs_json"]),
            "sentences": json.loads(row["sentences_json"]),
            "answers": json.loads(row["answers_json"]),
        },
    },
    7: {
        "table": "part7_tasks",
        "shows": "part7_task_shows",
        "select": "SELECT id, sections_json, questions_json FROM part7_tasks WHERE id = ?",
        "parse": lambda row: {
            "id": row["id"],
            "sections": json.loads(row["sections_json"]),
            "questions": json.loads(row["questions_json"]),
        },
    },
}


def get_task_by_id_for_part(part, task_id):
    schema = _PART_DB_SCHEMA.get(part)
    if not schema or not task_id:
        return None
    with db_connection() as conn:
        cur = conn.execute(schema["select"], (task_id,))
        row = cur.fetchone()
    if not row:
        return None
    return schema["parse"](row)


def record_show_for_part(part, task_id):
    schema = _PART_DB_SCHEMA.get(part)
    if schema:
        _record_show(schema["shows"], task_id)


def _generic_get_or_create(part, generate_fn, exclude_task_id=None, openai_available=False):
    """Generic get-or-create for any part. Picks from DB, generates if needed (when openai_available and generate_fn), records show.
    Returns (item, task_id) or (None, None)."""
    schema = _PART_DB_SCHEMA.get(part)
    if not schema:
        return (None, None)
    task_id = pick_task_id_for_part(part, exclude_current=exclude_task_id)
    if task_id is None and openai_available and generate_fn:
        item = generate_fn()
        if item:
            with db_connection() as conn:
                cur = conn.execute(f"SELECT id FROM {schema['table']} ORDER BY id DESC LIMIT 1")
                row = cur.fetchone()
            if row:
                record_show_for_part(part, row["id"])
                return (item, row["id"])
            return (item, None)
    if task_id is None:
        with db_connection() as conn:
            if exclude_task_id is not None:
                cur = conn.execute(
                    f"SELECT id FROM {schema['table']} WHERE id != ? ORDER BY RANDOM() LIMIT 1",
                    (exclude_task_id,),
                )
            else:
                cur = conn.execute(f"SELECT id FROM {schema['table']} ORDER BY RANDOM() LIMIT 1")
            row = cur.fetchone()
            task_id = row["id"] if row else None
    if task_id is None:
        return (None, None)
    record_show_for_part(part, task_id)
    return (get_task_by_id_for_part(part, task_id), task_id)


def pick_task_id_for_part(part, exclude_current=None):
    schema = _PART_DB_SCHEMA.get(part)
    if not schema:
        return None
    return _pick_one_task_id(schema["table"], schema["shows"], exclude_current)


def get_excluded_task_ids():
    return _get_excluded_ids("uoe_task_shows")


# --- Part 4 / UOE helpers ---


def pick_task_ids_from_db(count: int, recent_grammar_topics=None):
    recent_grammar_topics = recent_grammar_topics or []
    excluded = get_excluded_task_ids()
    with db_connection() as conn:
        if recent_grammar_topics and _uoe_has_grammar_topic_column(conn):
            placeholders = ",".join("?" * len(recent_grammar_topics))
            order = f"CASE WHEN grammar_topic IN ({placeholders}) THEN 1 ELSE 0 END, RANDOM()"
            if excluded:
                ph_ex = ",".join("?" * len(excluded))
                cur = conn.execute(
                    f"SELECT id FROM uoe_tasks WHERE id NOT IN ({ph_ex}) ORDER BY {order} LIMIT ?",
                    (*excluded, *recent_grammar_topics, count * 2),
                )
            else:
                cur = conn.execute(
                    f"SELECT id FROM uoe_tasks ORDER BY {order} LIMIT ?",
                    (*recent_grammar_topics, count * 2),
                )
        else:
            if excluded:
                ph = ",".join("?" * len(excluded))
                cur = conn.execute(
                    f"SELECT id FROM uoe_tasks WHERE id NOT IN ({ph}) ORDER BY RANDOM() LIMIT ?",
                    (*excluded, count * 2),
                )
            else:
                cur = conn.execute("SELECT id FROM uoe_tasks ORDER BY RANDOM() LIMIT ?", (count * 2,))
        ids = [r["id"] for r in cur.fetchall()]
    return ids[: count * 2]


def _uoe_has_grammar_topic_column(conn=None):
    if conn is None:
        with db_connection() as c:
            cur = c.execute("PRAGMA table_info(uoe_tasks)")
            return any(r["name"] == "grammar_topic" for r in cur.fetchall())
    cur = conn.execute("PRAGMA table_info(uoe_tasks)")
    return any(r["name"] == "grammar_topic" for r in cur.fetchall())


def get_recent_grammar_topics(limit=20):
    try:
        with db_connection() as conn:
            cur = conn.execute("PRAGMA table_info(uoe_tasks)")
            if not any(r["name"] == "grammar_topic" for r in cur.fetchall()):
                return []
            cur = conn.execute(
                """
                SELECT DISTINCT t.grammar_topic FROM uoe_tasks t
                INNER JOIN uoe_task_shows s ON t.id = s.task_id
                WHERE t.grammar_topic IS NOT NULL AND trim(t.grammar_topic) != ''
                ORDER BY s.shown_at DESC
                LIMIT ?
            """,
                (limit,),
            )
            return [r["grammar_topic"].strip() for r in cur.fetchall() if r.get("grammar_topic")]
    except Exception:
        return []


def record_shows(task_ids):
    with db_connection() as conn:
        for tid in task_ids:
            conn.execute("INSERT INTO uoe_task_shows (task_id, shown_at) VALUES (?, datetime('now'))", (tid,))
        conn.commit()


def get_tasks_by_ids(ids):
    if not ids:
        return []
    ph = ",".join("?" * len(ids))
    with db_connection() as conn:
        try:
            cur = conn.execute(
                f"SELECT id, sentence1, keyword, sentence2, answer, grammar_topic FROM uoe_tasks WHERE id IN ({ph})",
                ids,
            )
        except sqlite3.OperationalError:
            cur = conn.execute(
                f"SELECT id, sentence1, keyword, sentence2, answer FROM uoe_tasks WHERE id IN ({ph})",
                ids,
            )
        rows = cur.fetchall()
    by_id = {r["id"]: dict(r) for r in rows}
    out = [by_id[i] for i in ids if i in by_id]
    for r in out:
        if "grammar_topic" not in r:
            r["grammar_topic"] = None
    return out


def uoe_task_exists(sentence1: str, keyword: str) -> bool:
    with db_connection() as conn:
        cur = conn.execute(
            "SELECT 1 FROM uoe_tasks WHERE sentence1 = ? AND keyword = ? LIMIT 1",
            (sentence1.strip(), keyword.strip().upper()),
        )
        return cur.fetchone() is not None


# --- Backward-compatible aliases ---


def get_part1_task_by_id(tid):
    return get_task_by_id_for_part(1, tid)


def get_part3_task_by_id(tid):
    return get_task_by_id_for_part(3, tid)


def record_part1_show(tid):
    record_show_for_part(1, tid)


def record_part3_show(tid):
    record_show_for_part(3, tid)


def get_part2_task_by_id(tid):
    return get_task_by_id_for_part(2, tid)


def get_part5_task_by_id(tid):
    return get_task_by_id_for_part(5, tid)


def get_part6_task_by_id(tid):
    return get_task_by_id_for_part(6, tid)


def get_part7_task_by_id(tid):
    return get_task_by_id_for_part(7, tid)


def record_part2_show(tid):
    record_show_for_part(2, tid)


def record_part5_show(tid):
    record_show_for_part(5, tid)


def record_part6_show(tid):
    record_show_for_part(6, tid)


def record_part7_show(tid):
    record_show_for_part(7, tid)
