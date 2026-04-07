"""User lookup/create: Google OAuth and email/password."""
from __future__ import annotations

from werkzeug.security import check_password_hash, generate_password_hash

from app.db import db_connection

EMAIL_PREFIX = "email:"


def _normalise_email(email):
    return (email or "").strip().lower()


def find_or_create_user(google_id: str, email: str | None = None, name: str | None = None) -> int:
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


def find_user_by_email(email: str) -> dict | None:
    """Return user row (id, email, name, password_hash) or None. Only for email-registered users."""
    email = _normalise_email(email)
    if not email:
        return None
    with db_connection() as conn:
        cur = conn.execute(
            "SELECT id, email, name, password_hash FROM users WHERE google_id = ?",
            (EMAIL_PREFIX + email,),
        )
        return cur.fetchone()


def create_email_user(email: str, password: str, name: str | None = None) -> int | None:
    """Create a user with email/password. Returns user id or None if email already used."""
    email = _normalise_email(email)
    if not email or not (password or "").strip():
        return None
    with db_connection() as conn:
        cur = conn.execute("SELECT id FROM users WHERE google_id = ?", (EMAIL_PREFIX + email,))
        if cur.fetchone():
            return None
        cur = conn.execute(
            "SELECT id FROM users WHERE email = ?",
            (email,),
        )
        if cur.fetchone():
            return None
        password_hash = generate_password_hash(password.strip(), method="scrypt")
        cur = conn.execute(
            "INSERT INTO users (google_id, email, name, password_hash) VALUES (?, ?, ?, ?)",
            (EMAIL_PREFIX + email, email, (name or "").strip(), password_hash),
        )
        uid = cur.lastrowid
        conn.commit()
        return uid


def verify_email_password(email: str, password: str) -> dict | None:
    """Return user row (id, email, name) if email/password match, else None."""
    user = find_user_by_email(email)
    if not user or not user["password_hash"]:
        return None
    if not check_password_hash(user["password_hash"], password):
        return None
    return {"id": user["id"], "email": user["email"] or "", "name": user["name"] or ""}


def update_password(user_id: int, new_password: str) -> None:
    """Hash and store a new password for the given user."""
    password_hash = generate_password_hash(new_password.strip(), method="scrypt")
    with db_connection() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (password_hash, user_id),
        )
        conn.commit()


def get_user_by_id(user_id: int | None) -> dict | None:
    """Return user row (id, email, name) or None."""
    if not user_id:
        return None
    with db_connection() as conn:
        cur = conn.execute("SELECT id, email, name FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        return dict(row) if row else None
