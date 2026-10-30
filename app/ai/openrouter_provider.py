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
You are an expert AI talent recruiter and career matching engine for Indonesian and global tech opportunities.
Your task is to analyze the job posting and evaluate its suitability against the Candidate Profile below:

Candidate Details:
{cv_text}

Evaluation Criteria:
1. Role Match: Does the job title, responsibilities, and experience level match what fits the candidate?
2. Technical & Practical Skills: How well do candidate's skills match the required technologies?
3. Opportunity Scope: Evaluate matches fairly across Full-Time, Contract, Remote, Fresh Graduate, and Internship/Magang roles depending on candidate's background.
4. Location & Work Mode: Is it in candidate's preferred location, easily accessible, Hybrid, or Remote?

You MUST return a JSON response with the following exact structure:
{{
  "recommended": true/false,
  "score": 0-100 (integer representing match score),
  "reason": ["reason 1", "reason 2"],
  "matched_skills": ["skill 1", "skill 2"],
  "missing_skills": ["skill 3", "skill 4"],
  "summary": "A concise summary in Indonesian of why this job fits or why it doesn't.",
  "company_category": "Software House" or "IoT/Hardware" or "Robotics" or "Fintech" or "General Tech",
  "work_mode": "Remote" or "Hybrid" or "On-site",
  "priority": "low" or "medium" or "high"
}}

Response instructions:
- Output ONLY the JSON block. Do not include any explanation outside the JSON.
- If the job substantially aligns with candidate's capabilities and interests, score 70-100 and set recommended: true.
- If the role requires senior/lead level far above candidate or is completely unrelated, score below 50 and set recommended: false.
"""

CV_ANALYSIS_PROMPT = """
You are an expert AI Career Profiler and Technical Talent Advisor.
Analyze the candidate's CV text below and detect their skills, suitable job roles, and optimal search keywords for job hunting portals (Glints, LinkedIn, Indeed, JobStreet, Kalibrr).

Candidate CV:
{cv_text}

You MUST return a JSON object with this exact structure:
{{
  "candidate_name": "Full name or Identified Candidate",
  "specialization": "Primary field (e.g., Software Engineering, Embedded Systems, Backend, Data)",
  "experience_level": "Entry-Level / Fresh Graduate / Junior / Mid-Level",
  "top_skills": ["Skill 1", "Skill 2", "Skill 3", "Skill 4", "Skill 5"],
  "recommended_roles": ["Job Title 1", "Job Title 2", "Job Title 3", "Job Title 4"],
  "search_keywords": ["search keyword 1", "search keyword 2", "search keyword 3"],
  "preferred_work_modes": ["Remote", "Hybrid", "On-site"],
  "summary": "2-3 sentences in Indonesian summarizing the candidate's core strengths and ideal career direction."
}}

