# AutoRE Setup Guide

## OpenAI API Integration

This guide will help you set up AutoRE to work with OpenAI's API.

### Prerequisites

- Python 3.7 or higher
- An OpenAI API account and API key

### Step 1: Get Your OpenAI API Key

1. Go to [https://platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. Sign in or create an account
3. Click "Create new secret key"
4. Copy the API key (you won't be able to see it again!)

### Step 2: Set Up Environment Variables

Create a `.env` file in the project root directory:

```bash
cp .env.example .env
```

Then edit `.env` and replace `your-api-key-here` with your actual API key:

```bash
OPENAI_API_KEY=sk-...your-actual-key-here...
```

**Alternative:** Set the environment variable directly in your shell:

```bash
# For Linux/Mac:
export OPENAI_API_KEY="sk-...your-actual-key-here..."

# For Windows (Command Prompt):
set OPENAI_API_KEY=sk-...your-actual-key-here...

# For Windows (PowerShell):
$env:OPENAI_API_KEY="sk-...your-actual-key-here..."
```

### Step 3: Configure LLM Settings

Edit `config.yaml` to customize the LLM settings:

```yaml
llm:
  api_type: "openai"
  model: "gpt-5"          # Options: gpt-5, gpt-4, gpt-4-turbo, gpt-3.5-turbo
  temperature: 0.7        # 0.0 = deterministic, 1.0 = creative
  max_tokens: 8000        # Maximum response length
```

**Model Recommendations:**
- **gpt-5**: Latest model, best quality, supports larger context
- **gpt-4**: Excellent quality, proven reliability
- **gpt-4-turbo**: Good balance of quality and speed
- **gpt-3.5-turbo**: Fastest, cheapest, lower quality

### Step 4: Install Dependencies

```bash
pip install -r requirements.txt
```

This will install:
- `metagpt` - Multi-agent framework
- `openai` - OpenAI API client
- `pyyaml` - Configuration file parser
- Other required packages

### Step 5: Verify Setup

Run a simple test to verify your configuration:

```bash
python -c "from src.utils import ConfigLoader; config = ConfigLoader(); print('✓ Configuration loaded successfully'); llm_config = config.get_llm_config(); print(f'✓ Using model: {llm_config[\"model\"]}')"
```

If you see success messages, you're ready to go!

### Step 6: Run AutoRE

```bash
python main.py example_input.txt
```

You should see:
```
✓ LLM configured: gpt-5
✓ Temperature: 0.7
✓ Max tokens: 8000
```

## Troubleshooting

### Error: "OPENAI_API_KEY environment variable not set"

**Solution:** Make sure you've created a `.env` file or set the environment variable as described in Step 2.

### Error: "Config file not found: config.yaml"

**Solution:** Ensure you're running the command from the project root directory where `config.yaml` is located.

### Error: "Invalid API key"

**Solution:**
1. Verify your API key is correct
2. Check that you haven't accidentally added extra spaces or quotes
3. Ensure your OpenAI account has billing set up

### Error: Rate limit or quota exceeded

**Solution:**
1. Check your OpenAI account usage at [https://platform.openai.com/usage](https://platform.openai.com/usage)
2. Consider switching to a cheaper model (gpt-3.5-turbo) in `config.yaml`
3. Wait a few moments and try again

## Cost Estimation

AutoRE makes multiple LLM calls per iteration. Approximate costs per iteration:

- **gpt-5**: $0.15 - $0.75 per iteration (higher context window)
- **gpt-4**: $0.10 - $0.50 per iteration
- **gpt-4-turbo**: $0.05 - $0.25 per iteration
- **gpt-3.5-turbo**: $0.01 - $0.05 per iteration

A typical run with 5-10 iterations will cost $1.50-$7.50 with gpt-5.

## Security Best Practices

1. **Never commit `.env` files** to version control (already in `.gitignore`)
2. **Rotate your API keys** regularly
3. **Set usage limits** in your OpenAI account settings
4. **Monitor your usage** to detect unexpected costs

## Next Steps

- Read the main [README.md](README.md) for usage instructions
- Check `prompts/` directory to customize agent behavior
- Review `config.yaml` for other configuration options
