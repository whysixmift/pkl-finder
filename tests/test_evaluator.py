import unittest
from app.ai.evaluator import OpenRouterEvaluator

class TestOpenRouterEvaluator(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluator = OpenRouterEvaluator()

    def test_fallback_evaluate_matching_internship(self) -> None:
        """Test that a matching internship in a preferred location/role scores high."""
        res = self.evaluator._fallback_evaluate(
            title="Embedded System IoT Intern",
            company="RoboTech Indonesia",
            location="Jakarta",
            description="We are looking for an intern with programming skills in Python/C++ and microcontrollers like ESP32/STM32."
        )
        self.assertTrue(res.score >= 70, f"Expected high score, got: {res.score}")
        self.assertTrue(res.recommended, "Expected recommended to be True")
        self.assertIn("Python", res.matched_skills)
        self.assertIn("Embedded", res.matched_skills)

    def test_fallback_evaluate_senior_role(self) -> None:
        """Test that senior or full-time roles are penalized and rejected."""
        res = self.evaluator._fallback_evaluate(
            title="Senior Python Backend Developer",
            company="Enterprise Corp",
            location="Bekasi",
            description="Looking for a senior developer with 5+ years of experience to manage database APIs."
        )
        self.assertFalse(res.recommended, "Expected senior job to not be recommended")
        self.assertTrue(any("senior" in r.lower() for r in res.reason), "Expected reason to mention senior level")

    def test_fallback_evaluate_location_mismatch(self) -> None:
        """Test that out-of-boundary locations are noted in evaluation."""
        res = self.evaluator._fallback_evaluate(
            title="Python Intern",
            company="Tech Start",
            location="Surabaya",
            description="Looking for an intern to assist in web API development."
        )
        # Should flag location mismatch in reasons
        self.assertTrue(any("location" in r.lower() for r in res.reason), "Expected reason to flag location mismatch")

if __name__ == "__main__":
    unittest.main()
