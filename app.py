"""
FCE Exam Trainer — Python only. Server-rendered HTML (Jinja2), no JavaScript files.
All logic and data in Python; timer is a small inline script in the template.
"""
import difflib
import html
import json
import os
import random
import re
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, redirect, render_template, request, session, url_for
from openai import OpenAI

# Server-side cache for check_result so we don't blow the session cookie (4KB limit)
# Key: token from URL; value: check_result dict. One-time read then removed.
_CHECK_RESULT_CACHE = {}
_CHECK_RESULT_CACHE_MAX = 20

load_dotenv()

app = Flask(__name__, template_folder="templates", static_folder="static", static_url_path="")
app.secret_key = os.environ.get("SECRET_KEY", "fce-trainer-secret-change-in-production")
app.config["SESSION_COOKIE_HTTPONLY"] = True

# Google OAuth (optional: set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET in .env)
app.config["GOOGLE_OAUTH_CLIENT_ID"] = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
app.config["GOOGLE_OAUTH_CLIENT_SECRET"] = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")

PORT = int(os.environ.get("PORT", 3000))
DB_PATH = Path(__file__).parent / "fce_trainer.db"
LAST_N_SHOWS = 100
TASKS_PER_SET = 5
PART4_TASKS_PER_SET = 6  # Part 4: 6 key word transformation questions per set
LETTERS = ["A", "B", "C", "D"]

openai_api_key = os.environ.get("OPENAI_API_KEY")
openai_client = OpenAI(api_key=openai_api_key) if openai_api_key else None
openai_model = os.environ.get("OPENAI_MODEL", "gpt-5.2")

# Google OAuth blueprint (optional)
if app.config["GOOGLE_OAUTH_CLIENT_ID"] and app.config["GOOGLE_OAUTH_CLIENT_SECRET"]:
    from flask_dance.contrib.google import make_google_blueprint, google
    google_bp = make_google_blueprint(
        scope=["profile", "email"],
        redirect_to="login_callback",
    )
    app.register_blueprint(google_bp, url_prefix="/login")
else:
    google = None  # noqa: F811


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _get_excluded_ids(shows_table: str):
    """Return list of task_ids from the last LAST_N_SHOWS in shows_table."""
    conn = get_db()
    cur = conn.execute(
        f"SELECT DISTINCT task_id FROM {shows_table} ORDER BY id DESC LIMIT ?",
        (LAST_N_SHOWS,),
    )
    ids = [r["task_id"] for r in cur.fetchall()]
    conn.close()
    return ids


def _pick_one_task_id(tasks_table: str, shows_table: str, exclude_current=None):
    """Pick one task id from tasks_table, excluding recent shows and optionally exclude_current."""
    excluded = list(_get_excluded_ids(shows_table))
    if exclude_current is not None and exclude_current not in excluded:
        excluded.append(exclude_current)
    conn = get_db()
    try:
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
    finally:
        conn.close()


def _record_show(shows_table: str, task_id: int):
    """Record that a task was shown."""
    conn = get_db()
    try:
        conn.execute(
            f"INSERT INTO {shows_table} (task_id, shown_at) VALUES (?, datetime('now'))",
            (task_id,),
        )
        conn.commit()
    finally:
        conn.close()


def init_db():
    conn = get_db()
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
    conn.close()


def _ensure_uoe_grammar_topic_column():
    """Add grammar_topic column to uoe_tasks if missing (for Part 4 grammar/construction tracking)."""
    conn = get_db()
    cur = conn.execute("PRAGMA table_info(uoe_tasks)")
    cols = [r["name"] for r in cur.fetchall()]
    conn.close()
    if "grammar_topic" in cols:
        return
    conn = get_db()
    conn.execute("ALTER TABLE uoe_tasks ADD COLUMN grammar_topic TEXT")
    conn.commit()
    conn.close()


def _ensure_check_history_user_id():
    """Add user_id column to check_history if missing (for per-account stats)."""
    conn = get_db()
    cur = conn.execute("PRAGMA table_info(check_history)")
    cols = [r["name"] for r in cur.fetchall()]
    conn.close()
    if "user_id" in cols:
        return
    conn = get_db()
    conn.execute("ALTER TABLE check_history ADD COLUMN user_id INTEGER REFERENCES users(id)")
    conn.commit()
    conn.close()


def seed_db():
    from data import UOE_SEED_TASKS, PART_1_DATA, PART_2_DATA, PART_3_DATA, PART_5_DATA, PART_6_DATA, PART_7_DATA
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
            # Store sentence text without "A) " prefix so display can add letter
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


def get_excluded_task_ids():
    conn = get_db()
    cur = conn.execute(
        "SELECT DISTINCT task_id FROM uoe_task_shows ORDER BY id DESC LIMIT ?", (LAST_N_SHOWS,)
    )
    ids = [r["task_id"] for r in cur.fetchall()]
    conn.close()
    return ids


def get_part1_excluded_ids():
    return _get_excluded_ids("part1_task_shows")


def pick_one_part1_task_id():
    return _pick_one_task_id("part1_tasks", "part1_task_shows")


