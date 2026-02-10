import json

from mem0_mcp_server.server import _mem0_call


def test_mem0_call_wraps_list_results_in_results_envelope():
    response = _mem0_call(lambda: [{"id": "1", "memory": "hello"}])

    assert json.loads(response) == {"results": [{"id": "1", "memory": "hello"}]}


def test_mem0_call_keeps_dict_results_unchanged():
    response = _mem0_call(lambda: {"results": [{"id": "1"}]})

    assert json.loads(response) == {"results": [{"id": "1"}]}
