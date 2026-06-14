import os
import json
import re
from crewai import Crew, Process
from agents import (
    build_scout_agent, build_analyst_agent,
    build_proposal_writer_agent, build_strategist_agent
)
from tasks import (
    build_scout_task, build_analyst_task,
    build_strategist_task, build_proposal_task
)
from security.sanitizer import get_secure_logger

logger = get_secure_logger(__name__)

PROFILE_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "my_profile.txt")


def load_user_profile() -> str:
    try:
        with open(PROFILE_PATH, "r", encoding="utf-8") as f:
            content = f.read().strip()
            return content if content else "No profile information provided."
    except (FileNotFoundError, OSError) as e:
        logger.warning(f"Profile file not found or unreadable: {e}")
        return "No profile information provided."


def build_llm():
    provider = os.getenv("LLM_PROVIDER", "groq").lower()
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            raise EnvironmentError("GEMINI_API_KEY is not set.")
        logger.info("Using LLM provider: Gemini (gemini-1.5-flash)")
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
        logger.info("Using LLM provider: Groq (llama-3.1-8b-instant)")
        return ChatGroq(
            model="llama-3.1-8b-instant",
            api_key=api_key,
            temperature=0.3,
            max_tokens=2000,
            max_retries=3,
        )


def _extract_json_array(text: str) -> list:
    text = text.strip()
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return []


def run_job_crew(keywords: str = "AI automation freelance Python") -> dict:
    logger.info(f"Starting job crew with keywords: {keywords}")
    try:
        llm = build_llm()
    except EnvironmentError as e:
        logger.error(f"LLM setup failed: {e}")
        return {"success": False, "error": str(e), "proposals": []}

    user_profile = load_user_profile()

    # Build agents
    scout = build_scout_agent(llm)
    analyst = build_analyst_agent(llm)
    strategist = build_strategist_agent(llm)
    writer = build_proposal_writer_agent(llm)

    # Build tasks — sequential pipeline
    scout_task = build_scout_task(scout, keywords)
    analyst_task = build_analyst_task(analyst, context_tasks=[scout_task])
    strategist_task = build_strategist_task(strategist, context_tasks=[scout_task, analyst_task])
    proposal_task = build_proposal_task(
        writer,
        context_tasks=[scout_task, analyst_task, strategist_task],
        user_profile=user_profile,
    )

    crew = Crew(
        agents=[scout, analyst, strategist, writer],
        tasks=[scout_task, analyst_task, strategist_task, proposal_task],
        process=Process.sequential,
        verbose=True,
    )

    try:
        result = crew.kickoff()
        raw_output = str(result)
        logger.info("Crew execution completed successfully.")
        proposals = _extract_json_array(raw_output)

        # Enrich proposals with strategist fields if present
        if proposals:
            for p in proposals:
                p.setdefault("recommendation", "Apply")
                p.setdefault("win_probability", 0)
                p.setdefault("competition_level", "Unknown")
                p.setdefault("skill_match_score", 0)
                p.setdefault("opportunity_tier", "Unknown")
                p.setdefault("reasoning", "")
                p.setdefault("red_flags", [])

        if not proposals:
            proposals = [
                {
                    "job_title": "Crew Run Complete",
                    "company": "N/A",
                    "job_url": "#",
                    "job_score": 0,
                    "proposal_text": raw_output[:2000],
                    "timeline": "N/A",
                    "price_range": "N/A",
                    "key_skills_highlighted": [],
                    "recommendation": "N/A",
                    "win_probability": 0,
                    "competition_level": "N/A",
                    "skill_match_score": 0,
                    "opportunity_tier": "N/A",
                    "reasoning": "",
                    "red_flags": [],
                    "raw": True,
                }
            ]
        return {"success": True, "proposals": proposals, "raw_output": raw_output}
    except Exception as e:
        logger.error(f"Crew execution failed: {type(e).__name__}: {e}")
        return {"success": False, "error": str(e), "proposals": []}
