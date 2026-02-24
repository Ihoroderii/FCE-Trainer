#!/usr/bin/env python3
"""Quick script to inspect the FCE trainer SQLite database. Run: python inspect_db.py"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "fce_trainer.db"

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    print("=== Tables and row counts ===\n")
    for table in ["uoe_tasks", "uoe_task_shows", "part1_tasks", "part1_task_shows"]:
        cur.execute(f"SELECT COUNT(*) as n FROM {table}")
        print(f"  {table}: {cur.fetchone()['n']} rows")

    print("\n=== Part 4 (key word transformation) – uoe_tasks (last 10) ===\n")
    cur.execute("""
        SELECT id, sentence1, keyword, sentence2, answer, source
        FROM uoe_tasks ORDER BY id DESC LIMIT 10
    """)
    for row in cur.fetchall():
        print(f"  id={row['id']} [{row['source']}]")
        print(f"    sentence1: {row['sentence1'][:60]}...")
        print(f"    keyword: {row['keyword']}  |  answer: {row['answer']}")
        print()

    print("=== Part 1 tasks – part1_tasks (id, source, text preview) ===\n")
    cur.execute("SELECT id, source, substr(text, 1, 80) as preview FROM part1_tasks ORDER BY id")
    for row in cur.fetchall():
        print(f"  id={row['id']} [{row['source']}]: {row['preview']}...")

    conn.close()
    print("\nDone. DB file:", DB_PATH.resolve())

if __name__ == "__main__":
    main()
