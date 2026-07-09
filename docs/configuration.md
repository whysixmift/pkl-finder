# Configuration Variables Reference

The PKL Finder application reads its configuration from environment variables defined in a `.env` file at the root of the project.

---

## 1. `OPENROUTER_API_KEY`
* **Purpose**: Authentication token for the OpenRouter LLM API.
* **Accepted values**: Alpha-numeric string.
* **Default value**: `"mock_key"` (Fallback rule-based matching is active if this value is unchanged).
* **Example**: `OPENROUTER_API_KEY=sk-or-v1-abc123xyz`
* **Common mistakes**: Including whitespace, prefixing with `Authorization:`, or using placeholder values in production.

## 2. `OPENROUTER_MODEL`
* **Purpose**: The LLM model used for job suitability evaluations.
* **Accepted values**: Any active OpenRouter model identifier.
* **Default value**: `"qwen/qwen3-30b-a3b:free"`
* **Example**: `OPENROUTER_MODEL=deepseek/deepseek-chat-v3-0324:free`
* **Common mistakes**: Using expensive models that lead to high API costs, or using retired model strings.

## 3. `TELEGRAM_BOT_TOKEN`
* **Purpose**: Token used to authenticate the Telegram Bot.
* **Accepted values**: Bot token string provided by @BotFather.
* **Default value**: `"mock_token"` (The application will crash on boot if this token is not configured).
* **Example**: `TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ`
* **Common mistakes**: Adding leading/trailing spaces or quotes, or using a revoked token.

## 4. `TELEGRAM_ADMIN_ID`
* **Purpose**: The Telegram account ID allowed to interact with the bot.
* **Accepted values**: Integer account identifier.
* **Default value**: `0`
* **Example**: `TELEGRAM_ADMIN_ID=987654321`
* **Common mistakes**: Providing a bot username instead of the numeric ID, or omitting it, which blocks access to all commands.

## 5. `DATABASE_URL`
* **Purpose**: SQLAlchemy connection URI.
* **Accepted values**: Standard database URL. To run asynchronously with SQLite, prefix with `sqlite+aiosqlite://`.
* **Default value**: `"sqlite+aiosqlite:///./data/jobs.db"`
* **Example**: `DATABASE_URL=sqlite+aiosqlite:///./data/jobs.db`
* **Common mistakes**: Using standard `sqlite:///` (which lacks async support and causes runtime errors with aiosqlite), or pointing to directories that the application cannot write to.

## 6. `CHECK_INTERVAL_MINUTES`
* **Purpose**: Background scraping cycle interval.
* **Accepted values**: Positive integers.
* **Default value**: `60`
* **Example**: `CHECK_INTERVAL_MINUTES=120`
* **Common mistakes**: Setting this value too low (e.g. less than 15 minutes), which can trigger rate limits on job portals.

## 7. `MAX_JOBS_PER_RUN`
* **Purpose**: Maximum number of new jobs processed in a single scraping run.
* **Accepted values**: Positive integers.
* **Default value**: `20`
* **Example**: `MAX_JOBS_PER_RUN=50`
* **Common mistakes**: Setting this value too high, which can consume a large amount of OpenRouter API tokens in a short period.

## 8. `SCORE_THRESHOLD`
* **Purpose**: Minimum match score for a job to be flagged as recommended.
* **Accepted values**: Integers between `0` and `100`.
* **Default value**: `70`
* **Example**: `SCORE_THRESHOLD=80`
* **Common mistakes**: Setting the threshold too high (preventing any matches from being sent) or too low (sending low-quality recommendations).

## 9. `SEARCH_KEYWORDS`
* **Purpose**: Comma-separated list of search queries passed to the scraper engines.
* **Accepted values**: Text strings separated by commas.
* **Default value**: `"internship software engineering,magang backend,intern iot,pkl rpl"`
* **Example**: `SEARCH_KEYWORDS=intern python,magang embedded,pkl robotics`
* **Common mistakes**: Adding leading/trailing commas or using overly broad search queries.

## 10. `SEARCH_LOCATIONS`
* **Purpose**: Comma-separated list of location filters passed to the scraper engines.
* **Accepted values**: City names or regions.
* **Default value**: `"Jakarta,Bekasi,Depok,Tangerang,Bogor,Remote"`
* **Example**: `SEARCH_LOCATIONS=Jakarta,Bekasi,Remote`
* **Common mistakes**: Omitting "Remote" for hybrid/remote positions, or searching for overly specific regions that return no results.
