import os
import json
import time
import requests
import feedparser
from typing import Optional, Type
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field
from security.sanitizer import get_secure_logger, sanitize_input

logger = get_secure_logger(__name__)

FREELANCE_RSS_FEEDS = [
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
]

REMOTEOK_API = "https://remoteok.com/api?tags=automation,ai,python"


class JobSearchInput(BaseModel):
    keywords: str = Field(
        default="AI automation freelance",
        description="Keywords to search for in job listings"
    )
    max_results: int = Field(default=15, description="Maximum number of jobs to return")


class JobSearchTool(BaseTool):
    name: str = "freelance_job_search"
    description: str = (
        "Searches multiple freelance and remote job boards for automation and AI jobs. "
        "Returns structured job listings with title, description, URL, and source."
    )
    args_schema: Type[BaseModel] = JobSearchInput

    def _run(self, keywords: str = "AI automation freelance", max_results: int = 15) -> str:
        try:
            safe_keywords = sanitize_input(keywords, max_length=200)
        except ValueError:
            safe_keywords = "AI automation freelance"

        jobs = []
        jobs.extend(self._fetch_rss_jobs(safe_keywords, max_results // 2))
        jobs.extend(self._fetch_remoteok_jobs(safe_keywords, max_results // 2))
        jobs.extend(self._fetch_adzuna_jobs(safe_keywords, max_results // 4))

        if not jobs:
            jobs = self._fallback_mock_jobs(safe_keywords)

        seen = set()
        unique_jobs = []
        for job in jobs:
            key = job.get("title", "") + job.get("company", "")
            if key not in seen:
                seen.add(key)
                unique_jobs.append(job)

        unique_jobs = unique_jobs[:max_results]
        logger.info(f"Job search completed: {len(unique_jobs)} unique jobs found for keywords: {safe_keywords}")
        return json.dumps(unique_jobs, indent=2)

    def _fetch_rss_jobs(self, keywords: str, limit: int) -> list:
        jobs = []
        kw_lower = keywords.lower().split()
        for feed_url in FREELANCE_RSS_FEEDS:
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries[:limit]:
                    title = entry.get("title", "")
                    summary = entry.get("summary", "")
                    combined = (title + " " + summary).lower()
                    if any(k in combined for k in kw_lower) or not kw_lower:
                        jobs.append({
                            "title": title,
                            "company": entry.get("author", "Unknown"),
                            "description": summary[:500],
                            "url": entry.get("link", ""),
                            "source": "WeWorkRemotely",
                            "posted": entry.get("published", ""),
                            "type": "remote",
                        })
            except Exception as e:
                logger.warning(f"RSS feed fetch failed for {feed_url}: {type(e).__name__}")
        return jobs

    def _fetch_remoteok_jobs(self, keywords: str, limit: int) -> list:
        jobs = []
        try:
            headers = {"User-Agent": "Mozilla/5.0 (compatible; JobBot/1.0)"}
            resp = requests.get(REMOTEOK_API, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                kw_lower = keywords.lower().split()
                for item in data[1:limit + 1]:
                    if not isinstance(item, dict):
                        continue
                    title = item.get("position", "")
                    desc = item.get("description", "")
                    combined = (title + " " + desc).lower()
                    if any(k in combined for k in kw_lower) or not kw_lower:
                        jobs.append({
                            "title": title,
                            "company": item.get("company", "Unknown"),
                            "description": desc[:500],
                            "url": item.get("url", ""),
                            "source": "RemoteOK",
                            "posted": item.get("date", ""),
                            "salary": item.get("salary", ""),
                            "type": "remote",
                        })
        except Exception as e:
            logger.warning(f"RemoteOK fetch failed: {type(e).__name__}")
        return jobs

    def _fetch_adzuna_jobs(self, keywords: str, limit: int) -> list:
        app_id = os.getenv("ADZUNA_APP_ID", "")
        app_key = os.getenv("ADZUNA_APP_KEY", "")
        if not app_id or not app_key:
            return []
        jobs = []
        try:
            url = (
                f"https://api.adzuna.com/v1/api/jobs/us/search/1"
                f"?app_id={app_id}&app_key={app_key}"
                f"&results_per_page={limit}&what={requests.utils.quote(keywords)}"
                f"&content-type=application/json"
            )
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("results", []):
                    jobs.append({
                        "title": item.get("title", ""),
                        "company": item.get("company", {}).get("display_name", "Unknown"),
                        "description": item.get("description", "")[:500],
                        "url": item.get("redirect_url", ""),
                        "source": "Adzuna",
                        "salary": f"${item.get('salary_min', 0):.0f} - ${item.get('salary_max', 0):.0f}",
                        "type": "freelance",
                    })
        except Exception as e:
            logger.warning(f"Adzuna fetch failed: {type(e).__name__}")
        return jobs

    def _fallback_mock_jobs(self, keywords: str) -> list:
        logger.info("Using fallback mock jobs (no live APIs returned results)")
        return [
            {
                "title": "AI Automation Developer – Zapier/Make Expert",
                "company": "TechStartup Inc.",
                "description": (
                    "We need an expert in building AI-powered automation workflows using "
                    "Zapier, Make (Integromat), and Python. Must integrate OpenAI/Groq APIs "
                    "to automate lead generation and CRM updates."
                ),
                "url": "https://weworkremotely.com/jobs/sample-1",
                "source": "WeWorkRemotely (mock)",
                "salary": "$50-$80/hr",
                "type": "freelance",
            },
            {
                "title": "Python AI Agent Developer – CrewAI/LangChain",
                "company": "DataFlow Solutions",
                "description": (
                    "Build a multi-agent AI system using CrewAI or LangChain to automate "
                    "market research and report generation. Must have experience with LLM "
                    "APIs and prompt engineering."
                ),
                "url": "https://remoteok.com/jobs/sample-2",
                "source": "RemoteOK (mock)",
                "salary": "$4,000-$8,000/project",
                "type": "project",
            },
            {
                "title": "No-Code AI Automation Specialist",
                "company": "E-commerce Brand",
                "description": (
                    "Automate our customer support using AI chatbots and integrate with "
                    "Shopify, HubSpot, and Slack. No-code tools preferred (n8n, Activepieces). "
                    "Short turnaround required."
                ),
                "url": "https://weworkremotely.com/jobs/sample-3",
                "source": "WeWorkRemotely (mock)",
                "salary": "$1,500-$3,000/project",
                "type": "project",
            },
            {
                "title": "LLM Fine-tuning & RAG Pipeline Engineer",
                "company": "AI Research Lab",
                "description": (
                    "Implement a Retrieval-Augmented Generation pipeline for a legal document "
                    "Q&A system. Must have experience with vector databases (Pinecone/Chroma), "
                    "LangChain, and Python. 3-month contract."
                ),
                "url": "https://remoteok.com/jobs/sample-4",
                "source": "RemoteOK (mock)",
                "salary": "$6,000-$10,000/month",
                "type": "contract",
            },
            {
                "title": "Freelance Data Scraping & Automation Expert",
                "company": "Marketing Agency",
                "description": (
                    "Build automated scrapers and data pipelines to collect competitor pricing, "
                    "social media mentions, and SEO data. Deliver clean JSON/CSV output. "
                    "Python + Playwright or Selenium required."
                ),
                "url": "https://weworkremotely.com/jobs/sample-5",
                "source": "WeWorkRemotely (mock)",
                "salary": "$25-$50/hr",
                "type": "freelance",
            },
        ]


FreelanceJobSearchTool = JobSearchTool
