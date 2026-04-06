# AutoRE - Automated Requirement Engineering

A multi-agent system that uses requirement modeling and model checking for requirement verification. The system refines requirements to ensure consistency and unambiguity through an iterative process involving requirement analysis, formal modeling with Alloy, and automated verification.

## Overview

AutoRE implements a collaborative multi-agent architecture with two specialized agents:

- **Requirement Engineer (RE)**: Analyzes requirements, creates formal Alloy models, and refines models based on feedback
- **Evaluator**: Executes Alloy Analyzer, interprets results, generates feedback, and updates requirements

## Features

- Automated requirement analysis and documentation
- Formal modeling using Alloy specification language
- Automated verification with Alloy Analyzer
- Iterative refinement based on user feedback
- Memory-based learning to avoid repeated mistakes
- File-based user interaction for easy collaboration
- Comprehensive tracking of all iterations and changes

## Installation

### Prerequisites

- Python 3.7 or higher
- Java Runtime Environment (JRE) for Alloy Analyzer
- MetaGPT framework

### Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd autoRE
```

2. Install Python dependencies:
```bash
pip install -r requirements.txt
```

3. Verify Alloy Analyzer installation:
```bash
java -jar tools/alloy.jar --version
```

## Usage

### Basic Usage

Run the system with an input requirements file:

```bash
python main.py example_input.txt
```

### Advanced Usage

Specify maximum iterations:
```bash
python main.py my_requirements.txt --max-iterations 15
```

Use verbose output:
```bash
python main.py my_requirements.txt --verbose
```

## Workflow

The system follows this iterative workflow:

1. **Initial Analysis** (Step 1)
   - RE agent analyzes raw requirements
   - Produces structured requirements document
   - Lists key assumptions

2. **User Clarification** (Step 2)
   - System requests clarification on assumptions
   - User provides feedback via `user_feedback.txt`

3. **Model Creation** (Step 3)
   - RE agent builds initial Alloy model
   - Model captures formal specifications

4. **Verification** (Step 4)
   - Evaluator runs Alloy Analyzer
   - Checks for syntax errors, counterexamples, and satisfying instances

5. **Evaluation Feedback** (Steps 5-6)
   - Evaluator interprets analyzer results
   - Generates feedback for improvements
   - Requests user review and additional scenarios

6. **User Feedback** (Step 6 continued)
   - User reviews evaluation
   - Provides feedback or additional scenarios
   - Indicates satisfaction when complete

7. **Requirement Updates** (Step 7)
   - Evaluator updates English requirements
   - Incorporates user feedback

8. **Model Updates** (Step 8)
   - RE agent refines Alloy model
   - Addresses identified issues

9. **Iteration**
   - Steps 4-8 repeat until:
     - No syntax errors
     - No counterexamples
     - Satisfying instances exist
     - User is satisfied

## User Interaction

### CLI-Based Communication

AutoRE uses **interactive CLI** for real-time user input:

**How it works:**
1. System displays prompts directly in terminal
2. You type responses in the CLI
3. End multi-line input with `END` on a new line
4. All interactions logged to `outputlog/MMDDYY.log`

**Example:**
```
Your response (type your feedback, then 'END' on a new line):
> Members cannot reserve books they already borrowed.
> Reservations cancelled if membership expires.
> END
```

**Timeout:**
- 5-minute window for each response
- System auto-proceeds if no input received
- Can provide feedback in next iteration

**Viewing Files:**
- Requirements: `ReqsDoc/Reqs_*.txt`
- Models: `AlloyModels/AlloyModel__*.als`
- Results: `AnalyzerOutput/*/`
- Logs: `outputlog/MMDDYY.log`

See [CLI_USAGE.md](Documentations/CLI_USAGE.md) for detailed instructions.

## Project Structure

```
autoRE/
├── src/
│   ├── agents/
│   │   ├── requirement_engineer.py  # RE agent implementation
│   │   └── evaluator.py             # Evaluator agent implementation
│   ├── utils/
│   │   ├── memory.py                # Memory management system
│   │   ├── file_manager.py          # File operations
│   │   ├── alloy_executor.py        # Alloy Analyzer integration
│   │   ├── logger.py                # Session logging
│   │   └── cli_interaction.py       # CLI user interaction
│   └── workflow.py                   # Main workflow orchestrator
├── ReqsDoc/                          # Requirements documents by iteration
├── AlloyModels/                      # Alloy models by iteration
├── AnalyzerOutput/                   # Alloy Analyzer results
│   └── [iteration]/                  # Results per iteration
├── memory/                           # Agent memory files
├── outputlog/                        # Session logs (MMDDYY.log)
├── tools/
│   └── alloy.jar                     # Alloy Analyzer
├── Documentations/                   # Documentation files
│   ├── CLI_USAGE.md                 # CLI interaction guide
│   ├── QUICKSTART.md                # Quick start guide
│   └── IMPLEMENTATION_SUMMARY.md    # Technical details
├── prompts/                          # Agent system prompts
│   ├── RE_prompt.txt                # RE agent prompt
│   └── Evaluator_prompt.txt         # Evaluator prompt
├── config.yaml                       # Configuration file
├── requirements.txt                  # Python dependencies
├── main.py                          # Main entry point
└── example_input.txt                # Example requirements file
```

## Output Files

### Requirements Documents
- Location: `ReqsDoc/Reqs_[iteration].txt`
- Contains: Structured requirements with assumptions and constraints

### Alloy Models
- Location: `AlloyModels/AlloyModel__[iteration].als`
- Contains: Formal Alloy specifications

### Analyzer Output
- Location: `AnalyzerOutput/[iteration]/`
- Contains: JSON files with verification results
  - Syntax errors
  - Counterexamples
  - Satisfying instances

### Memory Files
- Location: `memory/`
- Files:
  - `RE_memory.json`: Requirement Engineer's memory
  - `Evaluator_memory.json`: Evaluator's memory
- Contains: Iteration history, lessons learned, detailed tracking

### Session Logs
- Location: `outputlog/MMDDYY.log`
- Format: Date-based filenames (e.g., `040626.log` for April 6, 2026)
- Contains:
  - All terminal output and user inputs
  - Full prompts (detailed versions)
  - Complete user responses
  - File update notifications
  - Timestamps for all events
  - Session start/end markers
- **Complete audit trail of entire workflow**

## Configuration

Edit `config.yaml` to customize:

```yaml
alloy:
  jar_path: "tools/alloy.jar"
  execution_timeout: 300

workflow:
  max_iterations: 10

agents:
  requirement_engineer:
    max_lessons_to_remember: 10
  evaluator:
    max_feedback_history: 5
```

## Example

See `example_input.txt` for a sample requirements file for a Library Management System.

Run the example:
```bash
python main.py example_input.txt
```

## Troubleshooting

**Alloy Analyzer not found:**
- Ensure `tools/alloy.jar` exists
- Verify Java is installed: `java -version`

**MetaGPT import errors:**
- Install MetaGPT: `pip install metagpt`
- Ensure API keys are configured for LLM access

**Workflow hangs waiting for feedback:**
- Create `user_feedback.txt` with your response
- Ensure file has content before the system reads it

## Development

### Adding New Features

1. Extend agent actions in `src/agents/`
2. Update workflow in `src/workflow.py`
3. Add new utilities in `src/utils/`

### Testing

Run individual components:
```bash
python -m src.workflow example_input.txt
```

### Memory Management

Memory is automatically managed but can be manually inspected:
```bash
cat memory/RE_memory.json
cat memory/Evaluator_memory.json
```

## Contributing

Contributions are welcome! Please ensure:
- Code follows existing structure
- New features include documentation
- Memory management is properly implemented

## License

[To be determined]

## Citation

If you use AutoRE in your research, please cite:
```
[Citation information to be added]
```

## Contact

For questions and support:
- Create an issue in the repository
- [Contact information to be added]
