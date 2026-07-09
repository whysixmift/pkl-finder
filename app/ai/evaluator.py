import json
import asyncio
import re
from typing import Dict, Any, List, Optional
import httpx
from pydantic import BaseModel, Field
from app.config.settings import settings
from app.utils.logger import logger

class AIResult(BaseModel):
    recommended: bool = Field(default=False)
    score: int = Field(default=0, ge=0, le=100)
    reason: List[str] = Field(default_factory=list)
    matched_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)
    summary: str = Field(default="")

# Candidate Profile Constant
CANDIDATE_PROFILE = """
Candidate Details:
- Education: SMK Negeri 2 Bekasi
- Major: Software Engineering (RPL / Rekayasa Perangkat Lunak)
- Skills: Python, Java, C++, Robotics, Embedded Systems, IoT, Android Studio, Git, PID Tuning, Driver Robot
- Extracurricular/Experience: FIRST Tech Challenge (FTC), Hack Club Mentor, Business Development
- Preferred Locations: Bekasi, Jakarta, Depok, Tangerang, Bogor, Remote
- Preferred Roles: Embedded, IoT, Robotics, Backend, Python, Software Engineer, AI, Machine Learning, Firmware, Computer Vision
- Searching for: PKL (Praktek Kerja Lapangan) or Internship
"""

SYSTEM_PROMPT = f"""
You are an expert AI recruiter matching internship/PKL jobs for Indonesian high school (SMK) / university students.
Your task is to analyze the job posting and evaluate its suitability against the Candidate Profile below:

{CANDIDATE_PROFILE}

Evaluation Criteria:
1. Role Match: Does the job fit the preferred roles (Embedded, IoT, Robotics, Backend Python, Software Engineer, ML, CV)?
2. Location Match: Is it in Bekasi, Jakarta, Depok, Tangerang, Bogor, or Remote?
3. Type Match: Is it explicitly a "PKL", "Internship", "Magang", or suitable for a junior/student? (Reject full-time jobs requiring years of experience).
4. Skill Match: How many of the candidate's skills match?

You MUST return a JSON response with the following exact structure:
{{
  "recommended": true/false (true only if score is >= {settings.SCORE_THRESHOLD} and it is an internship/magang/PKL),
  "score": 0-100 (integer representing match score),
  "reason": ["reason 1", "reason 2"],
  "matched_skills": ["skill 1", "skill 2"],
  "missing_skills": ["skill 3", "skill 4"],
  "summary": "A concise summary of why this job fits or why it doesn't."
}}

Response instructions:
- Output ONLY the JSON block. Do not include any explanation outside the JSON.
- If it is not an internship/magang/PKL (e.g. it is a mid-senior level full-time job), score it below 50 and set recommended to false.
"""

