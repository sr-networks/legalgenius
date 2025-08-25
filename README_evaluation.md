# Legal Research Evaluation Script

This script evaluates the legal research app against gold standard cases from `cases2021.csv`.

## Features

1. **Reads CSV Input**: Processes `Fallbeschreibung` (case description) and `Rechtsprechung` (gold standard answer) columns
2. **Batch Processing**: Sends each case to the legal research app via `client/agent_cli.py`
3. **OpenAI Evaluation**: Compares results using OpenAI with expert legal evaluation prompt
4. **CSV Output**: Saves detailed results including scores and reasoning

## Usage

### Basic Usage
```bash
python3 evaluate_cases.py --openai-api-key YOUR_OPENAI_KEY
```

### Advanced Options
```bash
python3 evaluate_cases.py \
  --input ludwig/cases2021.csv \
  --output evaluation_results.csv \
  --max-cases 10 \
  --start-row 0 \
  --research-provider nebius \
  --research-model "your-model" \
  --eval-model gpt-4o \
  --openai-api-key YOUR_OPENAI_KEY
```

### Parameters

- `--input`: Input CSV file (default: `ludwig/cases2021.csv`)
- `--output`: Output CSV file (default: `evaluation_results.csv`)
- `--start-row`: Start from this row (0-based, excluding header)
- `--max-cases`: Maximum number of cases to evaluate
- `--research-model`: Model to use for legal research
- `--research-provider`: Provider for legal research (nebius, openrouter, ollama)
- `--eval-model`: OpenAI model for evaluation (default: gpt-4o)
- `--openai-api-key`: OpenAI API key (or set `OPENAI_API_KEY` env var)

## Output Format

The output CSV contains:
- `fallnummer`: Case identifier
- `fallbeschreibung`: Original case description
- `gold_answer`: Gold standard answer
- `our_answer`: Answer from our legal research app
- `evaluation_score`: Score 1-10 from OpenAI evaluation
- `evaluation_reasoning`: Detailed reasoning for the score
- `error`: Any errors that occurred
- `processing_time`: Time taken to process each case

## Requirements

### Environment Setup
The script requires a working Python environment with:
- `requests` library (for OpenAI API calls)
- Access to the legal research system

### API Keys
- **OpenAI API Key**: Required for evaluation
- **Legal Research API**: Depends on `--research-provider` setting
  - For Nebius: Set `NEBIUS_API_KEY` and `NEBIUS_MODEL`
  - For OpenRouter: Set `OPENROUTER_API_KEY`
  - For Ollama: Local setup required

## Troubleshooting

### Python Environment Issues
If you encounter library import errors (e.g., pydantic/OpenAI library issues), try:

1. **Use a clean Python environment**:
   ```bash
   python3 -m venv eval_env
   source eval_env/bin/activate
   pip install requests openai
   ```

2. **Alternative: Direct API calls**:
   The script uses `requests` for OpenAI calls to avoid dependency issues.

### Legal Research System Issues
- Ensure the MCP server is properly configured
- Check that elasticsearch is running if required
- Verify API keys and models are correctly set

## Example Evaluation Prompt

The script uses this German evaluation prompt:

```
Du bist ein juristischer Experte und sollst die Antwort auf eine juristische 
Recherche-Arbeit bewerten und mit der Gold-Antwort vergleichen. 
Schätze die Korrektheit der Antwort auf einer Skala von 1 bis 10 ein und begründe. 
Bewerte nur die juristische Korrektheit und nicht die Form der Antwort.

Bewerte besonders:
- Rechtliche Genauigkeit der zitierten Gesetze und Urteile
- Vollständigkeit der Argumentation  
- Korrekte Anwendung der Rechtsprechung
- Praktische Relevanz der Lösung
```

## Resuming Interrupted Runs

The script appends to existing output files, so you can resume interrupted evaluations:

```bash
# Resume from row 50 if previous run stopped
python3 evaluate_cases.py --start-row 50 --output evaluation_results.csv
```

## Performance Notes

- Each case takes ~30-60 seconds to process (research + evaluation)
- The script includes 1-second delays between cases to avoid overwhelming services
- Use `--max-cases` for testing with smaller batches
- Results are written immediately (not buffered) so partial results are saved