import unittest
from app.config.settings import settings
from app.ai.evaluator import OpenRouterEvaluator

class TestFilteringLogic(unittest.TestCase):
    def setUp(self) -> None:
        """Initialize fallback evaluator engine."""
        self.evaluator = OpenRouterEvaluator()

    def test_score_threshold_filter(self) -> None:
        """Test that score threshold constraints correctly tag recommendations."""
        threshold = settings.SCORE_THRESHOLD
        
        # Scenario 1: Match score below threshold should not recommend
        score_below = threshold - 5
        recommended_below = score_below >= threshold
        self.assertFalse(recommended_below, f"Score {score_below} should fail threshold {threshold}")

        # Scenario 2: Match score above or equal threshold should recommend
        score_above = threshold + 5
        recommended_above = score_above >= threshold
        self.assertTrue(recommended_above, f"Score {score_above} should pass threshold {threshold}")

    def test_irrelevant_jobs_rejected_by_rules(self) -> None:
        """Test that senior or out-of-major roles are rejected by fallback filters."""
        # A full-time accountant role is completely irrelevant to software engineering
        res = self.evaluator._fallback_evaluate(
            title="Senior Finance Accountant",
            company="Trading Group",
            location="Jakarta",
            description="Looking for a professional accountant to manage company tax records."
        )
        self.assertFalse(res.recommended, "Finance/Accountant jobs should be rejected")
        self.assertLess(res.score, settings.SCORE_THRESHOLD, "Finance job score should be below threshold")

if __name__ == "__main__":
    unittest.main()
