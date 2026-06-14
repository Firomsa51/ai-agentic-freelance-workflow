from crewai import Task

CORE_SKILLS = [
    "Python", "Flask", "FastAPI", "CrewAI", "AI Agents",
    "Automation", "PostgreSQL", "RAG Systems", "LangChain",
    "REST APIs", "web scraping", "LLM", "Groq"
]


def build_strategist_task(agent, context_tasks: list) -> Task:
    skills_str = ", ".join(CORE_SKILLS)
    return Task(
        description=(
            f"The freelancer's core skills are: {skills_str}.\n\n"
            "Review the scored and ranked job list from the Analyst. "
            "For each of the top jobs, produce a strategic evaluation:\n\n"
            "1. RECOMMENDATION: 'Apply' or 'Skip'\n"
            "2. WIN_PROBABILITY: Integer 0-100 representing estimated chance of winning this job\n"
            "3. COMPETITION_LEVEL: 'Low', 'Medium', or 'High'\n"
            "4. SKILL_MATCH_SCORE: Integer 0-100 based on overlap with the freelancer's core skills above\n"
            "5. OPPORTUNITY_TIER: 'High Value', 'Medium Value', or 'Low Value'\n"
            "6. REASONING: 1-2 sentences explaining the recommendation clearly and specifically\n"
            "7. RED_FLAGS: List any concerns (vague scope, low pay, skill gap). Empty list if none.\n\n"
            "Rules:\n"
            "- Recommend 'Skip' if win probability is below 40% or skill match is below 50\n"
            "- Recommend 'Skip' if the job has more than 2 red flags\n"
            "- Mark as 'High Value' only if score >= 80 AND win probability >= 60\n"
            "- Keep reasoning direct and specific — no filler phrases\n"
            "- Return as a JSON array, one object per job, preserving all original job fields"
        ),
        expected_output=(
            "A JSON array of job objects, each containing all original fields plus: "
            "recommendation (str: 'Apply' or 'Skip'), win_probability (int 0-100), "
            "competition_level (str), skill_match_score (int 0-100), "
            "opportunity_tier (str), reasoning (str), red_flags (list of str)."
        ),
        agent=agent,
        context=context_tasks,
    )
