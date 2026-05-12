"""Test CLI countdown and extension functionality."""

import sys
import threading
import time
from src.utils.logger import AutoRELogger
from src.utils.cli_interaction import CLIInteraction

def test_countdown_display():
    """Test that countdown displays every 2 minutes."""
    print("=" * 80)
    print("TEST 1: Countdown Display Every 2 Minutes")
    print("=" * 80)
    print("This test will show countdown updates.")
    print("The countdown should display immediately, then every 2 minutes.")
    print("Type some text and then 'END' to finish.")
    print("Or type 'EXTEND' to add 5 more minutes (up to 10 times).")
    print()

    logger = AutoRELogger()
    cli = CLIInteraction(logger, timeout=300)  # 5 minutes

    result = cli.request_input(
        prompt="Test prompt for countdown display",
        concise_prompt="Test countdown (type and end with 'END'):",
        multiline=True
    )

    print()
    print("=" * 80)
    print("TEST 1 RESULTS:")
    print("=" * 80)
    if result:
        print(f"✓ Received input: {result[:100]}...")
        print(f"✓ Extensions used: {cli.extensions_used}")
    else:
        print("✗ No input received (timeout or empty)")
    print()

def test_extension_limit():
    """Test that extension limit is enforced."""
    print("=" * 80)
    print("TEST 2: Extension Limit (10 max)")
    print("=" * 80)
    print("This test verifies the 10 extension limit.")
    print("Try typing 'EXTEND' multiple times to test the limit.")
    print()

    logger = AutoRELogger()
    cli = CLIInteraction(logger, timeout=60)  # Start with 1 minute for faster test

    result = cli.request_input(
        prompt="Test prompt for extension limit",
        concise_prompt="Test extensions (type 'EXTEND' to test, then 'END'):",
        multiline=True
    )

    print()
    print("=" * 80)
    print("TEST 2 RESULTS:")
    print("=" * 80)
    if result:
        print(f"✓ Received input")
        print(f"✓ Extensions used: {cli.extensions_used}/{cli.max_extensions}")
    else:
        print("✗ No input received (timeout or empty)")
    print()

def test_singleline_with_extension():
    """Test single-line input with extension."""
    print("=" * 80)
    print("TEST 3: Single-Line Input with Extension")
    print("=" * 80)
    print("This test uses single-line input mode.")
    print("Type 'EXTEND' to add time, or type your answer directly.")
    print()

    logger = AutoRELogger()
    cli = CLIInteraction(logger, timeout=120)  # 2 minutes

    result = cli.request_input(
        prompt="Test prompt for single-line input",
        concise_prompt="Single-line test (type answer or 'EXTEND'):",
        multiline=False
    )

    print()
    print("=" * 80)
    print("TEST 3 RESULTS:")
    print("=" * 80)
    if result:
        print(f"✓ Received input: {result}")
        print(f"✓ Extensions used: {cli.extensions_used}")
    else:
        print("✗ No input received (timeout or empty)")
    print()

def quick_demo():
    """Quick demonstration of the feature."""
    print("=" * 80)
    print("QUICK DEMO: CLI Countdown and Extension Feature")
    print("=" * 80)
    print()
    print("Features implemented:")
    print("  ✓ Live countdown every 2 minutes")
    print("  ✓ Up to 10 time extensions per session")
    print("  ✓ Each extension adds 5 minutes")
    print("  ✓ Maximum total time: 5 + (10 × 5) = 55 minutes")
    print()
    print("Instructions:")
    print("  1. Countdown displays immediately and every 2 minutes")
    print("  2. Type 'EXTEND' on a new line to add 5 minutes")
    print("  3. Type 'END' on a new line to finish (multiline mode)")
    print("  4. Extensions reset for each new input session")
    print()
    print("Let's try it! (Timeout set to 5 minutes for demo)")
    print()

    logger = AutoRELogger()
    cli = CLIInteraction(logger, timeout=300)

    result = cli.request_input(
        prompt="Demo of countdown and extension feature",
        concise_prompt="Try the countdown feature (type answers, 'EXTEND' to add time, 'END' to finish):",
        multiline=True
    )

    print()
    print("=" * 80)
    print("DEMO COMPLETE")
    print("=" * 80)
    if result:
        print(f"✓ You provided input ({len(result)} characters)")
        print(f"✓ You used {cli.extensions_used} extension(s)")
    else:
        print("✗ No input received")
    print()

if __name__ == "__main__":
    print()
    print("╔" + "═" * 78 + "╗")
    print("║" + " " * 20 + "CLI COUNTDOWN & EXTENSION TESTS" + " " * 26 + "║")
    print("╚" + "═" * 78 + "╝")
    print()

    if len(sys.argv) > 1:
        if sys.argv[1] == "1":
            test_countdown_display()
        elif sys.argv[1] == "2":
            test_extension_limit()
        elif sys.argv[1] == "3":
            test_singleline_with_extension()
        else:
            print("Usage: python test_cli_countdown_extension.py [1|2|3|demo]")
            print("  1: Test countdown display")
            print("  2: Test extension limit")
            print("  3: Test single-line input")
            print("  demo: Quick demonstration")
    else:
        quick_demo()

    print("All tests completed!")
    print()
