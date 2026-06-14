import os
import uuid
import threading
from datetime import datetime
from pathlib import Path

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify
)
from dotenv import load_dotenv

load_dotenv()

from security.sanitizer import (
    sanitize_input, mask_secrets, get_secure_logger, login_required, validate_auth_token
)
from email_sender import send_proposal_email, is_smtp_configured
from email_sender import validate_email_address
from database import (
    init_db, insert_proposals, get_proposals, get_proposal_by_id,
    update_status, delete_proposal_by_id, update_proposal_text, get_analytics
)

logger = get_secure_logger(__name__)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(32))
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

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
            next_url = request.args.get("next", url_for("index"))
            return redirect(next_url)
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
    pending = [p for p in proposals if p.get("status") == "pending"]
    approved = [p for p in proposals if p.get("status") == "approved"]
    rejected = [p for p in proposals if p.get("status") == "rejected"]
    analytics = get_analytics()
    return render_template(
        "index.html",
        pending=pending,
        approved=approved,
        rejected=rejected,
        crew_status=_crew_status,
        analytics=analytics,
    )


@app.route("/run", methods=["POST"])
@login_required
def run_crew():
    global _crew_status
    if _crew_status["running"]:
        flash("Agents are already running. Please wait for the current run to finish.", "warning")
        return redirect(url_for("index"))

    raw_keywords = request.form.get("keywords", "AI automation freelance Python")
    try:
        keywords = sanitize_input(raw_keywords, max_length=300)
    except ValueError:
        flash("Invalid keywords detected. Please remove special characters.", "error")
        return redirect(url_for("index"))

    def _run_in_background():
        global _crew_status
        _crew_status["running"] = True
        _crew_status["last_error"] = None
        logger.info(f"Background crew run started with keywords: {keywords}")
        try:
            from crew.job_crew import run_job_crew
            result = run_job_crew(keywords)

            if result["success"] and result.get("proposals"):
                new_proposals = []
                for p in result["proposals"]:
                    new_proposals.append({
                        "id": str(uuid.uuid4()),
                        "status": "pending",
                        "created_at": datetime.utcnow().isoformat(),
                        "reviewed_at": None,
                        "keywords": keywords,
                        **p,
                    })
                insert_proposals(new_proposals)
                logger.info(f"Saved {len(new_proposals)} proposals to database.")
            else:
                _crew_status["last_error"] = result.get("error", "Unknown error")
                logger.error(f"Crew run failed: {_crew_status['last_error']}")
        except Exception as e:
            _crew_status["last_error"] = str(e)
            logger.error(f"Background crew run exception: {type(e).__name__}: {e}")
        finally:
            _crew_status["running"] = False
            _crew_status["last_run"] = datetime.utcnow().isoformat()

    thread = threading.Thread(target=_run_in_background, daemon=True)
    thread.start()
    flash("Agents have been dispatched! Refresh this page in 30-60 seconds to see proposals.", "success")
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
        flash("Proposal updated successfully.", "success")
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
        flash(f"Invalid recipient address: {exc}", "error")
        return redirect(url_for("approved_proposals"))

    proposal = get_proposal_by_id(proposal_id)

    if not proposal:
        flash("Proposal not found.", "error")
        return redirect(url_for("approved_proposals"))

    if proposal.get("status") != "approved":
        flash("Only approved proposals can be emailed.", "error")
        return redirect(url_for("approved_proposals"))

    if not is_smtp_configured():
        flash(
            "SMTP is not configured. Set SMTP_SERVER, SMTP_PORT, SENDER_EMAIL, "
            "and SENDER_PASSWORD environment variables to enable email delivery.",
            "error",
        )
        return redirect(url_for("approved_proposals"))

    success, error = send_proposal_email(
        recipient=recipient,
        job_title=proposal.get("job_title", "Untitled"),
        company=proposal.get("company", "Unknown"),
        proposal_text=proposal.get("proposal_text", ""),
    )

    if success:
        logger.info(f"Proposal {proposal_id} emailed successfully.")
        flash(f"Proposal emailed successfully to {recipient}.", "success")
    else:
        logger.error(f"Failed to email proposal {proposal_id}: {error}")
        flash(f"Failed to send email: {error}", "error")

    return redirect(url_for("approved_proposals"))


@app.route("/approved")
@login_required
def approved_proposals():
    proposals = get_proposals(status="approved")
    return render_template(
        "proposals.html",
        proposals=proposals,
        view="approved",
        smtp_configured=is_smtp_configured(),
    )


@app.route("/analytics")
@login_required
def analytics():
    stats = get_analytics()
    return jsonify(stats)


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "crewai-job-agent"}), 200


if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", os.getenv("PORT", 5000)))
    debug = os.getenv("FLASK_ENV", "production") == "development"
    logger.info(f"Starting CrewAI Job Agent dashboard on 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
