from crewai import Task


def build_analyst_task(agent, context_tasks: list) -> Task:
    return Task(
        description=(
            "Analyze the job listings found by the Scout Agent and rank them using the scoring matrix below.\n\n"
            "Scoring Matrix (total 100 points):\n"
            "  • Ease of Implementation (25 pts): Well-defined scope? Standard tools? Clear deliverables?\n"
            "  • Hourly/Project Value (25 pts): Rate vs. effort ratio. $50+/hr or $2,000+/project scores high.\n"
            "  • Skill Match (20 pts): Python, AI/LLM APIs, automation, CrewAI, LangChain, REST APIs.\n"
            "  • Client Clarity (15 pts): Specific requirements? Named company? Reasonable timeline?\n"
            "  • Time-to-Completion (15 pts): Can it realistically be completed in under 2 weeks?\n\n"
            "Instructions:\n"
            "1. Score each job on each dimension (0 to max points).\n"
            "2. Sum the scores for a total out of 100.\n"
            "3. Add a one-sentence reasoning for the total score.\n"
            "4. Sort by total score descending.\n"
            "5. Select the TOP 2 jobs only — to conserve processing budget.\n"
            "6. Return as a JSON array sorted by score.\n"
            "7. IMPORTANT: Preserve the exact original job URL and company name — never modify them."
        ),
        expected_output=(
            "A JSON array of the top 2 jobs, each containing all original job fields plus: "
            "score (int 0-100), score_breakdown (object with each dimension and its points), "
            "and reasoning (str explaining the total score). Sorted by score descending."
        ),
        agent=agent,
        context=context_tasks,
    )
