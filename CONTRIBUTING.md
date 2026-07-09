# Contributing Guidelines

Thank you for considering contributing to the PKL Finder project. To maintain code quality and stability, please review the guidelines below.

## Code Standards and Style

To maintain a clean codebase, we enforce the following quality standards:
* **Python Version**: All code must target Python 3.12 or newer.
* **Typing**: Use static type hints for all public classes, methods, and functions.
* **Style Guidelines**: Follow PEP 8 guidelines. Keep line lengths under 120 characters.
* **Docstrings**: Public modules, classes, and methods must include descriptive docstrings detailing parameters and return types.
* **Async/Await**: Use asynchronous programming models (`async`/`await`) for I/O operations (database queries, network requests) to avoid blocking the main event loop.

## Development Workflow

1. **Branch Naming**: Use descriptive branch names:
   * Bug fixes: `fix/issue-description`
   * New features: `feat/feature-description`
   * Documentation updates: `docs/doc-description`
2. **Local Environment**:
   * Set up a virtual environment: `python3 -m venv .venv && source .venv/bin/activate`
   * Install dependencies: `pip install -r requirements.txt`
3. **Running the Test Suite**:
   Ensure all tests pass before submitting code changes:
   ```bash
   pytest
   ```

## Pull Request Guidelines

* Create clear, modular commits with descriptive messages.
* Ensure all tests pass locally.
* Keep pull requests focused on a single feature or bug fix.
* Document any new configuration variables added to `.env.example`.
