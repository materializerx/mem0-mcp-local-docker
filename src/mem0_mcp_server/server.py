"""MCP server that exposes Mem0 REST endpoints as MCP tools."""

# pyright: reportMissingImports=false, reportImplicitRelativeImport=false

from __future__ import annotations

import json
import logging
import os
from typing import Annotated, Any, Dict, Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mem0 import Memory
from mem0.exceptions import MemoryError
from pydantic import Field

try:  # Support both package (`python -m mem0_mcp.server`) and script (`python mem0_mcp/server.py`) runs.
    from .schemas import (
        AddMemoryArgs,
        DeleteAllArgs,
        DeleteEntitiesArgs,
        GetMemoriesArgs,
        SearchMemoriesArgs,
        ToolMessage,
    )
except ImportError:  # pragma: no cover - fallback for script execution
    from mem0_mcp_server.schemas import (
        AddMemoryArgs,
        DeleteAllArgs,
        DeleteEntitiesArgs,
        GetMemoriesArgs,
        SearchMemoriesArgs,
        ToolMessage,
    )

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("mem0_mcp_server")


# graph remains off by default , also set the default user_id to "mem0-mcp" when nothing set
ENV_DEFAULT_USER_ID = os.getenv("MEM0_DEFAULT_USER_ID", "mem0-mcp")
ENV_ENABLE_GRAPH_DEFAULT = os.getenv("MEM0_ENABLE_GRAPH_DEFAULT", "false").lower() in {
    "1",
    "true",
    "yes",
}

_memory_client_instance: Optional[Memory] = None


def _config_value(source: Any, field: str):
    if source is None:
        return None
    if isinstance(source, dict):
        return source.get(field)
    return getattr(source, field, None)


def _extract_id_value(value: Any) -> Optional[str]:
    if isinstance(value, (str, int, float)):
        return str(value)
    if not isinstance(value, dict):
        return None

    eq_value = value.get("eq")
    if isinstance(eq_value, (str, int, float)):
        return str(eq_value)

    in_values = value.get("in")
    if isinstance(in_values, list) and in_values:
        first = in_values[0]
        if isinstance(first, (str, int, float)):
            return str(first)

    return None


def _extract_user_id(filters: Optional[Dict[str, Any]], default_user_id: str) -> str:
    if not filters:
        return default_user_id

    queue: list[Any] = [filters]
    while queue:
        node = queue.pop(0)
        if isinstance(node, dict):
            if "user_id" in node:
                extracted = _extract_id_value(node.get("user_id"))
                if extracted:
                    return extracted
            queue.extend(node.values())
        elif isinstance(node, list):
            queue.extend(node)

    return default_user_id


def _mem0_call(func, *args, **kwargs):
    try:
        result = func(*args, **kwargs)
    except MemoryError as exc:  # surface structured error back to MCP client
        logger.error("Mem0 call failed: %s", exc)
        # returns the erorr to the model
        return json.dumps(
            {
                "error": str(exc),
                "status": getattr(exc, "status", None),
                "payload": getattr(exc, "payload", None),
            },
            ensure_ascii=False,
        )
    if isinstance(result, list):
        result = {"results": result}
    return json.dumps(result, ensure_ascii=False)


def _resolve_settings(ctx: Context[Any, Any, Any] | None) -> tuple[str, bool]:
    session_config = getattr(ctx, "session_config", None)
    default_user = _config_value(session_config, "default_user_id") or ENV_DEFAULT_USER_ID
    enable_graph_default = _config_value(session_config, "enable_graph_default")
    if enable_graph_default is None:
        enable_graph_default = ENV_ENABLE_GRAPH_DEFAULT

    return default_user, enable_graph_default


# init the client
def _mem0_client() -> Memory:
    global _memory_client_instance

    if _memory_client_instance is None:
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if not openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is required to initialize self-hosted Mem0 (used by both LLM and embedder)."
            )

        config = {
            "version": "v1.1",
            "vector_store": {
                "provider": "pgvector",
                "config": {
                    "host": os.getenv("POSTGRES_HOST", "localhost"),
                    "port": int(os.getenv("POSTGRES_PORT", "8432")),
                    "dbname": os.getenv("POSTGRES_DB", "postgres"),
                    "user": os.getenv("POSTGRES_USER", "postgres"),
                    "password": os.getenv("POSTGRES_PASSWORD", "postgres"),
                    "collection_name": "memories",
                },
            },
            "graph_store": {
                "provider": "neo4j",
                "config": {
                    "url": os.getenv("NEO4J_URI", "bolt://localhost:8687"),
                    "username": os.getenv("NEO4J_USERNAME", "neo4j"),
                    "password": os.getenv("NEO4J_PASSWORD", "mem0graph"),
                },
            },
            "llm": {
                "provider": "openai",
                "config": {
                    "api_key": openai_api_key,
                    "temperature": 0.2,
                    "model": "gpt-4.1-nano-2025-04-14",
                },
            },
            "embedder": {
                "provider": "openai",
                "config": {
                    "api_key": openai_api_key,
                    "model": "text-embedding-3-small",
                },
            },
        }
        _memory_client_instance = Memory.from_config(config)

    return _memory_client_instance


