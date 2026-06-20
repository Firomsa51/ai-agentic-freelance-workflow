import os
import json
import re
from crewai import Crew, Process
from agents.resume_agent import build_resume_agent
from tasks.resume_task import build_resume_task
from security.sanitizer import get_secure_logger

logger = get_secure_logger(__name__)


def _build_llm():
    """Lightweight LLM builder for resume tasks — mirrors job_crew.py settings."""
    provider = os.getenv("LLM_PROVIDER", "groq").lower()
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            raise EnvironmentError("GEMINI_API_KEY is not set.")
        return ChatGoogleGenerativeAI(
            model="gemini-1.5-flash",
            google_api_key=api_key,
            temperature=0.3,
        )
    else:
        from langchain_groq import ChatGroq
        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key:
            raise EnvironmentError("GROQ_API_KEY is not set.")
        return ChatGroq(
            model="llama-3.1-8b-instant",
            api_key=api_key,
            temperature=0.3,
            max_tokens=1500,
            max_retries=3,
        )


def _extract_json_object(text: str) -> dict:
    text = text.strip()
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def run_resume_crew(input_text: str, target_role: str = "") -> dict:
    logger.info(f"Starting resume crew — target_role: {target_role}")
    try:
        llm = _build_llm()
    except EnvironmentError as e:
        logger.error(f"LLM setup failed: {e}")
        return {"success": False, "error": str(e)}

    agent = build_resume_agent(llm)
    task = build_resume_task(agent, input_text, target_role)

    crew = Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=True,
    )

    try:
        result = crew.kickoff()
        raw_output = str(result)
        logger.info("Resume crew execution completed.")
        parsed = _extract_json_object(raw_output)

        if not parsed or "optimized_text" not in parsed:
            return {
                "success": True,
                "optimized_text": raw_output[:3000],
                "ats_score": 0,
                "improvements": [],
                "raw": True,
            }

        return {
            "success": True,
            "optimized_text": parsed.get("optimized_text", ""),
            "ats_score": parsed.get("ats_score", 0),
            "improvements": parsed.get("improvements", []),
        }
    except Exception as e:
        logger.error(f"Resume crew execution failed: {type(e).__name__}: {e}")
        return {"success": False, "error": str(e)}
