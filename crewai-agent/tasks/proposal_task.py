from crewai import Task


def build_proposal_task(agent, context_tasks: list, user_profile: str = "") -> Task:
    return Task(
        description=(
            "Here is the freelancer's real background, skills, and experience profile. "
            "Use this as the source of truth for any claims about skills, experience, or past results "
            "in the proposals — do not invent skills or experience not supported by this profile:\n\n"
            f"--- FREELANCER PROFILE ---\n{user_profile}\n--- END PROFILE ---\n\n"
            "Write a professional, tailored freelance proposal for each of the top 2 ranked jobs.\n\n"
            "For each proposal:\n"
            "1. HOOK (1-2 sentences): Reference something specific from the job description to show you "
            "   read it carefully. Identify the core problem the client needs solved.\n"
            "2. RELEVANT EXPERIENCE (1-2 sentences): Mention a specific, relevant skill or past result "
            "   from the freelancer's profile above that directly applies.\n"
            "3. TECHNICAL APPROACH (2-3 sentences): Briefly describe HOW you would solve their problem, "
            "   drawing on the tools and frameworks listed in the profile. Name specific tools, "
            "   frameworks, or methods.\n"
            "4. TIMELINE & PRICE (1 sentence): Give a realistic delivery window and price range. "
            "   Be specific — e.g., '5-7 business days, $800-$1,200 depending on scope.'\n"
            "5. CALL TO ACTION (1 sentence): End with a specific next step — schedule a call, share "
            "   a portfolio link, or ask one clarifying question.\n\n"
            "Rules:\n"
            "- Never use: 'I am passionate', 'I would love to', 'I am a fast learner'\n"
            "- Each proposal must be 120-180 words\n"
            "- Write in first person, confident tone, no fluff\n"
            "- Only reference skills/experience that appear in the freelancer's profile above\n"
            "- Return ONLY the top 2 proposals as a single JSON array, no extra text"
        ),
        expected_output=(
            "A JSON array of exactly 2 proposal objects, each containing: "
            "job_title (str), company (str), job_url (str), job_score (int), "
            "proposal_text (str, 120-180 words), timeline (str), price_range (str), "
            "key_skills_highlighted (list of strings)."
        ),
        agent=agent,
        context=context_tasks,
    )