def get_part1_task_by_id(task_id):
    conn = get_db()
    cur = conn.execute("SELECT id, text, gaps_json, source FROM part1_tasks WHERE id = ?", (task_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row["id"],
        "text": row["text"],
        "gaps": json.loads(row["gaps_json"]),
    }


def record_part1_show(task_id):
    _record_show("part1_task_shows", task_id)


def get_part3_excluded_ids():
    return _get_excluded_ids("part3_task_shows")


def pick_one_part3_task_id(exclude_current=None):
    return _pick_one_task_id("part3_tasks", "part3_task_shows", exclude_current)


def get_part3_task_by_id(task_id):
    conn = get_db()
    cur = conn.execute("SELECT id, items_json, source FROM part3_tasks WHERE id = ?", (task_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    data = json.loads(row["items_json"])
    # New format: {"text": "...", "stems": [...], "answers": [...]}; old format: list of 8 items
    if isinstance(data, dict) and "text" in data:
        return {"id": row["id"], "text": data["text"], "stems": data.get("stems", []), "answers": data.get("answers", []), "source": row["source"]}
    return {"id": row["id"], "items": data, "source": row["source"]}


def record_part3_show(task_id):
    _record_show("part3_task_shows", task_id)


# Wide variety of topics for Part 1
PART1_TOPICS = [
    "a famous explorer or journey",
    "underwater life and the ocean",
    "a local festival or tradition",
    "inventing something by accident",
    "migration of birds or animals",
    "a childhood memory of a place",
    "street art and urban culture",
    "how coffee or tea became popular",
    "a lost and found object",
    "the history of a bridge or building",
    "volunteering in a community project",
    "learning to cook a family recipe",
    "a day in the life of a lighthouse keeper",
    "the origin of a superstition",
    "a musician's first concert",
    "repairing an old vehicle or machine",
    "a scientific experiment at school",
    "moving to a new country",
    "a surprise party or celebration",
    "wildlife in cities",
    "an unusual hobby or collection",
    "a long-distance friendship",
    "the discovery of a hidden garden",
    "a sports team's comeback",
    "how a word or phrase entered the language",
    "a journey by boat or train",
    "a chef's visit to a market",
    "the first day at a new job",
    "a mystery or detective story",
    "climate and weather in a region",
    "a museum or gallery visit",
    "learning to ride a bike or drive",
    "a famous invention and its impact",
    "life in a remote village",
    "a pet that changed someone's life",
    "the story behind a painting or sculpture",
    "a camping or hiking adventure",
    "how newspapers were first delivered",
    "a talent show or competition",
    "the history of a sport",
    "a rescue or act of bravery",
    "food from different cultures",
    "a photographer's favourite subject",
    "ancient customs that still exist",
    "noise and silence in modern life",
    "a journey to the mountains",
    "how a town got its name",
    "a surprise encounter with a celebrity",
    "the importance of sleep",
    "a craft or skill passed down generations",
    "a shipwreck or lost treasure",
    "the life of a street performer",
    "how people celebrated before the internet",
    "a doctor or nurse's memorable day",
    "the history of a park or square",
    "a misunderstanding that led to friendship",
    "extreme weather or natural event",
    "a book that changed someone's view",
    "life on a farm or in the countryside",
    "the first aeroplane flight",
    "a teacher who made a difference",
    "the story of a famous landmark",
    "nocturnal animals and night life",
    "a family business that grew",
    "how music affects mood",
    "a journey through a desert",
    "the tradition of sending postcards",
    "a scientist's breakthrough",
    "sharing a flat or house with others",
    "the history of a type of dance",
    "a film that became a classic",
    "living without technology for a week",
    "a firefighter's or paramedic's story",
    "how languages borrow words",
    "a boat race or sailing event",
    "the meaning of dreams",
    "a comedian's first performance",
    "life in a treehouse or unusual home",
    "the invention of the bicycle",
    "a reunion after many years",
    "endangered species and conservation",
    "a journalist's most memorable interview",
    "the origin of a holiday",
    "learning a new language abroad",
    "a circus or carnival",
    "the story of a famous painting",
    "noise pollution in cities",
    "a pilot's first solo flight",
    "how chocolate is made",
    "a neighbour who became a friend",
    "the history of a river or canal",
    "a magician's secret",
    "life without electricity",
    "the first heart transplant",
    "a gardener's favourite season",
    "the tradition of afternoon tea",
    "a runner's first marathon",
    "how cartoons are made",
    "a sailor's voyage",
    "the discovery of a new species",
    "a baker's early morning",
    "the history of the postal service",
    "a surprise gift or gesture",
    "life in the Arctic or Antarctic",
    "the story of a famous song",
    "queueing and waiting in different cultures",
    "a vet's most unusual patient",
    "how the calendar was invented",
    "a dancer's audition",
    "the tradition of birthday cakes",
    "a cyclist's long-distance ride",
    "how soap was first made",
    "a librarian's favourite book",
    "the history of a castle",
    "a comedian's worst gig",
    "life on board a spaceship",
    "the invention of the telephone",
    "a surprise visit from a relative",
    "coral reefs and marine life",
    "the story of a famous photograph",
    "silence in meditation and mindfulness",
    "an architect's dream project",
    "how fireworks were invented",
    "a farmer's harvest day",
    "the tradition of shaking hands",
    "a climber's near miss",
    "how ice cream spread around the world",
    "a nurse's night shift",
    "the history of a theatre",
    "a writer's block and how they overcame it",
    "life in a monastery or convent",
    "the invention of the camera",
    "a surprise proposal",
    "bees and pollination",
    "the story behind a monument",
    "laughter and humour across cultures",
    "an astronaut's training",
    "how the weekend was created",
    "a fisherman's biggest catch",
    "the tradition of toasting",
    "a surfer's perfect wave",
    "how paper was first made",
    "a bus driver's route",
    "the history of a university",
    "a musician's worst performance",
    "life in a tent or caravan",
    "the invention of the umbrella",
    "a surprise inheritance",
    "owls and other night birds",
    "the story of a famous statue",
    "gestures and body language worldwide",
    "a diver's discovery",
    "how the alphabet was formed",
    "a barber's or hairdresser's tale",
    "the tradition of wedding rings",
    "a skier's avalanche escape",
    "how tea reached Europe",
    "a taxi driver's passenger",
    "the history of a stadium",
    "a painter's favourite light",
    "life in a yurt or igloo",
    "the invention of the wheel",
    "a surprise reunion at an airport",
    "bats and echolocation",
    "the story of a famous bridge",
    "punctuality in different countries",
    "a sailor's storm at sea",
    "how the first map was drawn",
    "a florist's busiest day",
    "the tradition of blowing out candles",
    "a mountaineer's summit",
    "how spices changed history",
    "a train conductor's story",
    "the history of a library",
    "a sculptor's block of stone",
    "life in a submarine",
    "the invention of the mirror",
    "a surprise letter from the past",
    "ants and colony behaviour",
    "the story of a famous tower",
    "siesta and rest around the world",
    "a pilot's emergency landing",
    "how the first book was printed",
    "a jeweller's most valuable piece",
    "the tradition of exchanging gifts",
    "a sailor's round-the-world trip",
    "how sugar spread across the world",
    "a busker's best day",
    "the history of a hospital",
    "a potter's kiln disaster",
    "life in a cave or underground",
    "the invention of the compass",
    "a surprise guest at a wedding",
    "dolphins and communication",
    "the story of a famous fountain",
    "hospitality in different cultures",
    "a cyclist's accident and recovery",
    "how the first clock was made",
    "a tailor's perfect suit",
    "the tradition of naming ships",
    "a kayaker's river journey",
    "how tomatoes came to Europe",
    "a street cleaner's morning",
    "the history of a prison",
    "a glassblower's technique",
    "life in a tree",
    "the invention of the lock",
    "a surprise discovery in an attic",
    "wolves and pack behaviour",
    "the story of a famous square",
    "table manners across cultures",
    "a balloonist's flight",
    "how the first lens was made",
    "a blacksmith's forge",
    "the tradition of midnight on New Year",
    "a rower's race",
    "how potatoes changed diets",
    "a night watchman's rounds",
    "the history of a cemetery",
    "a weaver's pattern",
    "life on a desert island",
    "the invention of the needle",
    "a surprise message in a bottle",
    "elephants and memory",
    "the story of a famous gate",
    "greetings around the world",
]

# Part 3 (word formation): same idea — one random topic per generated text (150–200 words, 8 gaps).
PART3_TOPICS = [
    "a famous explorer or journey",
    "underwater life and the ocean",
    "a local festival or tradition",
    "migration of birds or animals",
    "street art and urban culture",
    "how coffee or tea became popular",
    "a lost and found object",
    "the history of a bridge or building",
    "volunteering in a community project",
    "learning to cook a family recipe",
    "a day in the life of a lighthouse keeper",
    "the origin of a superstition",
    "a musician's first concert",
    "repairing an old vehicle or machine",
    "a scientific experiment at school",
    "moving to a new country",
    "a surprise party or celebration",
    "wildlife in cities",
    "an unusual hobby or collection",
    "a long-distance friendship",
    "the discovery of a hidden garden",
    "a sports team's comeback",
    "how a word entered the language",
    "a journey by boat or train",
    "a chef's visit to a market",
    "the first day at a new job",
    "a mystery or detective story",
    "climate and weather in a region",
    "a museum or gallery visit",
    "learning to ride a bike or drive",
    "a famous invention and its impact",
    "life in a remote village",
    "a pet that changed someone's life",
    "the story behind a painting or sculpture",
    "a camping or hiking adventure",
    "how newspapers were first delivered",
    "a talent show or competition",
    "the history of a sport",
    "a rescue or act of bravery",
    "food from different cultures",
    "a photographer's favourite subject",
    "ancient customs that still exist",
    "noise and silence in modern life",
    "a journey to the mountains",
    "how a town got its name",
    "a surprise encounter with a celebrity",
    "the importance of sleep",
    "a craft or skill passed down generations",
    "a shipwreck or lost treasure",
    "the life of a street performer",
    "how people celebrated before the internet",
    "a doctor or nurse's memorable day",
    "the history of a park or square",
    "a misunderstanding that led to friendship",
    "extreme weather or natural event",
    "a book that changed someone's view",
    "life on a farm or in the countryside",
    "the first aeroplane flight",
    "a teacher who made a difference",
    "the story of a famous landmark",
    "nocturnal animals and night life",
    "a family business that grew",
    "how music affects mood",
    "a journey through a desert",
    "the tradition of sending postcards",
    "a scientist's breakthrough",
    "sharing a flat or house with others",
    "the history of a type of dance",
    "a film that became a classic",
    "living without technology for a week",
    "a firefighter's or paramedic's story",
    "how languages borrow words",
    "a boat race or sailing event",
    "the meaning of dreams",
    "a comedian's first performance",
    "life in a treehouse or unusual home",
    "the invention of the bicycle",
    "a reunion after many years",
    "endangered species and conservation",
    "a journalist's most memorable interview",
    "the origin of a holiday",
    "learning a new language abroad",
    "a circus or carnival",
    "the story of a famous painting",
    "noise pollution in cities",
    "a pilot's first solo flight",
    "how chocolate is made",
    "a neighbour who became a friend",
    "the history of a river or canal",
    "a magician's secret",
    "life without electricity",
    "the first heart transplant",
    "a gardener's favourite season",
    "the tradition of afternoon tea",
    "a runner's first marathon",
    "how cartoons are made",
    "a sailor's voyage",
    "the discovery of a new species",
    "a baker's early morning",
    "the history of the postal service",
    "a surprise gift or gesture",
    "life in the Arctic or Antarctic",
    "the story of a famous song",
    "queueing and waiting in different cultures",
    "a vet's most unusual patient",
    "how the calendar was invented",
    "a dancer's audition",
    "the tradition of birthday cakes",
    "a cyclist's long-distance ride",
    "how soap was first made",
    "a librarian's favourite book",
    "the history of a castle",
    "a comedian's worst gig",
    "life on board a spaceship",
    "the invention of the telephone",
    "a surprise visit from a relative",
    "coral reefs and marine life",
    "the story of a famous photograph",
    "silence in meditation and mindfulness",
    "an architect's dream project",
    "how fireworks were invented",
    "a farmer's harvest day",
    "the tradition of shaking hands",
    "a climber's near miss",
    "how ice cream spread around the world",
    "a nurse's night shift",
    "the history of a theatre",
    "a writer's block and how they overcame it",
    "life in a monastery or convent",
    "the invention of the camera",
    "a surprise proposal",
    "bees and pollination",
    "the story behind a monument",
    "laughter and humour across cultures",
    "an astronaut's training",
    "how the weekend was created",
    "a fisherman's biggest catch",
    "the tradition of toasting",
    "a surfer's perfect wave",
    "how paper was first made",
    "a bus driver's route",
    "the history of a university",
    "a musician's worst performance",
    "life in a tent or caravan",
    "the invention of the umbrella",
    "a surprise inheritance",
    "owls and other night birds",
    "the story of a famous statue",
    "gestures and body language worldwide",
    "a diver's discovery",
    "how the alphabet was formed",
    "a barber's or hairdresser's tale",
    "the tradition of wedding rings",
    "a skier's avalanche escape",
    "how tea reached Europe",
    "a taxi driver's passenger",
    "the history of a stadium",
    "a painter's favourite light",
    "life in a yurt or igloo",
    "the invention of the wheel",
    "a surprise reunion at an airport",
    "bats and echolocation",
    "the story of a famous bridge",
    "punctuality in different countries",
    "a sailor's storm at sea",
    "how the first map was drawn",
    "a florist's busiest day",
    "the tradition of blowing out candles",
    "a mountaineer's summit",
    "how spices changed history",
    "a train conductor's story",
    "the history of a library",
    "a sculptor's block of stone",
    "life in a submarine",
    "the invention of the mirror",
    "a surprise letter from the past",
    "ants and colony behaviour",
    "the story of a famous tower",
    "siesta and rest around the world",
    "a pilot's emergency landing",
    "how the first book was printed",
    "a jeweller's most valuable piece",
    "the tradition of exchanging gifts",
    "a sailor's round-the-world trip",
    "how sugar spread across the world",
    "a busker's best day",
    "the history of a hospital",
    "a potter's kiln disaster",
    "life in a cave or underground",
    "the invention of the compass",
    "a surprise guest at a wedding",
    "dolphins and communication",
    "the story of a famous fountain",
    "hospitality in different cultures",
    "a cyclist's accident and recovery",
    "how the first clock was made",
    "a tailor's perfect suit",
    "the tradition of naming ships",
    "a kayaker's river journey",
    "how tomatoes came to Europe",
    "a street cleaner's morning",
    "the history of a prison",
    "a glassblower's technique",
    "life in a tree",
    "the invention of the lock",
    "a surprise discovery in an attic",
    "wolves and pack behaviour",
    "the story of a famous square",
    "table manners across cultures",
    "a balloonist's flight",
    "how the first lens was made",
    "a blacksmith's forge",
    "the tradition of midnight on New Year",
    "a rower's race",
    "how potatoes changed diets",
    "a night watchman's rounds",
    "the history of a cemetery",
    "a weaver's pattern",
    "life on a desert island",
    "the invention of the needle",
    "a surprise message in a bottle",
    "elephants and memory",
    "the story of a famous gate",
    "greetings around the world",
]


def generate_part1_with_openai(level="b2"):
    """Generate one Part 1 (multiple-choice cloze) task via OpenAI and save to DB. Topic is chosen at random. level='b2' or 'b2plus'."""
    if not openai_client:
        return None
    level = (level or "b2").strip().lower()
    if level != "b2plus":
        level = "b2"
    topic = random.choice(PART1_TOPICS)
    if level == "b2plus":
        level_instruction = "The text must be at B2+ level: slightly more complex vocabulary and grammar (e.g. less common collocations, more formal linkers, or subtle meaning differences between options). Standard FCE Part 1 length (4-6 sentences, 8 gaps)."
    else:
        level_instruction = "The text must be at B2 level: clear vocabulary and grammar appropriate for FCE. Standard Part 1 length (4-6 sentences, 8 gaps)."
    prompt = f"""You are an FCE (B2 First) English exam expert. Generate exactly ONE "multiple-choice cloze" task.

The text MUST be clearly about this topic: "{topic}". Write a short, coherent paragraph that is obviously on this theme (not work or offices unless the topic says so). Use a specific angle or situation so the text feels fresh and varied.

{level_instruction}

The task must have:
- text: A short paragraph with exactly 8 gaps. Each gap must be written as (1)_____, (2)_____, ... (8)_____ in order. The gaps should test vocabulary/grammar in context.
- gaps: An array of exactly 8 objects. Each object has: "options" (array of exactly 4 words/phrases that could fit the gap), "correct" (integer 0, 1, 2, or 3 - the index of the correct option in "options").

Return ONLY a valid JSON object with keys "text" and "gaps". No other text. Example shape:
{{"text": "Some text with (1)_____ and (2)_____ ...", "gaps": [{{"options": ["a","b","c","d"], "correct": 0}}, ...]}}"""

    try:
        comp = openai_client.chat.completions.create(
            model=openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
        )
        content = (comp.choices[0].message.content or "").strip()
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            return None
        data = json.loads(m.group(0))
        text = (data.get("text") or "").strip()
        gaps = data.get("gaps")
        if not text or not isinstance(gaps, list) or len(gaps) != 8:
            return None
        normalized = []
        for g in gaps:
            opts = g.get("options") or []
            if len(opts) != 4:
                return None
            correct = int(g.get("correct", 0))
            if correct not in (0, 1, 2, 3):
                correct = 0
            normalized.append({"options": [str(o).strip() for o in opts], "correct": correct})
        conn = get_db()
        cur = conn.execute(
            "INSERT INTO part1_tasks (text, gaps_json, source) VALUES (?, ?, ?)",
            (text, json.dumps(normalized), "openai"),
        )
        tid = cur.lastrowid
        conn.commit()
        conn.close()
        return get_part1_task_by_id(tid)
    except Exception as e:
        print("OpenAI Part 1 error:", e)
        return None


def get_or_create_part1_task():
    """Get one Part 1 task (exclude last 100 shown). If none available, generate via OpenAI. Record show."""
    task_id = pick_one_part1_task_id()
    if task_id is None and openai_client:
        task = generate_part1_with_openai()
        if task:
            record_part1_show(task["id"])
            return task
    if task_id is None:
        conn = get_db()
        cur = conn.execute("SELECT id FROM part1_tasks ORDER BY RANDOM() LIMIT 1")
        row = cur.fetchone()
        conn.close()
        task_id = row["id"] if row else None
    if task_id is None:
        return None
    record_part1_show(task_id)
    return get_part1_task_by_id(task_id)


def generate_part3_with_openai(level="b2"):
    """Generate one Part 3 (word formation) task: one text 150-200 words, 8 gaps with stem words in CAPITALS. Topic chosen at random."""
    if not openai_client:
        return None
    level = (level or "b2").strip().lower()
    if level != "b2plus":
        level = "b2"
    topic = random.choice(PART3_TOPICS)
    if level == "b2plus":
        level_instruction = "Use B2+ vocabulary and grammar: slightly more complex word formation (e.g. less common suffixes, negative prefixes, or abstract nouns)."
    else:
        level_instruction = "Use B2-level vocabulary and grammar. Test common suffixes (-tion, -ness, -ly, -ful, -less, -able), prefixes (un-, in-, im-), and word class changes."
    prompt = f"""You are an FCE (B2 First) Use of English exam expert. Generate exactly ONE Part 3 (Word formation) task.

The text MUST be clearly about this topic: "{topic}". Write one continuous passage (150-200 words) that is obviously on this theme.

{level_instruction}

Requirements:
- One continuous text (150-200 words) with exactly 8 gaps.
- Each gap must be written as (1)_____, (2)_____, (3)_____, (4)_____, (5)_____, (6)_____, (7)_____, (8)_____ in order.
- At the end of the sentence or clause that contains each gap, put the STEM WORD in CAPITAL LETTERS (e.g. "...has been delayed. COMPLETE" or "...looked at him. SUSPECT"). So the reader sees the stem word in capitals after each gap.
- The stem word is the base form; the student must change it (prefix, suffix, plural, etc.) to fit the gap.

Return ONLY a valid JSON object with these exact keys:
- "text": the full passage (150-200 words) with (1)_____ through (8)_____ and each stem word in CAPITALS at the end of its sentence/clause. Example fragment: "The (1)_____ of the centre has been delayed. COMPLETE She looked at him (2)_____ when he told the joke. SUSPECT"
- "stems": array of exactly 8 strings — the stem words in order (e.g. ["COMPLETE", "SUSPECT", ...])
- "answers": array of exactly 8 strings — the correct formed word for each gap, lowercase unless capitalised (e.g. ["completion", "suspiciously", ...])

No other text or markdown."""

    try:
        comp = openai_client.chat.completions.create(
            model=openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        content = (comp.choices[0].message.content or "").strip()
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            return None
        data = json.loads(m.group(0))
        text = (data.get("text") or "").strip()
        stems = data.get("stems")
        answers = data.get("answers")
        if not text or not isinstance(stems, list) or len(stems) != 8 or not isinstance(answers, list) or len(answers) != 8:
            return None
        for i in range(1, 9):
            if f"({i})_____" not in text:
                return None
        payload = {"text": text, "stems": [str(s).strip().upper() for s in stems], "answers": [str(a).strip() for a in answers]}
        conn = get_db()
        cur = conn.execute(
            "INSERT INTO part3_tasks (items_json, source) VALUES (?, ?)",
            (json.dumps(payload), "openai"),
        )
        tid = cur.lastrowid
        conn.commit()
        conn.close()
        return get_part3_task_by_id(tid)
    except Exception as e:
        print("OpenAI Part 3 error:", e)
        return None


def get_or_create_part3_item(exclude_task_id=None):
    """Get one Part 3 task. If none available, generate via OpenAI. Returns (item, task_id) or (None, None)."""
    task_id = pick_one_part3_task_id(exclude_current=exclude_task_id)
    if task_id is None and openai_client:
        task = generate_part3_with_openai()
        if task:
            conn = get_db()
            cur = conn.execute("SELECT id FROM part3_tasks ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            conn.close()
            if row:
                record_part3_show(row["id"])
                return (task, row["id"])
            return (task, None)
    if task_id is None:
        conn = get_db()
        cur = conn.execute("SELECT id FROM part3_tasks ORDER BY RANDOM() LIMIT 1")
        row = cur.fetchone()
        conn.close()
        task_id = row["id"] if row else None
    if task_id is None:
        return (None, None)
    record_part3_show(task_id)
    return (get_part3_task_by_id(task_id), task_id)


def get_part2_excluded_ids():
    return _get_excluded_ids("part2_task_shows")


def pick_one_part2_task_id(exclude_current=None):
    return _pick_one_task_id("part2_tasks", "part2_task_shows", exclude_current)


def get_part2_task_by_id(task_id):
    conn = get_db()
    cur = conn.execute("SELECT id, text, answers_json FROM part2_tasks WHERE id = ?", (task_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "text": row["text"],
        "answers": json.loads(row["answers_json"]),
    }


def record_part2_show(task_id):
    _record_show("part2_task_shows", task_id)


def _generate_part2_with_openai(level="b2"):
    """Generate one Part 2 (open cloze): one text with 8 gaps, 8 single-word answers. level='b2' or 'b2plus' (B2+ slightly more complex). Topic varies each time."""
    if not openai_client:
        return None
    part2_topics = [
        "travel and holidays",
        "education and learning",
        "technology and the internet",
        "health and fitness",
        "the environment and climate",
        "arts and music",
        "sport and competition",
        "work and careers",
        "family and relationships",
        "food and cooking",
        "science and discovery",
        "history and culture",
        "shopping and consumerism",
        "nature and wildlife",
        "entertainment and media",
        "transport and cities",
        "hobbies and free time",
        "news and current events",
    ]
    topic = random.choice(part2_topics)
    level = (level or "b2").strip().lower()
    if level != "b2plus":
        level = "b2"

    if level == "b2plus":
        level_instruction = """- The text must be at B2+ level: slightly more complex grammar and vocabulary than standard B2. Use a mix of sentence structures (e.g. participle clauses, inversion, or more formal linkers). Include at least one or two gaps that could require phrasal verbs, complex prepositions, or linking words (e.g. however, although, despite, whereas). Length about 180-220 words."""
    else:
        level_instruction = """- A short text (about 150-200 words) at B2 level. Standard FCE open-cloze difficulty."""

    prompt = f"""You are an FCE (B2 First) Use of English exam expert. Generate exactly ONE Part 2 (Open cloze) task.

The text must be about this topic: {topic}. Use a different angle or situation (e.g. a personal story, a news-style piece, advice, or a description). Do NOT write about working from home or remote work unless the chosen topic is "work and careers" and you pick that angle.

Part 2 consists of:
{level_instruction}
- The text must contain exactly 8 gaps marked (1)_____, (2)_____, (3)_____, (4)_____, (5)_____, (6)_____, (7)_____, (8)_____ in order. Each gap needs ONE word (articles, prepositions, auxiliaries, pronouns, conjunctions, phrasal verb particles, linkers, etc.).
- The 8 correct answers (one word per gap).

Return ONLY a valid JSON object with these exact keys:
- "text": the full text with the exact placeholders (1)_____, (2)_____, ... (8)_____ where the gaps are. No other placeholder format.
- "answers": an array of exactly 8 strings: the correct word for gap 1, then gap 2, ... gap 8. Use lowercase unless the word must be capitalised (e.g. start of sentence).

No other text or markdown."""

    try:
        comp = openai_client.chat.completions.create(
            model=openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        content = (comp.choices[0].message.content or "").strip()
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            return None
        data = json.loads(m.group(0))
        text = (data.get("text") or "").strip()
        answers = data.get("answers")
        if not text or not isinstance(answers, list) or len(answers) != 8:
            return None
        for i in range(1, 9):
            if f"({i})_____" not in text:
                return None
        answers_clean = [str(a).strip() for a in answers]
        conn = get_db()
        cur = conn.execute(
            "INSERT INTO part2_tasks (text, answers_json, source) VALUES (?, ?, ?)",
            (text, json.dumps(answers_clean), "openai"),
        )
        tid = cur.lastrowid
        conn.commit()
        conn.close()
        return get_part2_task_by_id(tid)
    except Exception as e:
        print("OpenAI Part 2 error:", e)
        return None


def get_or_create_part2_item(exclude_task_id=None):
    """Get one Part 2 task. If none available, generate via OpenAI. Returns (item, task_id) or (None, None)."""
    task_id = pick_one_part2_task_id(exclude_current=exclude_task_id)
    if task_id is None and openai_client:
        item = _generate_part2_with_openai()
        if item:
            conn = get_db()
            cur = conn.execute("SELECT id FROM part2_tasks ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            conn.close()
            if row:
                record_part2_show(row["id"])
                return (item, row["id"])
            return (item, None)
    if task_id is None:
        conn = get_db()
        if exclude_task_id is not None:
            cur = conn.execute("SELECT id FROM part2_tasks WHERE id != ? ORDER BY RANDOM() LIMIT 1", (exclude_task_id,))
        else:
            cur = conn.execute("SELECT id FROM part2_tasks ORDER BY RANDOM() LIMIT 1")
        row = cur.fetchone()
        conn.close()
        task_id = row["id"] if row else None
    if task_id is None:
        return (None, None)
    record_part2_show(task_id)
    return (get_part2_task_by_id(task_id), task_id)


def get_part5_excluded_ids():
    return _get_excluded_ids("part5_task_shows")


def pick_one_part5_task_id(exclude_current=None):
    return _pick_one_task_id("part5_tasks", "part5_task_shows", exclude_current)


def get_part5_task_by_id(task_id):
    conn = get_db()
    cur = conn.execute("SELECT id, title, text, questions_json FROM part5_tasks WHERE id = ?", (task_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "title": row["title"],
        "text": row["text"],
        "questions": json.loads(row["questions_json"]),
    }


def record_part5_show(task_id):
    _record_show("part5_task_shows", task_id)


def _generate_part5_with_openai():
    """Generate one Part 5 (reading: long text + 6 MC questions) via OpenAI. B2, 550-650 words, 6 questions in order."""
    if not openai_client:
        return None
    prompt = """You are an FCE (B2 First) Reading and Use of English exam expert. Generate exactly ONE Part 5 task.

Part 5 consists of:
1. A single continuous text (e.g. magazine article, report, or extract from a modern novel). Length: between 550 and 650 words. Upper-Intermediate (B2) level. The text should test understanding of the writer's opinion, attitude, purpose, tone, and implied meaning—not just surface facts.
2. Exactly 6 multiple-choice questions. Each question has four options (A, B, C, D). Questions must follow the chronological order of the text: question 1 relates to the beginning, question 6 may relate to the end or the text as a whole. Each correct answer is worth 2 marks.

Return ONLY a valid JSON object with these exact keys:
- "title": a short title for the text (e.g. "The benefits of learning music")
- "text": the full text. Use <p>...</p> for paragraphs. No other HTML. The text must be 550-650 words.
- "questions": an array of exactly 6 objects. Each object has: "q" (the question text), "options" (array of exactly 4 strings, in order A then B then C then D), "correct" (integer 0, 1, 2, or 3—the index of the correct option).

Example shape:
{"title": "...", "text": "<p>...</p><p>...</p>", "questions": [{"q": "...", "options": ["A text", "B text", "C text", "D text"], "correct": 1}, ...]}

No other text or markdown."""

    try:
        comp = openai_client.chat.completions.create(
            model=openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        content = (comp.choices[0].message.content or "").strip()
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            return None
        data = json.loads(m.group(0))
        title = (data.get("title") or "").strip()
        text = (data.get("text") or "").strip()
        questions = data.get("questions")
        if not title or not text or not isinstance(questions, list) or len(questions) != 6:
            return None
        word_count = len(text.split())
        if word_count < 400 or word_count > 750:
            return None  # allow some flexibility
        normalized = []
        for i, qq in enumerate(questions):
            q = (qq.get("q") or "").strip()
            opts = qq.get("options") or []
            if len(opts) != 4:
                return None
            correct = int(qq.get("correct", 0))
            if correct not in (0, 1, 2, 3):
                correct = 0
            normalized.append({
                "q": q,
                "options": [str(o).strip() for o in opts],
                "correct": correct,
            })
        conn = get_db()
        cur = conn.execute(
            "INSERT INTO part5_tasks (title, text, questions_json, source) VALUES (?, ?, ?, ?)",
            (title, text, json.dumps(normalized), "openai"),
        )
        tid = cur.lastrowid
        conn.commit()
        conn.close()
        return get_part5_task_by_id(tid)
    except Exception as e:
        print("OpenAI Part 5 error:", e)
        return None


def get_or_create_part5_item(exclude_task_id=None):
    """Get one Part 5 task (exclude last 100 shown, and optionally exclude_task_id). If none available, generate via OpenAI. Record show. Returns (item, task_id) or (None, None)."""
    task_id = pick_one_part5_task_id(exclude_current=exclude_task_id)
    if task_id is None and openai_client:
        item = _generate_part5_with_openai()
        if item:
            conn = get_db()
            cur = conn.execute("SELECT id FROM part5_tasks ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            conn.close()
            if row:
                record_part5_show(row["id"])
                return (item, row["id"])
            return (item, None)
    if task_id is None:
        # Fallback: pick any task that is not the one we're excluding (so "Next" gives a different one)
        conn = get_db()
        if exclude_task_id is not None:
            cur = conn.execute("SELECT id FROM part5_tasks WHERE id != ? ORDER BY RANDOM() LIMIT 1", (exclude_task_id,))
        else:
            cur = conn.execute("SELECT id FROM part5_tasks ORDER BY RANDOM() LIMIT 1")
        row = cur.fetchone()
        conn.close()
        task_id = row["id"] if row else None
    if task_id is None:
        return (None, None)
    record_part5_show(task_id)
    return (get_part5_task_by_id(task_id), task_id)


def get_part6_excluded_ids():
    return _get_excluded_ids("part6_task_shows")


def pick_one_part6_task_id(exclude_current=None):
    return _pick_one_task_id("part6_tasks", "part6_task_shows", exclude_current)


def get_part6_task_by_id(task_id):
    conn = get_db()
    cur = conn.execute(
        "SELECT id, paragraphs_json, sentences_json, answers_json FROM part6_tasks WHERE id = ?",
        (task_id,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "paragraphs": json.loads(row["paragraphs_json"]),
        "sentences": json.loads(row["sentences_json"]),
        "answers": json.loads(row["answers_json"]),
    }


def record_part6_show(task_id):
    _record_show("part6_task_shows", task_id)


def _generate_part6_with_openai():
    """Generate one Part 6 (gapped text: 500-600 words, 6 gaps, 7 sentences A-G). Returns item dict or None."""
    if not openai_client:
        return None
    prompt = """You are an FCE (B2 First) Reading and Use of English exam expert. Generate exactly ONE Part 6 (gapped text) task.

Part 6 consists of:
- A single continuous text of 500-600 words (B2 level). The text must contain exactly 6 numbered gaps where a sentence has been removed. Use the exact placeholders GAP1, GAP2, GAP3, GAP4, GAP5, GAP6 in order where each gap appears (each on its own line/segment).
- 7 sentences labeled A–G. Exactly 6 of these fit into the gaps (one per gap); one sentence is a distractor and does not fit any gap.

Return ONLY a valid JSON object with these exact keys:
- "paragraphs": an array of strings. Each string is either a paragraph (or part of the text) or exactly "GAP1", "GAP2", "GAP3", "GAP4", "GAP5", "GAP6" where that gap appears. The gaps can be in any order but must appear as separate elements. Example: ["First paragraph text.", "GAP1", "More text.", "GAP2", ...]
- "sentences": an array of exactly 7 strings: the sentence for A, then B, then C, D, E, F, G. Give only the sentence text (no "A)" prefix). Example: ["First option text.", "Second option.", ...]
- "answers": an array of exactly 6 integers (0-6). answers[i] is the index into "sentences" (0=A, 1=B, ... 6=G) that correctly fills gap i+1. So the first gap gets sentences[answers[0]], etc. One index 0-6 will not appear (the distractor).

No other text or markdown."""

    try:
        comp = openai_client.chat.completions.create(
            model=openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        content = (comp.choices[0].message.content or "").strip()
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            return None
        data = json.loads(m.group(0))
        paragraphs = data.get("paragraphs")
        sentences = data.get("sentences")
        answers = data.get("answers")
        if not isinstance(paragraphs, list) or not isinstance(sentences, list) or len(sentences) != 7:
            return None
        if not isinstance(answers, list) or len(answers) != 6:
            return None
        gap_placeholders = {"GAP1", "GAP2", "GAP3", "GAP4", "GAP5", "GAP6"}
        if sum(1 for p in paragraphs if p in gap_placeholders) != 6:
            return None
        for a in answers:
            if a not in range(7):
                return None
        sentences_clean = [str(s).strip() for s in sentences]
        paragraphs_clean = [str(p).strip() for p in paragraphs]
        answers_clean = [int(a) for a in answers]
        conn = get_db()
        cur = conn.execute(
            "INSERT INTO part6_tasks (paragraphs_json, sentences_json, answers_json, source) VALUES (?, ?, ?, ?)",
            (json.dumps(paragraphs_clean), json.dumps(sentences_clean), json.dumps(answers_clean), "openai"),
        )
        tid = cur.lastrowid
        conn.commit()
        conn.close()
        return get_part6_task_by_id(tid)
    except Exception as e:
        print("OpenAI Part 6 error:", e)
        return None


def get_or_create_part6_item(exclude_task_id=None):
    """Get one Part 6 task. Returns (item, task_id) or (None, None)."""
    task_id = pick_one_part6_task_id(exclude_current=exclude_task_id)
    if task_id is None and openai_client:
        item = _generate_part6_with_openai()
        if item:
            conn = get_db()
            cur = conn.execute("SELECT id FROM part6_tasks ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            conn.close()
            if row:
                record_part6_show(row["id"])
                return (item, row["id"])
            return (item, None)
    if task_id is None:
        conn = get_db()
        if exclude_task_id is not None:
            cur = conn.execute("SELECT id FROM part6_tasks WHERE id != ? ORDER BY RANDOM() LIMIT 1", (exclude_task_id,))
        else:
            cur = conn.execute("SELECT id FROM part6_tasks ORDER BY RANDOM() LIMIT 1")
        row = cur.fetchone()
        conn.close()
        task_id = row["id"] if row else None
    if task_id is None:
        return (None, None)
    record_part6_show(task_id)
    return (get_part6_task_by_id(task_id), task_id)


def get_part7_excluded_ids():
    return _get_excluded_ids("part7_task_shows")


def pick_one_part7_task_id(exclude_current=None):
    return _pick_one_task_id("part7_tasks", "part7_task_shows", exclude_current)


def get_part7_task_by_id(task_id):
    conn = get_db()
    cur = conn.execute(
        "SELECT id, sections_json, questions_json FROM part7_tasks WHERE id = ?",
        (task_id,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "sections": json.loads(row["sections_json"]),
        "questions": json.loads(row["questions_json"]),
    }


def record_part7_show(task_id):
    _record_show("part7_task_shows", task_id)


def _generate_part7_with_openai():
    """Generate one Part 7 (multiple matching): 600-700 words total in 4-6 sections (A-F), 10 statements to match. 1 mark each."""
    if not openai_client:
        return None
    prompt = """You are an FCE (B2 First) Reading exam expert. Generate exactly ONE Part 7 (Multiple matching) task.

Part 7 consists of:
- Either ONE long text divided into 4-6 sections (labeled A, B, C, D, and optionally E, F) OR 4-5 short separate texts. Total length 600-700 words (B2 level).
- 10 statements that the candidate must match to the correct section. Use paraphrasing: do not copy phrases from the text; rephrase (e.g. "financial struggle" in the question might appear as "barely having enough money for rent" in the text). Each correct match = 1 mark.

Return ONLY a valid JSON object with these exact keys:
- "sections": an array of 4 to 6 objects. Each object has "id" (letter "A", "B", "C", "D", "E", or "F"), "title" (short section title), "text" (the section body text). The combined word count of all section "text" must be between 600 and 700 words.
- "questions": an array of exactly 10 objects. Each has "text" (the statement to match, one sentence) and "correct" (the section id, e.g. "A", "B"). Each section should be matched by at least one question; distribute matches across sections. Use paraphrasing in statements so answers are not obvious from word-for-word matching.

No other text or markdown."""

    try:
        comp = openai_client.chat.completions.create(
            model=openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        content = (comp.choices[0].message.content or "").strip()
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            return None
        data = json.loads(m.group(0))
        sections = data.get("sections")
        questions = data.get("questions")
        if not isinstance(sections, list) or len(sections) < 4 or len(sections) > 6:
            return None
        if not isinstance(questions, list) or len(questions) != 10:
            return None
        ids_seen = set()
        for sec in sections:
            sid = (sec.get("id") or "").strip().upper()
            if not sid or len(sid) != 1:
                return None
            ids_seen.add(sid)
        section_ids = [s.get("id", "").strip().upper() for s in sections]
        sections_clean = []
        for s in sections:
            sections_clean.append({
                "id": (s.get("id") or "").strip().upper(),
                "title": (s.get("title") or "").strip(),
                "text": (s.get("text") or "").strip(),
            })
        total_words = sum(len(sec["text"].split()) for sec in sections_clean)
        if total_words < 550 or total_words > 750:
            return None  # allow slight flexibility
        questions_clean = []
        for q in questions:
            text = (q.get("text") or "").strip()
            correct = (q.get("correct") or "").strip().upper()
            if not text or correct not in section_ids:
                return None
            questions_clean.append({"text": text, "correct": correct})
        conn = get_db()
        cur = conn.execute(
            "INSERT INTO part7_tasks (sections_json, questions_json, source) VALUES (?, ?, ?)",
            (json.dumps(sections_clean), json.dumps(questions_clean), "openai"),
        )
        tid = cur.lastrowid
        conn.commit()
        conn.close()
        return get_part7_task_by_id(tid)
    except Exception as e:
        print("OpenAI Part 7 error:", e)
        return None


def get_or_create_part7_item(exclude_task_id=None):
    """Get one Part 7 task. If none available, generate via OpenAI. Returns (item, task_id) or (None, None)."""
    task_id = pick_one_part7_task_id(exclude_current=exclude_task_id)
    if task_id is None and openai_client:
        item = _generate_part7_with_openai()
        if item:
            conn = get_db()
            cur = conn.execute("SELECT id FROM part7_tasks ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            conn.close()
            if row:
                record_part7_show(row["id"])
                return (item, row["id"])
            return (item, None)
    if task_id is None:
        conn = get_db()
        if exclude_task_id is not None:
            cur = conn.execute("SELECT id FROM part7_tasks WHERE id != ? ORDER BY RANDOM() LIMIT 1", (exclude_task_id,))
        else:
            cur = conn.execute("SELECT id FROM part7_tasks ORDER BY RANDOM() LIMIT 1")
        row = cur.fetchone()
        conn.close()
        task_id = row["id"] if row else None
    if task_id is None:
        return (None, None)
    record_part7_show(task_id)
    return (get_part7_task_by_id(task_id), task_id)


def fetch_explanations_part1(item, details):
    """Ask OpenAI to explain why the correct answer is right and (if wrong) why the student's answer is wrong. Returns list of 8 strings."""
    if not openai_client or not item or not item.get("gaps") or len(details) < 8:
        return []
    passage = (item.get("text") or "").strip()
    lines = []
    for i in range(8):
        g = item["gaps"][i]
        opts = g.get("options", [])
        correct_idx = g.get("correct", 0)
        user_idx = details[i].get("user_val")
        if user_idx is None or user_idx < 0:
            user_idx = -1
        correct_letter = LETTERS[correct_idx] if correct_idx < len(LETTERS) else "?"
        correct_word = opts[correct_idx] if correct_idx < len(opts) else ""
        user_letter = LETTERS[user_idx] if 0 <= user_idx < len(LETTERS) else "—"
        user_word = opts[user_idx] if 0 <= user_idx < len(opts) else "(no answer)"
        lines.append(f"Gap {i+1}: A) {opts[0]} B) {opts[1]} C) {opts[2]} D) {opts[3]}. Correct: {correct_letter}) {correct_word}. Student chose: {user_letter}) {user_word}.")
    prompt = """You are an FCE (B2 First) English teacher. You will see a multiple-choice cloze passage and, for each gap, the four options (A–D), the correct answer, and what the student chose.

Use the PASSAGE as context so your explanations refer to the actual sentences (e.g. "In this sentence, X is needed because...").

PASSAGE (gaps are marked as (1)_____, (2)_____, etc.):
---
""" + passage + """

---
For each gap, write ONE short explanation (1-2 sentences) in plain English:
1) Why the correct answer is right in this context (grammar/meaning in the sentence above).
2) If the student's answer was wrong, briefly why that option is wrong or doesn't fit here.

Keep each explanation clear and educational. Return ONLY a JSON array of exactly 8 strings (one per gap, in order). No other text.

Gaps:
""" + "\n".join(lines)
    try:
        comp = openai_client.chat.completions.create(
            model=openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        content = (comp.choices[0].message.content or "").strip()
        m = re.search(r"\[[\s\S]*?\]", content)
        if not m:
            return []
        arr = json.loads(m.group(0))
        if isinstance(arr, list) and len(arr) >= 8:
            return [str(arr[i]).strip() for i in range(8)]
        return []
    except Exception as e:
        print("OpenAI explanations Part 1 error:", e)
        return []


def fetch_explanations_part2(item, details):
    """Ask OpenAI to explain why the correct answer is right and (if wrong) why the student's answer doesn't fit. Returns list of 8 strings."""
    if not openai_client or not item or not item.get("answers") or len(details) < 8:
        return []
    passage = (item.get("text") or "").strip()
    lines = []
    for i in range(8):
        correct = (item["answers"][i] if i < len(item["answers"]) else "").strip()
        user_val = (details[i].get("user_val") or "").strip()
        lines.append(f"Gap {i+1}: Correct answer: '{correct}'. Student wrote: '{user_val or '(blank)'}'.")
    prompt = """You are an FCE (B2 First) English teacher. You will see an open-cloze passage and, for each gap, the correct answer and what the student wrote.

Use the PASSAGE as context so your explanations refer to the actual sentences (e.g. "In this sentence, X is needed because...").

PASSAGE (gaps are marked as (1)_____, (2)_____, etc.):
---
""" + passage + """

---
For each gap, write ONE short explanation (1-2 sentences) in plain English:
1) Why the correct word is right in this context (grammar/meaning in the sentence above).
2) If the student's answer was wrong or blank, briefly why their word doesn't fit or what the gap requires here.

Keep each explanation clear and educational. Return ONLY a JSON array of exactly 8 strings (one per gap, in order). No other text.

Gaps:
""" + "\n".join(lines)
    try:
        comp = openai_client.chat.completions.create(
            model=openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        content = (comp.choices[0].message.content or "").strip()
        m = re.search(r"\[[\s\S]*?\]", content)
        if not m:
            return []
        arr = json.loads(m.group(0))
        if isinstance(arr, list) and len(arr) >= 8:
            return [str(arr[i]).strip() for i in range(8)]
        return []
    except Exception as e:
        print("OpenAI explanations Part 2 error:", e)
        return []


def fetch_explanations_part3(task, details):
    """Ask OpenAI for each gap: (1) why the answer is correct or why the student's is wrong, (2) word family (noun, adjective, adverb, verb) for the stem. Returns list of 8 dicts with 'explanation' and 'word_family'."""
    if not openai_client or not task or len(details) < 8:
        return []
    # Get passage and stems/answers
    if isinstance(task, dict) and "text" in task:
        passage = (task.get("text") or "").strip()
        stems = task.get("stems") or []
        answers = task.get("answers") or []
    else:
        items = task.get("items") if isinstance(task, dict) else (task if isinstance(task, list) else [])
        if not items or len(items) < 8:
            return []
        passage = " ".join((it.get("sentence") or "").strip() for it in items[:8])
        stems = [items[i].get("key", "").strip() for i in range(8)]
        answers = [items[i].get("answer", "").strip() for i in range(8)]
    if len(stems) < 8 or len(answers) < 8:
        return []
    lines = []
    for i in range(8):
        stem = (stems[i] if i < len(stems) else "").strip()
        correct = (answers[i] if i < len(answers) else "").strip()
        user_val = (details[i].get("user_val") or "").strip()
        lines.append(f"Gap {i+1}: Stem word: {stem}. Correct answer: '{correct}'. Student wrote: '{user_val or '(blank)'}'.")
    prompt = """You are an FCE (B2 First) English teacher. For a Part 3 (word formation) task, you will see the passage and for each gap: the stem word in CAPITALS, the correct answer, and what the student wrote.

PASSAGE (for context):
---
""" + passage[:4000] + """

---
For each gap, provide TWO things:

1) **Explanation** (1-2 sentences): Why the correct word fits in this context (grammar/meaning). If the student's answer was wrong or blank, explain briefly why their word doesn't fit or what form was needed (e.g. "We need an adverb here to describe the verb" or "The negative form 'impossible' is required by the context").

2) **Word family** for the stem: Give the main forms that exist for this word, in this exact format (use — for forms that don't exist or aren't common):
  noun: ... ; adjective: ... ; adverb: ... ; verb: ...

Example for COMPLETE: noun: completion ; adjective: complete ; adverb: completely ; verb: complete
Example for QUIET: noun: quiet ; adjective: quiet ; adverb: quietly ; verb: (no common verb form — use —)

Return ONLY a valid JSON array of exactly 8 objects. Each object has two keys: "explanation" (string) and "word_family" (string, the "noun: ... ; adjective: ... ; adverb: ... ; verb: ..." line). No other text.

Gaps:
""" + "\n".join(lines)
    try:
        comp = openai_client.chat.completions.create(
            model=openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        content = (comp.choices[0].message.content or "").strip()
        m = re.search(r"\[[\s\S]*?\]", content)
        if not m:
            return []
        arr = json.loads(m.group(0))
        if not isinstance(arr, list) or len(arr) < 8:
            return []
        result = []
        for i in range(8):
            el = arr[i] if isinstance(arr[i], dict) else {}
            result.append({
                "explanation": str(el.get("explanation") or "").strip()[:400],
                "word_family": str(el.get("word_family") or "").strip()[:200],
            })
        return result
    except Exception as e:
        print("OpenAI explanations Part 3 error:", e)
        return []


def fetch_explanations_part4(tasks, details):
    """Ask OpenAI to explain why the correct answer is right and (if wrong) why the student's answer is wrong. Returns list of n strings."""
    if not openai_client or not tasks or len(details) < len(tasks):
        return []
    lines = []
    for i in range(len(tasks)):
        t = tasks[i]
        d = details[i]
        correct_ans = t.get("answer", "")
        user_ans = d.get("user_val", "") or "(no answer)"
        lines.append(f"Item {i+1}: First sentence: {t.get('sentence1')}. Key word: {t.get('keyword')}. Second sentence (gap): {t.get('sentence2')}. Correct answer: \"{correct_ans}\". Student wrote: \"{user_ans}\".")
    prompt = """You are an FCE (B2 First) English teacher. Below are key word transformation items with the correct answer and what the student wrote.

For each item, write ONE short explanation (1-2 sentences) in plain English:
1) Why the correct answer is right (same meaning, uses the key word correctly).
2) If the student's answer was wrong, briefly why it doesn't work or what the mistake is.

Keep each explanation clear and educational. Return ONLY a JSON array of strings (one per item). No other text.

Items:
""" + "\n".join(lines)
    try:
        comp = openai_client.chat.completions.create(
            model=openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        content = (comp.choices[0].message.content or "").strip()
        m = re.search(r"\[[\s\S]*?\]", content)
        if not m:
            return []
        arr = json.loads(m.group(0))
        if isinstance(arr, list) and len(arr) >= len(tasks):
            return [str(arr[i]).strip() for i in range(len(tasks))]
        return []
    except Exception as e:
        print("OpenAI explanations Part 4 error:", e)
        return []


def pick_task_ids_from_db(count: int, recent_grammar_topics=None):
    """Pick task IDs for Part 4. Prefer tasks whose grammar_topic is NOT in recent_grammar_topics (avoid repeating same grammar)."""
    recent_grammar_topics = recent_grammar_topics or []
    excluded = get_excluded_task_ids()
    conn = get_db()
    # Prefer tasks with grammar_topic not in recent list; then random
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
    conn.close()
    return ids[: count * 2]


def _uoe_has_grammar_topic_column(conn=None):
    if conn is None:
        conn = get_db()
        try:
            cur = conn.execute("PRAGMA table_info(uoe_tasks)")
            out = any(r["name"] == "grammar_topic" for r in cur.fetchall())
            return out
        finally:
            conn.close()
    cur = conn.execute("PRAGMA table_info(uoe_tasks)")
    return any(r["name"] == "grammar_topic" for r in cur.fetchall())


def get_recent_grammar_topics(limit=20):
    """Return list of grammar_topic values from recently shown Part 4 tasks (from uoe_task_shows)."""
    conn = get_db()
    try:
        cur = conn.execute("PRAGMA table_info(uoe_tasks)")
        if not any(r["name"] == "grammar_topic" for r in cur.fetchall()):
            return []
        cur = conn.execute("""
            SELECT DISTINCT t.grammar_topic FROM uoe_tasks t
            INNER JOIN uoe_task_shows s ON t.id = s.task_id
            WHERE t.grammar_topic IS NOT NULL AND trim(t.grammar_topic) != ''
            ORDER BY s.shown_at DESC
            LIMIT ?
        """, (limit,))
        return [r["grammar_topic"].strip() for r in cur.fetchall() if r.get("grammar_topic")]
    except Exception:
        return []
    finally:
        conn.close()


def record_shows(task_ids):
    conn = get_db()
    for tid in task_ids:
        conn.execute("INSERT INTO uoe_task_shows (task_id, shown_at) VALUES (?, datetime('now'))", (tid,))
    conn.commit()
    conn.close()


def get_tasks_by_ids(ids):
    if not ids:
        return []
    conn = get_db()
    ph = ",".join("?" * len(ids))
    try:
        cur = conn.execute(
            f"SELECT id, sentence1, keyword, sentence2, answer, grammar_topic FROM uoe_tasks WHERE id IN ({ph})", ids
        )
    except sqlite3.OperationalError:
        cur = conn.execute(
            f"SELECT id, sentence1, keyword, sentence2, answer FROM uoe_tasks WHERE id IN ({ph})", ids
        )
    rows = cur.fetchall()
    conn.close()
    by_id = {r["id"]: dict(r) for r in rows}
    out = [by_id[i] for i in ids if i in by_id]
    for r in out:
        if "grammar_topic" not in r:
            r["grammar_topic"] = None
    return out


def fetch_part4_tasks(level: str = "b2plus", db_only: bool = False):
    """Fetch Part 4 tasks. When db_only=True, only pick from database (no OpenAI generation). Otherwise generate if OpenAI is set."""
    _ensure_uoe_grammar_topic_column()
    tasks = []
    if not db_only and openai_client:
        tasks = _generate_tasks_with_openai(
            PART4_TASKS_PER_SET,
            level=level,
            recent_grammar_topics=get_recent_grammar_topics(15),
        )
    if not tasks:
        # Pick extra ids so after filtering we still have enough; prefer grammar topics not recently shown
        recent_topics = get_recent_grammar_topics(15)
        ids = pick_task_ids_from_db(PART4_TASKS_PER_SET * 2, recent_grammar_topics=recent_topics)
        if not ids:
            return None
        rows = get_tasks_by_ids(ids)
        out = []
        for r in rows:
            if len(out) >= PART4_TASKS_PER_SET:
                break
            if not _answer_uses_keyword(r["answer"], r["keyword"]) or not _part4_answer_length_ok(r["answer"]):
                continue
            if _part4_sentence2_same_as_sentence1(r["sentence1"], r["sentence2"], r["answer"]):
                continue  # skip tasks where sentence2 is just sentence1 with a gap
            out.append(r)
        if out:
            record_shows([r["id"] for r in out])
        return [{"sentence1": r["sentence1"], "keyword": r["keyword"], "sentence2": r["sentence2"], "answer": r["answer"]} for r in out] if out else None
    record_shows([t["id"] for t in tasks])
    return [{"sentence1": t["sentence1"], "keyword": t["keyword"], "sentence2": t["sentence2"], "answer": t["answer"]} for t in tasks]


def _uoe_task_exists(sentence1: str, keyword: str) -> bool:
    """Check if a Part 4 task with the same sentence1 and keyword already exists (uniqueness)."""
    conn = get_db()
    cur = conn.execute(
        "SELECT 1 FROM uoe_tasks WHERE sentence1 = ? AND keyword = ? LIMIT 1",
        (sentence1.strip(), keyword.strip().upper()),
    )
    exists = cur.fetchone() is not None
    conn.close()
    return exists


def _generate_tasks_with_openai(count: int, level: str = "b2plus", recent_grammar_topics=None):
    """Generate Part 4 key word transformation tasks. level is 'b2' or 'b2plus'.
    recent_grammar_topics: list of grammar topics to avoid repeating (from get_recent_grammar_topics)."""
    if not openai_client:
        return []
    _ensure_uoe_grammar_topic_column()
    recent_grammar_topics = recent_grammar_topics or []
    recent_avoid = ""
    if recent_grammar_topics:
        recent_avoid = "\nAvoid or minimise repetition of these recently used grammar topics: " + ", ".join(recent_grammar_topics[:10]) + ".\n"
    level_instruction = (
        "Level: B2+ (slightly more difficult than B2). Use vocabulary and grammar that is upper-intermediate to advanced: less common collocations, more complex structures, idiomatic expressions. Avoid items that are too easy (A2/B1)."
        if (level or "").strip().lower() == "b2plus"
        else "Level: B2 (Cambridge B2 First). Use vocabulary and grammar appropriate for upper-intermediate learners. Standard FCE difficulty. Avoid items that are too easy (A2/B1) or too hard (C1)."
    )
    prompt_template = """You are an FCE (B2 First) English exam expert. Generate exactly {count} "key word transformation" items.

""" + level_instruction + """

Each item: sentence1 (first sentence), keyword (ONE word in CAPITALS that MUST appear in the answer), sentence2 (second sentence with the SAME meaning, with exactly one gap "_____"), answer (EXACTLY 3 to 5 words to fill the gap—never 1 or 2 words; the answer MUST contain the key word. E.g. for CHANCE use "chance of winning" or "no chance of succeeding", not just "chance". The gap must require a phrase of 3-5 words.), grammar_topic (ONE short label for the main grammar/construction tested, e.g. "passive voice", "third conditional", "reported speech", "comparatives", "past perfect", "modal verbs", "causative have", "wish/if only", "phrasal verbs", "linking words").

CRITICAL: The second sentence (sentence2) must be a REAL REPHRASING: different wording, different grammar or structure where possible. It must NOT be the first sentence with one phrase simply replaced by "_____". For example, if sentence1 is "You should take a jumper in case it gets colder later", do NOT use sentence2 "You should take a jumper _____ colder later" (that is just sentence1 with a gap). Instead rephrase properly, e.g. "Take a jumper _____ it gets colder later" or use a different structure so the two sentences are clearly different formulations of the same meaning.

Use a DIFFERENT grammar_topic for each item—vary the grammar (passive, conditionals, reported speech, modals, etc.). Do not repeat the same grammar focus in the set.
""" + recent_avoid + """
Return ONLY a valid JSON array of objects with keys: sentence1, keyword, sentence2, answer, grammar_topic. No other text."""
    result = []
    topics_used_in_batch = set()
    for attempt in range(2):
        need = count - len(result)
        if need <= 0:
            break
        prompt = prompt_template.format(count=need)
        try:
            comp = openai_client.chat.completions.create(
                model=openai_model, messages=[{"role": "user", "content": prompt}], temperature=0.8
            )
            content = (comp.choices[0].message.content or "").strip()
            m = re.search(r"\[[\s\S]*\]", content)
            arr = json.loads(m.group(0)) if m else []
            if not isinstance(arr, list):
                continue
            conn = get_db()
            try:
                for item in arr[:need]:
                    s1 = (item.get("sentence1") or "").strip()
                    kw = (item.get("keyword") or "").strip().upper()
                    s2 = (item.get("sentence2") or "").strip()
                    if "_____" not in s2:
                        s2 = re.sub(r"\s+_{2,}\s*", " _____ ", s2)
                    ans = (item.get("answer") or "").strip()
                    grammar_topic = (item.get("grammar_topic") or "").strip() or None
                    if not all([s1, kw, s2, ans]):
                        continue
                    if not _answer_uses_keyword(ans, kw):
                        continue  # reject: answer must contain the key word
                    if not _part4_answer_length_ok(ans):
                        continue  # reject: answer must be 3–5 words
                    if _part4_sentence2_same_as_sentence1(s1, s2, ans):
                        continue  # reject: sentence2 must not be the same as sentence1 with a gap
                    if _part4_similar_to_existing(s1, s2, ans, exclude_ids=[x["id"] for x in result]):
                        continue  # reject: too similar to existing task in DB
                    if _uoe_task_exists(s1, kw):
                        continue
                    # Reject if we already have this grammar topic in this batch (max one per topic per set)
                    if grammar_topic and grammar_topic.lower() in topics_used_in_batch:
                        continue
                    cur = conn.execute(
                        "INSERT INTO uoe_tasks (sentence1, keyword, sentence2, answer, source, grammar_topic) VALUES (?, ?, ?, ?, ?, ?)",
                        (s1, kw, s2, ans, "openai", grammar_topic),
                    )
                    new_id = cur.lastrowid
                    result.append({"id": new_id, "sentence1": s1, "keyword": kw, "sentence2": s2, "answer": ans, "grammar_topic": grammar_topic})
                    if grammar_topic:
                        topics_used_in_batch.add(grammar_topic.lower())
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            print("OpenAI error:", e)
            break
    return result


def _answer_uses_keyword(answer: str, keyword: str) -> bool:
    """Return True if the answer contains the key word (as a word) in any form."""
    if not answer or not keyword:
        return False
    a = _norm(answer)
    kw = keyword.strip().lower()
    # Key word must appear as a whole word (so "no" matches "had no chance" but not "knowledge")
    return bool(re.search(r"\b" + re.escape(kw) + r"\b", a))


def _word_count(s: str) -> int:
    """Return number of words in s (split on whitespace)."""
    return len((s or "").split())


def _part4_answer_length_ok(answer: str) -> bool:
    """Part 4 gap must be filled with 3–5 words."""
    n = _word_count(answer)
    return 3 <= n <= 5


def _part4_sentence2_same_as_sentence1(sentence1: str, sentence2: str, answer: str) -> bool:
    """True if sentence2 with the gap filled by answer is essentially the same as sentence1.
    Reject such items so the second sentence is a real rephrasing, not the first with a blank."""
    if not sentence1 or not sentence2 or "_____" not in sentence2:
        return False
    reconstructed = sentence2.replace("_____", (answer or "").strip()).strip()
    return _norm(reconstructed) == _norm(sentence1)


def _part4_similar_to_existing(sentence1: str, sentence2: str, answer: str, exclude_ids=None) -> bool:
    """True if this task is too similar to any existing task in DB (sentence1 or reconstructed sentence2).
    Uses normalized text and SequenceMatcher ratio >= 0.88 to catch near-duplicates and same grammar structure."""
    if not sentence1 or not sentence2 or "_____" not in sentence2:
        return False
    conn = get_db()
    cur = conn.execute(
        "SELECT id, sentence1, sentence2, answer FROM uoe_tasks ORDER BY id DESC LIMIT 500"
    )
    rows = cur.fetchall()
    conn.close()
    exclude_ids = set(exclude_ids or [])
    n1_new = _norm(sentence1)
    recon_new = _norm(sentence2.replace("_____", (answer or "").strip()))
    for r in rows:
        if r["id"] in exclude_ids:
            continue
        n1_old = _norm(r["sentence1"] or "")
        recon_old = _norm((r["sentence2"] or "").replace("_____", (r["answer"] or "").strip()))
        if not n1_old and not recon_old:
            continue
        if n1_old and difflib.SequenceMatcher(None, n1_new, n1_old).ratio() >= 0.88:
            return True
        if recon_old and difflib.SequenceMatcher(None, recon_new, recon_old).ratio() >= 0.88:
            return True
    return False


def _answers_match(user_val: str, expected: str) -> bool:
    """True if answers are equal after normalization, or close enough (spelling tolerance)."""
    a, b = _norm(user_val), _norm(expected)
    if a == b:
        return True
    if not a or not b:
        return False
    # Allow minor typos: ratio >= 0.88 (e.g. capacity vs capecety, chance of wining vs chance of winning)
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.88


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _e(s):
    return html.escape(str(s)) if s is not None else ""


# --- Session indices for each part ---
def _get_idx(part: int):
    key = f"part{part}_idx"
    if key not in session:
        session[key] = 0
    return session[key]


def _inc_idx(part: int):
    session[f"part{part}_idx"] = _get_idx(part) + 1


# --- HTML builders (with optional check_result for styling) ---
def build_part1_html(item, check_result=None):
    if not item or not item.get("gaps"):
        return "<p>No data.</p>"
    parts = re.split(r"(\(\d+\)_____)", item["text"])
    gap_i = 0
    out = []
    for p in parts:
        if re.match(r"^\(\d+\)_____$", p) and gap_i < len(item["gaps"]):
            g = item["gaps"][gap_i]
            opts = "".join(
                f'<option value="{j}"{" selected" if check_result and check_result.get("details") and check_result["details"][gap_i].get("user_val") == j else ""}>'
                f"{LETTERS[j]}) {_e(opt)}</option>"
                for j, opt in enumerate(g["options"])
            )
            cls = ""
            if check_result and check_result.get("details") and gap_i < len(check_result["details"]):
                d = check_result["details"][gap_i]
                cls = " result-correct" if d.get("correct") else " result-wrong"
            out.append(f'<span class="gap-inline{cls}"><select name="p1_{gap_i}"><option value="">—</option>{opts}</select></span>')
            gap_i += 1
        else:
            out.append(_e(p))
    html = "".join(out)
    if check_result and check_result.get("details"):
        expl_list = []
        for i, d in enumerate(check_result["details"]):
            if i >= len(item["gaps"]):
                break
            correct = d.get("correct")
            correct_idx = item["gaps"][i].get("correct", 0)
            correct_letter = LETTERS[correct_idx] if correct_idx < len(LETTERS) else "?"
            expected_word = d.get("expected") or (item["gaps"][i].get("options") or [""])[correct_idx]
            exp = d.get("explanation", "")
            if not correct:
                if exp:
                    expl_list.append(
                        f'<li class="part2-expl-item part2-expl-wrong">'
                        f'<strong>Gap {i + 1}:</strong> <span class="part2-expl-correct">Correct: <em>{correct_letter}) {_e(expected_word)}</em></span>. '
                        f'<span class="part2-expl-reason">{_e(exp)}</span></li>'
                    )
                else:
                    expl_list.append(
                        f'<li class="part2-expl-item part2-expl-wrong">'
                        f'<strong>Gap {i + 1}:</strong> <span class="part2-expl-correct">Correct: <em>{correct_letter}) {_e(expected_word)}</em></span>.</li>'
                    )
            elif exp:
                expl_list.append(f'<li class="part2-expl-item part2-expl-correct"><strong>Gap {i + 1}:</strong> <span class="part2-expl-reason">{_e(exp)}</span></li>')
        if expl_list:
            html += '<div class="explanations-block"><h4>Why this answer is correct / why it is wrong</h4><ol class="answer-explanations">' + "".join(expl_list) + "</ol></div>"
    return html


def build_part2_html(item, check_result=None):
    if not item or not item.get("answers"):
        return "<p>No data.</p>"
    parts = re.split(r"(\(\d+\)_____)", item["text"])
    gap_i = 0
    out = []
    for p in parts:
        if re.match(r"^\(\d+\)_____$", p) and gap_i < len(item["answers"]):
            val = ""
            if check_result and check_result.get("details") and gap_i < len(check_result["details"]):
                val = check_result["details"][gap_i].get("user_val", "")
            cls = ""
            if check_result and check_result.get("details") and gap_i < len(check_result["details"]):
                d = check_result["details"][gap_i]
                cls = " result-correct" if d.get("correct") else " result-wrong"
            out.append(f'<span class="gap-inline{cls}"><input type="text" name="p2_{gap_i}" value="{_e(val)}" placeholder="{gap_i + 1}" /></span>')
            gap_i += 1
        else:
            out.append(_e(p))
    html = "".join(out)
    if check_result and check_result.get("details"):
        expl_list = []
        for i, d in enumerate(check_result["details"]):
            if i >= len(item["answers"]):
                break
            correct = d.get("correct")
            expected = d.get("expected", "")
            exp = d.get("explanation", "")
            if not correct and expected:
                if exp:
                    expl_list.append(
                        f'<li class="part2-expl-item part2-expl-wrong">'
                        f'<strong>Gap {i + 1}:</strong> <span class="part2-expl-correct">Correct: <em>{_e(expected)}</em></span>. '
                        f'<span class="part2-expl-reason">{_e(exp)}</span></li>'
                    )
                else:
                    expl_list.append(
                        f'<li class="part2-expl-item part2-expl-wrong">'
                        f'<strong>Gap {i + 1}:</strong> <span class="part2-expl-correct">Correct: <em>{_e(expected)}</em></span>.</li>'
                    )
            elif exp:
                expl_list.append(f'<li class="part2-expl-item part2-expl-correct"><strong>Gap {i + 1}:</strong> <span class="part2-expl-reason">{_e(exp)}</span></li>')
        if expl_list:
            html += '<div class="explanations-block"><h4>Why this answer is correct / why it is wrong</h4><ol class="answer-explanations">' + "".join(expl_list) + "</ol></div>"
    return html


def build_part3_html(task_or_items, check_result=None):
    """Part 3: word formation. Two-column layout like Part 5: LEFT = text with gaps, RIGHT = stem words to transform. Resizer between."""
    if not task_or_items:
        return "<p>No data.</p>"
    # New format: one text with (1)_____ ... (8)_____, stems, answers
    if isinstance(task_or_items, dict) and "text" in task_or_items:
        text = (task_or_items.get("text") or "").strip()
        stems = task_or_items.get("stems") or []
        answers = task_or_items.get("answers") or []
        if not text or len(answers) < 8 or len(stems) < 8:
            return "<p>No data.</p>"
        parts = re.split(r"\((?:1|2|3|4|5|6|7|8)\)_____", text)
        if len(parts) != 9:
            return "<p>Invalid Part 3 text format.</p>"
        # Remove stem word from each segment so it appears only on the right column (stem is in the segment after the gap, e.g. "...shoreline. QUIET Suddenly...")
        for i in range(1, 9):
            stem = (stems[i - 1] if i - 1 < len(stems) else "").strip()
            if stem:
                # Remove " STEM " or " STEM" (space + stem + optional space); keep the period at end of sentence
                parts[i] = re.sub(r"\s+" + re.escape(stem) + r"\s*", " ", parts[i], count=1)
                parts[i] = parts[i].strip()
                if parts[i] and not parts[i].startswith(" "):
                    parts[i] = " " + parts[i]
        out = []
        for i in range(8):
            val = ""
            cls = ""
            if check_result and check_result.get("details") and i < len(check_result["details"]):
                val = check_result["details"][i].get("user_val", "")
                cls = " result-correct" if check_result["details"][i].get("correct") else " result-wrong"
            out.append(_e(parts[i]))
            out.append(f'<span class="gap-inline part3-gap{cls}"><input type="text" name="p3_{i}" value="{_e(val)}" placeholder="{i + 1}" autocomplete="off" /></span>')
        out.append(_e(parts[8]))
        left_html = "".join(out)
        if check_result and check_result.get("details"):
            expl_list = []
            for i, d in enumerate(check_result["details"]):
                if i >= 8:
                    break
                expected = d.get("expected", answers[i] if i < len(answers) else "")
                correct = d.get("correct")
                exp = d.get("explanation", "")
                word_family = d.get("word_family", "")
                cls = " part2-expl-correct" if correct else " part2-expl-wrong"
                body = ""
                if not correct and expected:
                    body = f'<span class="part2-expl-correct">Correct: <em>{_e(expected)}</em></span>. <span class="part2-expl-reason">{_e(exp)}</span>'
                elif correct and exp:
                    body = f'<span class="part2-expl-reason">{_e(exp)}</span>'
                elif correct:
                    body = "Correct."
                else:
                    body = f'<span class="part2-expl-correct">Correct: <em>{_e(expected)}</em></span>.'
                if word_family:
                    body += f'<div class="part3-word-family"><strong>Word family:</strong> {_e(word_family)}</div>'
                expl_list.append(f'<li class="part2-expl-item{cls}"><strong>Gap {i + 1}:</strong> {body}</li>')
            if expl_list:
                left_html += '<div class="explanations-block"><h4>Why this answer is correct / why it is wrong</h4><ol class="answer-explanations">' + "".join(expl_list) + "</ol></div>"
        right_html = "".join(
            f'<div class="part3-stem-row"><span class="part3-stem-num">{i + 1}.</span> <strong class="part3-stem-word">{_e((stems[i] if i < len(stems) else "").strip())}</strong></div>'
            for i in range(8)
        )
        return (
            '<div class="part3-layout" id="part3-layout">'
            '<div class="part3-text-col reading-text exercise cloze-text">' + left_html + '</div>'
            '<div class="part3-resizer" id="part3-resizer" title="Drag to resize"></div>'
            '<div class="part3-stems-col exercise">' + right_html + '</div>'
            '</div>'
        )
    # Old format: list of 8 items, each sentence + stem at end
    items = task_or_items if isinstance(task_or_items, list) else task_or_items.get("items") or []
    if not items or len(items) < 8:
        return "<p>No data.</p>"
    out = []
    stems_right = []
    for i, it in enumerate(items):
        sent = (it.get("sentence") or "").strip()
        key = (it.get("key") or "").strip()
        val = ""
        cls = ""
        if check_result and check_result.get("details") and i < len(check_result["details"]):
            val = check_result["details"][i].get("user_val", "")
            cls = " result-correct" if check_result["details"][i].get("correct") else " result-wrong"
        segs = sent.split("_____", 1)
        sent_without_stem = re.sub(r"\s+" + re.escape(key) + r"\s*$", "", sent).strip() if key else sent
        segs_clean = sent_without_stem.split("_____", 1)
        if len(segs_clean) == 2:
            out.append(f'<span class="part3-sentence">{_e(segs_clean[0])}<span class="gap-inline part3-gap{cls}"><input type="text" name="p3_{i}" value="{_e(val)}" placeholder="{i + 1}" autocomplete="off" /></span>{_e(segs_clean[1])}</span> ')
        else:
            out.append(f'<span class="gap-inline part3-gap{cls}"><input type="text" name="p3_{i}" value="{_e(val)}" placeholder="{i + 1}" autocomplete="off" /></span> ')
        if check_result and check_result.get("details") and i < len(check_result["details"]) and not check_result["details"][i].get("correct"):
            out.append(f'<span class="correct-answer-hint">(Correct: {_e(check_result["details"][i].get("expected"))})</span> ')
        stems_right.append(f'<div class="part3-stem-row"><span class="part3-stem-num">{i + 1}.</span> <strong class="part3-stem-word">{_e(key)}</strong></div>')
    left_html = "".join(out)
    if check_result and check_result.get("details"):
        expl_list = []
        for i, d in enumerate(check_result["details"]):
            if i >= 8:
                break
            expected = d.get("expected", items[i].get("answer", "") if i < len(items) else "")
            correct = d.get("correct")
            exp = d.get("explanation", "")
            word_family = d.get("word_family", "")
            li_cls = " part2-expl-correct" if correct else " part2-expl-wrong"
            body = ""
            if not correct and expected:
                body = f'<span class="part2-expl-correct">Correct: <em>{_e(expected)}</em></span>. <span class="part2-expl-reason">{_e(exp)}</span>'
            elif correct and exp:
                body = f'<span class="part2-expl-reason">{_e(exp)}</span>'
            elif correct:
                body = "Correct."
            else:
                body = f'<span class="part2-expl-correct">Correct: <em>{_e(expected)}</em></span>.'
            if word_family:
                body += f'<div class="part3-word-family"><strong>Word family:</strong> {_e(word_family)}</div>'
            expl_list.append(f'<li class="part2-expl-item{li_cls}"><strong>Gap {i + 1}:</strong> {body}</li>')
        if expl_list:
            left_html += '<div class="explanations-block"><h4>Why this answer is correct / why it is wrong</h4><ol class="answer-explanations">' + "".join(expl_list) + "</ol></div>"
    right_html = "".join(stems_right)
    left_html = "".join(out)
    return (
        '<div class="part3-layout" id="part3-layout">'
        '<div class="part3-text-col reading-text exercise cloze-text">' + left_html + '</div>'
        '<div class="part3-resizer" id="part3-resizer" title="Drag to resize"></div>'
        '<div class="part3-stems-col exercise">' + right_html + '</div>'
        '</div>'
    )


def build_part4_html(tasks, check_result=None):
    if not tasks:
        return "<p>No tasks loaded.</p>"
    out = []
    for i, t in enumerate(tasks):
        if not isinstance(t, dict):
            continue
        s2 = (t.get("sentence2") or "").replace("_____", '<span class="gap-placeholder">_____</span>')
        val = ""
        cls = ""
        detail = None
        if check_result and isinstance(check_result.get("details"), list) and i < len(check_result["details"]):
            d = check_result["details"][i]
            detail = d if isinstance(d, dict) else None
        # Only show answer/check feedback for fields the user actually populated
        attempted = detail is not None and (detail.get("user_val") or "").strip()
        if attempted:
            val = detail.get("user_val", "")
            cls = " result-correct" if detail.get("correct") else " result-wrong"
        out.append(
            f'<div class="question-block uoe-block{cls}">'
            f'<p class="uoe-sentence1"><strong>{i + 1}.</strong> {_e(t.get("sentence1"))}</p>'
            f'<p class="uoe-keyword">Use <strong>{_e(t.get("keyword"))}</strong></p>'
            f'<p class="uoe-sentence2">{s2}</p>'
            f'<div class="gap-line"><input type="text" name="p4_{i}" value="{_e(val)}" placeholder="3–5 words" /></div>'
        )
        if attempted and not detail.get("correct"):
            out.append(f'<p class="correct-answer-hint">Correct: {_e(detail.get("expected"))}</p>')
        if attempted:
            exp = detail.get("explanation")
            if exp:
                out.append(f'<p class="answer-explanation">{_e(exp)}</p>')
        out.append("</div>")
    return "".join(out)


def build_part5_text(item):
    if not item:
        return ""
    return f'<h3>{_e(item.get("title"))}</h3>{item.get("text", "")}'


def build_part5_html(item, check_result=None):
    if not item or not item.get("questions"):
        return "<p>No data.</p>"
    out = []
    for i, q in enumerate(item["questions"]):
        detail = None
        if check_result and check_result.get("details") and i < len(check_result["details"]):
            detail = check_result["details"][i]
        cls = " result-correct" if detail and detail.get("correct") else (" result-wrong" if detail else "")
        selected_val = detail.get("user_val") if detail is not None else None
        opts = "".join(
            f'<label class="part5-option">'
            f'<input type="radio" name="p5_{i}" value="{j}"{" checked" if selected_val == j else ""} /> '
            f'<span class="part5-option-letter">{LETTERS[j]}</span>) {_e(opt)}</label>'
            for j, opt in enumerate(q.get("options", []))
        )
        out.append(
            f'<div class="question-block{cls}"><p>{i + 1}. {_e(q.get("q"))}</p>'
            f'<div class="part5-choices"><span class="part5-choose-label">Choose</span><div class="part5-options">{opts}</div></div></div>'
        )
    return "".join(out)


def build_part6_text(item, check_result=None):
    """Left column: paragraphs with gap drop zones (drag sentence from right into gap). No extra wrapper div."""
    if not item:
        return "<p>No data.</p>"
    letters_g = ["A", "B", "C", "D", "E", "F", "G"]
    sentences = item.get("sentences", [])
    out = []
    gap_i = 0
    for para in item.get("paragraphs", []):
        if para.startswith("GAP"):
            user_val = None
            if check_result and check_result.get("details") and gap_i < len(check_result["details"]):
                user_val = check_result["details"][gap_i].get("user_val")
            cls = ""
            if check_result and check_result.get("details") and gap_i < len(check_result["details"]):
                cls = " result-correct" if check_result["details"][gap_i].get("correct") else " result-wrong"
            try:
                sel_idx = int(user_val) if user_val is not None else -1
            except (TypeError, ValueError):
                sel_idx = -1
            letter = letters_g[sel_idx] if 0 <= sel_idx < len(letters_g) else "—"
            val_attr = str(sel_idx) if 0 <= sel_idx < len(letters_g) else ""
            out.append(
                f'<div class="part6-gap-drop{cls}" data-gap-index="{gap_i}" data-droppable="true">'
                f'<span class="part6-gap-label">{letter}</span>'
                f'<button type="button" class="part6-gap-clear" title="Clear gap" aria-label="Clear gap">×</button>'
                f'<input type="hidden" name="p6_{gap_i}" value="{val_attr}">'
                f'</div>'
            )
            gap_i += 1
        else:
            out.append(f'<p class="part6-para">{_e(para)}</p>')
    return "".join(out)


def build_part6_questions(item):
    """Right column: draggable sentences A–G to drag into gaps."""
    if not item:
        return ""
    letters_g = ["A", "B", "C", "D", "E", "F", "G"]
    sentences = item.get("sentences", [])
    out = ['<div class="part6-sentences"><p><strong>Drag a sentence into a gap:</strong></p><div class="part6-sentence-list">']
    for j, s in enumerate(sentences):
        out.append(
            f'<div class="part6-sentence-drag" draggable="true" data-sentence-index="{j}" role="button" tabindex="0">'
            f'<strong>{letters_g[j]}</strong>) {_e(s)}'
            f'</div>'
        )
    out.append("</div></div>")
    return "".join(out)


def build_part7_text(item):
    """Left column: section texts (A, B, C, D…) in one wrapper for layout."""
    if not item:
        return "<p>No data.</p>"
    sections = item.get("sections", [])
    out = ['<div class="part7-text-col">']
    for sec in sections:
        out.append(f'<div class="part7-section"><h4>{_e(sec.get("id"))}: {_e(sec.get("title"))}</h4><p>{_e(sec.get("text"))}</p></div>')
    out.append("</div>")
    return "".join(out)


def build_part7_questions(item, check_result=None):
    """Right column: 10 statements with section letter choices (choose mark A, B, C…)."""
    if not item:
        return "<p>No data.</p>"
    sections = item.get("sections", [])
    questions = item.get("questions", [])
    ids = [s["id"] for s in sections]
    out = ['<div class="part7-questions"><div class="part7-sentences">']
    for i, q in enumerate(questions):
        selected_val = None
        if check_result and check_result.get("details") and i < len(check_result["details"]):
            selected_val = check_result["details"][i].get("user_val")
        dash_checked = " checked" if (selected_val is None or selected_val == "") else ""
        opts = '<label class="part7-letter"><input type="radio" name="p7_{}" value=""{}><span>—</span></label>'.format(i, dash_checked)
        opts += "".join(
            f'<label class="part7-letter"><input type="radio" name="p7_{i}" value="{_e(sid)}"{" checked" if selected_val == sid else ""}><span>{_e(sid)}</span></label>'
            for sid in ids
        )
        cls = ""
        if check_result and check_result.get("details") and i < len(check_result["details"]):
            cls = " result-correct" if check_result["details"][i].get("correct") else " result-wrong"
        out.append(
            f'<div class="question-block{cls}"><p>{i + 1}. {_e(q.get("text"))}</p>'
            f'<div class="part7-choose"><span class="part7-choose-label">Choose</span><div class="part7-letters">{opts}</div></div></div>'
        )
    out.append("</div></div>")
    return "".join(out)


def check_part1(data, form):
    item = session.get("part1_task")
    if not item or not item.get("gaps"):
        return None
    details = []
    score = 0
    for i in range(8):
        user_val = form.get(f"p1_{i}")
        try:
            user_int = int(user_val)
        except (TypeError, ValueError):
            user_int = -1
        correct_idx = item["gaps"][i]["correct"]
        correct = user_int == correct_idx
        if correct:
            score += 1
        details.append({"correct": correct, "user_val": user_int, "expected": item["gaps"][i]["options"][correct_idx]})
    result = {"part": 1, "score": score, "total": 8, "details": details}
    explanations = fetch_explanations_part1(item, details)
    for i, exp in enumerate(explanations):
        if i < len(result["details"]):
            result["details"][i]["explanation"] = exp
    return result


def check_part2(data, form):
    task_id = session.get("part2_task_id")
    if not task_id:
        _, task_id = get_or_create_part2_item()
        if task_id:
            session["part2_task_id"] = task_id
    item = get_part2_task_by_id(task_id) if task_id else None
    if not item or not item.get("answers"):
        return None
    details = []
    score = 0
    for i in range(len(item["answers"])):
        user_val = (form.get(f"p2_{i}") or "").strip()
        expected = item["answers"][i]
        correct = _answers_match(user_val, expected)
        if correct:
            score += 1
        details.append({"correct": correct, "user_val": user_val, "expected": expected})
    result = {"part": 2, "score": score, "total": len(item["answers"]), "details": details}
    explanations = fetch_explanations_part2(item, details)
    max_len = 400
    for i, exp in enumerate(explanations):
        if i < len(result["details"]) and exp:
            result["details"][i]["explanation"] = (str(exp)[:max_len]).strip()
    return result


def check_part3(data, form):
    task_id = session.get("part3_task_id")
    if not task_id:
        _, task_id = get_or_create_part3_item()
        if task_id:
            session["part3_task_id"] = task_id
    task = get_part3_task_by_id(task_id) if task_id else None
    if not task:
        return None
    if "answers" in task:
        answers = task["answers"]
    else:
        items = task.get("items") or []
        if not items:
            return None
        answers = [items[i].get("answer", "") for i in range(min(8, len(items)))]
    if len(answers) < 8:
        return None
    details = []
    score = 0
    for i in range(8):
        user_val = (form.get(f"p3_{i}") or "").strip()
        expected = answers[i] if i < len(answers) else ""
        correct = _answers_match(user_val, expected)
        if correct:
            score += 1
        details.append({"correct": correct, "user_val": user_val, "expected": expected})
    result = {"part": 3, "score": score, "total": 8, "details": details}
    explanations_data = fetch_explanations_part3(task, details)
    for i, data in enumerate(explanations_data):
        if i < len(result["details"]):
            if data.get("explanation"):
                result["details"][i]["explanation"] = (str(data["explanation"])[:400]).strip()
            if data.get("word_family"):
                result["details"][i]["word_family"] = (str(data["word_family"])[:200]).strip()
    return result


def check_part4(data, form):
    raw = session.get("part4_tasks")
    tasks = list(raw) if isinstance(raw, list) else []
    if not tasks:
        return None
    details = []
    score = 0
    total_attempted = 0  # only count fields that were populated
    for i in range(len(tasks)):
        t = tasks[i]
        if not isinstance(t, dict):
            continue
        user_val = (form.get(f"p4_{i}") or "").strip()
        expected = t.get("answer") or ""
        correct = _answers_match(user_val, expected)
        if user_val:
            total_attempted += 1
            if correct:
                score += 1
        details.append({"correct": correct, "user_val": user_val, "expected": expected})
    result = {"part": 4, "score": score, "total": total_attempted, "details": details}
    explanations = fetch_explanations_part4(tasks, details)
    max_explanation_len = 400  # keep session cookie under size limit
    for i, exp in enumerate(explanations):
        if i < len(result["details"]) and exp:
            result["details"][i]["explanation"] = (str(exp)[:max_explanation_len]).strip()
    return result


def check_part5(data, form):
    task_id = session.get("part5_task_id")
    item = get_part5_task_by_id(task_id) if task_id else None
    if not item or not item.get("questions"):
        return None
    details = []
    score = 0
    for i, q in enumerate(item["questions"]):
        try:
            user_int = int(form.get(f"p5_{i}"))
        except (TypeError, ValueError):
            user_int = -1
        correct_idx = q["correct"]
        correct = user_int == correct_idx
        if correct:
            score += 1
        details.append({"correct": correct, "user_val": user_int})
    return {"part": 5, "score": score, "total": len(item["questions"]), "details": details}


def check_part6(data, form):
    task_id = session.get("part6_task_id")
    item = get_part6_task_by_id(task_id) if task_id else None
    if not item or not item.get("answers"):
        return None
    answers = item["answers"]
    details = []
    score = 0
    for i in range(6):
        try:
            user_int = int(form.get(f"p6_{i}"))
        except (TypeError, ValueError):
            user_int = -1
        correct = user_int == answers[i]
        if correct:
            score += 1
        details.append({"correct": correct, "user_val": user_int})
    return {"part": 6, "score": score, "total": 6, "details": details}


def check_part7(data, form):
    task_id = session.get("part7_task_id")
    if not task_id:
        _, task_id = get_or_create_part7_item()
        if task_id:
            session["part7_task_id"] = task_id
    item = get_part7_task_by_id(task_id) if task_id else None
    if not item or not item.get("questions"):
        return None
    details = []
    score = 0
    for i, q in enumerate(item["questions"]):
        user_val = (form.get(f"p7_{i}") or "").strip()
        correct = user_val == q.get("correct")
        if correct:
            score += 1
        details.append({"correct": correct, "user_val": user_val})
    return {"part": 7, "score": score, "total": len(item["questions"]), "details": details}


def _record_check_result(result):
    """Store check result in history for statistics (includes timestamp)."""
    part = result.get("part")
    score = result.get("score", 0)
    total = result.get("total", 0)
    if part not in range(1, 8) or total <= 0:
        return
    user_id = session.get("user_id")
    conn = get_db()
    conn.execute(
        "INSERT INTO check_history (part, score, total, user_id, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
        (part, score, total, user_id),
    )
    conn.commit()
    conn.close()


def get_part_stats(user_id=None):
    """Return per-part stats: list of dicts with part, total_correct, total_questions, attempts, percent, last_attempt_at.
    If user_id is None, uses session user_id (so stats are for current user or anonymous)."""
    if user_id is None:
        user_id = session.get("user_id")
    conn = get_db()
    if user_id is None:
        cur = conn.execute(
            "SELECT part, SUM(score) AS total_correct, SUM(total) AS total_questions, COUNT(*) AS attempts, MAX(created_at) AS last_attempt_at FROM check_history WHERE user_id IS NULL GROUP BY part"
        )
    else:
        cur = conn.execute(
            "SELECT part, SUM(score) AS total_correct, SUM(total) AS total_questions, COUNT(*) AS attempts, MAX(created_at) AS last_attempt_at FROM check_history WHERE user_id = ? GROUP BY part",
            (user_id,),
        )
    rows = cur.fetchall()
    conn.close()
    stats_by_part = {r["part"]: r for r in rows}
    out = []
    for part in range(1, 8):
        row = stats_by_part.get(part)
        if not row or not row["total_questions"]:
            out.append({"part": part, "total_correct": 0, "total_wrong": 0, "total_questions": 0, "attempts": 0, "percent": None, "last_attempt_at": None, "last_attempt_at_display": None})
        else:
            total_correct = row["total_correct"] or 0
            total_questions = row["total_questions"] or 0
            total_wrong = total_questions - total_correct
            percent = round(100 * total_correct / total_questions, 1) if total_questions else None
            raw_at = row["last_attempt_at"] if row.get("last_attempt_at") else None
            try:
                dt = datetime.strptime(raw_at[:19], "%Y-%m-%d %H:%M:%S") if raw_at and len(raw_at) >= 19 else None
                last_display = dt.strftime("%d %b %Y, %H:%M") if dt else None
            except Exception:
                last_display = raw_at[:16] if raw_at else None
            out.append({
                "part": part,
                "total_correct": total_correct,
                "total_wrong": total_wrong,
                "total_questions": total_questions,
                "attempts": row["attempts"] or 0,
                "percent": percent,
                "last_attempt_at": raw_at,
                "last_attempt_at_display": last_display,
            })
    return out


def _find_or_create_user(google_id, email=None, name=None):
    """Get user id by google_id, or create user and return id."""
    conn = get_db()
    cur = conn.execute("SELECT id FROM users WHERE google_id = ?", (google_id,))
    row = cur.fetchone()
    if row:
        conn.close()
        return row["id"]
    conn.execute(
        "INSERT INTO users (google_id, email, name) VALUES (?, ?, ?)",
        (google_id, email or "", name or ""),
    )
    cur = conn.execute("SELECT last_insert_rowid() AS id")
    uid = cur.fetchone()["id"]
    conn.commit()
    conn.close()
    return uid


CHECKERS = {
   1: check_part1,
   2: check_part2,
   3: check_part3,
   4: check_part4,
   5: check_part5,
   6: check_part6,
   7: check_part7,
}

# Config for parts 2,3,5,6,7: session key, get_or_create fn, get_by_id fn
_PART_TASK_CONFIG = {
   2: ("part2_task_id", get_or_create_part2_item, get_part2_task_by_id),
   3: ("part3_task_id", get_or_create_part3_item, get_part3_task_by_id),
   5: ("part5_task_id", get_or_create_part5_item, get_part5_task_by_id),
   6: ("part6_task_id", get_or_create_part6_item, get_part6_task_by_id),
   7: ("part7_task_id", get_or_create_part7_item, get_part7_task_by_id),
}


def _ensure_part_task(part, exclude_task_id=None):
    """Ensure session has task_id for part 2,3,5,6,7; return (item, task_id)."""
    if part not in _PART_TASK_CONFIG:
        return None, None
    key, get_or_create, get_by_id = _PART_TASK_CONFIG[part]
    if not session.get(key):
        _, tid = get_or_create(exclude_task_id=exclude_task_id)
        if tid:
            session[key] = tid
    tid = session.get(key)
    return (get_by_id(tid) if tid else None, tid)


@app.route("/")
def home():
    user_id = session.get("user_id")
    user_email = session.get("user_email") or ""
    user_name = session.get("user_name") or ""
    user_stats = get_part_stats(user_id) if user_id is not None else None
    has_attempts = user_stats and any(s.get("attempts", 0) for s in user_stats)
    google_available = bool(
        app.config.get("GOOGLE_OAUTH_CLIENT_ID") and app.config.get("GOOGLE_OAUTH_CLIENT_SECRET")
    )
    return render_template(
        "home.html",
        user_id=user_id,
        user_email=user_email,
        user_name=user_name,
        user_stats=user_stats,
        has_attempts=has_attempts,
        google_available=google_available,
    )


@app.route("/login/callback")
def login_callback():
    """After Google OAuth: create/find user, set session, redirect home."""
    try:
        from flask_dance.contrib.google import google as google_client
    except ImportError:
        google_client = None
    if google_client is not None and google_client.authorized:
        try:
            resp = google_client.get("/oauth2/v1/userinfo")
            if resp.ok:
                data = resp.json()
                google_id = data.get("id") or data.get("sub") or ""
                email = data.get("email") or ""
                name = data.get("name") or ""
                if google_id:
                    uid = _find_or_create_user(google_id, email=email, name=name)
                    session["user_id"] = uid
                    session["user_email"] = email
                    session["user_name"] = name
        except Exception:
            pass
    return redirect(url_for("home"))


@app.route("/logout")
def logout():
    """Clear session and redirect home."""
    session.clear()
    return redirect(url_for("home"))


@app.route("/use-of-english", methods=["GET", "POST"])
def use_of_english():
    if request.method == "POST":
        import traceback
        try:
            if request.form.get("action") == "generate_part1":
                level = (request.form.get("level") or "b2").strip().lower()
                if level not in ("b2", "b2plus"):
                    level = "b2"
                task = generate_part1_with_openai(level=level)
                if task:
                    session["part1_task"] = task
                    session.pop("check_result", None)
                    return redirect(url_for("use_of_english", part=1, part1_generated=1, part1_level=level))
                return redirect(url_for("use_of_english", part=1))
            if request.form.get("action") == "generate_part4":
                level = (request.form.get("level") or "b2plus").strip().lower()
                if level not in ("b2", "b2plus"):
                    level = "b2plus"
                generated = _generate_tasks_with_openai(
                    PART4_TASKS_PER_SET,
                    level=level,
                    recent_grammar_topics=get_recent_grammar_topics(15),
                )
                task_list = [{"sentence1": t["sentence1"], "keyword": t["keyword"], "sentence2": t["sentence2"], "answer": t["answer"]} for t in generated]
                if task_list:
                    session["part4_tasks"] = task_list
                    session.pop("check_result", None)
                return redirect(url_for("use_of_english", part=4, part4_generated=len(task_list), part4_level=level))
            if request.form.get("action") == "generate_part2":
                level = (request.form.get("level") or "b2").strip().lower()
                if level not in ("b2", "b2plus"):
                    level = "b2"
                item = _generate_part2_with_openai(level=level)
                if item:
                    conn = get_db()
                    cur = conn.execute("SELECT id FROM part2_tasks ORDER BY id DESC LIMIT 1")
                    row = cur.fetchone()
                    conn.close()
                    if row:
                        session["part2_task_id"] = row["id"]
                        session.pop("check_result", None)
                    return redirect(url_for("use_of_english", part=2, part2_generated=1, part2_level=level))
            if request.form.get("action") == "generate_part3":
                level = (request.form.get("level") or "b2").strip().lower()
                if level not in ("b2", "b2plus"):
                    level = "b2"
                task = generate_part3_with_openai(level=level)
                if task:
                    conn = get_db()
                    cur = conn.execute("SELECT id FROM part3_tasks ORDER BY id DESC LIMIT 1")
                    row = cur.fetchone()
                    conn.close()
                    if row:
                        session["part3_task_id"] = row["id"]
                        session.pop("check_result", None)
                    return redirect(url_for("use_of_english", part=3, part3_generated=1, part3_level=level))
                return redirect(url_for("use_of_english", part=3))
            part = request.form.get("part", type=int)
            switch_to_part = request.form.get("switch_to_part", type=int)
            if part not in range(1, 8):
                return redirect(url_for("use_of_english", part=1))
            # Switching part: redirect immediately without running the checker (no delay)
            if switch_to_part in range(1, 8):
                return redirect(url_for("use_of_english", part=switch_to_part))
            checker = CHECKERS.get(part)
            if not checker:
                return redirect(url_for("use_of_english", part=part))
            result = checker(None, request.form)
            if result:
                _record_check_result(result)
                part_checked = result.get("part")
                if part_checked and part_checked in range(1, 8):
                    parts_checked = session.get("parts_checked") or []
                    if part_checked not in parts_checked:
                        session["parts_checked"] = parts_checked + [part_checked]
                # Store result in server-side cache to avoid session cookie overflow (~4KB limit)
                if len(_CHECK_RESULT_CACHE) >= _CHECK_RESULT_CACHE_MAX:
                    _CHECK_RESULT_CACHE.pop(next(iter(_CHECK_RESULT_CACHE)))
                token = uuid.uuid4().hex
                _CHECK_RESULT_CACHE[token] = result
                return redirect(url_for("use_of_english", part=part, check_result_token=token))
            return redirect(url_for("use_of_english", part=part))
        except Exception as e:
            traceback.print_exc()
            raise

    current_part = request.args.get("part", type=int, default=1)
    if current_part not in range(1, 8):
        current_part = 1
    # Part 4: toggle "database only" mode via ?part4_db_only=1 or 0
    if "part4_db_only" in request.args:
        session["part4_db_only"] = request.args.get("part4_db_only", "").strip().lower() in ("1", "true", "on", "yes")
    next_ = request.args.get("next", type=int, default=0)

    if next_:
        _inc_idx(current_part)
        if current_part == 1:
            session["part1_task"] = get_or_create_part1_task()
        if current_part == 4:
            session["part4_tasks"] = fetch_part4_tasks(level="b2plus", db_only=bool(session.get("part4_db_only")))
        if current_part in _PART_TASK_CONFIG:
            key = _PART_TASK_CONFIG[current_part][0]
            current_tid = session.get(key)
            _, tid = _ensure_part_task(current_part, exclude_task_id=current_tid)
            session[key] = tid
        session.pop("check_result", None)
        return redirect(url_for("use_of_english", part=current_part))

    # Prefer check result from URL token (server-side cache) to avoid cookie size limit
    check_result = None
    token = request.args.get("check_result_token")
    if token and token in _CHECK_RESULT_CACHE:
        check_result = _CHECK_RESULT_CACHE.pop(token)
    if check_result is None:
        check_result = session.pop("check_result", None)

    # Load part data (Part 1 from DB + OpenAI, repeat once in 100)
    if current_part == 1 and not session.get("part1_task"):
        session["part1_task"] = get_or_create_part1_task()
    part1_item = session.get("part1_task")

    part2_item, _ = _ensure_part_task(2)
    part3_item, _ = _ensure_part_task(3)
    part3_items_fallback = []
    part5_item, _ = _ensure_part_task(5)
    part6_item, _ = _ensure_part_task(6)
    part7_item, _ = _ensure_part_task(7)

    if current_part == 4 and not session.get("part4_tasks"):
        session["part4_tasks"] = fetch_part4_tasks(
            level="b2plus",
            db_only=bool(session.get("part4_db_only")),
        )
    part4_tasks = session.get("part4_tasks")
    part4_error = None
    if current_part == 4 and not part4_tasks:
        part4_error = "No tasks in database. Set OPENAI_API_KEY to generate new tasks." if not session.get("part4_db_only") else "No Part 4 tasks in database. Generate tasks or turn off 'Database only'."
    part4_generated = request.args.get("part4_generated", type=int)
    part4_level = request.args.get("part4_level") or ""
    part4_db_only = bool(session.get("part4_db_only"))

    part2_error = None
    if current_part == 2 and not part2_item:
        part2_error = "No Part 2 tasks in database. Set OPENAI_API_KEY to generate new open cloze texts."
    part1_generated = request.args.get("part1_generated", type=int)
    part1_level = request.args.get("part1_level") or ""
    part2_generated = request.args.get("part2_generated", type=int)
    part2_level = request.args.get("part2_level") or ""
    part3_generated = request.args.get("part3_generated", type=int)
    part3_level = request.args.get("part3_level") or ""

    part5_error = None
    if current_part == 5 and not part5_item:
        part5_error = "No Part 5 tasks in database. Set OPENAI_API_KEY to generate new texts and questions."

    part6_error = None
    if current_part == 6 and not part6_item:
        part6_error = "No Part 6 tasks in database. Set OPENAI_API_KEY to generate new gapped texts."

    part7_error = None
    if current_part == 7 and not part7_item:
        part7_error = "No Part 7 tasks in database. Set OPENAI_API_KEY to generate new multiple-matching texts (600-700 words, 10 questions)."

    part3_error = None
    if current_part == 3 and not (part3_item or part3_items_fallback):
        part3_error = "No Part 3 tasks available. Set OPENAI_API_KEY to generate new word-formation texts (150-200 words, 8 gaps)."

    part_stats = get_part_stats()
    current_part_stats = part_stats[current_part - 1] if part_stats else None

    parts_checked = session.get("parts_checked") or []
    parts_done = [p in parts_checked for p in range(1, 8)]
    part_counts = [8, 8, 8, 6, 6, 6, 10]

    cr = check_result if check_result and check_result.get("part") == current_part else None

    part1_error = None
    if current_part == 1 and part1_item is None:
        part1_error = "No tasks available. Set OPENAI_API_KEY to generate new tasks (database is seeded with 2 sample tasks)."
    part1_html = build_part1_html(part1_item, cr if current_part == 1 else None) if not part1_error else ""
    part2_html = build_part2_html(part2_item, cr if current_part == 2 else None)
    part3_html = build_part3_html(part3_item or part3_items_fallback, cr if current_part == 3 else None)
    part4_html = build_part4_html(part4_tasks or [], cr if current_part == 4 else None) if not part4_error else ""
    part5_text = build_part5_text(part5_item) if not part5_error else ""
    part5_html = build_part5_html(part5_item, cr if current_part == 5 else None) if not part5_error else ""
    part6_text = build_part6_text(part6_item, cr if current_part == 6 else None) if not part6_error else ""
    part6_questions = build_part6_questions(part6_item) if not part6_error else ""
    part7_text = build_part7_text(part7_item) if part7_item else ""
    part7_questions = build_part7_questions(part7_item, cr if current_part == 7 else None) if part7_item else ""

    return render_template(
        "index.html",
        current_part=current_part,
        part1_html=part1_html,
        part1_error=part1_error,
        part1_generated=part1_generated,
        part1_level=part1_level,
        part2_html=part2_html,
        part2_error=part2_error,
        part2_generated=part2_generated,
        part2_level=part2_level,
        part3_html=part3_html,
        part3_error=part3_error,
        part3_generated=part3_generated,
        part3_level=part3_level,
        part4_html=part4_html,
        part4_db_only=part4_db_only,
        part4_error=part4_error,
        part4_generated=part4_generated,
        part4_level=part4_level,
        part5_text=part5_text,
        part5_html=part5_html,
        part5_error=part5_error,
        part6_text=part6_text,
        part6_questions=part6_questions,
        part6_error=part6_error,
        part7_text=part7_text,
        part7_questions=part7_questions,
        part7_error=part7_error,
        check_result=check_result,
        current_part_stats=current_part_stats,
        parts_done=parts_done,
        part_counts=part_counts,
    )


@app.route("/writing")
def writing():
    return render_template("writing.html")


if __name__ == "__main__":
    init_db()
    _ensure_uoe_grammar_topic_column()
    _ensure_check_history_user_id()
    seed_db()
    print(f"FCE Trainer at http://localhost:{PORT}")
    print("OpenAI:", "configured" if openai_api_key else "not set")
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=PORT, debug=debug)
