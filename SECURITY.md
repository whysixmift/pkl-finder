# Security Policy

This document describes security practices and vulnerability reporting for the PKL Finder project.

## Supported Versions

We actively support the following versions with security updates:

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |

## Security Considerations

To ensure the security of your deployment:
* **Admin Verification**: Never disable or modify the `@admin_only` decorator in `app/bot/handlers.py`. This ensures only the configured administrator can control the bot.
* **Sensitive Credentials**: Do not commit your `.env` file to version control. It is excluded in `.gitignore` by default.
* **Volume Permissions**: Restrict access to the mounted database folder (`./data/`) on your host machine to prevent unauthorized access to job histories.

## Reporting a Vulnerability

If you discover a security vulnerability, please report it immediately:
1. Do not open a public GitHub issue.
2. Email your findings to `security@example.com` (replace with your secure email).
3. Include details of the vulnerability, a proof of concept, and steps to reproduce.
4. We will acknowledge receipt of your report within 48 hours and work to provide a patch within 7 days.