def _default_enable_graph(enable_graph: Optional[bool], default: bool) -> bool:
    if enable_graph is None:
        return default
    return enable_graph


def create_server() -> FastMCP:
    """Create a FastMCP server usable via stdio or Docker."""

    server = FastMCP(
        "mem0",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8081")),
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    # graph is disabled by default to make queries simpler and fast
    # Mention " Enable/Use graph while calling memory " in your system prompt to run it in each instance

    @server.tool(
        description="Store a new preference, fact, or conversation snippet. Requires at least one: user_id, agent_id, or run_id."
    )
    def add_memory(
        text: Annotated[
            str,
            Field(
                description="Plain sentence summarizing what to store. Required even if `messages` is provided."
            ),
        ],
        messages: Annotated[
            Optional[list[Dict[str, str]]],
            Field(
                default=None,
                description="Structured conversation history with `role`/`content`. "
                "Use when you have multiple turns.",
            ),
        ] = None,
        user_id: Annotated[
            Optional[str],
            Field(default=None, description="Override the default user scope for this write."),
        ] = None,
        agent_id: Annotated[
            Optional[str], Field(default=None, description="Optional agent identifier.")
        ] = None,
        app_id: Annotated[
            Optional[str], Field(default=None, description="Optional app identifier.")
        ] = None,
        run_id: Annotated[
            Optional[str], Field(default=None, description="Optional run identifier.")
        ] = None,
        metadata: Annotated[
            Optional[Dict[str, Any]],
            Field(default=None, description="Attach arbitrary metadata JSON to the memory."),
        ] = None,
        enable_graph: Annotated[
            Optional[bool],
            Field(
                default=None,
                description="Set true only if the caller explicitly wants Mem0 graph memory.",
            ),
        ] = None,
        ctx: Context[Any, Any, Any] | None = None,
    ) -> str:
        """Write durable information to Mem0."""

        default_user, graph_default = _resolve_settings(ctx)
        args = AddMemoryArgs(
            text=text,
            messages=[ToolMessage(**msg) for msg in messages] if messages else None,
            user_id=user_id if user_id else (default_user if not (agent_id or run_id) else None),
            agent_id=agent_id,
            app_id=app_id,
            run_id=run_id,
            metadata=metadata,
            enable_graph=_default_enable_graph(enable_graph, graph_default),
        )
        payload = args.model_dump(exclude_none=True)
        payload.pop("enable_graph", None)
        payload.pop("app_id", None)
        conversation = payload.pop("messages", None)
        if not conversation:
            derived_text = payload.pop("text", None)
            if derived_text:
                conversation = [{"role": "user", "content": derived_text}]
            else:
                return json.dumps(
                    {
                        "error": "messages_missing",
                        "detail": "Provide either `text` or `messages` so Mem0 knows what to store.",
                    },
                    ensure_ascii=False,
                )
        else:
            payload.pop("text", None)

        client = _mem0_client()
        return _mem0_call(client.add, conversation, **payload)

    @server.tool(
        description="""Run a semantic search over existing memories.

        Use filters to narrow results. Common filter patterns:
        - Single user: {"AND": [{"user_id": "john"}]}
        - Agent memories: {"AND": [{"agent_id": "agent_name"}]}
        - Recent memories: {"AND": [{"user_id": "john"}, {"created_at": {"gte": "2024-01-01"}}]}
        - Multiple users: {"AND": [{"user_id": {"in": ["john", "jane"]}}]}
        - Cross-entity: {"OR": [{"user_id": "john"}, {"agent_id": "agent_name"}]}

        user_id is automatically added to filters if not provided.
        """
    )
    def search_memories(
        query: Annotated[str, Field(description="Natural language description of what to find.")],
        filters: Annotated[
            Optional[Dict[str, Any]],
            Field(
                default=None,
                description="Additional filter clauses (user_id injected automatically).",
            ),
        ] = None,
        limit: Annotated[
            Optional[int], Field(default=None, description="Maximum number of results to return.")
        ] = None,
        enable_graph: Annotated[
            Optional[bool],
            Field(
                default=None,
                description="Set true only when the user explicitly wants graph-derived memories.",
            ),
        ] = None,
        ctx: Context[Any, Any, Any] | None = None,
    ) -> str:
        """Semantic search against existing memories."""

        default_user, graph_default = _resolve_settings(ctx)
        args = SearchMemoriesArgs(
            query=query,
            filters=filters,
            limit=limit,
            enable_graph=_default_enable_graph(enable_graph, graph_default),
        )
        payload = args.model_dump(exclude_none=True)
        resolved_user_id = _extract_user_id(payload.get("filters"), default_user)
        # payload.pop("filters", None)  <-- FIXED: Do not remove filters
        payload.pop("enable_graph", None)
        payload["user_id"] = resolved_user_id
        client = _mem0_client()
        return _mem0_call(client.search, **payload)

    @server.tool(
        description="""Page through memories using filters instead of search.

        Use filters to list specific memories. Common filter patterns:
        - Single user: {"AND": [{"user_id": "john"}]}
        - Agent memories: {"AND": [{"agent_id": "agent_name"}]}
        - Recent memories: {"AND": [{"user_id": "john"}, {"created_at": {"gte": "2024-01-01"}}]}
        - Multiple users: {"AND": [{"user_id": {"in": ["john", "jane"]}}]}

        Pagination: Use page (1-indexed) and page_size for browsing results.
        user_id is automatically added to filters if not provided.
        """
    )
    def get_memories(
        filters: Annotated[
            Optional[Dict[str, Any]],
            Field(default=None, description="Structured filters; user_id injected automatically."),
        ] = None,
        page: Annotated[
            Optional[int], Field(default=None, description="1-indexed page number when paginating.")
        ] = None,
        page_size: Annotated[
            Optional[int],
            Field(default=None, description="Number of memories per page (default 10)."),
        ] = None,
        enable_graph: Annotated[
            Optional[bool],
            Field(
                default=None,
                description="Set true only if the caller explicitly wants graph-derived memories.",
            ),
        ] = None,
        ctx: Context[Any, Any, Any] | None = None,
    ) -> str:
        """List memories via structured filters or pagination."""

        default_user, graph_default = _resolve_settings(ctx)
        args = GetMemoriesArgs(
            filters=filters,
            page=page,
            page_size=page_size,
            enable_graph=_default_enable_graph(enable_graph, graph_default),
        )
        payload = args.model_dump(exclude_none=True)
        resolved_user_id = _extract_user_id(payload.get("filters"), default_user)
        # payload.pop("filters", None) <-- FIXED: Do not remove filters
        payload.pop("enable_graph", None)
        requested_page = payload.pop("page", None)
        requested_page_size = payload.pop("page_size", None)
        payload["user_id"] = resolved_user_id

        # FIXED: Pagination logic to fetch enough records for slicing
        if requested_page_size is not None:
            # If paging is requested, we need to fetch enough items to cover the requested page
            # e.g., for page 3 with size 10, we need at least 30 items
            page_num = max(requested_page or 1, 1)
            fetch_limit = page_num * requested_page_size
            payload["limit"] = fetch_limit
        else:
            payload["limit"] = 100

        client = _mem0_client()
        response = _mem0_call(client.get_all, **payload)
        if requested_page and requested_page_size:
            try:
                parsed = json.loads(response)
                results = parsed.get("results")
                if isinstance(results, list):
                    page_num = max(requested_page, 1)
                    page_len = max(requested_page_size, 1)
                    start = (page_num - 1) * page_len
                    end = start + page_len
                    parsed["results"] = results[start:end]
                response = json.dumps(parsed, ensure_ascii=False)
            except Exception:
                logger.exception("Failed to post-process pagination for get_memories")
        return response

    @server.tool(
        description="Delete every memory in the given user/agent/app/run but keep the entity."
    )
    def delete_all_memories(
        user_id: Annotated[
            Optional[str],
            Field(default=None, description="User scope to delete; defaults to server user."),
        ] = None,
        agent_id: Annotated[
            Optional[str], Field(default=None, description="Optional agent scope to delete.")
        ] = None,
        app_id: Annotated[
            Optional[str], Field(default=None, description="Optional app scope to delete.")
        ] = None,
        run_id: Annotated[
            Optional[str], Field(default=None, description="Optional run scope to delete.")
        ] = None,
        ctx: Context[Any, Any, Any] | None = None,
    ) -> str:
        """Bulk-delete every memory in the confirmed scope."""

        default_user, _ = _resolve_settings(ctx)
        args = DeleteAllArgs(
            user_id=user_id or default_user,
            agent_id=agent_id,
            app_id=app_id,
            run_id=run_id,
        )
        payload = args.model_dump(exclude_none=True)
        payload.pop("app_id", None)
        client = _mem0_client()
        return _mem0_call(client.delete_all, **payload)

    @server.tool(description="List which users/agents/apps/runs currently hold memories.")
    def list_entities(ctx: Context[Any, Any, Any] | None = None) -> str:
        """List users/agents/apps/runs with stored memories."""

        _resolve_settings(ctx)
        return json.dumps(
            {
                "error": "unsupported_operation",
                "detail": "list_entities not available in self-hosted mode",
            },
            ensure_ascii=False,
        )

    @server.tool(description="Fetch a single memory once you know its memory_id.")
    def get_memory(
        memory_id: Annotated[str, Field(description="Exact memory_id to fetch.")],
        ctx: Context[Any, Any, Any] | None = None,
    ) -> str:
        """Retrieve a single memory once the user has picked an exact ID."""

        _resolve_settings(ctx)
        client = _mem0_client()
        return _mem0_call(client.get, memory_id)

    @server.tool(description="Overwrite an existing memory’s text.")
    def update_memory(
        memory_id: Annotated[str, Field(description="Exact memory_id to overwrite.")],
        text: Annotated[str, Field(description="Replacement text for the memory.")],
        ctx: Context[Any, Any, Any] | None = None,
    ) -> str:
        """Overwrite an existing memory’s text after the user confirms the exact memory_id."""

        _resolve_settings(ctx)
        client = _mem0_client()
        return _mem0_call(client.update, memory_id=memory_id, data=text)

    @server.tool(description="Delete one memory after the user confirms its memory_id.")
    def delete_memory(
        memory_id: Annotated[str, Field(description="Exact memory_id to delete.")],
        ctx: Context[Any, Any, Any] | None = None,
    ) -> str:
        """Delete a memory once the user explicitly confirms the memory_id to remove."""

        _resolve_settings(ctx)
        client = _mem0_client()
        return _mem0_call(client.delete, memory_id)

    @server.tool(
        description="Remove a user/agent/app/run record entirely (and cascade-delete its memories)."
    )
    def delete_entities(
        user_id: Annotated[
            Optional[str], Field(default=None, description="Delete this user and its memories.")
        ] = None,
        agent_id: Annotated[
            Optional[str], Field(default=None, description="Delete this agent and its memories.")
        ] = None,
        app_id: Annotated[
            Optional[str], Field(default=None, description="Delete this app and its memories.")
        ] = None,
        run_id: Annotated[
            Optional[str], Field(default=None, description="Delete this run and its memories.")
        ] = None,
        ctx: Context[Any, Any, Any] | None = None,
    ) -> str:
        """Delete a user/agent/app/run (and its memories) once the user confirms the scope."""

        _resolve_settings(ctx)
        args = DeleteEntitiesArgs(
            user_id=user_id,
            agent_id=agent_id,
            app_id=app_id,
            run_id=run_id,
        )
        if not any([args.user_id, args.agent_id, args.app_id, args.run_id]):
            return json.dumps(
                {
                    "error": "scope_missing",
                    "detail": "Provide user_id, agent_id, app_id, or run_id before calling delete_entities.",
                },
                ensure_ascii=False,
            )
        if args.app_id is not None:
            return json.dumps(
                {
                    "error": "unsupported_scope",
                    "detail": "app_id scope is not available in self-hosted mode",
                },
                ensure_ascii=False,
            )
        payload = {
            "user_id": args.user_id,
            "agent_id": args.agent_id,
            "run_id": args.run_id,
        }
        payload = {key: value for key, value in payload.items() if value is not None}
        client = _mem0_client()
        return _mem0_call(client.delete_all, **payload)

    # Add a simple prompt for server capabilities
    @server.prompt()
    def memory_assistant() -> str:
        """Get help with memory operations and best practices."""
        return """You are using the Mem0 MCP server for long-term memory management.

Quick Start:
1. Store memories: Use add_memory to save facts, preferences, or conversations
2. Search memories: Use search_memories for semantic queries
3. List memories: Use get_memories for filtered browsing
4. Update/Delete: Use update_memory and delete_memory for modifications

Filter Examples:
- User memories: {"AND": [{"user_id": "john"}]}
- Agent memories: {"AND": [{"agent_id": "agent_name"}]}
- Recent only: {"AND": [{"user_id": "john"}, {"created_at": {"gte": "2024-01-01"}}]}

Tips:
- user_id is automatically added to filters
- Use "*" as wildcard for any non-null value
- Combine filters with AND/OR/NOT for complex queries"""

    return server


def main() -> None:
    """Run the MCP server over stdio."""

    server = create_server()
    logger.info("Starting Mem0 MCP server (default user=%s)", ENV_DEFAULT_USER_ID)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
