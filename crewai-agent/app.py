import os
import uuid
import threading
from datetime import datetime
from pathlib import Path

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify, g
)
from dotenv import load_dotenv
from flask_cors import CORS

load_dotenv()

from security.sanitizer import (
    sanitize_input, mask_secrets, get_secure_logger,
    login_required, validate_auth_token
)
from email_sender import send_proposal_email, is_smtp_configured
from email_sender import validate_email_address
from database import (
    init_db, insert_proposals, get_proposals, get_proposal_by_id,
    update_status, delete_proposal_by_id, update_proposal_text, get_analytics,
    insert_resume_generation, get_resume_generations, get_resume_generation_by_id
)
from auth import api_login_required, ensure_user_exists

logger = get_secure_logger(__name__)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(32))
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# ── CORS — only allow Vercel frontend ────────────────────────────────────────
ALLOWED_ORIGINS = [
    o.strip() for o in
    os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]
CORS(app, resources={r"/api/*": {"origins": ALLOWED_ORIGINS}},
     supports_credentials=True)

Path("data").mkdir(exist_ok=True)
init_db()

_crew_status: dict = {"running": False, "last_run": None, "last_error": None}


@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; script-src 'self' 'unsafe-inline';"
    )
    return response


# ═══════════════════════════════════════════════════════════════════════════════
# EXISTING FLASK DASHBOARD ROUTES (unchanged — single user session auth)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("authenticated"):
        return redirect(url_for("index"))
    if request.method == "POST":
        password = request.form.get("password", "")
        try:
            password = sanitize_input(password, max_length=256)
        except ValueError:
            flash("Invalid input detected.", "error")
            return render_template("login.html"), 400
        if validate_auth_token(password):
            session["authenticated"] = True
            session.permanent = False
            logger.info("Successful dashboard login.")
            return redirect(request.args.get("next", url_for("index")))
        else:
            logger.warning("Failed login attempt.")
            flash("Incorrect password. Please try again.", "error")
            return render_template("login.html"), 401
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    proposals = get_proposals()
    pending  = [p for p in proposals if p.get("status") == "pending"]
    approved = [p for p in proposals if p.get("status") == "approved"]
    rejected = [p for p in proposals if p.get("status") == "rejected"]
    analytics = get_analytics()
    return render_template(
        "index.html",
        pending=pending, approved=approved, rejected=rejected,
        crew_status=_crew_status, analytics=analytics,
    )


@app.route("/run", methods=["POST"])
@login_required
def run_crew():
    global _crew_status
    if _crew_status["running"]:
        flash("Agents are already running.", "warning")
        return redirect(url_for("index"))
    raw_keywords = request.form.get("keywords", "AI automation freelance Python")
    try:
        keywords = sanitize_input(raw_keywords, max_length=300)
    except ValueError:
        flash("Invalid keywords detected.", "error")
        return redirect(url_for("index"))
    _start_crew_thread(keywords, user_id=None)
    flash("Agents dispatched! Refresh in 30-60 seconds.", "success")
    return redirect(url_for("index"))


@app.route("/status")
@login_required
def crew_status():
    return jsonify({
        "running": _crew_status["running"],
        "last_run": _crew_status["last_run"],
        "last_error": mask_secrets(_crew_status["last_error"] or ""),
        "pending_count": len(get_proposals(status="pending")),
    })


@app.route("/proposal/<proposal_id>/approve", methods=["POST"])
@login_required
def approve_proposal(proposal_id: str):
    try:
        proposal_id = sanitize_input(proposal_id, max_length=64)
    except ValueError:
        return jsonify({"error": "Invalid proposal ID"}), 400
    if update_status(proposal_id, "approved", datetime.utcnow().isoformat()):
        flash("Proposal approved!", "success")
    else:
        flash("Proposal not found.", "error")
    return redirect(url_for("index"))


@app.route("/proposal/<proposal_id>/reject", methods=["POST"])
@login_required
def reject_proposal(proposal_id: str):
    try:
        proposal_id = sanitize_input(proposal_id, max_length=64)
    except ValueError:
        return jsonify({"error": "Invalid proposal ID"}), 400
    if update_status(proposal_id, "rejected", datetime.utcnow().isoformat()):
        flash("Proposal rejected.", "info")
    else:
        flash("Proposal not found.", "error")
    return redirect(url_for("index"))


@app.route("/proposal/<proposal_id>/delete", methods=["POST"])
@login_required
def delete_proposal(proposal_id: str):
    try:
        proposal_id = sanitize_input(proposal_id, max_length=64)
    except ValueError:
        return jsonify({"error": "Invalid proposal ID"}), 400
    delete_proposal_by_id(proposal_id)
    flash("Proposal deleted.", "info")
    return redirect(url_for("index"))


