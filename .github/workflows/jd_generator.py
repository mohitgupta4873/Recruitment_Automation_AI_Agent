"""
jd_generator.py
Generates an inclusive, early-career-friendly Job Description for a given role.

In production:
- optionally calls an LLM (e.g. Gemini / GPT) with an API key stored in secrets
- caches the approved JD to job_description.md
"""

from textwrap import dedent

def generate_jd(role_prompt: str, llm_fn=None) -> str:
    """
    role_prompt: e.g. "Backend Engineer (0–2 years)"
    llm_fn: optional callable(prompt:str)->str for JD drafting

    Returns a markdown JD string.
    """
    base_prompt = f"""
    Draft an inclusive, crisp Job Description for: {role_prompt}.
    Include: About the role, Responsibilities, Must-haves, Nice-to-haves,
    What we offer, How to apply.
    Target early-career (0–2 yrs). ~350–450 words. Use short bullets.
    """

    if llm_fn:
        # external LLM call (not committed in codebase with keys)
        jd = llm_fn(base_prompt.strip())
        if jd:
            return jd.strip()

    # fallback JD template (no external API)
    jd_fallback = f"""
    # {role_prompt}

    ## About the role
    We’re looking for an early-career engineer who wants to build real products,
    ship to users fast, and learn modern backend practices.

    ## Responsibilities
    - Build and maintain backend services / APIs
    - Write clean, testable code and basic docs
    - Debug production issues with teammates
    - Collaborate with product & frontend

    ## Must-haves
    - Comfort with at least one server-side language
      (Python / Node / Go / Java etc.)
    - SQL and data-structures fundamentals
    - Understanding of HTTP / REST / Git basics
    - Clear communication and accountability

    ## Nice-to-haves
    - Docker / container basics
    - Cloud exposure (AWS/GCP/Azure)
    - Basic testing (unit/integration)

    ## What we offer
    - Mentorship from experienced engineers
    - Real ownership early in your career
    - Supportive, fast-paced learning environment

    ## How to apply
    Fill the application form (Google Form) and share your resume link (PDF).
    """
    return dedent(jd_fallback).strip()
