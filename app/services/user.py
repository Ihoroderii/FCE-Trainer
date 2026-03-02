"""User lookup/create (Google OAuth)."""
from app.db import db_connection


def find_or_create_user(google_id, email=None, name=None):
    with db_connection() as conn:
        cur = conn.execute("SELECT id FROM users WHERE google_id = ?", (google_id,))
        row = cur.fetchone()
        if row:
            return row["id"]
        cur = conn.execute(
            "INSERT INTO users (google_id, email, name) VALUES (?, ?, ?)",
            (google_id, email or "", name or ""),
        )
        uid = cur.lastrowid
        conn.commit()
        return uid
