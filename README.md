# LegalGenius

A comprehensive German legal research and question-answering system that provides AI-powered search capabilities over German federal laws, regulations, and court decisions. Available as both a modern web interface and command-line tool.

## Overview

LegalGenius combines a comprehensive corpus of German legal documents with an intelligent search agent to help users find relevant legal information. The system uses a Model Context Protocol (MCP) server architecture with advanced search capabilities powered by ripgrep and natural language processing.

## Features

- **Modern Web Interface**: React-based frontend with real-time streaming responses
- **Comprehensive Legal Database**: Complete collection of German federal laws and regulations (Bundesgesetze und -verordnungen) in Markdown format
- **Court Decision Archive**: Extensive collection of court decisions organized by year (1970-2029)
- **Intelligent Search**: Boolean query support with AND/OR operators and parentheses
- **Multi-Provider LLM Support**: Compatible with OpenRouter, Nebius, and Ollama
- **Advanced Text Search**: Powered by ripgrep for fast, precise text matching
- **Context-Aware Results**: Provides relevant excerpts with configurable context
- **German Language Optimized**: Designed specifically for German legal terminology and structure
- **Modular Architecture**: Supports web UI, CLI, and batch processing
- **Real-time Streaming**: Live updates showing tool usage and reasoning steps

## Quick Start

### Prerequisites

- Python 3.8+
- Node.js 18+ (for web interface)
- ripgrep (`rg`) installed and available in PATH
- An API key for your chosen LLM provider

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

**3. Start the application:**
```bash
# Terminal 1: API server
make api

# Terminal 2: Frontend server
make web-dev

# Open http://localhost:5173 in your browser
```

### Detailed Configuration

**Environment Variables:**

**For Nebius (default):**
```bash
export LLM_PROVIDER="nebius"
export NEBIUS_API_KEY="your-api-key"
export NEBIUS_MODEL="zai-org/GLM-4.5"
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

The web interface provides:
- Clean, modern interface for legal questions
- Real-time responses from the AI system
- Direct access to German legal document corpus
- Error handling and loading states

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
   - Real-time streaming using Server-Sent Events
   - Modern UI with Tailwind CSS
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

- **`file_search`**: Boolean content search across the legal corpus
- **`search_rg`**: Precise line-by-line search using ripgrep
- **`read_file_range`**: Extract text snippets with configurable context
- **`list_paths`**: Browse available documents and directories

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

### Adding New Documents

Legal documents should be placed in the appropriate subdirectory within `data/`:
- Laws and regulations: `data/gesetze/`
- Court decisions: `data/urteile_markdown_by_year/`

All documents must be in Markdown format (`.md`) or plain text (`.txt`).

## Security

- All file access is sandboxed to the configured legal document root
- Path traversal attempts are blocked
- Only allowed file extensions (`.md`, `.txt`) are accessible
- No arbitrary code execution in document processing

## Legal Notice

This tool is for research and informational purposes only. Always consult official legal sources and qualified legal professionals for authoritative legal advice. The authors make no claims about the accuracy or completeness of the legal information provided.

## License

The software is provided as-is. German federal laws and regulations are official works not subject to copyright (amtliche Werke).

## Data Sources

- **Laws and Regulations**: Sourced from [gesetze-im-internet.de](http://www.gesetze-im-internet.de/)
- **Court Decisions**: Various German court databases and archives
- **Format**: All documents converted to Markdown for optimal readability and searchability

## Contributing

Contributions are welcome! Please ensure that:
- Only official, verified legal documents are added
- All code follows the existing security and architectural patterns
- New features include appropriate documentation

## Support

For technical issues or questions about the codebase, please open an issue in the project repository.