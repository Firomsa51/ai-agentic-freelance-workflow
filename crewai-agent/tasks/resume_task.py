from crewai import Task


def build_resume_task(agent, input_text: str, target_role: str = "") -> Task:
    role_context = f" for a '{target_role}' role" if target_role else ""
    return Task(
        description=(
            f"Here is the candidate's current resume or background text:\n\n"
            f"--- ORIGINAL TEXT ---\n{input_text}\n--- END ORIGINAL TEXT ---\n\n"
            f"Rewrite and optimize this content{role_context}.\n\n"
            "Instructions:\n"
            "1. Restructure into clear resume sections where applicable (Summary, "
            "Experience, Skills, Education) based on what's present in the original.\n"
            "2. Use strong action verbs and quantify achievements ONLY when numbers "
            "or concrete outcomes are present in the original text.\n"
            "3. Optimize keyword density for ATS systems relevant to the target role.\n"
            "4. Do NOT invent new skills, jobs, companies, or experience not present "
            "in the original input.\n"
            "5. Estimate an ATS compatibility score (0-100) based on structure, "
            "keyword alignment, and clarity.\n"
            "6. List 3-5 specific improvements you made (e.g., 'Added quantified "
            "metrics to bullet 2', 'Restructured into standard ATS sections').\n\n"
            "Return ONLY a single JSON object with this exact structure, no extra text:\n"
            '{\n'
            '  "optimized_text": "...",\n'
            '  "ats_score": 75,\n'
            '  "improvements": ["...", "...", "..."]\n'
            '}'
        ),
        expected_output=(
            "A single JSON object containing: optimized_text (str), "
            "ats_score (int 0-100), improvements (list of strings, 3-5 items)."
        ),
        agent=agent,
    )
