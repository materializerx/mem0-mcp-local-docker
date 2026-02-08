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

### 1. Start the backing services

Ensure your Docker Compose stack is running with PostgreSQL (pgvector) and Neo4j containers. These should be configured with `restart: unless-stopped` so they survive VM reboots.

### 2. Create `.env`

```bash
cp .env.example .env
```

Required variables:

```env
OPENAI_API_KEY=sk-...

# PostgreSQL (pgvector)
POSTGRES_HOST=localhost
POSTGRES_PORT=8432
POSTGRES_DB=postgres
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres

# Neo4j (graph store)
NEO4J_URI=bolt://localhost:8687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=mem0graph

# Mem0 defaults
MEM0_DEFAULT_USER_ID=sisyphus
MEM0_ENABLE_GRAPH_DEFAULT=true
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
