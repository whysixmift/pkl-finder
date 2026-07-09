# AI Evaluator and OpenRouter Client

The evaluation engine is located in `app/ai/evaluator.py`. It scores and checks job descriptions against the student's CV profile using the OpenRouter API.

## OpenRouter Integration

The evaluator uses the OpenRouter HTTP endpoint `https://openrouter.ai/api/v1/chat/completions`. To identify the bot to OpenRouter and access free-tier optimization policies, custom headers are included in the request:

* `Authorization`: Bearer token authorization header.
* `HTTP-Referer`: Project repository URL.
* `X-Title`: Application identifier.

### Payload Model Configuration
The client passes a standard chat completion payload:
* `model`: Loaded from `.env` (default is `qwen/qwen3-30b-a3b:free` or `deepseek/deepseek-chat-v3-0324:free`).
* `response_format`: Explicitly set to `{"type": "json_object"}` to force the model to return a structured JSON response instead of text markdown.
* `messages`: System prompt defining the evaluation criteria, and user prompt containing the job metadata and description.

---

## Evaluation Prompts

### 1. CV Context
The system prompt contains the student's CV context, ensuring consistent matching criteria across evaluations:

* **Education**: SMK Negeri 2 Bekasi.
* **Major**: Software Engineering (RPL).
* **Skills**: Python, Java, C++, Robotics, Embedded Systems, IoT, Android Studio, Git, PID Tuning, Driver Robot.
* **Experience**: FIRST Tech Challenge (FTC), Hack Club Mentor, Business Development.
* **Preferred Locations**: Bekasi, Jakarta, Depok, Tangerang, Bogor, Remote.
* **Preferred Roles**: Embedded, IoT, Robotics, Backend, Python, Software Engineer, AI, Machine Learning, Firmware, Computer Vision.
* **Goal**: Searching for a PKL (Praktek Kerja Lapangan) or Internship.

### 2. Output Schema
The AI is instructed to return a JSON object with the following schema:

```json
{
  "recommended": true,
  "score": 95,
  "reason": ["reason 1", "reason 2"],
  "matched_skills": ["skill 1", "skill 2"],
  "missing_skills": ["skill 3"],
  "summary": "Detailed summary text."
}
```

If the position is not an internship, magang, or PKL (e.g. it is a senior full-time role), the model is instructed to set `recommended` to false and score it below 50.

---

## Retry Strategy & Error Handling

To handle network issues and rate limits (HTTP 429), the evaluator implements a retry loop with exponential backoff:

1. **HTTP 429 (Rate Limit)**: The client inspects the `Retry-After` header. If present, it waits for the specified duration; if not, it defaults to exponential backoff (starting at 2.0s, doubling each attempt).
2. **HTTP 5xx (Server Error) & Timeouts**: The client logs a warning, waits for the backoff duration, and retries up to 3 times.
3. **JSON Parsing Mismatch**: If the response contains markdown code block markers (e.g. ` ```json `), a regular expression extracts the inner block. If parsing still fails, it triggers the fallback engine.

---

## Fallback Matching Engine

If the API key is not configured, OpenRouter is down, or the model returns invalid JSON, the evaluator falls back to the local rule engine (`_fallback_evaluate`).

The fallback engine uses regular expressions to score the job posting:
* **Internship Check**: Searches for `intern`, `magang`, `pkl`, `praktek kerja`, `student`, `co-op`. If found, it awards 40 points. If missing, it logs a penalty.
* **Seniority Penalty**: Searches for `senior`, `lead`, `principal`, `manager`, `5+ years`, `3+ years`. If found, it deducts 30 points.
* **Location Check**: Searches for preferred locations (Bekasi, Jakarta, Depok, Tangerang, Bogor, Remote). If a match is found, it awards 15 points.
* **Role Check**: Searches for role-specific keywords (Python, IoT, Embedded, Robotics, Backend, Machine Learning). Each match awards 15 points (up to 45 points max).

If the final score is greater than or equal to the configured threshold and the internship check passes, the job is marked as recommended. This fallback ensures the bot continues to work even during API outages.