@app.route("/proposal/<proposal_id>/edit", methods=["POST"])
@login_required
def edit_proposal(proposal_id: str):
    try:
        proposal_id = sanitize_input(proposal_id, max_length=64)
    except ValueError:
        return jsonify({"error": "Invalid proposal ID"}), 400
    new_text = request.form.get("proposal_text", "").strip()
    if not new_text:
        flash("Proposal text cannot be empty.", "error")
        return redirect(url_for("index"))
    if update_proposal_text(proposal_id, new_text):
        flash("Proposal updated.", "success")
    else:
        flash("Proposal not found.", "error")
    return redirect(url_for("index"))


@app.route("/proposal/<proposal_id>/email", methods=["POST"])
@login_required
def email_proposal(proposal_id: str):
    try:
        proposal_id = sanitize_input(proposal_id, max_length=64)
    except ValueError:
        flash("Invalid proposal ID.", "error")
        return redirect(url_for("approved_proposals"))
    raw_recipient = request.form.get("recipient", "").strip()
    try:
        recipient = validate_email_address(raw_recipient)
    except ValueError as exc:
        flash(f"Invalid recipient: {exc}", "error")
        return redirect(url_for("approved_proposals"))
    proposal = get_proposal_by_id(proposal_id)
    if not proposal:
        flash("Proposal not found.", "error")
        return redirect(url_for("approved_proposals"))
    if proposal.get("status") != "approved":
        flash("Only approved proposals can be emailed.", "error")
        return redirect(url_for("approved_proposals"))
    if not is_smtp_configured():
        flash("SMTP not configured.", "error")
        return redirect(url_for("approved_proposals"))
    success, error = send_proposal_email(
        recipient=recipient,
        job_title=proposal.get("job_title", "Untitled"),
        company=proposal.get("company", "Unknown"),
        proposal_text=proposal.get("proposal_text", ""),
    )
    if success:
        flash(f"Emailed to {recipient}.", "success")
    else:
        flash(f"Email failed: {error}", "error")
    return redirect(url_for("approved_proposals"))


@app.route("/approved")
@login_required
def approved_proposals():
    proposals = get_proposals(status="approved")
    return render_template(
        "proposals.html", proposals=proposals,
        view="approved", smtp_configured=is_smtp_configured(),
    )


@app.route("/analytics")
@login_required
def analytics():
    return jsonify(get_analytics())


# ═══════════════════════════════════════════════════════════════════════════════
# NEW JSON API ROUTES — for Next.js frontend (Clerk JWT auth)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/v1/me", methods=["GET"])
@api_login_required
def api_me():
    """Return current user info."""
    ensure_user_exists(g.user_id, g.user_email)
    return jsonify({
        "user_id": g.user_id,
        "email": g.user_email,
        "tier": "free",
    })


@app.route("/api/v1/proposals", methods=["GET"])
@api_login_required
def api_get_proposals():
    """Get all proposals for the authenticated user."""
    ensure_user_exists(g.user_id, g.user_email)
    status_filter = request.args.get("status")
    proposals = get_proposals(status=status_filter, user_id=g.user_id)
    return jsonify({"proposals": proposals, "total": len(proposals)})


@app.route("/api/v1/proposals/<proposal_id>", methods=["GET"])
@api_login_required
def api_get_proposal(proposal_id: str):
    """Get a single proposal by ID for the authenticated user."""
    proposal = get_proposal_by_id(proposal_id, user_id=g.user_id)
    if not proposal:
        return jsonify({"error": "Proposal not found"}), 404
    return jsonify(proposal)


@app.route("/api/v1/proposals/<proposal_id>/approve", methods=["POST"])
@api_login_required
def api_approve_proposal(proposal_id: str):
    if update_status(proposal_id, "approved",
                     datetime.utcnow().isoformat(), user_id=g.user_id):
        return jsonify({"success": True, "status": "approved"})
    return jsonify({"error": "Proposal not found"}), 404


@app.route("/api/v1/proposals/<proposal_id>/reject", methods=["POST"])
@api_login_required
def api_reject_proposal(proposal_id: str):
    if update_status(proposal_id, "rejected",
                     datetime.utcnow().isoformat(), user_id=g.user_id):
        return jsonify({"success": True, "status": "rejected"})
    return jsonify({"error": "Proposal not found"}), 404


@app.route("/api/v1/proposals/<proposal_id>", methods=["DELETE"])
@api_login_required
def api_delete_proposal(proposal_id: str):
    delete_proposal_by_id(proposal_id, user_id=g.user_id)
    return jsonify({"success": True})


@app.route("/api/v1/proposals/<proposal_id>/edit", methods=["PATCH"])
@api_login_required
def api_edit_proposal(proposal_id: str):
    data = request.get_json(silent=True) or {}
    new_text = data.get("proposal_text", "").strip()
    if not new_text:
        return jsonify({"error": "proposal_text required"}), 400
    if update_proposal_text(proposal_id, new_text, user_id=g.user_id):
        return jsonify({"success": True})
    return jsonify({"error": "Proposal not found"}), 404


