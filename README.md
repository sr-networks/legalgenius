# LegalGenius

A German legal research and question-answering system that provides AI-powered search capabilities over German federal laws, regulations, and court decisions.

## Overview

LegalGenius combines a comprehensive corpus of German legal documents with an intelligent search agent to help users find relevant legal information. The system uses a Model Context Protocol (MCP) server architecture with advanced search capabilities powered by ripgrep and natural language processing.

## Features

- **Comprehensive Legal Database**: Complete collection of German federal laws and regulations (Bundesgesetze und -verordnungen) in Markdown format
- **Court Decision Archive**: Extensive collection of court decisions organized by year (1970-2029)
- **Intelligent Search**: Boolean query support with AND/OR operators and parentheses
- **Multi-Provider LLM Support**: Compatible with OpenRouter, Nebius, and Ollama
- **Advanced Text Search**: Powered by ripgrep for fast, precise text matching
- **Context-Aware Results**: Provides relevant excerpts with configurable context
- **German Language Optimized**: Designed specifically for German legal terminology and structure

## Quick Start

### Prerequisites

- Python 3.8+
- ripgrep (`rg`) installed and available in PATH
- An API key for your chosen LLM provider

### Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd legalgenius
```

2. Set up the environment:
```bash
make venv
make dev
```

3. Configure your LLM provider by setting environment variables:

**For OpenRouter (default):**
```bash
export OPENROUTER_API_KEY="your-api-key"
export OPENROUTER_MODEL="anthropic/claude-sonnet-4"  # optional
```

**For Nebius:**
```bash
export LLM_PROVIDER="nebius"
export NEBIUS_API_KEY="your-api-key"
export NEBIUS_MODEL="your-model-id"
```

**For Ollama (local):**
```bash
export LLM_PROVIDER="ollama"
export OLLAMA_MODEL="qwen/qwen3-4b-2507"  # optional
```

### Usage

#### Command Line Interface

Ask a legal question using the CLI:

```bash
make client q="Was ist die Kündigungsfrist bei Mietverträgen?"
```

Or use the Python client directly:

```bash
python client/agent_cli.py "Was sind die Voraussetzungen für eine Scheidung?"
```

#### Starting the MCP Server

To run the server independently:

```bash
make server
```

## Architecture

### Components

1. **MCP Server** (`mcp_server/`):
   - `server.py`: JSON-RPC server handling tool calls
   - `tools.py`: Core search and file access tools with security sandbox
   - Provides secure, sandboxed access to legal documents

2. **Client** (`client/`):
   - `agent_cli.py`: Command-line interface with LLM integration
   - Supports multiple LLM providers through OpenAI-compatible APIs
   - Implements function calling for intelligent tool usage

3. **Data** (`data/`):
   - `gesetze/`: German federal laws and regulations in Markdown
   - `urteile_markdown_by_year/`: Court decisions organized by year
   - All content sourced from official German legal repositories

### Available Tools

- **`file_search`**: Boolean content search across the legal corpus
- **`search_rg`**: Precise line-by-line search using ripgrep
- **`read_file_range`**: Extract text snippets with configurable context
- **`list_paths`**: Browse available documents and directories

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
├── client/               # CLI client and LLM integration
├── mcp_server/          # MCP server implementation
├── data/                # Legal document corpus
│   ├── gesetze/        # Federal laws and regulations
│   └── urteile_markdown_by_year/  # Court decisions
├── logs/               # Session logs
├── Makefile           # Build and development commands
└── README.md
```

### Available Make Commands

- `make dev`: Install dependencies in virtual environment
- `make server`: Start the MCP server
- `make client q="query"`: Run a query through the client
- `make test`: Run tests (if available)
- `make venv`: Create virtual environment

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