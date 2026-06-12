import os
import json
import psycopg2
import psycopg2.extras
from contextlib import contextmanager

DATABASE_URL = os.getenv("DATABASE_URL", "")


@contextmanager
def get_conn():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
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
        with conn.cursor() as cur:
            for p in proposals:
                cur.execute("""
                    INSERT INTO proposals
                    (id, status, created_at, reviewed_at, keywords, job_title, company, job_url,
                     job_score, proposal_text, timeline, price_range, key_skills_highlighted)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        status = EXCLUDED.status,
                        created_at = EXCLUDED.created_at,
                        reviewed_at = EXCLUDED.reviewed_at,
                        keywords = EXCLUDED.keywords,
                        job_title = EXCLUDED.job_title,
                        company = EXCLUDED.company,
                        job_url = EXCLUDED.job_url,
                        job_score = EXCLUDED.job_score,
                        proposal_text = EXCLUDED.proposal_text,
                        timeline = EXCLUDED.timeline,
                        price_range = EXCLUDED.price_range,
                        key_skills_highlighted = EXCLUDED.key_skills_highlighted
                """, (
                    p["id"], p.get("status", "pending"), p.get("created_at"),
                    p.get("reviewed_at"), p.get("keywords"), p.get("job_title"),
                    p.get("company"), p.get("job_url"), p.get("job_score"),
                    p.get("proposal_text"), p.get("timeline"), p.get("price_range"),
                    json.dumps(p.get("key_skills_highlighted", []))
                ))


def get_proposals(status: str = None) -> list:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if status:
                cur.execute("SELECT * FROM proposals WHERE status = %s ORDER BY created_at DESC", (status,))
            else:
                cur.execute("SELECT * FROM proposals ORDER BY created_at DESC")
            rows = cur.fetchall()
            result = []
            for r in rows:
                d = dict(r)
                try:
                    d["key_skills_highlighted"] = json.loads(d.get("key_skills_highlighted") or "[]")
                except (json.JSONDecodeError, TypeError):
                    d["key_skills_highlighted"] = []
                result.append(d)
            return result


def get_proposal_by_id(proposal_id: str):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM proposals WHERE id = %s", (proposal_id,))
            row = cur.fetchone()
            if row:
                d = dict(row)
                try:
                    d["key_skills_highlighted"] = json.loads(d.get("key_skills_highlighted") or "[]")
                except (json.JSONDecodeError, TypeError):
                    d["key_skills_highlighted"] = []
                return d
            return None


def update_status(proposal_id: str, status: str, reviewed_at: str) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE proposals SET status = %s, reviewed_at = %s WHERE id = %s",
                (status, reviewed_at, proposal_id)
            )
            return cur.rowcount > 0


def delete_proposal_by_id(proposal_id: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM proposals WHERE id = %s", (proposal_id,))
