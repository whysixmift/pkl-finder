import json
import asyncio
import time
import re
from typing import Optional, List, Tuple, Dict, Any
import httpx
from app.config.settings import settings
from app.ai.base_provider import BaseLLMProvider, AIResult
from app.utils.logger import logger

# Base System Prompt
SYSTEM_PROMPT = """
You are an expert AI recruiter matching internship/PKL jobs for Indonesian high school (SMK) / university students.
Your task is to analyze the job posting and evaluate its suitability against the Candidate Profile below:

Candidate Details:
{cv_text}

Evaluation Criteria:
1. Role Match: Does the job fit the preferred roles?
2. Location Match: Is it in the candidate's preferred location or Remote?
3. Type Match: Is it explicitly a "PKL", "Internship", "Magang", or suitable for a student?
4. Skill Match: How many of the candidate's skills match?

You MUST return a JSON response with the following exact structure:
{{
  "recommended": true/false,
  "score": 0-100 (integer representing match score),
  "reason": ["reason 1", "reason 2"],
  "matched_skills": ["skill 1", "skill 2"],
  "missing_skills": ["skill 3", "skill 4"],
  "summary": "A concise summary of why this job fits or why it doesn't.",
  "company_category": "Embedded Systems" or "Software House" or "Robotics" or "IoT" or "General Tech",
  "work_mode": "Remote" or "Hybrid" or "On-site",
  "priority": "low" or "medium" or "high"
}}

Response instructions:
- Output ONLY the JSON block. Do not include any explanation outside the JSON.
- If it is not an internship/magang/PKL (e.g. it is a mid-senior level full-time job), score it below 50 and set recommended to false.
"""


