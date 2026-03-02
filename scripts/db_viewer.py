#!/usr/bin/env python3
"""
Web-based DB viewer for FCE Trainer. No tkinter required.
Run from project root: python scripts/db_viewer.py
Then open http://127.0.0.1:5001 in your browser.
"""
import sqlite3
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DB_PATH = PROJECT_ROOT / "fce_trainer.db"

# Minimal Flask app for the viewer only
from flask import Flask, render_template_string, request

app = Flask(__name__)


def get_connection():
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_tables(conn):
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    return [row[0] for row in cur.fetchall()]


def get_row_count(conn, table):
    cur = conn.execute(f"SELECT COUNT(*) FROM [{table}]")
    return cur.fetchone()[0]


def get_table_info(conn, table):
    cur = conn.execute(f"PRAGMA table_info([{table}])")
    return [dict(row) for row in cur.fetchall()]


def fetch_rows(conn, table, limit=100, offset=0):
    cur = conn.execute(f"SELECT * FROM [{table}] LIMIT ? OFFSET ?", (limit, offset))
    return [dict(row) for row in cur.fetchall()]


HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FCE Trainer — DB Viewer</title>
  <style>
    * { box-sizing: border-box; }
    body { font-family: system-ui, sans-serif; margin: 1rem; background: #f5f5f5; }
    h1 { font-size: 1.25rem; margin-bottom: 0.5rem; }
    .path { font-size: 0.85rem; color: #666; margin-bottom: 1rem; }
    .tables { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1rem; }
    .tables a { display: block; padding: 0.5rem 0.75rem; background: #fff; border: 1px solid #ddd; border-radius: 6px; text-decoration: none; color: #333; }
    .tables a:hover { background: #e8f4fc; border-color: #4da6ff; }
    .tables a.active { background: #4da6ff; color: #fff; border-color: #4da6ff; }
    .data-wrap { overflow-x: auto; background: #fff; border: 1px solid #ddd; border-radius: 6px; padding: 0.75rem; }
    table { border-collapse: collapse; font-size: 0.85rem; }
    th, td { padding: 0.35rem 0.6rem; text-align: left; border-bottom: 1px solid #eee; max-width: 280px; overflow: hidden; text-overflow: ellipsis; }
    th { background: #f0f0f0; font-weight: 600; }
    tr:hover td { background: #fafafa; }
    .empty { color: #999; padding: 1rem; }
    .error { color: #c00; padding: 1rem; }
  </style>
</head>
<body>
  <h1>FCE Trainer — Database Viewer</h1>
  <p class="path">{{ db_path }}</p>
  <p class="path" style="margin-top:0;">Part 4 (Use of English / key word transformation) tasks are in <strong>uoe_tasks</strong>. Answer explanations are stored in <strong>answer_explanations</strong> (after you check answers).</p>
  <div class="tables">
    {% for t in tables %}
    <a href="?table={{ t.name }}" class="{{ 'active' if t.name == current_table else '' }}">{{ t.name }} ({{ t.count }})</a>
    {% endfor %}
  </div>
  <div class="data-wrap">
    {% if error %}
    <p class="error">{{ error }}</p>
    {% elif current_table %}
    <table>
      <thead><tr>{% for c in columns %}<th>{{ c }}</th>{% endfor %}</tr></thead>
      <tbody>
        {% for row in rows %}
        <tr>{% for c in columns %}{% set val = (row[c]|default('')|string) %}<td title="{{ val }}">{{ val[:200] }}{{ '…' if val|length > 200 else '' }}</td>{% endfor %}</tr>
        {% endfor %}
      </tbody>
    </table>
    <p style="margin-top:0.75rem;color:#666;font-size:0.85rem;">Showing up to 100 rows. Table: {{ current_table }}</p>
    {% else %}
    <p class="empty">Select a table above.</p>
    {% endif %}
  </div>
</body>
</html>
"""


@app.route("/")
def index():
    conn = get_connection()
    if not conn:
        return render_template_string(
            HTML,
            db_path=str(DB_PATH),
            tables=[],
            current_table=None,
            columns=[],
            rows=[],
            error=f"Database not found: {DB_PATH}",
        )
    try:
        tables = []
        for t in get_tables(conn):
            tables.append({"name": t, "count": get_row_count(conn, t)})
        current_table = request.args.get("table")
        columns = []
        rows = []
        error = None
        if current_table and current_table in [t["name"] for t in tables]:
            info = get_table_info(conn, current_table)
            columns = [c["name"] for c in info]
            rows = fetch_rows(conn, current_table)
            # Convert Row to dict for template
            rows = [dict(r) for r in rows]
        elif not current_table and tables:
            current_table = tables[0]["name"]
            info = get_table_info(conn, current_table)
            columns = [c["name"] for c in info]
            rows = fetch_rows(conn, current_table)
            rows = [dict(r) for r in rows]
        return render_template_string(
            HTML,
            db_path=str(DB_PATH),
            tables=tables,
            current_table=current_table,
            columns=columns,
            rows=rows,
            error=error,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    print(f"DB path: {DB_PATH}")
    print("Open in browser: http://127.0.0.1:5001")
    app.run(host="127.0.0.1", port=5001, debug=False)
