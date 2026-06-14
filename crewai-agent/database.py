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
                    key_skills_highlighted TEXT,
                    recommendation TEXT DEFAULT 'Apply',
                    win_probability INTEGER DEFAULT 0,
                    competition_level TEXT DEFAULT 'Unknown',
                    skill_match_score INTEGER DEFAULT 0,
                    opportunity_tier TEXT DEFAULT 'Unknown',
                    reasoning TEXT DEFAULT '',
                    red_flags TEXT DEFAULT '[]',
                    proposal_version INTEGER DEFAULT 1,
                    previous_versions TEXT DEFAULT '[]'
                )
            """)
            # Add new columns if upgrading from old schema
            new_columns = [
                ("recommendation", "TEXT DEFAULT 'Apply'"),
                ("win_probability", "INTEGER DEFAULT 0"),
                ("competition_level", "TEXT DEFAULT 'Unknown'"),
                ("skill_match_score", "INTEGER DEFAULT 0"),
                ("opportunity_tier", "TEXT DEFAULT 'Unknown'"),
                ("reasoning", "TEXT DEFAULT ''"),
                ("red_flags", "TEXT DEFAULT '[]'"),
                ("proposal_version", "INTEGER DEFAULT 1"),
                ("previous_versions", "TEXT DEFAULT '[]'"),
            ]
            for col_name, col_def in new_columns:
                try:
                    cur.execute(f"ALTER TABLE proposals ADD COLUMN {col_name} {col_def}")
                except psycopg2.errors.DuplicateColumn:
                    conn.rollback()


def insert_proposals(proposals: list):
    with get_conn() as conn:
        with conn.cursor() as cur:
            for p in proposals:
                cur.execute("""
                    INSERT INTO proposals
                    (id, status, created_at, reviewed_at, keywords, job_title, company,
                     job_url, job_score, proposal_text, timeline, price_range,
                     key_skills_highlighted, recommendation, win_probability,
                     competition_level, skill_match_score, opportunity_tier,
                     reasoning, red_flags, proposal_version, previous_versions)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (id) DO UPDATE SET
                        status = EXCLUDED.status,
                        job_title = EXCLUDED.job_title,
                        company = EXCLUDED.company,
                        job_url = EXCLUDED.job_url,
                        job_score = EXCLUDED.job_score,
                        proposal_text = EXCLUDED.proposal_text,
                        timeline = EXCLUDED.timeline,
                        price_range = EXCLUDED.price_range,
                        key_skills_highlighted = EXCLUDED.key_skills_highlighted,
                        recommendation = EXCLUDED.recommendation,
                        win_probability = EXCLUDED.win_probability,
                        competition_level = EXCLUDED.competition_level,
                        skill_match_score = EXCLUDED.skill_match_score,
                        opportunity_tier = EXCLUDED.opportunity_tier,
                        reasoning = EXCLUDED.reasoning,
                        red_flags = EXCLUDED.red_flags
                """, (
                    p["id"], p.get("status", "pending"), p.get("created_at"),
                    p.get("reviewed_at"), p.get("keywords"), p.get("job_title"),
                    p.get("company"), p.get("job_url"), p.get("job_score"),
                    p.get("proposal_text"), p.get("timeline"), p.get("price_range"),
                    json.dumps(p.get("key_skills_highlighted", [])),
                    p.get("recommendation", "Apply"),
                    p.get("win_probability", 0),
                    p.get("competition_level", "Unknown"),
                    p.get("skill_match_score", 0),
                    p.get("opportunity_tier", "Unknown"),
                    p.get("reasoning", ""),
                    json.dumps(p.get("red_flags", [])),
                    p.get("proposal_version", 1),
                    json.dumps(p.get("previous_versions", [])),
                ))


def get_proposals(status: str = None) -> list:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if status:
                cur.execute(
                    "SELECT * FROM proposals WHERE status = %s ORDER BY created_at DESC",
                    (status,)
                )
            else:
                cur.execute("SELECT * FROM proposals ORDER BY created_at DESC")
            rows = cur.fetchall()
            result = []
            for r in rows:
                d = dict(r)
                for json_field in ["key_skills_highlighted", "red_flags", "previous_versions"]:
                    try:
                        d[json_field] = json.loads(d.get(json_field) or "[]")
                    except (json.JSONDecodeError, TypeError):
                        d[json_field] = []
                result.append(d)
            return result


def get_proposal_by_id(proposal_id: str):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM proposals WHERE id = %s", (proposal_id,))
            row = cur.fetchone()
            if row:
                d = dict(row)
                for json_field in ["key_skills_highlighted", "red_flags", "previous_versions"]:
                    try:
                        d[json_field] = json.loads(d.get(json_field) or "[]")
                    except (json.JSONDecodeError, TypeError):
                        d[json_field] = []
                return d
            return None


def update_status(proposal_id: str, status: str, reviewed_at: str) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE proposals SET status = %s, reviewed_at = %s WHERE id = ?",
                (status, reviewed_at, proposal_id)
            )
            return cur.rowcount > 0


def update_proposal_text(proposal_id: str, new_text: str) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Save current version to history first
            cur.execute(
                "SELECT proposal_text, proposal_version, previous_versions FROM proposals WHERE id = %s",
                (proposal_id,)
            )
            row = cur.fetchone()
            if not row:
                return False
            current_text, version, prev_versions_raw = row
            try:
                prev_versions = json.loads(prev_versions_raw or "[]")
            except (json.JSONDecodeError, TypeError):
                prev_versions = []
            prev_versions.append({
                "version": version,
                "text": current_text,
            })
            cur.execute(
                """UPDATE proposals SET
                    proposal_text = %s,
                    proposal_version = %s,
                    previous_versions = %s
                WHERE id = %s""",
                (new_text, version + 1, json.dumps(prev_versions), proposal_id)
            )
            return cur.rowcount > 0


def delete_proposal_by_id(proposal_id: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM proposals WHERE id = %s", (proposal_id,))


def get_analytics() -> dict:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT COUNT(*) as total FROM proposals")
            total = cur.fetchone()["total"]

            cur.execute("SELECT COUNT(*) as c FROM proposals WHERE status = 'approved'")
            approved = cur.fetchone()["c"]

            cur.execute("SELECT COUNT(*) as c FROM proposals WHERE status = 'rejected'")
            rejected = cur.fetchone()["c"]

            cur.execute("SELECT COUNT(*) as c FROM proposals WHERE status = 'pending'")
            pending = cur.fetchone()["c"]

            cur.execute("SELECT COUNT(*) as c FROM proposals WHERE job_score >= 80")
            high_match = cur.fetchone()["c"]

            cur.execute(
                "SELECT COUNT(*) as c FROM proposals WHERE job_score >= 60 AND job_score < 80"
            )
            medium_match = cur.fetchone()["c"]

            cur.execute("SELECT COUNT(*) as c FROM proposals WHERE job_score < 60")
            low_match = cur.fetchone()["c"]

            cur.execute("SELECT AVG(win_probability) as avg FROM proposals WHERE recommendation = 'Apply'")
            avg_win = cur.fetchone()["avg"] or 0

            cur.execute(
                "SELECT COUNT(*) as c FROM proposals WHERE opportunity_tier = 'High Value'"
            )
            high_value = cur.fetchone()["c"]

            approval_rate = round((approved / total * 100), 1) if total > 0 else 0

            return {
                "total": total,
                "approved": approved,
                "rejected": rejected,
                "pending": pending,
                "high_match": high_match,
                "medium_match": medium_match,
                "low_match": low_match,
                "avg_win_probability": round(avg_win, 1),
                "high_value_opportunities": high_value,
                "approval_rate": approval_rate,
            }
