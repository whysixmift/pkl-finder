import os
import sys
import json
import time
import asyncio
import difflib
import subprocess
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple, Callable, Awaitable

from app.agents.base_agent import BaseAgent
from app.ai.evaluator import evaluator
from app.config.settings import settings
from app.utils.logger import logger

def get_project_root() -> str:
    """Returns the absolute path to the project root directory."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def trigger_service_restart(delay_seconds: float = 2.5) -> None:
    """Schedules a delayed service restart so Telegram responses finish sending."""
    async def _worker():
        await asyncio.sleep(delay_seconds)
        logger.info("Self-healing: Triggering systemctl restart pkl-finder...")
        try:
            proc = await asyncio.create_subprocess_exec(
                "systemctl", "restart", "pkl-finder",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            await proc.wait()
            logger.info("Self-healing: Service restart command executed successfully.")
        except Exception as e:
            logger.warning(f"Self-healing: Service restart notice (systemctl not available or error): {e}")

    asyncio.create_task(_worker())


class SelfHealingAgent(BaseAgent):
    """Autonomous Self-Healing Agent that diagnoses bug reports, formulates code fixes,
    verifies them via the automated test suite, commits them, and triggers deployment."""

    def __init__(self) -> None:
        super().__init__(
            agent_name="self_healing_agent",
            feature_description="Autonomous Bug Diagnostics, Code Patching, Regression Testing & Deployment"
        )
        self.history_file = os.path.join(get_project_root(), "data", "self_healing_history.json")

    def get_recent_error_logs(self, max_lines: int = 40) -> str:
        """Fetch recent error and warning logs from the application log file or journalctl."""
        project_root = get_project_root()
        log_path = os.path.join(project_root, "logs", "pkl_finder.log")
        
        lines: List[str] = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                    all_lines = f.readlines()
                    lines = all_lines[-max_lines:]
            except Exception as e:
                logger.warning(f"Could not read pkl_finder.log: {e}")

        # If log file is empty or missing, try journalctl if on Linux
        if not lines:
            try:
                res = subprocess.run(
                    ["journalctl", "-u", "pkl-finder", "-n", str(max_lines), "--no-pager"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if res.returncode == 0 and res.stdout:
                    lines = res.stdout.splitlines(keepends=True)
            except Exception:
                pass

        # Filter lines to prioritize errors/tracebacks
        error_lines = [
            l for l in lines
            if any(k in l.lower() for k in ["error", "exception", "traceback", "failed", "critical", "warning"])
        ]
        return "".join(error_lines if error_lines else lines[-max_lines:])

    def find_relevant_source_context(
        self,
        bug_report: str,
        log_snippet: str
    ) -> Tuple[Optional[str], str]:
        """Detect the file mentioned in the bug or traceback, and extract relevant code snippet."""
        project_root = get_project_root()
        combined = f"{bug_report}\n{log_snippet}"

        # Standard project source files to check
        known_files = [
            "app/bot/handlers.py",
            "app/bot/admin_bot.py",
            "app/services/job_service.py",
            "app/services/cv_service.py",
            "app/services/email_service.py",
            "app/services/google_auth_service.py",
            "app/services/crawler_service.py",
            "app/services/discovery_service.py",
            "app/scraper/glints.py",
            "app/scraper/linkedin.py",
            "app/scraper/indeed.py",
            "app/scraper/jobstreet.py",
            "app/scraper/kalibrr.py",
            "app/scraper/google_jobs.py",
            "app/scraper/base.py",
            "app/ai/openrouter_provider.py",
            "app/database/models.py",
            "main.py",
        ]

        target_file: Optional[str] = None
        for kf in known_files:
            if kf.lower() in combined.lower() or os.path.basename(kf).lower() in combined.lower():
                target_file = kf
                break

        # Fallback keyword matching
        if not target_file:
            if any(term in combined.lower() for term in ["psutil", "cpu", "ram", "system_handler", "doctor"]):
                target_file = "app/bot/handlers.py"
            elif any(term in combined.lower() for term in ["ambiguous column", "get_latest_jobs", "scraping", "scraper"]):
                target_file = "app/services/job_service.py"
            elif any(term in combined.lower() for term in ["admin", "pending", "approve", "reject", "whitelist"]):
                target_file = "app/bot/admin_bot.py"
            elif any(term in combined.lower() for term in ["cv", "resume", "pdf", "docx"]):
                target_file = "app/services/cv_service.py"
            elif any(term in combined.lower() for term in ["google", "oauth", "sso"]):
                target_file = "app/services/google_auth_service.py"

        if not target_file:
            target_file = "app/bot/handlers.py"

        full_path = os.path.join(project_root, target_file)
        code_context = ""
        if os.path.exists(full_path):
            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    # Return reasonable preview length for LLM context
                    code_context = content[:5000]
            except Exception as e:
                logger.warning(f"Could not read source context from {full_path}: {e}")

        return target_file, code_context

    async def apply_code_patch(
        self,
        file_path: str,
        target: str,
        replacement: str
    ) -> Tuple[bool, str, str]:
        """Applies targeted replacement to source file and returns unified diff.
        Returns:
            Tuple[success: bool, diff: str, original_content: str]
        """
        project_root = get_project_root()
        full_path = os.path.join(project_root, file_path)

        if not os.path.exists(full_path):
            return False, f"File {file_path} tidak ditemukan.", ""

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                original = f.read()

            if target not in original:
                # Try normalized whitespace match
                normalized_target = "\n".join(line.rstrip() for line in target.strip().splitlines())
                if normalized_target in original:
                    target = normalized_target
                else:
                    return False, f"Target kode tidak cocok persis di dalam file {file_path}.", original

            new_content = original.replace(target, replacement, 1)

            # Generate diff
            diff = "".join(
                difflib.unified_diff(
                    original.splitlines(keepends=True),
                    new_content.splitlines(keepends=True),
                    fromfile=f"a/{file_path}",
                    tofile=f"b/{file_path}",
                    n=3
                )
            )

            with open(full_path, "w", encoding="utf-8") as f:
                f.write(new_content)

            return True, diff, original
        except Exception as e:
            return False, f"Gagal menerapkan patch ke file: {e}", ""

    async def run_regression_tests(self, timeout_sec: float = 45.0) -> Tuple[bool, str]:
        """Runs pytest suite to verify that the patch fixes the issue and doesn't break regressions."""
        project_root = get_project_root()
        pytest_bin = os.path.join(project_root, ".venv", "bin", "pytest")
        if not os.path.exists(pytest_bin):
            pytest_bin = sys.executable

        cmd = [pytest_bin, "tests/test_career_and_admin_bot.py", "-q"]
        logger.info(f"Self-healing: Running verification test command: {' '.join(cmd)}")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=project_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
            output = (stdout.decode(errors="ignore") + "\n" + stderr.decode(errors="ignore")).strip()
            success = (proc.returncode == 0)
            return success, output
        except asyncio.TimeoutError:
            return False, "Pytest execution timed out (45s limit exceeded)."
        except Exception as e:
            return False, f"Gagal menjalankan pytest: {e}"

    async def commit_and_deploy(
        self,
        file_path: str,
        explanation: str
    ) -> Tuple[bool, str, Optional[str]]:
        """Commit changes to git repository, attempt push, and trigger systemd service reload."""
        project_root = get_project_root()
        commit_msg = f"auto-fix: {explanation} [Self-Healing Agent]"

        # 1. git add
        add_proc = await asyncio.create_subprocess_exec(
            "git", "add", file_path,
            cwd=project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        await add_proc.communicate()

        # 2. git commit
        commit_proc = await asyncio.create_subprocess_exec(
            "git", "commit", "-m", commit_msg,
            cwd=project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        await commit_proc.communicate()

        # 3. get short hash
        hash_proc = await asyncio.create_subprocess_exec(
            "git", "rev-parse", "--short", "HEAD",
            cwd=project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        out_hash, _ = await hash_proc.communicate()
        commit_hash = out_hash.decode().strip() if out_hash else None

        # 4. git push (non-fatal if credentials are not configured)
        try:
            push_proc = await asyncio.create_subprocess_exec(
                "git", "push", "origin", "main",
                cwd=project_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            await asyncio.wait_for(push_proc.wait(), timeout=10.0)
        except Exception as pe:
            logger.debug(f"Git push notice during auto-fix: {pe}")

        # 5. Trigger delayed service restart
        trigger_service_restart(delay_seconds=2.5)

        return True, "Commit dibuat dan service direfresh.", commit_hash

    async def revert_file(self, file_path: str, backup_content: Optional[str] = None) -> None:
        """Revert modified file to baseline state."""
        project_root = get_project_root()
        full_path = os.path.join(project_root, file_path)
        if backup_content is not None and os.path.exists(full_path):
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(backup_content)
        else:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "git", "checkout", "--", file_path,
                    cwd=project_root
                )
                await proc.wait()
            except Exception as e:
                logger.warning(f"Could not revert file via git: {e}")

    async def rollback(self, commit_hash: Optional[str] = None) -> Tuple[bool, str]:
        """Rollback latest auto-fix commit and restart service."""
        project_root = get_project_root()
        try:
            if commit_hash:
                proc = await asyncio.create_subprocess_exec(
                    "git", "revert", "--no-edit", commit_hash,
                    cwd=project_root,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    "git", "revert", "--no-edit", "HEAD",
                    cwd=project_root,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                trigger_service_restart(delay_seconds=2.0)
                return True, "Rollback commit berhasil diterapkan dan service direstart."
            else:
                # Try checkout uncommitted
                proc2 = await asyncio.create_subprocess_exec(
                    "git", "checkout", "--", ".",
                    cwd=project_root
                )
                await proc2.wait()
                trigger_service_restart(delay_seconds=2.0)
                return True, "Perubahan kode dibatalkan dan service direload."
        except Exception as e:
            return False, f"Rollback gagal: {e}"

    def record_history(self, event: Dict[str, Any]) -> None:
        """Persist self-healing event to JSON history log."""
        try:
            os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
            history = []
            if os.path.exists(self.history_file):
                with open(self.history_file, "r", encoding="utf-8") as f:
                    try:
                        history = json.load(f)
                    except Exception:
                        history = []
            history.insert(0, event)
            # Retain last 30 events
            history = history[:30]
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Could not record self-healing history: {e}")

    def get_history(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Retrieve recent self-healing events."""
        if not os.path.exists(self.history_file):
            return []
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                history = json.load(f)
                return history[:limit]
        except Exception:
            return []

    async def diagnose_and_heal(
        self,
        bug_report: str,
        progress_callback: Optional[Callable[[str], Awaitable[None]]] = None
    ) -> Dict[str, Any]:
        """End-to-end auto-fix pipeline:
        1. Context & log gathering
        2. AI patch formulation
        3. Precision patch application
        4. Test suite validation
        5. Git commit & live deployment
        """
        start_time = self.mark_start()
        backup_content: Optional[str] = None
        target_file: Optional[str] = None

        try:
            # Step 1: Log & Code Context
            if progress_callback:
                await progress_callback("🔍 <i>Menganalisis laporan bug & membaca log sistem...</i>")

            recent_logs = self.get_recent_error_logs(max_lines=35)
            target_file, code_context = self.find_relevant_source_context(bug_report, recent_logs)

            # Step 2: Formulate Patch via AI
            if progress_callback:
                await progress_callback(f"🧠 <i>Merumuskan perbaikan kode dengan AI ({settings.PRIMARY_MODEL})...</i>")

            patch_data = await evaluator.generate_code_patch(
                bug_report=bug_report,
                log_context=recent_logs,
                code_context=code_context,
                file_hint=target_file
            )

            file_path = patch_data.get("file_path") or target_file
            target = patch_data.get("target", "")
            replacement = patch_data.get("replacement", "")
            diagnosis = patch_data.get("diagnosis", "Diagnosa bug otomatis")
            explanation = patch_data.get("explanation", "Perbaikan bug otomatis")

            if not target or not replacement:
                raise ValueError("AI tidak menghasilkan target atau replacement kode yang valid.")

            # Step 3: Apply Patch
            if progress_callback:
                await progress_callback(f"📝 <i>Menerapkan patch pada <code>{file_path}</code>...</i>")

            success_patch, diff, backup_content = await self.apply_code_patch(file_path, target, replacement)
            if not success_patch:
                raise RuntimeError(diff)

            # Step 4: Verification via Pytest
            if progress_callback:
                await progress_callback("🧪 <i>Memverifikasi integritas sistem dengan test suite (pytest)...</i>")

            test_passed, test_output = await self.run_regression_tests(timeout_sec=40.0)
            if not test_passed:
                # Revert immediately!
                await self.revert_file(file_path, backup_content)
                raise RuntimeError(f"Verifikasi test gagal! Perubahan dibatalkan secara otomatis:\n{test_output[:300]}")

            # Step 5: Git Commit & Deploy
            if progress_callback:
                await progress_callback("🚀 <i>Test berhasil! Menyimpan commit dan me-reload service...</i>")

            commit_ok, deploy_msg, commit_hash = await self.commit_and_deploy(file_path, explanation)

            self.mark_success(start_time)
            result = {
                "success": True,
                "file_path": file_path,
                "diagnosis": diagnosis,
                "explanation": explanation,
                "diff": diff,
                "test_output": test_output[:400],
                "commit_hash": commit_hash,
                "deployed": True,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            self.record_history(result)
            return result

        except Exception as e:
            self.mark_failure(start_time, e)
            if target_file and backup_content:
                await self.revert_file(target_file, backup_content)

            err_str = str(e)
            result = {
                "success": False,
                "file_path": target_file or "unknown",
                "diagnosis": "Gagal menyelesaikan proses self-healing",
                "explanation": err_str,
                "diff": "",
                "test_output": "",
                "commit_hash": None,
                "deployed": False,
                "error": err_str,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            self.record_history(result)
            return result


# Singleton instance
self_healing_agent = SelfHealingAgent()
