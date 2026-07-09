# Database Schema and Persistence Layer

The PKL Finder application uses SQLite as its default database engine, accessed asynchronously via the SQLAlchemy 2.0 ORM and the `aiosqlite` database driver.

## Database Settings and Pool Setup

The database connection is initialized in `app/database/db.py`. To prevent "database is locked" errors common with concurrent writes in SQLite, the engine is configured with a 30-second timeout parameter:

```python
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"timeout": 30} if "sqlite" in DATABASE_URL else {}
)
```

Sessions are spawned using `async_sessionmaker` with `expire_on_commit=False`, ensuring that entities loaded in one session do not raise attribute access errors outside the transaction context.

---

## Entity Schema Declarations

```
  +-------------+              +-----------------+
  |  companies  | 1        0..*|      jobs       |
  | ----------- |------------->|  -------------  |
  |  id (PK)    |              |  id (PK)        |
  |  name       |              |  job_key (Index)|
  +-------------+              |  company_id (FK)|
                               |  title (Index)  |
                               +-----------------+
                                     |
         +---------------------------+---------------------------+
         | 1                         | 1                         | 1
         v 0..1                      v 0..*                      v 0..*
  +-------------+             +-------------+             +-------------+
  |  ai_scores  |             |  favorites  |             |   history   |
  | ----------- |             | ----------- |             | ----------- |
  |  id (PK)    |             |  id (PK)    |             |  id (PK)    |
  |  job_id (FK)|             |  job_id (FK)|             |  job_id (FK)|
  |  score      |             |  created_at |             |  action     |
  +-------------+             +-------------+             +-------------+
```

### 1. `companies` Table
Stores unique company profiles to prevent redundant text entries and support company-specific searches.
* `id` (Integer, Primary Key): Unique autoincremented identifier.
* `name` (String(255), Unique, Indexed): Normalized company name.
* `logo_url` (String(500), Nullable): Link to company brand icon.
* `website` (String(255), Nullable): Main company homepage URL.
* `created_at` (DateTime): Timestamp of creation (default to UTC).

### 2. `jobs` Table
Stores unique job postings crawled by the scraper system.
* `id` (Integer, Primary Key): Unique autoincremented identifier.
* `job_key` (String(64), Unique, Indexed): SHA-256 hash representing the job URL. This serves as the primary deduplication constraint.
* `title` (String(255), Indexed): Title of the position.
* `company_id` (Integer, ForeignKey to `companies.id`, Nullable): Linked company record.
* `company_name` (String(255)): Denormalized company name to optimize joins.
* `location` (String(255)): Geographic location or Remote status.
* `description` (Text): Full markdown/text job description.
* `url` (String(1000), Unique): Direct vacancy application link.
* `posted_date` (DateTime, Nullable): Date the job was published on the origin platform.
* `source` (String(50), Indexed): Origin site identifier (e.g. `glints`, `linkedin`, `indeed`).
* `salary` (String(100), Nullable): Extracted salary brackets.
* `work_mode` (String(50), Nullable): Hybrid, Remote, or On-site.
* `employment_type` (String(50), Nullable): Internship, Full-time, etc.
* `created_at` (DateTime): Record registration timestamp.

### 3. `ai_scores` Table
Stores LLM feedback and match scoring evaluations for crawled jobs.
* `id` (Integer, Primary Key): Unique autoincremented identifier.
* `job_id` (Integer, ForeignKey to `jobs.id`, Cascade Delete, Unique): One-to-one link to the parent job posting.
* `recommended` (Boolean): Flag indicating suitability.
* `score` (Integer, Indexed): Match metric between 0 and 100.
* `reason` (Text): JSON-encoded list of criteria matching constraints.
* `matched_skills` (Text): JSON-encoded list of matched candidate qualities.
* `missing_skills` (Text): JSON-encoded list of missing requirements.
* `summary` (Text): Detailed evaluation breakdown compiled by the AI.
* `evaluated_at` (DateTime): Timestamp of AI parsing.

### 4. `favorites` Table
Tracks jobs marked as favorites by the student.
* `id` (Integer, Primary Key): Unique autoincremented identifier.
* `job_id` (Integer, ForeignKey to `jobs.id`, Cascade Delete, Unique): Linked job posting.
* `created_at` (DateTime): Timestamp of favoriting.

### 5. `history` Table
Tracks audit histories of system processes and interactions.
* `id` (Integer, Primary Key): Unique autoincremented identifier.
* `job_id` (Integer, ForeignKey to `jobs.id`, Cascade Delete): Linked job posting.
* `action` (String(50)): Event category (e.g. `scraped`, `evaluated`, `recheck_evaluated`, `favorited`).
* `details` (Text, Nullable): Custom parameters or system traceback payloads.
* `created_at` (DateTime): Action timestamp.

---

## Eager Loading Strategies

To prevent N+1 query execution problems when fetching large collections of jobs, all select statements in `JobService` load relationships explicitly using `selectinload`:

```python
stmt = select(Job).options(selectinload(Job.ai_score)).order_by(desc(Job.created_at))
```

This strategy issues a single SQL `IN` query for child rows immediately following the primary query, maximizing performance in SQLite.