Response instructions:
- Output ONLY the JSON block. Do not include markdown codeblocks or explanations outside the JSON.
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
            "max_tokens": 5,
            "stream": False
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
                "response_format": {"type": "json_object"},
                "stream": False
            }

        try:
            data = await self._post_with_fallback(payload_factory)
            content = data["choices"][0]["message"]["content"]
            return self._parse_ai_response(content)
        except Exception as e:
            logger.error(f"LLM evaluation failed, executing local regex fallback: {e}")
            return self._fallback_evaluate(title, company, location, description)

    async def write_cold_email(
        self,
        company_name: str,
        cv_text: str,
        job_title: Optional[str] = None,
        job_description: Optional[str] = None
    ) -> Tuple[str, str]:
        """Generates cold application emails seeking internships, matching candidate profile parameters."""
        effective_cv = cv_text.strip() if cv_text and cv_text.strip() else CANDIDATE_PROFILE.strip()
        role_context = f"Applying for role: {job_title}" if job_title else "Seeking PKL / Internship opening"
        desc_context = f"\nJob Context / Description: {job_description[:300]}" if job_description else ""

        system_prompt = f"""
        You are an elite, highly persuasive cold email copywriter specializing in tech job applications (Full-Time, Remote, Contract, Junior/Mid, and Internship).
        Write a concise, high-converting, professional, and personalized job application email to the recruitment / engineering team at {company_name}.
        
        Strict Requirements:
        - NEVER use generic placeholder templates.
        - Tailor the pitch directly to {company_name} and the candidate's actual qualifications from their CV.
        - Tone: Enthusiastic, highly competent, polite, professional Indonesian (or formal bilingual if appropriate).
        - State clearly that the candidate's complete CV is attached to this email.
        
        Candidate CV Information:
        {effective_cv[:1500]}
        
        Position / Target Context:
        {role_context}{desc_context}
        
        Output MUST be ONLY a valid JSON object with exact keys:
        {{
          "subject": "Unique, compelling subject line (e.g., Lamaran Posisi [Role] - [Candidate Name])",
          "body": "Complete, polite, and persuasive email body with professional sign-off and mention of attached CV."
        }}
        """

        def payload_factory(model_id: str) -> Dict[str, Any]:
            return {
                "model": model_id,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Draft the personalized internship application email for {company_name}."}
                ],
                "response_format": {"type": "json_object"},
                "stream": False
            }

        try:
            data = await self._post_with_fallback(payload_factory)
            content = data["choices"][0]["message"]["content"].strip()
            
            if content.startswith("```"):
                match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", content)
                if match:
                    content = match.group(1)

            parsed = json.loads(content)
            subject = parsed.get("subject", f"Permohonan Magang / PKL di {company_name}")
            body = parsed.get("body", "")
            if subject and body:
                return subject, body
        except Exception as e:
            logger.warning(f"OpenRouter cold email drafting failed ({e}), generating local tailored fallback.")

        # Local intelligent fallback
        target_role = job_title or "Software Engineer / Professional Tech Role"
        fallback_subject = f"Lamaran Posisi {target_role} - {company_name}"
        fallback_body = (
            f"Yth. Tim Rekrutmen & HRD {company_name},\n\n"
            f"Perkenalkan, saya tertarik untuk mengajukan lamaran kerja di {company_name} "
            f"untuk posisi {target_role}.\n\n"
            f"Berdasarkan latar belakang teknis yang saya miliki, saya memiliki ketertarikan mendalam dan pengalaman langsung dalam pengembangan software, problem solving, dan kolaborasi tim. "
            f"Saya sangat mengagumi produk & inovasi yang dijalankan oleh {company_name} dan yakin dapat memberikan kontribusi aktif dalam tim Bapak/Ibu.\n\n"
            f"Sebagai bahan pertimbangan Bapak/Ibu, Curriculum Vitae (CV) lengkap saya telah saya lampirkan pada email ini.\n\n"
            f"Besar harapan saya untuk mendapatkan kesempatan wawancara atau diskusi lebih lanjut. Terima kasih banyak atas perhatian dan waktu Bapak/Ibu.\n\n"
            f"Hormat saya,\n"
            f"Kandidat Pelamar"
        )
        return fallback_subject, fallback_body

    async def analyze_cv_intelligence(self, cv_text: str) -> Dict[str, Any]:
        """Analyze candidate CV to detect suitable job roles, top skills, and scraper search queries."""
        sys_prompt = CV_ANALYSIS_PROMPT.format(cv_text=cv_text)

        def payload_factory(model_id: str) -> Dict[str, Any]:
            return {
                "model": model_id,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": "Analyze the CV and provide the career intelligence JSON."}
                ],
                "response_format": {"type": "json_object"},
                "stream": False
            }

        try:
            data = await self._post_with_fallback(payload_factory)
            content = data["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", content)
                if match:
                    content = match.group(1)

            parsed = json.loads(content)
            return {
                "candidate_name": parsed.get("candidate_name", "Kandidat Job Finder"),
                "specialization": parsed.get("specialization", "Software Engineering / Tech"),
                "experience_level": parsed.get("experience_level", "Junior / Entry-Level"),
                "top_skills": parsed.get("top_skills", ["Python", "Backend", "Git"]),
                "recommended_roles": parsed.get("recommended_roles", ["Software Engineer", "Backend Developer"]),
                "search_keywords": parsed.get("search_keywords", ["software engineer", "backend developer"]),
                "preferred_work_modes": parsed.get("preferred_work_modes", ["Remote", "Hybrid", "On-site"]),
                "summary": parsed.get("summary", "Profil teknis yang solid dengan keahlian pengembangan aplikasi.")
            }
        except Exception as e:
            logger.warning(f"AI CV analysis failed ({e}), falling back to heuristic parsing.")
            return self._fallback_analyze_cv(cv_text)

    def _fallback_analyze_cv(self, cv_text: str) -> Dict[str, Any]:
        """Deterministic heuristic analysis of CV text when LLM is unavailable."""
        text_lower = cv_text.lower()
        skills = []
        skill_map = {
            "Python": ["python", "django", "flask", "fastapi"],
            "JavaScript / TypeScript": ["javascript", "typescript", "node", "react", "vue"],
            "Backend Engineering": ["backend", "api", "rest", "sql", "postgres", "mysql"],
            "Embedded Systems & IoT": ["embedded", "iot", "arduino", "esp32", "stm32", "microcontroller", "robotics"],
            "Linux & DevOps": ["linux", "docker", "git", "ci/cd", "bash"],
            "Mobile Development": ["flutter", "kotlin", "android", "swift", "react native"],
            "UI/UX & Frontend": ["html", "css", "tailwind", "figma", "frontend"],
            "Data Science & AI": ["machine learning", "data science", "pandas", "pytorch", "tensorflow"]
        }

        roles = []
        keywords = []
        for category, kws in skill_map.items():
            if any(k in text_lower for k in kws):
                skills.append(category)

        if "Python" in skills or "Backend Engineering" in skills:
            roles.extend(["Python Developer", "Backend Engineer", "Junior Software Engineer"])
            keywords.extend(["python developer", "backend engineer", "software engineer"])
        if "Embedded Systems & IoT" in skills:
            roles.extend(["IoT Engineer", "Embedded Software Developer", "Hardware Firmware Engineer"])
            keywords.extend(["iot engineer", "embedded engineer", "firmware developer"])
        if "JavaScript / TypeScript" in skills or "UI/UX & Frontend" in skills:
            roles.extend(["Frontend Developer", "Full Stack Developer"])
            keywords.extend(["frontend developer", "full stack developer"])
        if not roles:
            roles = ["Software Engineer", "IT Technical Support", "Junior Developer"]
            keywords = ["software engineer", "junior developer", "it programmer"]

        return {
            "candidate_name": "Kandidat Job Finder",
            "specialization": skills[0] if skills else "Software Engineering",
            "experience_level": "Entry-Level / Junior Developer",
            "top_skills": skills[:5] if skills else ["Programming", "Problem Solving", "Git"],
            "recommended_roles": list(dict.fromkeys(roles))[:4],
            "search_keywords": list(dict.fromkeys(keywords))[:4],
            "preferred_work_modes": ["Remote", "Hybrid", "On-site"],
            "summary": f"Kandidat memiliki keahlian utama di bidang {', '.join(skills[:3]) if skills else 'teknologi software'}."
        }

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
            score += 25
            reasons.append("Identified as entry/internship friendly.")
        elif any(kw in title_lower for kw in ["junior", "associate", "developer", "engineer", "programmer"]):
            score += 35
            reasons.append("Identified as junior/mid developer position.")
        else:
            score += 20

        if is_senior:
            reasons.append("Requires senior/lead level.")
        else:
            score += 25

        if matched_skills:
            score += 30
            reasons.append(f"Matched skills: {', '.join(matched_skills)}.")
        
        has_preferred_loc = any(loc in loc_lower for loc in ["bekasi", "jakarta", "depok", "tangerang", "bogor", "remote", "indonesia"])
        if has_preferred_loc:
            score += 15
        else:
            reasons.append("Location outside primary cities.")

        score = max(0, min(100, score))
        recommended = score >= settings.SCORE_THRESHOLD and not is_senior

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

    async def generate_code_patch(
        self,
        bug_report: str,
        log_context: str,
        code_context: str,
        file_hint: Optional[str] = None
    ) -> Dict[str, Any]:
        """Analyze bug report and code context, returning a surgical code fix dictionary."""
        system_prompt = (
            "You are an expert autonomous software engineer and debugging specialist for a Python project.\n"
            "Given the bug report, recent error logs, and relevant source code snippet, identify the root cause "
            "and produce a surgical, minimal fix that solves the bug without breaking existing functionality.\n\n"
            "Strict Instructions:\n"
            "1. Output MUST be ONLY a valid JSON object.\n"
            "2. 'file_path': The relative file path to edit (e.g., 'app/bot/handlers.py').\n"
            "3. 'target': The EXACT character-for-character substring in the file that must be replaced. "
            "It must match the source file exactly, including whitespace and indentation.\n"
            "4. 'replacement': The replacement code.\n"
            "5. 'diagnosis': A clear, concise explanation of the bug and its root cause in Indonesian.\n"
            "6. 'explanation': A summary of what the fix does in Indonesian.\n\n"
            "Response Schema:\n"
            "{\n"
            '  "file_path": "path/to/file.py",\n'
            '  "target": "exact text to replace",\n'
            '  "replacement": "new replacement text",\n'
            '  "diagnosis": "penjelasan akar masalah",\n'
            '  "explanation": "penjelasan perbaikan"\n'
            "}"
        )

        user_prompt = (
            f"=== LAPORAN BUG / ISSUE ===\n{bug_report}\n\n"
            f"=== RECENT ERROR LOGS ===\n{log_context[:2500]}\n\n"
            f"=== SOURCE CODE CONTEXT ===\n{code_context[:4000]}\n\n"
            f"Target File Hint: {file_hint or 'Detect from error'}\n\n"
            "Generate the surgical JSON fix."
        )

        def payload_factory(model_id: str) -> Dict[str, Any]:
            return {
                "model": model_id,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "response_format": {"type": "json_object"},
                "stream": False
            }

        try:
            data = await self._post_with_fallback(payload_factory)
            content = data["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", content)
                if match:
                    content = match.group(1)
            parsed = json.loads(content)
            return {
                "file_path": parsed.get("file_path", file_hint or ""),
                "target": parsed.get("target", ""),
                "replacement": parsed.get("replacement", ""),
                "diagnosis": parsed.get("diagnosis", "Diagnosa bug otomatis"),
                "explanation": parsed.get("explanation", "Perbaikan otomatis diterapkan")
            }
        except Exception as e:
            logger.warning(f"AI code patch generation failed ({e}), attempting rule-based fallback.")
            return self._fallback_generate_patch(bug_report, log_context, file_hint)

    def _fallback_generate_patch(
        self,
        bug_report: str,
        log_context: str,
        file_hint: Optional[str] = None
    ) -> Dict[str, Any]:
        """Rule-based heuristic fallback patch generation when OpenRouter is offline."""
        combined = f"{bug_report}\n{log_context}".lower()

        # Rule 1: psutil import missing
        if "psutil" in combined:
            return {
                "file_path": file_hint or "app/bot/handlers.py",
                "target": "import psutil",
                "replacement": "try:\n        import psutil\n    except Exception:\n        psutil = None",
                "diagnosis": "Modul 'psutil' belum terpasang atau tidak tersedia di container/host.",
                "explanation": "Membungkus import psutil dengan blok try-except fallback."
            }

        # Rule 2: Ambiguous column name in query
        if "ambiguous column" in combined:
            return {
                "file_path": file_hint or "app/services/job_service.py",
                "target": "stmt.join(AIScore, (Job.id == AIScore.job_id) & (AIScore.user_id == user_id))",
                "replacement": "# Duplicate join removed to eliminate ambiguous column name",
                "diagnosis": "Terjadi duplikasi join pada AIScore yang menyebabkan ambigu pada nama kolom SQLite.",
                "explanation": "Menghapus duplikasi join pada AIScore."
            }

        return {
            "file_path": file_hint or "",
            "target": "",
            "replacement": "",
            "diagnosis": "Tidak dapat merumuskan patch otomatis tanpa koneksi AI aktif.",
            "explanation": "Koneksi OpenRouter terputus dan tidak ada aturan rule-based yang cocok."
        }

    async def prepare_interview_cheatsheet(
        self,
        title: Optional[str] = None,
        company: Optional[str] = None,
        description: Optional[str] = None,
        cv_text: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate tailored technical questions, behavioral questions, and tips for this job opening."""
        title = title or kwargs.get("job_title", "Software Engineer")
        company = company or kwargs.get("company_name", "Perusahaan")
        description = description or kwargs.get("job_description", "")
        cv_text = cv_text or kwargs.get("candidate_cv_text")
        system_prompt = (
            "You are an expert Tech Hiring Manager and Interview Coach.\n"
            f"Generate an interview preparation guide in Indonesian for a candidate applying for the role '{title}' at '{company}'.\n\n"
            "Output MUST be ONLY a JSON object with this exact structure:\n"
            "{\n"
            '  "technical_questions": [\n'
            '    {"question": "Pertanyaan teknis 1", "answer_key": "Kunci jawaban/konsep penting yang harus dijawab pelamar"},\n'
            '    {"question": "Pertanyaan teknis 2", "answer_key": "Kunci jawaban/konsep penting"},\n'
            '    {"question": "Pertanyaan teknis 3", "answer_key": "Kunci jawaban/konsep penting"},\n'
            '    {"question": "Pertanyaan teknis 4", "answer_key": "Kunci jawaban/konsep penting"},\n'
            '    {"question": "Pertanyaan teknis 5", "answer_key": "Kunci jawaban/konsep penting"}\n'
            '  ],\n'
            '  "behavioral_questions": [\n'
            '    {"question": "Pertanyaan perilaku/budaya 1", "tip": "Tips menjawab"},\n'
            '    {"question": "Pertanyaan perilaku/budaya 2", "tip": "Tips menjawab"},\n'
            '    {"question": "Pertanyaan perilaku/budaya 3", "tip": "Tips menjawab"}\n'
            '  ],\n'
            '  "smart_questions_to_ask": [\n'
            '    "Pertanyaan cerdas 1 yang harus diajukan kandidat kepada pewawancara",\n'
            '    "Pertanyaan cerdas 2",\n'
            '    "Pertanyaan cerdas 3"\n'
            '  ]\n'
            "}"
        )

        user_prompt = (
            f"Job Title: {title}\nCompany: {company}\n"
            f"Job Context:\n{description[:1500]}\n\n"
            f"Candidate CV Snippet:\n{(cv_text or '')[:800]}"
        )

        def payload_factory(model_id: str) -> Dict[str, Any]:
            return {
                "model": model_id,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "response_format": {"type": "json_object"},
                "stream": False
            }

        try:
            data = await self._post_with_fallback(payload_factory)
            content = data["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", content)
                if match:
                    content = match.group(1)
            return json.loads(content)
        except Exception as e:
            logger.warning(f"AI interview prep failed ({e}), using heuristic fallback.")
            return {
                "technical_questions": [
                    {"question": f"Jelaskan arsitektur teknis atau framework utama yang pernah Anda gunakan relevan dengan posisi {title}.", "answer_key": "Fokus pada struktur project, pemisahan layer (MVC/Clean Architecture), dan penanganan request."},
                    {"question": "Bagaimana pendekatan Anda dalam menangani debugging query database atau performa API yang lambat?", "answer_key": "Sebutkan indexing, caching (Redis), profiling query SQL, dan pagination."},
                    {"question": "Bagaimana pengalaman Anda dalam menggunakan Git, branching strategy, dan CI/CD pipeline?", "answer_key": "Jelaskan Gitflow (feature branches, PR review) serta auto testing saat push."},
                    {"question": "Bagaimana Anda memastikan kode Anda aman dari kerentanan umum (misal SQL Injection, XSS, token expiry)?", "answer_key": "Gunakan ORM parameter binding, sanitize input, dan validasi JWT/Session."},
                    {"question": "Bagaimana Anda memprioritaskan penyelesaian bug darurat di lingkungan production?", "answer_key": "Identifikasi dampak pengguna, cek error log, rollback jika perlu, lalu rilis hotfix terisolasi."}
                ],
                "behavioral_questions": [
                    {"question": "Ceritakan saat Anda menghadapi kendala teknis yang sulit dan bagaimana Anda menyelesaikannya.", "tip": "Gunakan metode STAR (Situation, Task, Action, Result)."},
                    {"question": "Bagaimana cara Anda beradaptasi jika ada perubahan mendadak pada kebutuhan fitur?", "tip": "Tunjukkan fleksibilitas, komunikasi proaktif dengan tech lead, dan estimasi realistis."},
                    {"question": "Apa motivasi terbesar Anda ingin bergabung dan berkontribusi di perusahaan ini?", "tip": "Hubungkan visi perusahaan dengan ketertarikan karir teknologi Anda."}
                ],
                "smart_questions_to_ask": [
                    f"Bagaimana komposisi tim engineering dan alur kerja sprint mingguan untuk posisi {title} di {company}?",
                    "Teknologi atau tantangan teknis apa yang saat ini sedang menjadi fokus utama tim pengembang?",
                    "Bagaimana metrik evaluasi keberhasilan untuk kandidat yang mengisi posisi ini dalam 3 bulan pertama?"
                ]
            }

    async def optimize_cv_for_job(
        self,
        title: Optional[str] = None,
        company: Optional[str] = None,
        description: Optional[str] = None,
        cv_text: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate tailored ATS-friendly profile summary and achievement bullet points."""
        title = title or kwargs.get("job_title", "Software Engineer")
        company = company or kwargs.get("company_name", "Perusahaan")
        description = description or kwargs.get("job_description", "")
        cv_text = cv_text or kwargs.get("candidate_cv_text")
        system_prompt = (
            "You are an elite ATS Resume Specialist.\n"
            f"Generate tailored CV enhancements in Indonesian for a candidate applying to '{title}' at '{company}'.\n\n"
            "Output MUST be ONLY a JSON object:\n"
            "{\n"
            '  "tailored_summary": "1 paragraf ringkasan profil (About Me) padat keyword yang lolos screening ATS",\n'
            '  "highlight_bullets": [\n'
            '    "Poin pengalaman/proyek 1 yang menonjolkan kecocokan teknis",\n'
            '    "Poin pengalaman/proyek 2 berorientasi hasil terukur",\n'
            '    "Poin pengalaman/proyek 3 kolaborasi & best practices"\n'
            '  ],\n'
            '  "ats_keywords": ["keyword 1", "keyword 2", "keyword 3", "keyword 4", "keyword 5"]\n'
            "}"
        )

        user_prompt = f"Role: {title} at {company}\nJob Description:\n{description[:1500]}\nCandidate CV:\n{(cv_text or '')[:1000]}"

        def payload_factory(model_id: str) -> Dict[str, Any]:
            return {
                "model": model_id,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "response_format": {"type": "json_object"},
                "stream": False
            }

        try:
            data = await self._post_with_fallback(payload_factory)
            content = data["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", content)
                if match:
                    content = match.group(1)
            parsed = json.loads(content)
            if "must_have_keywords" not in parsed and "ats_keywords" in parsed:
                parsed["must_have_keywords"] = parsed["ats_keywords"]
            elif "ats_keywords" not in parsed and "must_have_keywords" in parsed:
                parsed["ats_keywords"] = parsed["must_have_keywords"]
            return parsed
        except Exception as e:
            logger.warning(f"AI CV optimize failed ({e}), using heuristic fallback.")
            kws = [title, "API Development", "Problem Solving", "Database Management", "Clean Code"]
            return {
                "tailored_summary": (
                    f"Pengembang perangkat lunak berorientasi solusi dengan keahlian praktis dalam pengembangan backend, API, dan sistem scalable. "
                    f"Berpengalaman dalam clean code, database relasional, dan kolaborasi tim agile, siap berkontribusi secara optimal untuk posisi {title} di {company}."
                ),
                "highlight_bullets": [
                    f"Mengembangkan dan mengoptimalkan RESTful API dengan response time cepat dan arsitektur database terstruktur.",
                    f"Mengimplementasikan otomatisasi pengujian, containerization, dan version control menggunakan Git.",
                    f"Bekerja sama dalam sprint development untuk merilis fitur sesuai requirement bisnis dan spesifikasi teknis."
                ],
                "ats_keywords": kws,
                "must_have_keywords": kws
            }

    async def recommend_portfolio_project(
        self,
        title: Optional[str] = None,
        company: Optional[str] = None,
        missing_skills: Optional[List[str]] = None,
        cv_text: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Recommend a practical 2-3 day weekend project to close skill gaps for this job opening."""
        title = title or kwargs.get("job_title", "Software Engineer")
        company = company or kwargs.get("company_name", "Perusahaan")
        missing_skills = missing_skills or kwargs.get("missing_skills") or []
        cv_text = cv_text or kwargs.get("candidate_cv_text")
        skills_str = ", ".join(missing_skills) if missing_skills else "Full-stack integration, Docker, Cloud"
        system_prompt = (
            "You are an elite Software Engineering Mentor.\n"
            f"Propose a concrete, impressive 2-3 day GitHub weekend project to help a candidate prove skills in: {skills_str}.\n"
            "Output MUST be ONLY a JSON object:\n"
            "{\n"
            '  "project_title": "Judul Proyek Keren & Relevan",\n'
            '  "elevator_pitch": "Penjelasan singkat 1-2 kalimat fungsi proyek",\n'
            '  "tech_stack": ["Teknologi 1", "Teknologi 2", "Teknologi 3"],\n'
            '  "implementation_steps": [\n'
            '    "Langkah 1: Setup arsitektur",\n'
            '    "Langkah 2: Fitur inti",\n'
            '    "Langkah 3: Testing & deployment"\n'
            '  ],\n'
            '  "github_readme_tip": "Tips menulis README agar recruiter langsung terkesan"\n'
            "}"
        )

        user_prompt = f"Role: {title} at {company}\nMissing/Target Skills: {skills_str}"

        def payload_factory(model_id: str) -> Dict[str, Any]:
            return {
                "model": model_id,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "response_format": {"type": "json_object"},
                "stream": False
            }

        try:
            data = await self._post_with_fallback(payload_factory)
            content = data["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", content)
                if match:
                    content = match.group(1)
            parsed = json.loads(content)
            if "pitch" not in parsed:
                parsed["pitch"] = parsed.get("elevator_pitch", "")
            if "architecture_hint" not in parsed:
                parsed["architecture_hint"] = "\n".join(parsed.get("implementation_steps", []))
            if "estimated_time" not in parsed:
                parsed["estimated_time"] = "2-3 Hari Weekend"
            return parsed
        except Exception as e:
            logger.warning(f"AI project recommend failed ({e}), using heuristic fallback.")
            primary_skill = missing_skills[0] if missing_skills else "FastAPI & Docker"
            steps = [
                "Inisialisasi repo GitHub dengan struktur modular dan environment config (.env.example).",
                f"Bangun endpoint CRUD dengan validasi skema dan integrasikan {primary_skill}.",
                "Tulis Dockerfile multi-stage build dan buat GitHub Actions workflow untuk automated testing."
            ]
            return {
                "project_title": f"Production-Ready Microservice with {primary_skill}",
                "elevator_pitch": f"Service API independen yang mengimplementasikan {primary_skill} dengan caching, logging terpusat, dan containerization.",
                "pitch": f"Service API independen yang mengimplementasikan {primary_skill} dengan caching, logging terpusat, dan containerization.",
                "tech_stack": [primary_skill, "Docker", "PostgreSQL / SQLite", "GitHub Actions"],
                "implementation_steps": steps,
                "architecture_hint": "\n".join(steps),
                "estimated_time": "2-3 Hari Weekend",
                "github_readme_tip": "Sertakan diagram arsitektur visual (Mermaid.js), instruksi 'Quickstart with Docker Compose', dan benchmark performa singkat."
            }

    async def draft_followup_email(
        self,
        company_name: Optional[str] = None,
        job_title: Optional[str] = None,
        cv_text: Optional[str] = None,
        candidate_name: Optional[str] = None,
        **kwargs
    ) -> Dict[str, str]:
        """Generate polite, professional follow-up email after applying."""
        company_name = company_name or kwargs.get("company", "Perusahaan")
        job_title = job_title or kwargs.get("title", "Posisi Lowongan")
        candidate_name = candidate_name or kwargs.get("name", "Kandidat Pelamar")
        subject = f"Menindaklanjuti Lamaran: {job_title} - {candidate_name}"
        body = (
            f"Yth. Tim Rekrutmen & HRD {company_name},\n\n"
            f"Semoga Bapak/Ibu senantiasa dalam keadaan sehat.\n\n"
            f"Melalui email ini, saya ({candidate_name}) ingin menindaklanjuti berkas lamaran saya untuk posisi {job_title} "
            f"yang telah saya kirimkan beberapa waktu yang lalu.\n\n"
            f"Saya sangat antusias dengan peluang untuk dapat berkontribusi di {company_name} dan yakin bahwa latar belakang "
            f"teknis serta portofolio saya dapat memberikan nilai tambah bagi tim Bapak/Ibu.\n\n"
            f"Apabila ada informasi atau berkas pendukung tambahan yang dibutuhkan, saya siap menyediakannya. "
            f"Terima kasih banyak atas perhatian dan waktu Bapak/Ibu.\n\n"
            f"Hormat saya,\n"
            f"{candidate_name}"
        )
        return {"subject": subject, "body": body}
