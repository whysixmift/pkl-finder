from app.ai.base_provider import BaseLLMProvider, AIResult
from app.ai.openrouter_provider import OpenRouterProvider, SYSTEM_PROMPT

CANDIDATE_PROFILE = """
Pendidikan: SMK Negeri 2 Bekasi
Jurusan: Rekayasa Perangkat Lunak (RPL)
Keahlian: Python, Java, C++, Robotics, Embedded Systems, IoT, Android Studio, Git, FTC Robotics, Hack Club Mentor, PID Tuning, Business Development, Driver Robot
Minat Posisi: PKL / Internship
Kota Pilihan: Bekasi, Jakarta, Depok, Bogor, Tangerang, Remote
"""

# Abstract provider factory instance
evaluator: BaseLLMProvider = OpenRouterProvider()

# Compatibility alias for existing tests
OpenRouterEvaluator = OpenRouterProvider

# Export symbols for backward compatibility
__all__ = ["evaluator", "AIResult", "CANDIDATE_PROFILE", "SYSTEM_PROMPT", "OpenRouterEvaluator"]