class OpenRouterEvaluator:
    def __init__(self) -> None:
        self.api_key = settings.OPENROUTER_API_KEY
        self.model = settings.OPENROUTER_MODEL
        self.api_url = settings.OPENROUTER_API_URL
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/avrjulian/pkl-finder",
            "X-Title": "PKL Finder Bot",
        }

    async def evaluate_job(
        self, title: str, company: str, location: str, description: str, retries: int = 3
    ) -> AIResult:
        """Evaluate a job against the candidate profile using OpenRouter AI."""
        if not self.api_key or self.api_key.startswith("your_"):
            logger.warning("OpenRouter API key is missing or placeholder. Running fallback local evaluator.")
            return self._fallback_evaluate(title, company, location, description)

        prompt = f"""
        Job Title: {title}
        Company: {company}
        Location: {location}
        Job Description:
        {description[:2500]}
        """

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"}
        }

        backoff = 2.0
        async with httpx.AsyncClient(timeout=30.0) as client:
            for attempt in range(retries):
                try:
                    response = await client.post(self.api_url, headers=self.headers, json=payload)
                    
                    if response.status_code == 429:
                        retry_after = float(response.headers.get("Retry-After", backoff))
                        logger.warning(f"Rate limited (429). Retrying after {retry_after}s. Attempt {attempt + 1}/{retries}")
                        await asyncio.sleep(retry_after)
                        backoff *= 2
                        continue
                        
                    if response.status_code >= 500:
                        logger.warning(f"Server error ({response.status_code}) from OpenRouter. Retrying... Attempt {attempt + 1}/{retries}")
                        await asyncio.sleep(backoff)
                        backoff *= 2
                        continue

                    response.raise_for_status()
                    data = response.json()
                    content = data["choices"][0]["message"]["content"]
                    return self._parse_ai_response(content)

                except httpx.HTTPError as e:
                    logger.error(f"HTTP error on AI evaluation attempt {attempt + 1}/{retries}: {e}")
                    if attempt == retries - 1:
                        return self._fallback_evaluate(title, company, location, description)
                    await asyncio.sleep(backoff)
                    backoff *= 2
                except (KeyError, IndexError, json.JSONDecodeError) as e:
                    logger.error(f"Failed to parse OpenRouter response on attempt {attempt + 1}/{retries}: {e}")
                    if attempt == retries - 1:
                        return self._fallback_evaluate(title, company, location, description)
                    await asyncio.sleep(backoff)
                    backoff *= 2

        return self._fallback_evaluate(title, company, location, description)

    def _parse_ai_response(self, content: str) -> AIResult:
        """Robustly parse JSON response from the LLM."""
        try:
            # Clean markdown code blocks if any
            clean_content = content.strip()
            if clean_content.startswith("```"):
                # Extract content inside code blocks
                match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", clean_content)
                if match:
                    clean_content = match.group(1)
            
            parsed = json.loads(clean_content)
            return AIResult(
                recommended=bool(parsed.get("recommended", False)),
                score=int(parsed.get("score", 0)),
                reason=list(parsed.get("reason", [])),
                matched_skills=list(parsed.get("matched_skills", [])),
                missing_skills=list(parsed.get("missing_skills", [])),
                summary=str(parsed.get("summary", ""))
            )
        except Exception as e:
            logger.error(f"Error parsing AI response content: {e}. Raw content: {content}")
            raise e

    def _fallback_evaluate(self, title: str, company: str, location: str, description: str) -> AIResult:
        """Regex-based rule matcher as a fallback when AI is unavailable or fails."""
        logger.info("Executing regex-based fallback evaluation")
        title_lower = title.lower()
        desc_lower = description.lower()
        loc_lower = location.lower()

        # 1. Check if it is internship
        intern_keywords = ["intern", "magang", "pkl", "praktek kerja", "student", "co-op"]
        is_intern = any(kw in title_lower or kw in desc_lower for kw in intern_keywords)
        
        # Avoid full time or senior
        senior_keywords = ["senior", "lead", "principal", "manager", "years of experience", "5+ years", "3+ years"]
        is_senior = any(kw in title_lower for kw in senior_keywords)

        # 2. Check Role Match
        roles = {
            "Python": ["python", "django", "flask", "fastapi"],
            "Embedded": ["embedded", "microcontroller", "stm32", "arduino", "esp32", "firmware"],
            "IoT": ["iot", "internet of things", "raspberry pi", "sensors"],
            "Robotics": ["robotics", "robot", "ros", "pid tuning", "first tech challenge"],
            "Backend": ["backend", "api", "database", "sql"],
            "Software Engineer": ["software engineer", "software developer", "rpl", "rekayasa perangkat lunak"],
            "AI/ML/CV": ["machine learning", "computer vision", "opencv", "tensorflow", "pytorch", "deep learning"]
        }

        matched_skills = []
        for role, keywords in roles.items():
            if any(kw in title_lower or kw in desc_lower for kw in keywords):
                matched_skills.append(role)

        # 3. Check Location Match
        locations = ["bekasi", "jakarta", "depok", "tangerang", "bogor", "remote", "anywhere"]
        loc_match = any(loc in loc_lower or (loc == "remote" and "remote" in desc_lower) for loc in locations)

        score = 0
        reasons = []

        if is_intern:
            score += 40
            reasons.append("Identified as an internship, magang, or PKL opportunity.")
        else:
            reasons.append("Could not confirm if it is an internship (score penalized).")

        if is_senior:
            score -= 30
            reasons.append("Title suggests a senior/lead role.")

        if matched_skills:
            score += min(len(matched_skills) * 15, 45)
            reasons.append(f"Matched role fields: {', '.join(matched_skills)}.")
        else:
            reasons.append("No preferred role keywords matched.")

        if loc_match:
            score += 15
            reasons.append("Location is within candidate's preferred regions or remote.")
        else:
            reasons.append("Location is outside preferred regions.")

        score = max(0, min(100, score))
        recommended = score >= settings.SCORE_THRESHOLD and is_intern

        missing_skills = []
        if "Python" not in matched_skills:
            missing_skills.append("Python programming match")
        if "Embedded" not in matched_skills and "IoT" not in matched_skills:
            missing_skills.append("Embedded / IoT development match")

        return AIResult(
            recommended=recommended,
            score=score,
            reason=reasons,
            matched_skills=matched_skills,
            missing_skills=missing_skills,
            summary=f"Fallback matched {len(matched_skills)} key areas. Score: {score}."
        )

# Shared evaluator instance
evaluator = OpenRouterEvaluator()
