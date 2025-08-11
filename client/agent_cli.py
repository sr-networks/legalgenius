import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from openai import OpenAI

import yaml

CONFIG_PATH = Path("configs/config.yaml")


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {
        "legal_doc_root": "./data/",
        "glob": "**/*.{txt,md}",
        "max_results": 50,
        "context_bytes": 300,
    }


class MCPClient:
    def __init__(self, server_cmd: Optional[List[str]] = None, cwd: Optional[Path] = None, env: Optional[dict] = None):
        if server_cmd is None:
            server_cmd = [sys.executable, "-u", "mcp_server/server.py"]
        self.proc = subprocess.Popen(
            server_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd or Path.cwd(),
            env=env,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._id = 0

    def call_tool(self, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        self._id += 1
        req = {"jsonrpc": "2.0", "id": self._id, "method": "call_tool", "params": {"tool": tool, "args": args}}
        assert self.proc.stdin and self.proc.stdout
        self.proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("No response from MCP server")
        resp = json.loads(line)
        if "error" in resp:
            raise RuntimeError(resp["error"].get("message", "Unknown error"))
        result = resp.get("result", {})
        # Log tool call result to stdout as JSON
        try:
            log_record = {"tool": tool, "args": args, "result": result}
            sys.stdout.write(json.dumps(log_record, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        except Exception:
            pass
        return result

    def close(self):
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        finally:
            try:
                self.proc.terminate()
            except Exception:
                pass


@dataclass
class Hit:
    path: str
    line_number: int
    line_text: str
    byte_start: int
    byte_end: int


# -------- LLM backend (OpenRouter via OpenAI-style API) --------

def call_llm(
    client: OpenAI,
    messages: List[Dict[str, str]],
    model: str,
    referer: Optional[str] = None,
    site_title: Optional[str] = None,
    temperature: float = 0.2,
) -> str:
    extra_headers: Dict[str, str] = {}
    if referer:
        extra_headers["HTTP-Referer"] = referer
    if site_title:
        extra_headers["X-Title"] = site_title
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            extra_headers=extra_headers or None,
            extra_body={},
        )
    except Exception as e:
        raise RuntimeError(f"LLM request failed: {e}")
    try:
        return completion.choices[0].message.content or ""
    except Exception as e:
        raise RuntimeError(f"LLM response parse error: {e}")


TOOL_SUMMARY = (
    "You can call tools via JSON. Available tools:\n"
    "1) file_search:\n"
    "   args: {query: string (use AND/OR and parentheses), glob?: string, max_results?: int}.\n"
    "   Returns: {files: string[]} where each file contains all terms in a conjunction somewhere in the file.\n"
    "2) list_paths:\n"
    "   args: {subdir?: string (default '.')}. Returns {files: string[]} of allowed files under subdir.\n"
    "3) search_rg (ripgrep):\n"
    "   args: {query: string, file_list?: string[], max_results?: int, context_lines?: int, context_bytes?: int}.\n"
    "   Returns: {hits: [{path, lines:{text, line_number}, byte_range, preview?}]}."
    "   Use a query with one keyword or a phrase. For search_rg never use boolean AND/OR and parentheses.\n"
    "   For search_rg, be extremely specific about the file names and only use file names that have been listed by other tools."
    "4) read_file_range: args: {path: string, start: int, end: int, context?: int}. Returns text around a match.\n"
)

FORMAT_INSTRUCTIONS = (
    "For a tool call, respond ONLY with a JSON object. One of:\n"
    "{\"action\": \"file_search\", \"args\": {\"query\": string}}\n"
    "{\"action\": \"list_paths\", \"args\": {\"query\": string}}\n"
    "{\"action\": \"search_rg\", \"args\": {\"query\": string, \"glob\": string|null, \"context_lines\": int|null}}\n"
    "For search keywords, never use an abbreviation or an acronym. For example, use 'Baugesetzbuch' instead of 'BauGB'."
)

SYSTEM_PROMPT = (
    "You are a legal research agent. Goal: answer the user's question using provided tools.\n"
    "Policy:\n"
    "- First think which legal resources, laws or legal procedures could be relevant." 
    "- Think about appropriate keywords to search for that are relevant to the question and the legal corpus." 
    "- The legal corpus consists of all the laws in Germany."
    "- They are stored in a number of subfolders which you can access using the tools."
    "- You must first use the list_paths tool to get a list of all files in the legal corpus."
    "- Think which file could be related to a law or legal domain."
    "- Think how you can leverage the tools and the structure of folders and laws and the meaning of filenames."
    "- Reflect on the results and whether it is sufficient to answer the user's request."
    "- If no sufficient knowledge is obtained yet, refine the requests, broaden the search, increase max_results and context_lines and try tool use again.\n"
    "- If it suffices, produce final_answer with a short quote and a citation (path + line number).\n"
    "- When stopping due to limit, produce final_answer explaining what was tried and why no answer found.\n"
    + "\n" + TOOL_SUMMARY + "\n" + FORMAT_INSTRUCTIONS
)


def summarize_files(files: List[str], limit: int = 20) -> str:
    if not files:
        return "No files."
    return "Top files:\n" + "\n".join(f"- {p}" for p in files[:limit])


def summarize_hits(hits: List[Dict[str, Any]], limit: int = 5) -> str:
    if not hits:
        return "No hits."
    lines: List[str] = []
    for h in hits[:limit]:
        path = h.get("path")
        ln = h.get("lines", {}).get("line_number")
        text = (h.get("lines", {}).get("text") or "").strip()
        lines.append(f"- {path}#L{ln}: {text[:180]}")
    return "Top hits:\n" + "\n".join(lines)


# Responses API tools spec for function-calling

def _build_tools_spec() -> List[Dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "file_search",
                "description": "Return files whose contents match a boolean query (AND/OR, parentheses) over the legal corpus.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "glob": {"type": ["string", "null"]},
                        "max_results": {"type": ["integer", "null"], "minimum": 40},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_paths",
                "description": "List allowed files under a subdirectory (relative to sandbox root).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "subdir": {"type": ["string", "null"]},
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_rg",
                "description": "Search lines using ripgrep (supports boolean AND/OR and parentheses). Optional file_list narrows search.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "file_list": {"type": ["array", "null"], "items": {"type": "string"}},
                        "max_results": {"type": ["integer", "null"], "minimum": 1},
                        "context_lines": {"type": ["integer", "null"], "minimum": 0},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file_range",
                "description": "Read a UTF-8 snippet around a byte range with optional context.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "start": {"type": "integer", "minimum": 0},
                        "end": {"type": "integer", "minimum": 0},
                        "context": {"type": ["integer", "null"], "minimum": 0},
                    },
                    "required": ["path", "start", "end"],
                },
            },
        },
    ]


