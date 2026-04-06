# AutoRE Quick Start Guide

This guide will help you get started with AutoRE in 5 minutes.

## Step 1: Install Dependencies

```bash
# Install Python packages
pip install -r requirements.txt
```

## Step 2: Verify Alloy Analyzer

```bash
# Check that Alloy is ready
java -jar tools/alloy.jar --help
```

## Step 3: Run the Example

```bash
# Start the workflow with the example input
python main.py example_input.txt
```

## Step 4: Interact with the System

### Initial Clarification (Step 1-2)

1. The system will analyze the requirements
2. A prompt will appear in `user_prompt.txt`
3. Create a file named `user_feedback.txt` with your clarifications

Example `user_feedback.txt`:
```
Clarification 1: A member cannot reserve a book they currently have borrowed.
Clarification 2: Members can only reserve books that are currently checked out.
Clarification 3: Reservations are cancelled if membership expires.
Clarification 4: Reserved books must be picked up within 3 days.
```

### Model Verification (Steps 3-8)

The system will:
1. Build an Alloy model (Step 3)
2. Run verification (Step 4)
3. Show results in `user_prompt.txt` (Steps 5-6)
4. Wait for your feedback in `user_feedback.txt`

Example feedback after verification:
```
The model looks good. Please also check the following scenario:

Scenario: Member with overdue book tries to reserve
Check: Verify that members with overdue books cannot make reservations
Expected: Reservation should be rejected

Scenario: Maximum reservations
Check: Verify that a member cannot have more than 2 active reservations
Expected: Third reservation attempt should fail
```

### Indicating Satisfaction

When you're happy with the results, respond with:
```
SATISFIED
```

## Step 5: Review Results

After completion, check these directories:

- `ReqsDoc/`: All requirement versions
- `AlloyModels/`: All Alloy model versions
- `AnalyzerOutput/`: Verification results by iteration
- `memory/`: Agent memory and learning

## Understanding the Output

### Requirements Documents
Location: `ReqsDoc/Reqs_[iteration].txt`

These contain:
- System overview
- Functional requirements
- Key concepts and entities
- Assumptions and constraints

### Alloy Models
Location: `AlloyModels/AlloyModel__[iteration].als`

These contain formal specifications with:
- Signatures (concepts/entities)
- Relations (connections between entities)
- Facts (constraints that always hold)
- Predicates (scenarios to check)
- Assertions (properties to verify)

### Analyzer Output
Location: `AnalyzerOutput/[iteration]/`

JSON files containing:
- **Syntax errors**: Issues in the model syntax
- **Counterexamples**: Cases where assertions fail
- **Instances**: Valid scenarios that satisfy the model

## Common Workflows

### Quick Test Run
```bash
python main.py example_input.txt --max-iterations 3
```

### Full Analysis
```bash
python main.py my_requirements.txt --max-iterations 15
```

### Verbose Output
```bash
python main.py example_input.txt --verbose
```

## Tips

1. **Be Specific**: Provide clear, detailed clarifications
2. **Think of Edge Cases**: Suggest scenarios that test boundaries
3. **Review Carefully**: Check each iteration's output before responding
4. **Use SATISFIED**: Don't iterate unnecessarily; stop when requirements are clear

## Troubleshooting

**System waiting forever:**
- Make sure `user_feedback.txt` exists and has content
- File must be in the project root directory

**MetaGPT errors:**
- Ensure you've installed metagpt: `pip install metagpt`
- Configure your LLM API keys (check MetaGPT documentation)

**Alloy Analyzer errors:**
- Verify Java is installed: `java -version`
- Check that `tools/alloy.jar` exists

**Want to start over:**
```bash
# Archive current results
mkdir archive_$(date +%Y%m%d_%H%M%S)
mv ReqsDoc AlloyModels AnalyzerOutput memory archive_$(date +%Y%m%d_%H%M%S)/

# Create fresh directories
mkdir ReqsDoc AlloyModels AnalyzerOutput memory

# Run again
python main.py example_input.txt
```

## Next Steps

- Read the full [README.md](README.md) for detailed information
- Customize [config.yaml](config.yaml) for your needs
- Create your own requirements file following `example_input.txt` format
- Explore agent memory in `memory/` to understand learning

## Support

For issues or questions:
1. Check [README.md](README.md) Troubleshooting section
2. Review example files
3. Open an issue in the repository