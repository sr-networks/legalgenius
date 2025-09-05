# LegalGenius

A comprehensive German legal research and question-answering system that provides LLM-powered search capabilities over German federal laws, regulations, and court decisions. Features Elasticsearch-powered search with agentic control and real-time reasoning traces. Available as a modern web interface, command-line chat and batch script for benchmarking.

<img width="1320" height="796" alt="image" src="https://github.com/user-attachments/assets/90d1499b-a0f9-45d1-9b22-9a1996e40f3e" />

## Overview

LegalGenius combines a comprehensive corpus of German legal documents with an intelligent search agent to help users find relevant legal information. The system uses a Model Context Protocol (MCP) server architecture with Elasticsearch-powered search capabilities optimized for German legal text processing and natural language understanding.

## Features

- **Modern Web Interface**: React-based frontend with real-time streaming responses
- **Comprehensive Legal Database**: Complete collection of German federal laws and regulations (Bundesgesetze und -verordnungen) in Markdown format
- **Court Decision Archive**: Extensive collection of court decisions organized by year (1970-now)
- **Intelligent Search**: Boolean query support with AND/OR operators and parentheses
- **Multi-Provider LLM Support**: Compatible with OpenRouter, Nebius, and Ollama
- **Advanced Text Search**: Powered by Elasticsearch for fast, scalable search with German language optimization and relevance ranking
- **Context-Aware Results**: Provides relevant excerpts with configurable context
- **German Language Optimized**: Designed specifically for German legal terminology and structure
- **Modular Architecture**: Supports web UI, CLI, and batch processing
- **Real-time Streaming**: Live updates showing tool usage and reasoning steps
- **Reasoning Traces**: View LLM internal reasoning process in real-time via web interface

## Benchmarking

First results with:

- Open-source LLM (cost-efficient, no proprietary lock-in, runs on EU cloud)
- 6,600 laws and 500,000 cases

Methodology:
- 10 tough, recent questions (German law; post-update topics)
- Gold solutions by a domain expert
- Evaluation: GPT-5 serves as a blind judge with a rubric
- Reference: r/LocalLLaMA — Agentic Legal Research for German Law — First Benchmark

Result:
- Even without any optimization, the agent reached GPT-5 level

Why this matters:
- SOTA accuracy at fractional cost with an auditable, tool-using agent; promising for compliant, on-prem legal assistants.

Next:
- Targeted domain adaptation and customer GPUs to run in small to midsized offices

