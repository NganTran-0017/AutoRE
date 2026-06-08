"""Test for EXTEND keyword filtering from user input."""

import unittest
from src.utils.cli_interaction import CLIInteraction
from src.utils.logger import AutoRELogger
import tempfile
import shutil


class TestExtendKeywordFilter(unittest.TestCase):
    """Test that EXTEND keyword is filtered from user input sent to agents."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.logger = AutoRELogger(project_name="test_project", log_dir=self.temp_dir)
        self.cli = CLIInteraction(self.logger, timeout=300)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_filter_extend_single_occurrence(self):
        """Test filtering single occurrence of EXTEND keyword."""
        text = "Please EXTEND the model to include delegation"
        filtered = self.cli._filter_extend_keyword(text)
        self.assertEqual(filtered, "Please the model to include delegation")
        self.assertNotIn("EXTEND", filtered)

    def test_filter_extend_multiple_occurrences(self):
        """Test filtering multiple occurrences of EXTEND keyword."""
        text = "EXTEND the model and EXTEND the permissions"
        filtered = self.cli._filter_extend_keyword(text)
        self.assertEqual(filtered, "the model and the permissions")
        self.assertNotIn("EXTEND", filtered)

    def test_filter_extend_case_sensitive(self):
        """Test that filtering is case-sensitive (only EXTEND, not extend)."""
        text = "Please extend the model and EXTEND permissions"
        filtered = self.cli._filter_extend_keyword(text)
        # 'extend' should remain, 'EXTEND' should be removed
        self.assertIn("extend", filtered)
        self.assertNotIn("EXTEND", filtered)
        self.assertEqual(filtered, "Please extend the model and permissions")

    def test_filter_extend_whole_word_only(self):
        """Test that only whole word EXTEND is filtered (not EXTENDED, EXTENDING, etc)."""
        text = "EXTEND the EXTENDED model while EXTENDING capabilities"
        filtered = self.cli._filter_extend_keyword(text)
        # Only 'EXTEND' should be removed, not 'EXTENDED' or 'EXTENDING'
        self.assertNotIn("EXTEND ", filtered)
        self.assertIn("EXTENDED", filtered)
        self.assertIn("EXTENDING", filtered)
        self.assertEqual(filtered, "the EXTENDED model while EXTENDING capabilities")

    def test_filter_extend_at_start(self):
        """Test filtering EXTEND at the beginning of text."""
        text = "EXTEND model to include new features"
        filtered = self.cli._filter_extend_keyword(text)
        self.assertEqual(filtered, "model to include new features")

    def test_filter_extend_at_end(self):
        """Test filtering EXTEND at the end of text."""
        text = "Please EXTEND"
        filtered = self.cli._filter_extend_keyword(text)
        self.assertEqual(filtered, "Please")

    def test_filter_extend_multiline(self):
        """Test filtering EXTEND from multiline text."""
        text = """Please review the requirements
EXTEND the delegation model
Add more constraints"""
        filtered = self.cli._filter_extend_keyword(text)
        expected = """Please review the requirements
the delegation model
Add more constraints"""
        self.assertEqual(filtered, expected)
        self.assertNotIn("EXTEND", filtered)

    def test_filter_extend_with_punctuation(self):
        """Test filtering EXTEND followed by punctuation."""
        text = "Should we EXTEND? Yes, EXTEND!"
        filtered = self.cli._filter_extend_keyword(text)
        # The word boundary should handle punctuation correctly
        self.assertNotIn("EXTEND", filtered)

    def test_filter_extend_empty_string(self):
        """Test filtering on empty string."""
        text = ""
        filtered = self.cli._filter_extend_keyword(text)
        self.assertEqual(filtered, "")

    def test_filter_extend_only_extend(self):
        """Test filtering when input is only EXTEND."""
        text = "EXTEND"
        filtered = self.cli._filter_extend_keyword(text)
        self.assertEqual(filtered, "")

    def test_filter_extend_double_spaces_cleanup(self):
        """Test that double spaces are cleaned up after filtering."""
        text = "Please  EXTEND  the model"
        filtered = self.cli._filter_extend_keyword(text)
        # Should not have multiple consecutive spaces
        self.assertNotIn("  ", filtered)
        self.assertEqual(filtered, "Please the model")


def run_manual_test():
    """Manual test demonstrating the filtering in action."""
    print("=" * 80)
    print("EXTEND Keyword Filtering - Manual Demonstration")
    print("=" * 80)
    print()

    temp_dir = tempfile.mkdtemp()
    try:
        logger = AutoRELogger(project_name="demo", log_dir=temp_dir)
        cli = CLIInteraction(logger, timeout=300)

        test_cases = [
            "Please EXTEND the model to include delegation",
            "EXTEND the permissions and EXTEND the roles",
            "Please extend (lowercase) but also EXTEND (uppercase)",
            "EXTEND EXTENDED EXTENDING",
            "I want to EXTEND this feature",
        ]

        print("Test Cases:")
        print("-" * 80)
        for i, text in enumerate(test_cases, 1):
            filtered = cli._filter_extend_keyword(text)
            print(f"{i}. Original: {text}")
            print(f"   Filtered: {filtered}")
            print()

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        # Run manual demonstration
        run_manual_test()
    else:
        # Run unit tests
        unittest.main()