class OpenRouterProvider(BaseLLMProvider):
    def __init__(self) -> None:
        self.api_key = settings.OPENROUTER_API_KEY
        self.api_url = settings.OPENROUTER_API_URL
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/whysixmift/pkl-finder",
            "X-Title": "PKL Finder Bot",
        }

    def _get_models_queue(self) -> List[str]:
        """Compile a list of models: Primary followed by Fallbacks."""
        models = [settings.PRIMARY_MODEL]
        for m in settings.fallback_models_list:
            if m and m not in models:
                models.append(m)
        return models

    def _parse_http_error(self, status_code: int, text: str) -> str:
        """Categorize OpenRouter API failure responses (insufficient credits, rate limits, etc.)."""
        try:
            parsed = json.loads(text)
            if "error" in parsed and "message" in parsed["error"]:
                return f"{parsed['error']['message']} (HTTP {status_code})"
        except Exception:
            pass

        if status_code == 401:
            return "Authentication failed (Invalid API Key)."
        elif status_code == 402:
            return "Insufficient account credits on OpenRouter."
        elif status_code == 403:
            return "Access forbidden. Check your API permissions or IP restrictions."
        elif status_code == 404:
            return "Model identifier not found or endpoint invalid."
        elif status_code == 408:
            return "Request timeout. The server took too long to respond."
        elif status_code == 429:
            return "Rate limit exceeded (Too many requests)."
        elif status_code == 500:
            return "Internal server error. OpenRouter encountered an issue."
        elif status_code in [502, 503, 504]:
            return "Upstream AI provider is currently offline or unreachable."
        return f"HTTP {status_code} - {text}"

    async def verify_connectivity(self) -> Tuple[bool, str, int]:
        """Perform api key check, latency checks, and test connection."""
        if not self.api_key or self.api_key.startswith("your_") or self.api_key == "mock_key":
            return False, "OpenRouter API Key is missing or placeholder.", 0

        payload = {
            "model": settings.PRIMARY_MODEL,
            "messages": [{"role": "user", "content": "Ping"}],
            "max_tokens": 5
        }

        start_time = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.api_url, headers=self.headers, json=payload)
                latency = int((time.perf_counter() - start_time) * 1000)

                if response.status_code == 200:
                    return True, "OpenRouter connected successfully.", latency
                
                err_msg = self._parse_http_error(response.status_code, response.text)
                return False, err_msg, latency
        except Exception as e:
            latency = int((time.perf_counter() - start_time) * 1000)
            return False, f"Network connection failed: {str(e)}", latency

    async def _post_with_fallback(self, payload_factory) -> Dict[str, Any]:
        """Sends API requests with automatic fallback failover to alternate models if primary fails."""
        models = self._get_models_queue()
        last_error = "No models configured"

        for model in models:
            payload = payload_factory(model)
            backoff = 2.0
            retries = 3

            logger.info(f"Invoking LLM model request: {model}")
            async with httpx.AsyncClient(timeout=35.0) as client:
                for attempt in range(retries):
                    try:
                        response = await client.post(self.api_url, headers=self.headers, json=payload)
                        
                        # Handle permanent HTTP blockages by immediately falling back to next model
                        if response.status_code in [401, 402, 403, 404]:
                            err = self._parse_http_error(response.status_code, response.text)
                            logger.warning(f"Model {model} failed with permanent error: {err}. Trying fallback...")
                            last_error = err
                            break # Break retry loop to try next model

                        # Handle rate limits
                        if response.status_code == 429:
                            retry_after = float(response.headers.get("Retry-After", backoff))
                            logger.warning(f"Rate limited (429) for model {model}. Retrying in {retry_after}s.")
                            await asyncio.sleep(retry_after)
                            backoff *= 2
                            continue

                        # Handle temporary server errors and timeouts
                        if response.status_code == 408 or response.status_code >= 500:
                            logger.warning(f"Temporary error ({response.status_code}) on {model}. Retrying in {backoff}s.")
                            await asyncio.sleep(backoff)
                            backoff *= 2
                            continue

                        response.raise_for_status()
                        return response.json()

                    except Exception as e:
                        logger.error(f"Error on model {model} attempt {attempt+1}: {e}")
                        last_error = str(e)
                        if attempt == retries - 1:
                            break # Fallback to next model
                        await asyncio.sleep(backoff)
                        backoff *= 2

        raise RuntimeError(f"All LLM models failed. Last error: {last_error}")

    async def evaluate_job(
        self, title: str, company: str, location: str, description: str, cv_text: Optional[str] = None
    ) -> AIResult:
        """Matches a job advertisement with candidate profile, falling back to regex matches if all LLM models fail."""
        cv_profile = cv_text or "SMK Negeri 2 Bekasi Software Engineering. Python, C++, Embedded Systems, IoT, Robotics."
        sys_prompt = SYSTEM_PROMPT.format(cv_text=cv_profile)

        prompt = f"""
        Job Title: {title}
        Company: {company}
        Location: {location}
        Job Description:
        {description[:2500]}
        """

        def payload_factory(model_id: str) -> Dict[str, Any]:
            return {
                "model": model_id,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": prompt}
                ],
                "response_format": {"type": "json_object"}
            }

        try:
            data = await self._post_with_fallback(payload_factory)
            content = data["choices"][0]["message"]["content"]
            return self._parse_ai_response(content)
        except Exception as e:
            logger.error(f"LLM evaluation failed, executing local regex fallback: {e}")
            return self._fallback_evaluate(title, company, location, description)

    async def write_cold_email(self, company_name: str, cv_text: str) -> Tuple[str, str]:
        """Generates cold application emails seeking internships, matching candidate profile parameters."""
        system_prompt = """
        You are a professional email copywriter writing unique cold emails for internship applications.
        Write a concise, professional, and convincing cold email to the recruitment team requesting a PKL / internship.
        Do NOT use generic templates. Write the actual company name and candidate details.
        
        The candidate is:
        Name: Julian
        School: SMK Negeri 2 Bekasi (Rekayasa Perangkat Lunak / Software Engineering)
        Skills: Python, Java, C++, Robotics, Embedded Systems, IoT, Git.
        Experience: FIRST Tech Challenge, Hack Club Mentor.
        Looking for: PKL (Praktek Kerja Lapangan) or Internship.
        
        You must output ONLY a JSON object with:
        {
          "subject": "Unique, catchy subject line",
          "body": "Complete email body"
        }
        """

        def payload_factory(model_id: str) -> Dict[str, Any]:
            return {
                "model": model_id,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Write an internship application email to: {company_name}"}
                ],
                "response_format": {"type": "json_object"}
            }

        data = await self._post_with_fallback(payload_factory)
        content = data["choices"][0]["message"]["content"].strip()
        
        if content.startswith("```"):
            match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", content)
            if match:
                content = match.group(1)

        parsed = json.loads(content)
        return parsed["subject"], parsed["body"]

    def _parse_ai_response(self, content: str) -> AIResult:
        """Ensure the LLM response adheres to the strict Pydantic output schema."""
        try:
            clean_content = content.strip()
            if clean_content.startswith("```"):
                match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", clean_content)
                if match:
                    clean_content = match.group(1)
            
            parsed = json.loads(clean_content)
            
            recommended = bool(parsed.get("recommended", False))
            score = parsed.get("score", 0)
            try:
                score = int(score)
            except (ValueError, TypeError):
                score = 0
            score = max(0, min(100, score))
            
            reason = parsed.get("reason", [])
            if not isinstance(reason, list):
                reason = [str(reason)] if reason else []
                
            matched_skills = parsed.get("matched_skills", [])
            if not isinstance(matched_skills, list):
                matched_skills = [str(matched_skills)] if matched_skills else []
                
            missing_skills = parsed.get("missing_skills", [])
            if not isinstance(missing_skills, list):
                missing_skills = [str(missing_skills)] if missing_skills else []
                
            summary = str(parsed.get("summary", ""))
            company_category = str(parsed.get("company_category", "Technology"))
            work_mode = str(parsed.get("work_mode", "On-site"))
            priority = str(parsed.get("priority", "medium")).lower()
            if priority not in ["low", "medium", "high"]:
                priority = "medium"

            return AIResult(
                recommended=recommended,
                score=score,
                reason=reason,
                matched_skills=matched_skills,
                missing_skills=missing_skills,
                summary=summary,
                company_category=company_category,
                work_mode=work_mode,
                priority=priority
            )
        except Exception as e:
            logger.error(f"Schema validation failed on AI output: {e}. Raw: {content}")
            raise e

    def _fallback_evaluate(self, title: str, company: str, location: str, description: str) -> AIResult:
        """Local regex fallback rules matcher."""
        logger.info("Executing local regex fallback matching")
        title_lower = title.lower()
        desc_lower = description.lower()
        loc_lower = location.lower()

        is_intern = any(kw in title_lower or kw in desc_lower for kw in ["intern", "magang", "pkl", "praktek kerja", "student"])
        is_senior = any(kw in title_lower for kw in ["senior", "lead", "principal", "manager"])

        roles = {
            "Python": ["python", "django", "flask", "fastapi"],
            "Embedded": ["embedded", "microcontroller", "stm32", "arduino", "esp32", "firmware"],
            "Robotics": ["robotics", "robot", "ros", "pid tuning"],
            "Backend": ["backend", "api", "database", "sql"]
        }

        matched_skills = [role for role, keywords in roles.items() if any(kw in title_lower or kw in desc_lower for kw in keywords)]

        score = 0
        reasons = []
        if is_intern:
            score += 45
            reasons.append("Identified as internship/magang/PKL.")
        if is_senior:
            reasons.append("Senior or management role. Not suitable for student.")
        else:
            score += 20
        if matched_skills:
            score += 20
        
        has_preferred_loc = any(loc in loc_lower for loc in ["bekasi", "jakarta", "depok", "tangerang", "bogor", "remote"])
        if has_preferred_loc:
            score += 15
        else:
            reasons.append("Location mismatch: not in preferred cities.")

        score = max(0, min(100, score))
        recommended = score >= settings.SCORE_THRESHOLD and is_intern and not is_senior

        return AIResult(
            recommended=recommended,
            score=score,
            reason=reasons,
            matched_skills=matched_skills,
            missing_skills=["Embedded Systems" if "Embedded" not in matched_skills else ""],
            summary=f"Regex fallback matched {len(matched_skills)} areas. Score: {score}.",
            company_category="General Tech",
            work_mode="Remote" if "remote" in desc_lower else "On-site",
            priority="high" if score >= 80 else "medium"
        )