![agentic-legal-research-for-german-law-first-benchmark-v0-btdmsvjhwclf1 jpg](https://github.com/user-attachments/assets/07a46623-9b0c-472a-862e-07854e6bb106)


## Recent Improvements

### Elasticsearch Integration (Latest)
- **Primary Search Engine**: Replaced ripgrep with Elasticsearch as the main search backend
- **German Language Analysis**: Custom German text processing with stemming and compound word handling  
- **Performance**: Millisecond search response times across the entire legal corpus
- **Relevance Scoring**: Advanced ranking algorithms for better result quality
- **Document Type Filtering**: Search specifically in laws (gesetze) or court decisions (urteile)
- **Fuzzy Matching**: Handle typos and variations in search queries automatically

### Architecture Enhancements
- **Unified Tool Dispatching**: Shared dispatcher functions between CLI and web interfaces
- **Elasticsearch Tool Integration**: New `elasticsearch_search` tool with comprehensive result formatting
- **Reasoning Visibility**: Real-time streaming of LLM reasoning content in web interface
- **Code Deduplication**: Consolidated tool handling logic for better maintainability

### User Interface Improvements
- **Persistent Research Log**: The "Durchsuche Rechtsquellen" pane now persists across steps and after completion, showing the full history of reasoning and tool calls.
- **Scrollable History**: Full step/tool history is rendered in a scrollable container with auto‑scroll to the latest event.
- **Integrated Reasoning Traces**: Reasoning content and tool activity stream into the pane during execution.
- **Real-time Updates**: Live streaming of tool usage and AI reasoning steps during search.

### Session Logs (Web API)
- **Per‑Session Persistence**: All streamed events are saved to `logs/sessions/<session_id>.jsonl`.
- **Session ID on Stream**: The first SSE carries `{ type: 'session', session_id }` so the UI can fetch logs later.
- **Retrieve Full Log**: `GET /sessions/{session_id}` returns the complete event history for permanent viewing.

### Streamlined Search Tools
- **Primary Tool**: `elasticsearch_search` now handles most search operations
- **Deprecated Tool**: `search_rg` retained as an optional fallback for precise file-local searches (requires ripgrep)
- **Enhanced Results**: Better structured results with metadata, relevance scores, and line matches

## Quick Start

### Prerequisites

- Python 3.8+
- Node.js 18+ (for web interface)
- Docker Desktop (for Elasticsearch search engine)
- An API key for your chosen LLM provider

Optional tools:
- ripgrep (`rg`) only if you choose to use the deprecated `search_rg` fallback

### Quick Start Guide

**1. Clone and setup:**
```bash
git clone <repository-url>
cd legalgenius
make venv
make dev
make web-install
```

**2. Configure LLM provider** (choose one):
```bash
# Nebius (default)
export LLM_PROVIDER="nebius"
export NEBIUS_API_KEY="your-api-key"
export NEBIUS_MODEL="zai-org/GLM-4.5"

# OR OpenRouter
export LLM_PROVIDER="openrouter"
export OPENROUTER_API_KEY="your-api-key"

# OR Ollama (local)
export LLM_PROVIDER="ollama"
```

**3. Start Elasticsearch:**

(In first use, begin with loading legal documents and indexing, see below.)

```bash
# Start Elasticsearch container
docker start elasticsearch-simple

# For first-time setup:
docker run -d --name elasticsearch-simple \
  -p 9200:9200 -p 9300:9300 \
  -e "discovery.type=single-node" \
  -e "xpack.security.enabled=false" \
  -e "ES_JAVA_OPTS=-Xms512m -Xmx512m" \
  elasticsearch:8.11.0
```

**4. Start the application:**
```bash
# Terminal 1: API server
make api

# Terminal 2: Frontend server
make web-dev

# Open http://localhost:5173 in your browser
```

### Alternative: Use package scripts (new)

If you prefer installed entry points over Makefile targets:

```bash
# 1) Install the package in editable mode to register scripts
pip install -e .

# 2) Start the API (respects API_HOST, API_PORT, API_RELOAD, API_ALLOW_ORIGINS)
legalgenius-api

# 3) Run the CLI directly
legalgenius-cli "Was ist die Kündigungsfrist bei Mietverträgen?"

# 4) Run the MCP server standalone (debugging / integration)
legalgenius-mcp

# 5) Index documents into Elasticsearch
legalgenius-index --host localhost --port 9200
```

Note: If `data/gesetze/` is empty on first run, populate it using the bundled scrapers described in “Populate Laws (First-Time)” below before indexing.

### Detailed Configuration

**Environment Variables:**

**For Nebius (default):**
```bash
export LLM_PROVIDER="nebius"
export NEBIUS_API_KEY="your-api-key"
export NEBIUS_MODEL="zai-org/GLM-4.5"  # recommended
```

**For OpenRouter:**
```bash
export LLM_PROVIDER="openrouter"
export OPENROUTER_API_KEY="your-api-key"
export OPENROUTER_MODEL="anthropic/claude-sonnet-4"  # optional
```

**For Ollama (local):**
```bash
export LLM_PROVIDER="ollama"
export OLLAMA_MODEL="qwen3:4b"  # optional
```

Additional API configuration:
```bash
# Comma-separated list of allowed origins for CORS (defaults to localhost dev ports)
export API_ALLOW_ORIGINS="http://localhost:5173,http://127.0.0.1:5173"

# Optional server settings for entry-point runner
export API_HOST=0.0.0.0
export API_PORT=8000
export API_RELOAD=false
```

Config files:
- Copy `configs/config.example.yaml` to `configs/config.yaml` to customize defaults like `legal_doc_root`, `glob`, `max_results`, and `context_bytes`.

### Usage

#### Web Interface (Recommended)

**First time setup:**
```bash
# Setup Python environment (if not done already)
make venv
make dev

# Setup Node.js environment and install dependencies
make web-install
```

**Starting the application:**

1. **Terminal 1**: Start the API server:
```bash
make api
```

2. **Terminal 2**: Start the web development server:
```bash
make web-dev
```

3. **Open your browser** to `http://localhost:5173`

**Services running:**
- Frontend: http://localhost:5173 (React/Vite dev server)
- Backend API: http://localhost:8000 (FastAPI server)

Alternative (new): start the API via the package script instead of Make:
```bash
pip install -e .
legalgenius-api
```

The web interface provides:
- Clean, modern interface for legal questions
- Real-time responses with integrated reasoning traces
- Live progress updates during search operations
- Direct access to German legal document corpus
- Error handling and intelligent loading states
- Compact reasoning display embedded in loading widget

#### Command Line Interface

Ask a legal question using the CLI:

```bash
make client q="Was ist die Kündigungsfrist bei Mietverträgen?"
```

Or use the Python client directly:

```bash
python client/agent_cli.py "Was sind die Voraussetzungen für eine Scheidung?"
```

#### Batch Processing API

For processing multiple queries, use the batch endpoint:

```bash
curl -X POST "http://localhost:8000/batch" \
  -H "Content-Type: application/json" \
  -d '{
    "queries": [
      "Was ist die Kündigungsfrist bei Mietverträgen?",
      "Welche Voraussetzungen gelten für eine Scheidung?"
    ],
    "provider": "nebius",
    "model": "zai-org/GLM-4.5"
  }'
```

#### Starting the MCP Server

To run the server independently:

```bash
make server
```

## Architecture

### Components

1. **Web Interface** (`web/`):
   - React TypeScript frontend with Vite bundling
   - Real-time streaming using Server-Sent Events with integrated reasoning traces
   - Modern UI with Tailwind CSS and compact progress displays
   - Embedded reasoning visualization in loading states
   - Local storage for configuration and chat history

2. **API Server** (`web_server/`):
   - FastAPI backend at `http://localhost:8000`
   - Modular agent runner supporting web UI and batch jobs
   - CORS-enabled for frontend integration
   - Health checks and error handling

3. **MCP Server** (`mcp_server/`):
   - `server.py`: JSON-RPC server handling tool calls
   - `tools.py`: Core search and file access tools with security sandbox
   - Provides secure, sandboxed access to legal documents

4. **Agent Core** (`client/`):
   - `agent_cli.py`: Modular agent implementation with `run_agent` method
   - Supports multiple LLM providers through OpenAI-compatible APIs
   - Implements function calling for intelligent tool usage
   - Configurable timeout and step limits

5. **Data** (`data/`):
   - `gesetze/`: German federal laws and regulations in Markdown
   - `urteile_markdown_by_year/`: Court decisions organized by year
   - All content sourced from official German legal repositories

### Available Tools

- **`elasticsearch_search`** (Primary): Fast full-text search across German legal corpus with relevance ranking and fuzzy matching. Supports document type filtering (laws/court decisions) and comprehensive metadata extraction
- **`file_search`**: Boolean content search across the legal corpus using AND/OR operators
- **`read_file_range`**: Extract text snippets with configurable context around search results
- **`list_paths`**: Browse available documents and directories

Note: The ripgrep-based `search_rg` tool is deprecated in favor of the more powerful Elasticsearch integration, but remains available as an optional fallback for precise file-local searches. It requires ripgrep (`rg`) if you choose to use it.

### API Endpoints

- `GET /health`: Server health check
- `POST /ask`: Single query processing
- `POST /batch`: Batch query processing
- `POST /test`: Limited-step testing endpoint

### Modular Agent Architecture

The core `run_agent` method in `client/agent_cli.py` is designed to be modular and supports multiple interfaces:

1. **Web Interface**: Real-time streaming via FastAPI endpoints
2. **Command Line**: Direct CLI usage with immediate results  
3. **Batch Processing**: Multiple queries processed sequentially
4. **API Integration**: RESTful endpoints for external systems

The agent automatically:
- Manages MCP server connections
- Handles LLM provider switching
- Provides tool usage tracking
- Implements configurable timeouts and step limits
- Never uses mock responses (always real LLM calls)

## Elasticsearch Search Engine

LegalGenius uses Elasticsearch as its primary search engine for fast, scalable, and intelligent document retrieval across the German legal corpus. The Elasticsearch integration provides advanced full-text search capabilities with semantic understanding.

### Elasticsearch Setup

**Prerequisites:**
- Docker Desktop installed and running
- At least 2GB RAM available for Elasticsearch

**Starting Elasticsearch:**

If the container already exists:
```bash
docker start elasticsearch-simple
```

For first-time setup, create a new container:
```bash
docker run -d --name elasticsearch-simple \
  -p 9200:9200 -p 9300:9300 \
  -e "discovery.type=single-node" \
  -e "xpack.security.enabled=false" \
  -e "ES_JAVA_OPTS=-Xms512m -Xmx512m" \
elasticsearch:8.11.0
```

Makefile shortcut:
```bash
make es-up   # starts or creates the container
make es-wait # waits until it responds on localhost:9200
```

**Verifying Elasticsearch is running:**
```bash
# Check container status
docker ps --filter "name=elasticsearch-simple"

# Test Elasticsearch is responding
curl -X GET "localhost:9200/"

# Check cluster health
curl -X GET "localhost:9200/_cluster/health?pretty"
```

**Stopping Elasticsearch:**
```bash
docker stop elasticsearch-simple
```

### Search Engine Features

**Advanced Text Search:**
- Full-text search across all German legal documents
- Fuzzy matching for typos and variations
- Boolean queries (AND, OR, NOT operators)
- Phrase searching with proximity
- Field-specific search (title, content, metadata)

**German Language Optimization:**
- German language analyzer with stemming
- Stop word filtering for legal context
- Compound word decomposition
- Case-insensitive search

**Performance Benefits:**
- Millisecond search response times
- Scalable to millions of documents
- Memory-efficient indexing
- Relevance scoring and ranking

### Indexing Legal Documents

**Index Creation:**
The system automatically creates optimized indices for different document types:
- `legal-laws`: German federal laws and regulations
- `legal-cases`: Court decisions and judgments
- `legal-combined`: Unified search across all documents

**Document Indexing:**
```bash
# Index all legal documents
python elasticsearch_indexer.py

# Index specific document types
python elasticsearch_indexer.py --type laws
python elasticsearch_indexer.py --type cases
```

**Reindexing Documents:**

To reindex specific document types (e.g., after data updates):

```bash
# Reindex all urteile (court decisions) - clean approach
curl -X DELETE "localhost:9200/legal_urteile"
python simple_elasticsearch_indexer.py --urteile-only

# Reindex all gesetze (laws and regulations) - clean approach  
curl -X DELETE "localhost:9200/legal_gesetze"
python simple_elasticsearch_indexer.py --gesetze-only

# Full reindex of everything
curl -X DELETE "localhost:9200/legal_urteile"
curl -X DELETE "localhost:9200/legal_gesetze"
python simple_elasticsearch_indexer.py

# Quick reindex (adds to existing - may create duplicates)
python simple_elasticsearch_indexer.py --urteile-only
```

**Reindexing Time Estimates:**
- Urteile only: ~5-10 minutes
- Gesetze only: ~2-3 minutes  
- Full reindex: ~10-15 minutes
- Stats check: <1 second

**Pre-Reindexing Checks:**
```bash
# Check current index status
python simple_elasticsearch_indexer.py --stats

# Check document count
curl -X GET "localhost:9200/legal_urteile/_count?pretty"
curl -X GET "localhost:9200/legal_gesetze/_count?pretty"

# Verify Elasticsearch health
curl -X GET "localhost:9200/_cluster/health?pretty"
```

**Index Management:**
```bash
# Check index status
curl -X GET "localhost:9200/_cat/indices?v"

# View index mapping
curl -X GET "localhost:9200/legal-combined/_mapping?pretty"

# Check document count
curl -X GET "localhost:9200/legal-combined/_count?pretty"
```

### Search API Integration

The Elasticsearch engine integrates seamlessly with the LegalGenius search tools:

**File Search Tool Enhancement:**
- Boolean queries automatically converted to Elasticsearch DSL
- Results ranked by relevance score
- Context extraction around matching terms
- Metadata enrichment (document type, date, source)

**Performance Monitoring:**
- Search query performance metrics
- Index size and document statistics
- Memory usage tracking
- Search latency monitoring

### Elasticsearch Configuration

**Memory Settings:**
- Minimum: 512MB (`ES_JAVA_OPTS=-Xms512m -Xmx512m`)
- Recommended: 1GB (`ES_JAVA_OPTS=-Xms1g -Xmx1g`)
- Production: 2-4GB depending on corpus size

**Index Settings:**
```json
{
  "settings": {
    "number_of_shards": 1,
    "number_of_replicas": 0,
    "analysis": {
      "analyzer": {
        "german_legal": {
          "type": "custom",
          "tokenizer": "standard",
          "filter": ["lowercase", "german_stop", "german_stemmer"]
        }
      }
    }
  }
}
```

**Document Mapping:**
- `title`: Analyzed text with German language processing
- `content`: Full-text with paragraph-aware tokenization
- `document_type`: Keyword field (law, regulation, case)
- `date`: Date field for temporal filtering
- `source`: Keyword field for document origin

### Troubleshooting

**Container Issues:**
```bash
# Check container logs
docker logs elasticsearch-simple

# Restart container
docker restart elasticsearch-simple

# Remove and recreate container
docker rm elasticsearch-simple
# Then run the docker run command again
```

**Index Issues:**
```bash
# Delete and recreate indices
curl -X DELETE "localhost:9200/legal_urteile"
curl -X DELETE "localhost:9200/legal_gesetze"
python simple_elasticsearch_indexer.py
```

**Reindexing Issues:**
```bash
# Check if Elasticsearch is running
curl -X GET "localhost:9200/_cluster/health?pretty"

# View available indices
curl -X GET "localhost:9200/_cat/indices?v"

# Check for indexing errors with verbose output
python simple_elasticsearch_indexer.py --urteile-only --host localhost --port 9200

# If reindexing fails midway, clean up and restart
curl -X DELETE "localhost:9200/legal_urteile"
python simple_elasticsearch_indexer.py --urteile-only

# Monitor indexing progress in separate terminal
watch 'curl -s "localhost:9200/legal_urteile/_count" | python -m json.tool'
```

**Performance Issues:**
- Increase memory allocation in `ES_JAVA_OPTS`
- Monitor cluster health with `/_cluster/health`
- Check disk space with `/_cat/allocation?v`

### Direct Search with simple_elasticsearch_indexer.py

For direct Elasticsearch searches without the AI agent, use the `simple_elasticsearch_indexer.py` script:

**Search Across Both Laws and Court Decisions:**
```bash
# Search multiple indices (recommended)
python simple_elasticsearch_indexer.py --search "Kündigungsfrist" --index "legal_gesetze,legal_urteile"

# Multiple keyword search (all terms must appear)
python simple_elasticsearch_indexer.py --search "Kündigung" "Mietvertrag" --index "legal_gesetze,legal_urteile"

# Phrase search for exact matches
python simple_elasticsearch_indexer.py --search "fristlose Kündigung" --index "legal_gesetze,legal_urteile"
```

**Search Specific Document Types:**
```bash
# Search only laws and regulations
python simple_elasticsearch_indexer.py --search "BGB § 573" --gesetze-only

# Search only court decisions
python simple_elasticsearch_indexer.py --search "Mietrecht BGH" --urteile-only
```

**Index Management:**
```bash
# Index all documents (laws + court decisions)
python simple_elasticsearch_indexer.py

# Index only specific types
python simple_elasticsearch_indexer.py --gesetze-only
python simple_elasticsearch_indexer.py --urteile-only

# Check index statistics
python simple_elasticsearch_indexer.py --stats
```

**Search Results Include:**
- Document titles and types (gesetz/urteil)
- File paths and relevance scores
- Line numbers where matches occur
- Highlighted excerpts with context
- Court information and case numbers (for urteile)

**Example Searches:**
```bash
# Comprehensive rental law research
python simple_elasticsearch_indexer.py --search "Mietrecht" "Kündigung" --index "legal_gesetze,legal_urteile"

# Divorce law across legislation and jurisprudence
python simple_elasticsearch_indexer.py --search "Scheidung" "Unterhalt" --index "legal_gesetze,legal_urteile"

# Specific BGB provisions with case law
python simple_elasticsearch_indexer.py --search "BGB" "§ 323" "Rücktritt" --index "legal_gesetze,legal_urteile"

# Contract law research
python simple_elasticsearch_indexer.py --search "Vertrag" "Willenserklärung" --index "legal_gesetze,legal_urteile"
```

This direct search method is ideal for:
- Quick fact-checking without AI interpretation
- Finding specific legal provisions or case citations
- Researching terminology across both legislation and case law
- Bulk research across the entire legal corpus

## Configuration

Create `configs/config.yaml` to customize settings:

```yaml
legal_doc_root: "./data/"
glob: "**/*.{txt,md}"
max_results: 50
context_bytes: 300
```

Environment variables take precedence over configuration files.

## Development

### Project Structure

```
legalgenius/
├── web/                 # React frontend
│   ├── src/            # TypeScript source code
│   ├── public/         # Static assets
│   └── package.json    # Frontend dependencies
├── web_server/          # FastAPI backend
│   ├── api.py         # Main API server
│   ├── app.py         # Legacy Flask server (deprecated)
│   └── requirements.txt
├── client/              # CLI client and agent core
│   └── agent_cli.py    # Modular agent with run_agent method
├── mcp_server/          # MCP server implementation
│   ├── server.py       # JSON-RPC server
│   └── tools.py        # Search and file access tools
├── data/                # Legal document corpus
│   ├── gesetze/        # Federal laws and regulations
│   └── urteile_markdown_by_year/  # Court decisions
├── logs/               # Session logs
├── Makefile           # Build and development commands
└── README.md
```

### Available Make Commands

- `make dev`: Install Python dependencies in virtual environment
- `make venv`: Create virtual environment
- `make server`: Start the MCP server independently
- `make client q="query"`: Run a query through the CLI
- `make api`: Start the FastAPI backend server (port 8000)
- `make web-install`: Install frontend dependencies
- `make web-dev`: Start the React development server (port 5173)
- `make gesetze-install`: Install scraper dependencies for laws
- `make gesetze-update-list`: Refresh law slug list from gesetze-im-internet.de
- `make gesetze-download`: Download all laws (XML) into `scrapers/gesetze-tools/laws/`
- `make gesetze-convert`: Convert downloaded XML to Markdown under `data/gesetze/`
- `make gesetze-all`: Run update-list, download, and convert in sequence
- `make index-gesetze`: Index `data/gesetze/` into Elasticsearch only
- `make es-up`: Start (or create) the local Elasticsearch container
- `make es-wait`: Wait until Elasticsearch responds on `localhost:9200`
- `make bootstrap-laws`: One-shot: scrape + convert laws, start ES, wait, then index
- `make urteile-neuris`: Fetch court decisions from Neuris API into `data/urteile_markdown_by_year/`

### Package Scripts (new)

After `pip install -e .`, these commands are available:
- `legalgenius-api`: Starts the FastAPI server; uses `API_HOST`, `API_PORT`, `API_RELOAD`, `API_ALLOW_ORIGINS`.
- `legalgenius-cli`: Runs the agent CLI.
- `legalgenius-mcp`: Launches the MCP server.
- `legalgenius-index`: Indexes laws/cases into Elasticsearch.
- `make test`: Run tests (if available)

### Development Workflow

**Daily development routine:**
```bash
# Terminal 1: Start API server
make api

# Terminal 2: Start frontend dev server
make web-dev

# Open browser to http://localhost:5173
```

**Individual service development:**

1. **Frontend Development**: 
   ```bash
   make web-dev  # Start React dev server with hot reload on port 5173
   ```

2. **Backend Development**:
   ```bash
   make api      # Start FastAPI server with auto-reload on port 8000
   ```

3. **CLI Testing**:
   ```bash
   make client q="test query"  # Test the CLI interface directly
   ```

**Troubleshooting:**

- **Dependencies not installed**: Run `make web-install` to install Node.js dependencies
- **Port conflicts**: Frontend uses 5173, API uses 8000
- **API not responding**: Check if backend is running with `curl http://localhost:8000/health`
- **Frontend not loading**: Check browser console (F12) for errors

### Adding Legal Documents

Legal documents should be placed in the appropriate subdirectory within `data/`:
- Laws and regulations: `data/gesetze/`
- Court decisions: `data/urteile_markdown_by_year/`

All documents must be in Markdown format (`.md`) or plain text (`.txt`).

### Court Decisions Dataset (Open Legal Data)

Use `scrapers/export_urteile_markdown_by_year.py` to download the Open Legal Data dump and generate one Markdown file per year. First download the caselaw with
```bash
curl https://static.openlegaldata.io/dumps/de/2020-12-10/cases.jsonl.gz --output cases.jsonl.gz
gunzip cases.jsonl.gz
```

**Outputs:**
- One file per year: `<out>/<YYYY>.md` with all decisions sorted by date (desc)
- Index file: `<out>/index.md`

Each yearly file starts with a metadata block and includes sections like title, court, file number, date, source URL, Leitsatz, Tenor, Normen, Verweise, and full decision text when available.

**Recommended usage (from repo root, writing into `data/`):**
```bash
# Download dump if missing and write Markdown files into data/
python3 scrapers/export_urteile_markdown_by_year.py \
  --download \
  --input scrapers/cases.jsonl \
  --out data/urteile_markdown_by_year
mkdir data
mv data/urteile_markdown_by_year data
```

**Alternative (run inside `scrapers/`):**
```bash
python3 export_urteile_markdown_by_year.py --download --out ../data/urteile_markdown_by_year
```

**Flags:**
- `--download`: If `--input` is missing, fetches and decompresses the official `.gz` dump
- `--download-url`: Custom URL to the `cases.jsonl.gz` file (defaults to the OLD dump)
- `--input`: Path to `cases.jsonl` (default: `./cases.jsonl` relative to CWD)
- `--out`: Output directory for generated Markdown (default: `urteile_markdown_by_year`)
- `--cafile`: Path to a CA bundle to verify TLS when downloading
- `--insecure`: Skip TLS verification for the download (not recommended)

**TLS tips (macOS):**
- Homebrew OpenSSL CA bundle:
  - Apple Silicon: `--cafile /opt/homebrew/etc/openssl@3/cert.pem`
  - Intel: `--cafile /usr/local/etc/openssl@3/cert.pem`
- Using certifi: `python3 -c "import certifi; print(certifi.where())"` and pass the printed path to `--cafile`
- Python.org installers: run `open "/Applications/Python 3.11/Install Certificates.command"`
- As a last resort for one-off runs: `--insecure`

**Troubleshooting:**
- No space left on device (`OSError: [Errno 28]`): Free disk space or change `--out` to a location with sufficient space (e.g., `--out /Volumes/External/urteile_markdown_by_year`). You can also remove the downloaded archive after decompression (`cases.jsonl.gz`).
- Permission denied: Ensure you have write permissions to the `--out` directory and `--input` location.

### Laws Dataset (Bundesgesetze)

Bundled scrapers for German federal laws are located at `scrapers/gesetze-tools` (forked from the official BundesGit tools). Use them to download XML from gesetze-im-internet.de and convert to Markdown under `data/gesetze/`. See the section “Populate Laws (First-Time)” below for exact commands. Upstream reference: https://github.com/bundestag/gesetze-tools

## Security

- All file access is sandboxed to the configured legal document root
- Path traversal attempts are blocked
- Only allowed file extensions (`.md`, `.txt`) are accessible
- No arbitrary code execution in document processing

API hardening tips:
- Set `API_ALLOW_ORIGINS` to your exact production domains.
- Keep LLM/API keys in secret managers or environment variables; do not commit `.env`.

## Legal Notice

This tool is for research and informational purposes only. Always consult official legal sources and qualified legal professionals for authoritative legal advice. The authors make no claims about the accuracy or completeness of the legal information provided.

## License

The software is provided as-is. German federal laws and regulations are official works not subject to copyright (amtliche Werke).

## Data Sources

- **Laws and Regulations**: Sourced from [gesetze-im-internet.de](http://www.gesetze-im-internet.de/)
- **Court Decisions**: Various German court databases and archives
- **Format**: All documents converted to Markdown for optimal readability and searchability

## Populate Laws (First-Time)

The repository includes a working copy of the official scraping tools in `scrapers/gesetze-tools` to download and convert German federal laws to Markdown under `data/gesetze/`.

### One-time setup

- Create a Python virtual environment (optional but recommended):
  - `python3 -m venv .venv && source .venv/bin/activate`
- Install scraper requirements:
  - `cd scrapers/gesetze-tools && pip install -r requirements.txt`

### Download laws (XML)

- Refresh the law list (optional):
  - `python lawde.py updatelist`
- Download all laws (takes hours, requires stable network):
  - `python lawde.py loadall --path laws`

Tips:
- To download only specific laws (faster), use slugs: `python lawde.py load bgb stgb vwvfg --path laws`
- You can interrupt and rerun; the script replaces per-law directories.

### Convert to Markdown and place into `data/gesetze/`

- From `scrapers/gesetze-tools`:
  - `python lawdown.py convert laws ../../data/gesetze`

Results:
- Markdown files are written to `data/gesetze/<first-letter>/<slug>/index.md` with supporting assets copied alongside.

### Index into Elasticsearch

- From the repo root, index the content:
  - `python simple_elasticsearch_indexer.py --gesetze-only`

Troubleshooting:
- If indexing or search shows zero laws, verify that Markdown files exist under `data/gesetze/` and re-run the indexer.
- If downloads fail, rerun `lawde.py` (it retries and replaces incomplete directories).
- Required tools for scraping: `docopt`, `requests`, `lxml`, etc. are installed by the `requirements.txt` in `scrapers/gesetze-tools`.

Alternative (Makefile):
- End-to-end flow: `make gesetze-all`
- Or step-by-step:
  - `make gesetze-update-list`
  - `make gesetze-download`
  - `make gesetze-convert`
  - `make index-gesetze`

## Populate Court Decisions (Neuris)

Fetch court decisions from the official Neuris API and write Markdown grouped by year under `data/urteile_markdown_by_year/`.

Manual usage:
```bash
# Default: 2000..current year
python3 scrapers/fetch_urteile_neuris.py --from-year 2000 --out data/urteile_markdown_by_year

# To target the public testphase endpoint explicitly:
python3 scrapers/fetch_urteile_neuris.py \
  --base-url https://testphase.rechtsinformationen.bund.de \
  --search-path /v1/case-law \
  --detail-path /v1/case-law/{id} \
  --from-year 2010 --to-year 2024 \
  --from-param decisionDateFrom --to-param decisionDateTo \
  --out data/urteile_markdown_by_year
```

Makefile shortcut:
```bash
# Defaults: from 2000 to current year
make urteile-neuris

# Override range or base
make urteile-neuris urteils-years=1990 urteils-years-to=2024 \
  urteils-base=https://testphase.rechtsinformationen.bund.de \
  urteils-search=/v1/case-law \
  urteils-detail=/v1/case-law/{id}
```

Notes:
- The script de-duplicates entries by source URL or id and merges new decisions into existing yearly files.
- If the API requires credentials, pass `--api-key` to the script; it will use `Authorization: Bearer <key>`.
- Refer to the official guides: https://docs.rechtsinformationen.bund.de/guides/ for endpoint details.
 - If you see a DNS error for the host, double‑check the base URL. For the test environment use `https://testphase.rechtsinformationen.bund.de`.
 - Some deployments use different date parameter names. For the testphase case-law endpoint, pass `--from-param decisionDateFrom --to-param decisionDateTo`. If you still see 0 results, try adding a query with `--query '*'` or other API-specific filters via `--extra key=value`.

## Contributing

Contributions are welcome! Please ensure that:
- Only official, verified legal documents are added
- All code follows the existing security and architectural patterns
- New features include appropriate documentation

## Support

For technical issues or questions about the codebase, please open an issue in the project repository.

## Next Steps Towards Production

- Dockerize services: API container with `uvicorn`, Elasticsearch with persistent volume, optional frontend static hosting.
- CI/CD: lint (ruff), type-check (mypy), run tests, build frontend; pin dependency ranges and enable Dependabot/Renovate.
- Observability: structured JSON logging, request metrics, health checks, and readiness probes.
- Security: restrict Elasticsearch host/port to env-configured values only; tighten CORS; add rate limiting and request size/time limits.
- Tests: unit tests for tools (query building, parsing), FastAPI smoke tests, agent loop with mocked LLM client.
- Frontend: production build (`web/dist`) served via CDN or behind reverse proxy; configure API base at build time.
- Multi-turn chat function.
