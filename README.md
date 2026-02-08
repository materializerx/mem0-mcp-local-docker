# mem0-mcp-local-docker

A self-hosted [Mem0](https://mem0.ai) MCP server adapted from the [official mem0-mcp](https://github.com/mem0ai/mem0-mcp) to run entirely on your own infrastructure using Docker containers (PostgreSQL with pgvector + Neo4j).

The official server connects to Mem0's cloud API via `MemoryClient`. This fork replaces it with the local `Memory` class, pointing to your own Postgres and Neo4j instances.

## Prerequisites

- Docker & Docker Compose
- Python >= 3.10
- An OpenAI API key (used by Mem0 internally for embeddings and LLM)

## Architecture

```
┌─────────────────────────────────┐
│  MCP Client (OpenCode, Claude)  │
└──────────────┬──────────────────┘
               │ stdio
┌──────────────▼──────────────────┐
│     mem0-mcp-server (Python)    │
│  src/mem0_mcp_server/server.py  │
└──┬───────────────────────────┬──┘
   │                           │
┌──▼─────────────┐  ┌─────────▼──────────┐
│  PostgreSQL    │  │      Neo4j         │
│  (pgvector)    │  │  (graph store)     │
│  port: 8432    │  │  port: 8687        │
└────────────────┘  └────────────────────┘
```

## Setup

### 1. Clone and configure

```bash
git clone https://github.com/materializerx/mem0-mcp-local-docker.git
cd mem0-mcp-local-docker
cp .env.example .env
```

Edit `.env` and set your `OPENAI_API_KEY`. The other defaults match the included `docker-compose.yml`.

### 2. Start backing services

```bash
docker compose up -d
```

This starts PostgreSQL (pgvector) on port `8432` and Neo4j on port `8687`. Both are configured with `restart: unless-stopped` so they survive reboots.

Wait for healthy status:

```bash
docker compose ps
```

### 3. Install dependencies

```bash
uv sync
# or
pip install -e .
```

### 4. Run the server

```bash
uv run mem0-mcp-server
# or
python -m mem0_mcp_server.server
```

The server runs over **stdio** by default (for MCP client integration).

## MCP Client Configuration

### OpenCode (`oh-my-opencode.json`)

```json
{
  "mcp": {
    "mem0": {
      "type": "stdio",
      "command": "/path/to/mem0-mcp/.venv/bin/python",
      "args": ["-m", "mem0_mcp_server.server"],
      "env": {
        "OPENAI_API_KEY": "sk-...",
        "MEM0_DEFAULT_USER_ID": "sisyphus",
        "MEM0_ENABLE_GRAPH_DEFAULT": "true"
      }
    }
  }
}
```

### Claude Desktop

```json
{
  "mcpServers": {
    "mem0": {
      "command": "uvx",
      "args": ["mem0-mcp-server"],
      "env": {
        "OPENAI_API_KEY": "sk-...",
        "MEM0_DEFAULT_USER_ID": "your-handle",
        "MEM0_ENABLE_GRAPH_DEFAULT": "true"
      }
    }
  }
}
```

## Tools

| Tool | Description |
|------|-------------|
| `add_memory` | Store a preference, fact, or conversation snippet |
| `search_memories` | Semantic search over existing memories |
| `get_memories` | List memories with filters and pagination |
| `get_memory` | Fetch a single memory by ID |
| `update_memory` | Overwrite a memory's text |
| `delete_memory` | Delete a single memory |
| `delete_all_memories` | Bulk delete all memories in a scope |
| `delete_entities` | Remove a user/agent/run and cascade-delete its memories |

## Key Differences from Official

| Aspect | Official (`mem0ai/mem0-mcp`) | This Fork |
|--------|------------------------------|-----------|
| Backend | Mem0 Cloud API (`MemoryClient`) | Local `Memory` class |
| Vector Store | Mem0 Cloud | Self-hosted PostgreSQL + pgvector |
| Graph Store | Mem0 Cloud | Self-hosted Neo4j |
| LLM | Mem0 Cloud | OpenAI API (configurable model) |
| Embedder | Mem0 Cloud | OpenAI `text-embedding-3-small` |
| Auth | `MEM0_API_KEY` | `OPENAI_API_KEY` + DB credentials |
| `list_entities` | Supported | Not available (returns error) |

## License

[Apache License 2.0](LICENSE)
