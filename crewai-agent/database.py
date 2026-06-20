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
            # Users table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    tier TEXT NOT NULL DEFAULT 'free',
                    is_active BOOLEAN NOT NULL DEFAULT true
                )
            """)
            # Proposals table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS proposals (
                    id TEXT PRIMARY KEY,
                    user_id TEXT REFERENCES users(id),
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
            # Resume generations table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS resume_generations (
                    id TEXT PRIMARY KEY,
                    user_id TEXT REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    input_text TEXT NOT NULL,
                    target_role TEXT,
                    output_text TEXT,
                    ats_score INTEGER DEFAULT 0,
                    improvements TEXT DEFAULT '[]'
                )
            """)
            # Indexes
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_proposals_user_id
                ON proposals(user_id)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_proposals_user_status
                ON proposals(user_id, status)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_resume_user_id
                ON resume_generations(user_id)
            """)
            # Add missing columns for existing deployments
            new_columns = [
                ("user_id", "TEXT REFERENCES users(id)"),
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
                    cur.execute(
                        f"ALTER TABLE proposals ADD COLUMN {col_name} {col_def}"
                    )
                except psycopg2.errors.DuplicateColumn:
                    conn.rollback()


def _parse_json_fields(d: dict) -> dict:
    for field in ["key_skills_highlighted", "red_flags", "previous_versions"]:
        try:
            d[field] = json.loads(d.get(field) or "[]")
        except (json.JSONDecodeError, TypeError):
            d[field] = []
    return d


def insert_proposals(proposals: list):
    with get_conn() as conn:
        with conn.cursor() as cur:
            for p in proposals:
                cur.execute("""
                    INSERT INTO proposals
                    (id, user_id, status, created_at, reviewed_at, keywords,
                     job_title, company, job_url, job_score, proposal_text,
                     timeline, price_range, key_skills_highlighted,
                     recommendation, win_probability, competition_level,
                     skill_match_score, opportunity_tier, reasoning,
                     red_flags, proposal_version, previous_versions)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
                    p["id"], p.get("user_id"), p.get("status", "pending"),
                    p.get("created_at"), p.get("reviewed_at"),
                    p.get("keywords"), p.get("job_title"), p.get("company"),
                    p.get("job_url"), p.get("job_score"), p.get("proposal_text"),
                    p.get("timeline"), p.get("price_range"),
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


def get_proposals(status: str = None, user_id: str = None) -> list:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if user_id and status:
                cur.execute(
                    "SELECT * FROM proposals WHERE user_id = %s AND status = %s ORDER BY created_at DESC",
                    (user_id, status)
                )
            elif user_id:
                cur.execute(
                    "SELECT * FROM proposals WHERE user_id = %s ORDER BY created_at DESC",
                    (user_id,)
                )
            elif status:
                cur.execute(
                    "SELECT * FROM proposals WHERE status = %s ORDER BY created_at DESC",
                    (status,)
                )
            else:
                cur.execute("SELECT * FROM proposals ORDER BY created_at DESC")
            return [_parse_json_fields(dict(r)) for r in cur.fetchall()]


def get_proposal_by_id(proposal_id: str, user_id: str = None):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if user_id:
                cur.execute(
                    "SELECT * FROM proposals WHERE id = %s AND user_id = %s",
                    (proposal_id, user_id)
                )
            else:
                cur.execute(
                    "SELECT * FROM proposals WHERE id = %s", (proposal_id,)
                )
            row = cur.fetchone()
            return _parse_json_fields(dict(row)) if row else None


def update_status(proposal_id: str, status: str, reviewed_at: str,
                  user_id: str = None) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            if user_id:
                cur.execute(
                    "UPDATE proposals SET status = %s, reviewed_at = %s WHERE id = %s AND user_id = %s",
                    (status, reviewed_at, proposal_id, user_id)
                )
            else:
                cur.execute(
                    "UPDATE proposals SET status = %s, reviewed_at = %s WHERE id = %s",
                    (status, reviewed_at, proposal_id)
                )
            return cur.rowcount > 0


