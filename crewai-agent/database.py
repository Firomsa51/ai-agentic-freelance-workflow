import sqlite3
import json
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path("data/proposals.db")
DB_PATH.parent.mkdir(exist_ok=True)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS proposals (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT,
                reviewed_at TEXT,
                keywords TEXT,
                job_title TEXT,
                company TEXT,
                job_url TEXT,
                job_score REAL,
                proposal_text TEXT,
                timeline TEXT,
                price_range TEXT,
                key_skills_highlighted TEXT
            )
        """)


def insert_proposals(proposals: list):
    with get_conn() as conn:
        for p in proposals:
            conn.execute("""
                INSERT OR REPLACE INTO proposals
                (id, status, created_at, reviewed_at, keywords, job_title, company, job_url,
                 job_score, proposal_text, timeline, price_range, key_skills_highlighted)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                p["id"], p.get("status", "pending"), p.get("created_at"),
                p.get("reviewed_at"), p.get("keywords"), p.get("job_title"),
                p.get("company"), p.get("job_url"), p.get("job_score"),
                p.get("proposal_text"), p.get("timeline"), p.get("price_range"),
                json.dumps(p.get("key_skills_highlighted", []))
            ))


def get_proposals(status: str = None) -> list:
    with get_conn() as conn:
        if status:
            rows = conn.execute("SELECT * FROM proposals WHERE status = ? ORDER BY created_at DESC", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM proposals ORDER BY created_at DESC").fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["key_skills_highlighted"] = json.loads(d.get("key_skills_highlighted") or "[]")
            except json.JSONDecodeError:
                d["key_skills_highlighted"] = []
            result.append(d)
        return result


def get_proposal_by_id(proposal_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
        if row:
            d = dict(row)
            try:
                d["key_skills_highlighted"] = json.loads(d.get("key_skills_highlighted") or "[]")
            except json.JSONDecodeError:
                d["key_skills_highlighted"] = []
            return d
        return None


def update_status(proposal_id: str, status: str, reviewed_at: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE proposals SET status = ?, reviewed_at = ? WHERE id = ?",
            (status, reviewed_at, proposal_id)
        )
        return cur.rowcount > 0


def delete_proposal_by_id(proposal_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM proposals WHERE id = ?", (proposal_id,))
