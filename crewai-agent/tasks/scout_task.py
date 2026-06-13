from crewai import Task


def build_scout_task(agent, keywords: str = "AI automation freelance Python") -> Task:
    return Task(
        description=(
            f"Search for freelance and remote job opportunities using these keywords: '{keywords}'.\n\n"
            "Requirements:\n"
            "1. Use the freelance_job_search tool to find at least 4 relevant jobs.\n"
            "2. For each job, extract: title, company, description, URL, source, salary (if available), "
            "and job type (freelance/contract/project).\n"
            "3. Focus on jobs involving: AI automation, Python scripting, LLM/AI APIs, workflow automation, "
            "no-code tools (Zapier/Make/n8n), data scraping, or RAG/chatbot development.\n"
            "4. Remove any duplicates or jobs that are clearly not tech/automation related.\n"
            "5. Keep descriptions brief (1-2 sentences max) to conserve tokens.\n"
            "6. Return the results as a clean JSON array."
        ),
        expected_output=(
            "A JSON array of job objects, each containing: title, company, description (brief), "
            "url, source, salary, type. Minimum 4 jobs, maximum 8."
        ),
        agent=agent,
    )