def update_proposal_text(proposal_id: str, new_text: str,
                         user_id: str = None) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            query = "SELECT proposal_text, proposal_version, previous_versions FROM proposals WHERE id = %s"
            params = [proposal_id]
            if user_id:
                query += " AND user_id = %s"
                params.append(user_id)
            cur.execute(query, params)
            row = cur.fetchone()
            if not row:
                return False
            current_text, version, prev_raw = row
            try:
                prev_versions = json.loads(prev_raw or "[]")
            except (json.JSONDecodeError, TypeError):
                prev_versions = []
            prev_versions.append({"version": version, "text": current_text})
            update_query = """
                UPDATE proposals SET
                    proposal_text = %s,
                    proposal_version = %s,
                    previous_versions = %s
                WHERE id = %s
            """
            update_params = [new_text, version + 1, json.dumps(prev_versions), proposal_id]
            if user_id:
                update_query += " AND user_id = %s"
                update_params.append(user_id)
            cur.execute(update_query, update_params)
            return cur.rowcount > 0


def delete_proposal_by_id(proposal_id: str, user_id: str = None) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            if user_id:
                cur.execute(
                    "DELETE FROM proposals WHERE id = %s AND user_id = %s",
                    (proposal_id, user_id)
                )
            else:
                cur.execute(
                    "DELETE FROM proposals WHERE id = %s", (proposal_id,)
                )


def get_analytics(user_id: str = None) -> dict:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            uid_filter = "WHERE user_id = %s" if user_id else ""
            params = (user_id,) if user_id else ()

            def count(extra=""):
                cur.execute(
                    f"SELECT COUNT(*) as c FROM proposals {uid_filter} {extra}",
                    params
                )
                return cur.fetchone()["c"]

            total    = count()
            approved = count("AND status = 'approved'" if user_id else "WHERE status = 'approved'")
            rejected = count("AND status = 'rejected'" if user_id else "WHERE status = 'rejected'")
            pending  = count("AND status = 'pending'"  if user_id else "WHERE status = 'pending'")
            high     = count("AND job_score >= 80"     if user_id else "WHERE job_score >= 80")
            medium   = count("AND job_score >= 60 AND job_score < 80" if user_id else "WHERE job_score >= 60 AND job_score < 80")
            low      = count("AND job_score < 60"      if user_id else "WHERE job_score < 60")
            hv       = count("AND opportunity_tier = 'High Value'" if user_id else "WHERE opportunity_tier = 'High Value'")

            win_q = f"SELECT AVG(win_probability) as avg FROM proposals {uid_filter} {'AND' if user_id else 'WHERE'} recommendation = 'Apply'"
            cur.execute(win_q, params)
            avg_win = cur.fetchone()["avg"] or 0

            return {
                "total": total,
                "approved": approved,
                "rejected": rejected,
                "pending": pending,
                "high_match": high,
                "medium_match": medium,
                "low_match": low,
                "avg_win_probability": round(avg_win, 1),
                "high_value_opportunities": hv,
                "approval_rate": round(approved / total * 100, 1) if total > 0 else 0,
            }


def insert_resume_generation(record: dict) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO resume_generations
                (id, user_id, created_at, input_text, target_role,
                 output_text, ats_score, improvements)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                record["id"], record.get("user_id"), record.get("created_at"),
                record.get("input_text"), record.get("target_role"),
                record.get("output_text"), record.get("ats_score", 0),
                json.dumps(record.get("improvements", [])),
            ))


def get_resume_generations(user_id: str) -> list:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM resume_generations WHERE user_id = %s ORDER BY created_at DESC",
                (user_id,)
            )
            result = []
            for r in cur.fetchall():
                d = dict(r)
                try:
                    d["improvements"] = json.loads(d.get("improvements") or "[]")
                except (json.JSONDecodeError, TypeError):
                    d["improvements"] = []
                result.append(d)
            return result


def get_resume_generation_by_id(generation_id: str, user_id: str = None):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if user_id:
                cur.execute(
                    "SELECT * FROM resume_generations WHERE id = %s AND user_id = %s",
                    (generation_id, user_id)
                )
            else:
                cur.execute(
                    "SELECT * FROM resume_generations WHERE id = %s",
                    (generation_id,)
                )
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            try:
                d["improvements"] = json.loads(d.get("improvements") or "[]")
            except (json.JSONDecodeError, TypeError):
                d["improvements"] = []
            return d
