import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from app.utils.logger import logger

class BaseAgent:
    """Base class for all feature-specific autonomous agents in PKL Finder."""
    
    def __init__(self, agent_name: str, feature_description: str) -> None:
        self.agent_name = agent_name
        self.feature_description = feature_description
        self.last_run_time: Optional[datetime] = None
        self.last_execution_duration: float = 0.0
        self.total_runs: int = 0
        self.successful_runs: int = 0
        self.failed_runs: int = 0
        self.last_error: Optional[str] = None
        self.is_running: bool = False

    def mark_start(self) -> float:
        """Mark agent execution start."""
        self.is_running = True
        self.total_runs += 1
        return time.time()

    def mark_success(self, start_time: float) -> None:
        """Mark agent execution successful."""
        duration = time.time() - start_time
        self.last_execution_duration = round(duration, 3)
        self.last_run_time = datetime.now(timezone.utc).replace(tzinfo=None)
        self.successful_runs += 1
        self.last_error = None
        self.is_running = False
        logger.info(f"[{self.agent_name}] Execution completed in {self.last_execution_duration}s")

    def mark_failure(self, start_time: float, error: Exception) -> None:
        """Mark agent execution failure with logged error details."""
        duration = time.time() - start_time
        self.last_execution_duration = round(duration, 3)
        self.last_run_time = datetime.now(timezone.utc).replace(tzinfo=None)
        self.failed_runs += 1
        self.last_error = str(error)
        self.is_running = False
        logger.error(f"[{self.agent_name}] Execution failed after {self.last_execution_duration}s: {error}", exc_info=True)

    def get_status(self) -> Dict[str, Any]:
        """Telemetry diagnostics data for agent monitoring and web admin dashboard."""
        return {
            "name": self.agent_name,
            "feature": self.feature_description,
            "is_running": self.is_running,
            "total_runs": self.total_runs,
            "successful_runs": self.successful_runs,
            "failed_runs": self.failed_runs,
            "last_run": self.last_run_time.isoformat() if self.last_run_time else None,
            "duration_sec": self.last_execution_duration,
            "last_error": self.last_error,
            "status": "Running" if self.is_running else ("Error" if self.last_error else "Idle / Healthy")
        }
