"""Quick test for EXTEND feature fix."""

import sys
from src.utils.logger import AutoRELogger
from src.utils.cli_interaction import CLIInteraction

def test_extend_countdown():
    """Test that countdown displays after EXTEND command."""

    print("=" * 80)
    print("EXTEND Feature Test")
    print("=" * 80)
    print()
    print("This test verifies the EXTEND feature works correctly:")
    print("  1. Countdown should display immediately at start")
    print("  2. When you type 'EXTEND', time should be added")
    print("  3. Countdown should display again within ~1.5 seconds after EXTEND")
    print("  4. Type more text and 'END' to finish")
    print()
    print("Try typing 'EXTEND' once or twice to verify the countdown appears")
    print()

    logger = AutoRELogger()
    cli = CLIInteraction(logger, timeout=30)  # 2 minutes for quick test

    result = cli.request_input(
        prompt="Test EXTEND feature",
        concise_prompt="Type something, use 'EXTEND' to add time, then 'END':",
        multiline=True
    )

    print()
    print("=" * 80)
    print("TEST RESULTS:")
    print("=" * 80)
    if result:
        print(f"✓ Received input: {len(result)} characters")
        print(f"✓ Extensions used: {cli.extensions_used}")
        print()
        print("Expected behavior:")
        print("  - Countdown appeared at start")
        print("  - After typing 'EXTEND', countdown appeared within ~1.5 seconds")
        print("  - Time was correctly extended")
    else:
        print("✗ No input received (timeout)")
    print()

if __name__ == "__main__":
    test_extend_countdown()