@app.route("/api/v1/run", methods=["POST"])
@api_login_required
def api_run_crew():
    """Trigger agent run for the authenticated user."""
    global _crew_status
    ensure_user_exists(g.user_id, g.user_email)
    if _crew_status["running"]:
        return jsonify({
            "error": "Agents already running",
            "running": True
        }), 409
    data = request.get_json(silent=True) or {}
    raw_keywords = data.get("keywords", "AI automation freelance Python")
    try:
        keywords = sanitize_input(str(raw_keywords), max_length=300)
    except ValueError:
        return jsonify({"error": "Invalid keywords"}), 400
    _start_crew_thread(keywords, user_id=g.user_id)
    return jsonify({
        "success": True,
        "message": "Agents dispatched",
        "keywords": keywords,
    })


@app.route("/api/v1/status", methods=["GET"])
@api_login_required
def api_crew_status():
    return jsonify({
        "running": _crew_status["running"],
        "last_run": _crew_status["last_run"],
        "last_error": mask_secrets(_crew_status["last_error"] or ""),
        "pending_count": len(get_proposals(
            status="pending", user_id=g.user_id
        )),
    })


@app.route("/api/v1/analytics", methods=["GET"])
@api_login_required
def api_analytics():
    return jsonify(get_analytics(user_id=g.user_id))


# ═══════════════════════════════════════════════════════════════════════════════
# RESUME AGENT API ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/v1/resume/generate", methods=["POST"])
@api_login_required
def api_generate_resume():
    """Generate an optimized resume for the authenticated user."""
    ensure_user_exists(g.user_id, g.user_email)
    data = request.get_json(silent=True) or {}
    raw_input_text = data.get("input_text", "")
    raw_target_role = data.get("target_role", "")

    try:
        input_text = sanitize_input(str(raw_input_text), max_length=1500)
    except ValueError:
        return jsonify({"error": "Invalid input_text — remove special characters or shorten it."}), 400

    if not input_text.strip():
        return jsonify({"error": "input_text is required"}), 400

    try:
        target_role = sanitize_input(str(raw_target_role), max_length=120)
    except ValueError:
        target_role = ""

    from crew.resume_crew import run_resume_crew
    result = run_resume_crew(input_text, target_role)

    if not result.get("success"):
        return jsonify({"error": result.get("error", "Resume generation failed")}), 500

    record_id = str(uuid.uuid4())
    record = {
        "id": record_id,
        "user_id": g.user_id,
        "created_at": datetime.utcnow().isoformat(),
        "input_text": input_text,
        "target_role": target_role,
        "output_text": result.get("optimized_text", ""),
        "ats_score": result.get("ats_score", 0),
        "improvements": result.get("improvements", []),
    }
    insert_resume_generation(record)
    logger.info(f"Resume generated — user:{g.user_id} id:{record_id}")

    return jsonify({
        "id": record_id,
        "optimized_text": result.get("optimized_text", ""),
        "ats_score": result.get("ats_score", 0),
        "improvements": result.get("improvements", []),
    })


@app.route("/api/v1/resume/history", methods=["GET"])
@api_login_required
def api_resume_history():
    """List past resume generations for the authenticated user."""
    generations = get_resume_generations(g.user_id)
    return jsonify({"generations": generations, "total": len(generations)})


@app.route("/api/v1/resume/<generation_id>", methods=["GET"])
@api_login_required
def api_get_resume_generation(generation_id: str):
    """Fetch a single resume generation by ID for the authenticated user."""
    generation = get_resume_generation_by_id(generation_id, user_id=g.user_id)
    if not generation:
        return jsonify({"error": "Resume generation not found"}), 404
    return jsonify(generation)


# ═══════════════════════════════════════════════════════════════════════════════
# SHARED HELPER
# ═══════════════════════════════════════════════════════════════════════════════

def _start_crew_thread(keywords: str, user_id: str | None):
    """Start a background crew run, scoped to user_id if provided."""
    global _crew_status

    def _run():
        global _crew_status
        _crew_status["running"] = True
        _crew_status["last_error"] = None
        logger.info(f"Crew run started — user:{user_id} keywords:{keywords}")
        try:
            from crew.job_crew import run_job_crew
            result = run_job_crew(keywords)
            if result["success"] and result.get("proposals"):
                new_proposals = []
                for p in result["proposals"]:
                    new_proposals.append({
                        "id": str(uuid.uuid4()),
                        "user_id": user_id,
                        "status": "pending",
                        "created_at": datetime.utcnow().isoformat(),
                        "reviewed_at": None,
                        "keywords": keywords,
                        **p,
                    })
                insert_proposals(new_proposals)
                logger.info(f"Saved {len(new_proposals)} proposals — user:{user_id}")
            else:
                _crew_status["last_error"] = result.get("error", "Unknown error")
                logger.error(f"Crew failed: {_crew_status['last_error']}")
        except Exception as e:
            _crew_status["last_error"] = str(e)
            logger.error(f"Crew exception: {type(e).__name__}: {e}")
        finally:
            _crew_status["running"] = False
            _crew_status["last_run"] = datetime.utcnow().isoformat()

    threading.Thread(target=_run, daemon=True).start()


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "crewai-job-agent"}), 200


if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", os.getenv("PORT", 5000)))
    debug = os.getenv("FLASK_ENV", "production") == "development"
    logger.info(f"Starting on 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
