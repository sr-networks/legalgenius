import sys
import json
import time
from pathlib import Path
from typing import Any, Dict

from mcp_server import tools

LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
SESSION_PATH = LOG_DIR / f"session_{int(time.time())}.jsonl"


def log_tool_call(tool: str, args: Dict[str, Any], result: Dict[str, Any]):
    truncated = result
    as_text = json.dumps(result, ensure_ascii=False)
    if len(as_text) > 2000:
        truncated = json.loads(as_text[:2000] + "...") if False else {"truncated": True}
    record = {"tool": tool, "args": args, "result": truncated, "ts": time.time()}
    with SESSION_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def handle_call(request: Dict[str, Any]) -> Dict[str, Any]:
    method = request.get("method")
    req_id = request.get("id")
    params = request.get("params") or {}

    if method == "call_tool":
        tool_name = params.get("tool")
        args = params.get("args") or {}
        try:
            if tool_name == "search_rg":
                result = tools.search_rg(**args)
            elif tool_name == "read_file_range":
                result = tools.read_file_range(**args)
            elif tool_name == "list_paths":
                result = tools.list_paths(**args)
            elif tool_name == "file_search":
                result = tools.file_search(**args)
            elif tool_name == "elasticsearch_search":
                result = tools.elasticsearch_search(**args)
            else:
                raise ValueError(f"Unknown tool: {tool_name}")
            log_tool_call(tool_name, args, result)
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": str(e)}}

    elif method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"ok": True}}

    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Method not found"}}


def main():
    # Simple line-delimited JSON-RPC over stdio
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle_call(req)
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
