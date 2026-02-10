# Mem0 Tool TypeError Handoff (2026-02-10)

## Issue

- Symptom in OpenCode tool layer: `TypeError: undefined is not an object (evaluating 'output.output.toLowerCase')`
- Failing tools: `functions.mem0_search_memories`, `functions.mem0_get_memories` (and other `functions.mem0_*`)
- Impact: agent-side memory tools are unusable in current session.

## Current Status

- Mem0 backend is healthy.
  - Docker stack is up: API + Postgres + Neo4j.
  - Direct Python SDK calls succeed and return memory records.
- OpenCode MCP shows mem0 as connected.
  - `opencode mcp list` reports `mem0 connected`.
- Despite that, `functions.mem0_*` still fails with the same TypeError.

## Root Cause Hypothesis

- Most likely failure domain is OpenCode mem0 tool parsing/bridge layer, not Mem0 backend.
- Error indicates parser expects a nested `output.output` string and attempts `.toLowerCase()` on undefined.
- There may be session/process caching or a strict response-shape assumption in the client tool runner.

## Work Completed

### 1) Upstream checks (official + fork)

- Official repo: `https://github.com/mem0ai/mem0-mcp`
- Fork in use: `https://github.com/materializerx/mem0-mcp-local-docker`
- Compared official vs fork server behavior around tool response contracts.

Findings:

- Official and fork both serialize tool returns via JSON strings in server wrapper.
- Fork uses self-hosted `Memory` path and can encounter list-shaped payloads in some flows.

### 2) Local compatibility patch (with test-first)

Changed file:

- `src/mem0_mcp_server/server.py`

Change:

- In `_mem0_call`, normalize list result to `{"results": result}` before `json.dumps`.

Added tests:

- `tests/test_mem0_call_contract.py`
  - verifies list return is wrapped into `{"results": [...]}`
  - verifies dict return remains unchanged

Test run:

- `./.venv/bin/pytest tests/test_mem0_call_contract.py -q`
- Result: `2 passed`

### 3) Runtime checks

- Verified mem0 backend directly via Python script using `Memory.from_config(...).get_all(user_id='sisyphus')`.
- Result: success with returned records.
- Re-checked OpenCode MCP connection: connected.
- Re-tested `functions.mem0_*`: still failing with same TypeError.

## Why This Is Still Broken

- The fork patch improved response normalization and is covered by tests.
- The failing TypeError persists in OpenCode tool invocation path, suggesting issue remains in:
  - OpenCode-side tool result parser assumptions, or
  - stale process/session cache not reloading expected bridge behavior.

## Reproduction Steps

1. Call `functions.mem0_search_memories` with any query.
2. Observe immediate tool error:
   - `TypeError: undefined is not an object (evaluating 'output.output.toLowerCase')`
3. Call `functions.mem0_get_memories` similarly; same error.

## High-Value Next Steps (new session)

1. Confirm OpenCode process reload semantics and force full runtime restart (not just MCP child process).
2. Add temporary OpenCode-side instrumentation around mem0 tool result parsing to capture raw envelope before transform.
3. Verify actual shape seen by OpenCode parser for mem0 tool responses after patch.
4. If parser requires `output` field, add compatibility envelope in fork (for example `{"output": "...", "results": [...]}`) behind minimal guarded change and re-test.
5. Re-run `functions.mem0_search_memories` and `functions.mem0_get_memories` from fresh session.

## gcloud Auth Side Note

- `gcloud` is installed.
- Current default compute service account lacks broad compute scope needed for some instance ops.
- Preferred identity for operations: `opencode@moltbot-gateway-20260127.iam.gserviceaccount.com` via key-file activation in future session.

## Files Touched in This Work

- `src/mem0_mcp_server/server.py`
- `tests/test_mem0_call_contract.py`
- `docs/handoffs/2026-02-10-mem0-tool-typeerror-handoff.md`
