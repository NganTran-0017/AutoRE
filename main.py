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


async def main():
    """Run AutoRE workflow."""
    parser = argparse.ArgumentParser(description="AutoRE - Automated Requirements Engineering")
    parser.add_argument("input_file", nargs="?", help="Input requirements file")
    parser.add_argument("--max-iterations", type=int, default=10,
                       help="Maximum refinement iterations (or additional iterations in resume mode)")
    parser.add_argument("--timeout", type=int, default=None,
                       help="User input timeout in seconds (default: config.yaml's "
                            "user_interaction.response_timeout, or 300 if unset)")
    parser.add_argument("--project", default="default",
                       help="Project name for memory isolation")
    parser.add_argument("--resume", action="store_true",
                       help="Resume from latest Alloy model and requirements")
    parser.add_argument("--resume-iteration", type=int, default=None,
                       help="Specific iteration to resume from (default: latest)")
    parser.add_argument("--list-iterations", action="store_true",
                       help="List available iterations and exit")

    args = parser.parse_args()

    # Handle --list-iterations flag
    if args.list_iterations:
        from src.utils.file_manager import FileManager
        file_manager = FileManager()

        req_versions = file_manager.get_all_requirement_versions()
        model_versions = file_manager.get_all_model_versions()

        if not req_versions and not model_versions:
            print("No iterations found.")
            return

        all_iterations = sorted(set(req_versions) | set(model_versions))

        print("\nAvailable iterations:")
        print(f"{'Iteration':<12} {'Requirements':<15} {'Model':<15}")
        print("-" * 45)
        for i in all_iterations:
            req_mark = "✓" if i in req_versions else "✗"
            model_mark = "✓" if i in model_versions else "✗"
            print(f"{i:<12} {req_mark:<15} {model_mark:<15}")

        print(f"\nTotal iterations: {len(all_iterations)}")
        return

    # Validate arguments
    if not args.resume and not args.input_file:
        parser.error("input_file is required when not using --resume")

    if args.resume and args.input_file:
        print("Warning: --resume specified, input_file will be ignored")

    if not args.resume:
        # Validate input file
        input_path = Path(args.input_file)
        if not input_path.exists():
            print(f"Error: Input file not found: {args.input_file}")
            sys.exit(1)
        input_file = str(input_path)
    else:
        input_file = None

    # Create workflow
    workflow = AutoREWorkflow(
        max_iterations=args.max_iterations,
        timeout=args.timeout,
        project_name=args.project,
        input_file=input_file
    )

    # Run workflow
    try:
        await workflow.run(
            resume_mode=args.resume,
            resume_iteration=args.resume_iteration
        )
    except KeyboardInterrupt:
        print("\n\nWorkflow interrupted by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
