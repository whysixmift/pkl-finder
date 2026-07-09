import unittest
import os
import logging
from app.utils.logger import setup_logger

class TestUtilities(unittest.TestCase):
    def test_logger_initialization(self) -> None:
        """Test that logger configures handlers and levels correctly."""
        test_logger_name = "test_system_logger"
        logger = setup_logger(test_logger_name)
        
        self.assertEqual(logger.name, test_logger_name)
        self.assertTrue(len(logger.handlers) >= 1)
        
        # Verify handler types are setup properly
        handler_classes = [type(h).__name__ for h in logger.handlers]
        self.assertIn("StreamHandler", handler_classes)
        
        # Verify we can log to the logger without exception
        with self.assertLogs(test_logger_name, level="INFO") as cm:
            logger.info("Test validation message")
        
        self.assertEqual(cm.output, ["INFO:test_system_logger:Test validation message"])

if __name__ == "__main__":
    unittest.main()
