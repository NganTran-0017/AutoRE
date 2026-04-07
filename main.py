#!/usr/bin/env python3
"""
AutoRE - Automated Requirement Engineering System
Main entry point for the application.
"""
import asyncio
import argparse
import sys
from pathlib import Path

from src.workflow import AutoREWorkflow


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="AutoRE - Multi-agent Requirement Engineering System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example usage:
  python main.py example_input.txt
  python main.py my_requirements.txt --max-iterations 15
  python main.py my_requirements.txt --verbose

The system will:
1. Analyze your requirements and ask for clarification
2. Build an Alloy model
3. Verify the model using Alloy Analyzer
4. Iterate based on your feedback until convergence

User interaction is CLI-based:
- Prompts appear directly in the terminal
- Type your feedback and end with 'END' on a new line
- All interactions logged to outputlog/MMDDYY.log
        """
    )

    parser.add_argument(
        "input_file",
        type=str,
        help="Path to initial requirements file"
    )

    parser.add_argument(
        "--max-iterations",
        type=int,
        default=10,
        help="Maximum number of refinement iterations (default: 10)"
    )

    parser.add_argument(
        "--base-dir",
        type=str,
        default=".",
        help="Base directory for the project (default: current directory)"
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output"
    )

    args = parser.parse_args()

    # Validate input file
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"Error: Input file not found: {args.input_file}")
        sys.exit(1)

    # Create workflow
    workflow = AutoREWorkflow(base_dir=args.base_dir)

    # Run workflow
    try:
        asyncio.run(workflow.run(
            input_file=str(input_path),
            max_iterations=args.max_iterations
        ))
    except KeyboardInterrupt:
        print("\n\nWorkflow interrupted by user.")
        print("Progress has been saved. You can resume by running the workflow again.")
        sys.exit(0)
    except Exception as e:
        print(f"\n\nError running workflow: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
