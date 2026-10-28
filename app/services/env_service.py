import os
from typing import Dict, Any, Optional
from app.config.settings import settings, reload_settings
from app.utils.logger import logger

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")
ENV_EXAMPLE_PATH = os.path.join(PROJECT_ROOT, ".env.example")

def get_env_file_path() -> str:
    """Return the absolute path of .env file."""
    return ENV_PATH

def get_env_example_path() -> str:
    """Return the absolute path of .env.example file."""
    return ENV_EXAMPLE_PATH

def read_env_content() -> str:
    """Read the raw text content of .env. If .env does not exist, return .env.example content."""
    if os.path.exists(ENV_PATH):
        try:
            with open(ENV_PATH, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to read .env file: {e}")
            return ""
    elif os.path.exists(ENV_EXAMPLE_PATH):
        try:
            with open(ENV_EXAMPLE_PATH, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to read .env.example file: {e}")
            return ""
    return ""

def get_env_dict() -> Dict[str, str]:
    """Parse key-value pairs from .env (or .env.example as fallback) into a dict."""
    content = read_env_content()
    result: Dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            key = k.strip()
            val = v.strip()
            # Strip quotes if present
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            result[key] = val
    return result

def save_raw_env(content: str) -> bool:
    """Save raw text directly to .env and reload in-memory settings."""
    try:
        with open(ENV_PATH, "w", encoding="utf-8") as f:
            f.write(content)
        reload_settings()
        logger.info("Successfully updated .env from raw content and reloaded settings.")
        return True
    except Exception as e:
        logger.error(f"Failed to save raw .env: {e}")
        return False

def save_env_dict(updates: Dict[str, Any]) -> bool:
    """
    Update specific key-value pairs in .env while preserving comments and order.
    If .env does not exist, uses .env.example as the baseline template.
    """
    try:
        content = read_env_content()
        lines = content.splitlines()
        found_keys = set()
        new_lines = []

        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in line:
                key, _, _ = line.partition("=")
                key_clean = key.strip()
                if key_clean in updates:
                    val = str(updates[key_clean])
                    new_lines.append(f"{key_clean}={val}")
                    found_keys.add(key_clean)
                    continue
            new_lines.append(line)

        # Append any new keys that weren't in the template
        for k, v in updates.items():
            if k not in found_keys:
                new_lines.append(f"{k}={v}")

        final_content = "\n".join(new_lines) + "\n"
        with open(ENV_PATH, "w", encoding="utf-8") as f:
            f.write(final_content)

        reload_settings()
        logger.info(f"Successfully updated {len(updates)} keys in .env and reloaded settings.")
        return True
    except Exception as e:
        logger.error(f"Failed to update .env from dict: {e}")
        return False

def reset_to_example() -> bool:
    """Reset .env by copying .env.example content and reload settings."""
    if not os.path.exists(ENV_EXAMPLE_PATH):
        return False
    try:
        with open(ENV_EXAMPLE_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        with open(ENV_PATH, "w", encoding="utf-8") as f:
            f.write(content)
        reload_settings()
        logger.info("Reset .env to .env.example template.")
        return True
    except Exception as e:
        logger.error(f"Failed to reset .env to example: {e}")
        return False
