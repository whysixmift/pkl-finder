# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-07-10

### Added
* Modular scrapers crawl job postings from Glints, LinkedIn Guest API, Indeed RSS feed, Jobstreet Redux state, Kalibrr, and Google Search.
* OpenRouter API client integration with exponential backoff retries and local regex-based fallback evaluations.
* Persistence layer using SQLAlchemy 2.0 with `asyncio` and `aiosqlite`.
* Background scheduler using APScheduler to run crawlers at configurable intervals.
* Telegram bot command and callback handler suite using `python-telegram-bot`.
* Docker Compose files with persistent host mount paths for data and logs.
* Unit test coverage for scrapers, evaluator fallback, database relationships, scheduler, and filtering rules.