def run_agent(query: str, mcp: MCPClient, cfg: dict, client: OpenAI, model: str, referer: Optional[str], site_title: Optional[str]) -> str:
    tools = _build_tools_spec()
    extra_headers: Dict[str, str] = {}
    if referer:
        extra_headers["HTTP-Referer"] = referer
    if site_title:
        extra_headers["X-Title"] = site_title

    # Dispatcher for function tools
    def dispatch_file_search(query: str, glob: Optional[str] = None, max_results: Optional[int] = None) -> str:
        res = mcp.call_tool("file_search", {
            "query": query,
            "glob": glob or cfg.get("glob", "**/*.{txt,md}"),
            "max_results": max_results or cfg.get("max_results", 50),
        })
        return json.dumps(res, ensure_ascii=False)

    def dispatch_search_rg(query: str, file_list: Optional[List[str]] = None, max_results: Optional[int] = None, context_lines: Optional[int] = None) -> str:
        res = mcp.call_tool("search_rg", {
            "query": query,
            "file_list": file_list,
            "max_results": max_results or 20,
            "context_lines": context_lines or 2,
        })
        return json.dumps(res, ensure_ascii=False)

    def dispatch_read_file_range(path: str, start: int, end: int, context: Optional[int] = None) -> str:
        res = mcp.call_tool("read_file_range", {
            "path": path,
            "start": int(start),
            "end": int(end),
            "context": context or cfg.get("context_bytes", 300),
        })
        return json.dumps(res, ensure_ascii=False)

    DISPATCH: Dict[str, Any] = {
        "file_search": dispatch_file_search,
        "search_rg": dispatch_search_rg,
        "read_file_range": dispatch_read_file_range,
    }

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Question: {query}"},
    ]

    steps = 0
    max_steps = 10
    while True:
        if steps >= max_steps:
            return "Konnte keine zufriedenstellende Antwort in 10 Schritten finden."
        print("\nSTEP", steps)
        steps += 1
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
#                extra_headers=extra_headers or None,
            )
        except Exception as e:
            return f"LLM create failed: {e}"

        msg = resp.choices[0].message
        print (msg.content,"\n")
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            # include assistant message that requested tool calls
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [tc.model_dump() for tc in tool_calls],
            })
            for tc in tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                fn = DISPATCH.get(name)
                if not fn:
                    result_text = json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False)
                else:
                    try:
                        result_text = fn(**args)
                    except Exception as e:
                        result_text = json.dumps({"error": str(e)}, ensure_ascii=False)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": name,
                    "content": result_text,
                })
            continue

        # Otherwise we're done
        return msg.content or ""


def main():
    parser = argparse.ArgumentParser(description="Legal QA over local corpus via MCP + LLM agent")
    parser.add_argument("query", type=str, help="User legal question")
    parser.add_argument("--model", default=os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4"), help="OpenRouter model id")
    parser.add_argument("--api-key", default=os.environ.get("OPENROUTER_API_KEY"), help="OpenRouter API key")
    parser.add_argument("--base-url", default=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"), help="OpenAI-compatible base URL")
    parser.add_argument("--referer", default=os.environ.get("OPENROUTER_SITE_URL"), help="HTTP-Referer header (your site URL)")
    parser.add_argument("--site-title", default=os.environ.get("OPENROUTER_SITE_TITLE"), help="X-Title header (your site title)")
    
    args = parser.parse_args()

    if not args.api_key:
        print("Missing OpenRouter API key. Set OPENROUTER_API_KEY or pass --api-key.", file=sys.stderr)
        raise SystemExit(2)

    cfg = load_config()
    server_cmd_env = os.environ.get("MCP_SERVER_CMD")
    server_cmd = server_cmd_env.split() if server_cmd_env else None

    env = os.environ.copy()
    env["PYTHONPATH"] = env.get("PYTHONPATH") or str(Path.cwd())
    env.setdefault("LEGAL_DOC_ROOT", cfg.get("legal_doc_root", "./data/"))

    mcp = MCPClient(server_cmd=server_cmd, env=env)
    try:
        client = OpenAI(base_url=args.base_url, api_key=args.api_key)
        answer = run_agent(args.query, mcp, cfg, client, model=args.model, referer=args.referer, site_title=args.site_title)
        print(answer)
    finally:
        mcp.close()


if __name__ == "__main__":
    main()
