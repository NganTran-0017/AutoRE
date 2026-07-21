# Repository Guidelines

## Project Structure & Module Organization

`main.py` is the CLI entry point. Core orchestration lives in `src/workflow.py`; agent roles are under `src/agents/`, and shared file, memory, logging, CLI, and Alloy helpers are under `src/utils/`. Store agent instructions in `prompts/`, maintenance utilities in `scripts/`, and the bundled Alloy analyzer in `tools/alloy.jar`. Tests are primarily in `test/`, with a few integration or diagnostic `test_*.py` files at the repository root. User documentation belongs in `docs/` or `Documentations/`. Runtime artifacts such as requirement revisions, Alloy models, analyzer output, memory, and logs are generated data and should not be mixed with source changes.

## Build, Test, and Development Commands

- `pip install -r requirements.txt` installs application dependencies.
- `python main.py example_input.txt` runs the complete workflow with sample requirements.
- `python main.py input.txt --max-iterations 15` limits refinement cycles.
- `python main.py --resume` resumes saved workflow state; use `--list-iterations` to inspect checkpoints.
- `pytest -q` runs the full automated suite; target one area with `pytest test/test_qa_parser.py -q`.
- `java -jar tools/alloy.jar --help` verifies Java and the bundled analyzer are available.

There is no separate compilation step; validate changes through tests and a representative CLI run.

## Coding Style & Naming Conventions

Use four-space indentation and standard Python/PEP 8 layout. Name classes in `PascalCase`, functions and variables in `snake_case`, constants in `UPPER_CASE`, and internal helpers with a leading underscore. Add type hints and concise Google-style docstrings (`Args`, `Returns`) to public APIs. Prefer `pathlib.Path` for filesystem work and preserve the existing async/`await` patterns in agents and workflow steps. No formatter or linter is currently enforced, so keep imports organized and changes locally consistent.
Prioritze re-use helper functions and avoid expanding the codebase unnecessarily.

## Testing Guidelines

Use `pytest` for new tests; existing `unittest` cases remain supported. Name files `test_<behavior>.py` and functions `test_<expected_outcome>`. Use fixtures and `unittest.mock` to isolate LLM, filesystem, CLI, and Alloy interactions. Mark coroutine tests with `@pytest.mark.asyncio`. Add regression coverage for bug fixes, especially workflow convergence, parser behavior, persisted memory, and cross-iteration state.

## Commit & Pull Request Guidelines

Recent commits use imperative, sentence-style subjects such as `Enhance syntax error handling...`; keep the first line focused and explain complex behavior in the body. Pull requests should summarize the problem and solution, list verification commands, link relevant issues, and call out configuration or generated-artifact changes. Include terminal output or screenshots only when CLI behavior or user-facing output changes.

## Security & Configuration Tips

Copy `.env.example` for local secrets and never commit API keys. Review `config.yaml` changes carefully and avoid committing private prompts, logs, or generated requirement data.
