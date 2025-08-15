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
        # Human-readable log lines
        def _fmt() -> str:
            if tool == "read_file_range":
                path = (result or {}).get("path") or args.get("path")
                text = (result or {}).get("text", "")
                return f"tool: {tool}\npath: {path}\nresult: {text}"
            if tool == "search_rg":
                hits = (result or {}).get("hits", [])
                q = args.get("query")
                lines: List[str] = [f"tool: {tool}", f"query: {q}", f"hits: {len(hits)}"]
                for h in hits[:5]:
                    p = h.get("path")
                    ln = h.get("lines", {}).get("line_number")
                    tx = (h.get("lines", {}).get("text") or "").strip()
                    lines.append(f"- {p}#L{ln}: {tx}")
                return "\n".join(lines)
            if tool in ("file_search", "list_paths"):
                files = (result or {}).get("files", [])
                q = args.get("query") or args.get("subdir")
                header = f"tool: {tool}\nquery: {q}\nfiles ({len(files)}):"
                body = "\n".join(files[:20])
                return f"{header}\n{body}" if files else header
            return f"tool: {tool}\n" + json.dumps(result, ensure_ascii=False)

        out = _fmt()
        try:
            sys.stdout.write(out + "\n")
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
    temperature: float = 0.0,
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
            max_tokens=800,
            extra_body={},
        )
    except Exception as e:
        raise RuntimeError(f"LLM request failed: {e}")
    try:
        return completion.choices[0].message.content or ""
    except Exception as e:
        raise RuntimeError(f"LLM response parse error: {e}")


TOOL_SUMMARY = (
    "Verfügbare Werkzeuge (Function Calling):\n"
    "1) file_search: Argumente {query: Zeichenkette mit AND/OR und Klammern, glob?: Zeichenkette, max_results?: Zahl}. Rückgabe {files: Zeichenkette[]}.\n"
    "2) list_paths: Argumente {subdir?: Zeichenkette}. Rückgabe {files: Zeichenkette[]} der erlaubten Dateien unterhalb von subdir. Für das Wurzelverzeichnis verwende '.'.\n"
    "3) search_rg (ripgrep): Argumente {query: Zeichenkette, file_list?: Zeichenkette[], max_results?: Zahl, context_lines?: Zahl}. Rückgabe {hits: [...]}\n"
    "4) read_file_range: Argumente {path, start, end, context?}. Rückgabe: Textausschnitt um den Treffer.\n"
)

SYSTEM_PROMPT = (
    "Du bist ein Recherche-Agent für deutsches Recht. Ziel: Beantworte die Nutzerfrage mithilfe der bereitgestellten Werkzeuge.\n"
    "Richtlinien:\n"
    "- Überlege zuerst, welche Rechtsquellen, Gesetze oder Verfahren relevant sein könnten."
    "- Denke über passende Suchbegriffe nach, die zur Frage und zum Rechtskorpus passen."
    "- Der Rechtskorpus besteht aus allen Gesetzen in Deutschland."
    "- Sie sind in mehreren Unterordnern abgelegt, auf die du mit den Werkzeugen zugreifen kannst."
    "- Nutze zuerst list_paths, um verfügbare Dateien zu sichten; verwende dann file_search zur Vorauswahl; nutze anschließend search_rg für präzise Fundstellen."
    "- Überlege, wie du die Ordnerstruktur, Gesetzesnamen und Dateinamen ausnutzen kannst."
    "- Reflektiere die Ergebnisse und ob sie für eine Antwort ausreichen."
    "- Falls nicht ausreichend, verfeinere oder erweitere die Suche, erhöhe ggf. max_results/context_lines und versuche die Werkzeuge erneut.\n"
    "- Verwende keine Abkürzungen oder Akronyme in Suchanfragen (z. B. 'Bürgerliches Gesetzbuch' statt 'BGB')."
    "- Suche auch mit search_rg in der neueren Rechtsprechung im Ordner urteile_markdown_by_year."
    "- Falls search_rg keine Ergebnisse liefert, vereinfache oder erweitere die Suchbegriffe."
    "- Wenn ausreichend, erzeuge final_answer mit kurzer Textstelle und Zitation (Pfad + Zeilennummer).\n"
    "- Bei Abbruch wegen Limit: final_answer mit kurzer Erklärung, was versucht wurde und warum keine Antwort gefunden wurde.\n\n"
    + TOOL_SUMMARY
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
                        "glob": {"type": "string"},
                        "max_results": {"type": "integer", "minimum": 10},
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
                        "subdir": {"type": "string"},
                    },
                    "required": ["subdir"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_rg",
                "description": "Search lines using ripgrep. Optional file_list narrows search. Use only one keyword or phrase per search. do not list several keywords.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "file_list": {"type": "array", "items": {"type": "string"}},
                        "max_results": {"type": "integer", "minimum": 10},
                        "context_lines": {"type": "integer", "minimum": 1},
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
                        "context": {"type": "integer", "minimum": 0},
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

    def dispatch_list_paths(subdir: Optional[str] = None) -> str:
        res = mcp.call_tool("list_paths", {
            "subdir": subdir,
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
        "list_paths": dispatch_list_paths,
        "search_rg": dispatch_search_rg,
        "read_file_range": dispatch_read_file_range,
    }

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Question: {query}"},
    ]

    steps = 0
    max_steps = 50
    while True:
        if steps >= max_steps:
            return "Konnte keine zufriedenstellende Antwort finden."
        print("\nSTEP", steps)
        used_any_tool = any(m.get("role") == "tool" for m in messages)
        tool_choice_val = "auto" if used_any_tool else "required"

        steps += 1
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice_val,
                extra_headers=extra_headers or None,
                parallel_tool_calls=False,
            )
        except Exception as e:
            return f"LLM create failed: {e}"

        # Guard against empty or malformed responses
        if not getattr(resp, "choices", None) or not resp.choices:
            # Retry next loop iteration
            time.sleep(0.2)
            continue

        msg = resp.choices[0].message
        out_text = getattr(msg, "content", None) or getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None) or ""
        if out_text:
            print(out_text, "\n")
        tool_calls = getattr(msg, "tool_calls", None)
#        print (tool_calls)
        fc = getattr(msg, "function_call", None)
        if fc and not tool_calls:
            tool_calls = [{
                "id": "fc_1",
                "type": "function",
                "function": {"name": fc.name, "arguments": fc.arguments or "{}"},
            }]
        if tool_calls:
            # Build assistant message with properly stringified function.arguments
            assistant_msg: Dict[str, Any] = {
                "role": "assistant",
                "content": (getattr(msg, "content", None) or ""),
                "tool_calls": [],
            }
            for tc in tool_calls:
                args_val = getattr(tc.function, "arguments", "")
                if not isinstance(args_val, str):
                    try:
                        args_val = json.dumps(args_val, ensure_ascii=False)
                    except Exception:
                        args_val = "{}"
                assistant_msg["tool_calls"].append({
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": args_val},
                })
            messages.append(assistant_msg)
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
                    "content": result_text,
                })
            continue

        # Otherwise we're done
        return msg.content or ""


def main():
    parser = argparse.ArgumentParser(description="Legal QA over local corpus via MCP + LLM agent")
    parser.add_argument("query", type=str, help="User legal question")
    #"qwen/qwen3-235b-a22b" geht aber langsam
    # qwen/qwen3-235b-a22b-thinking-2507 etwas schneller
    # "openai/gpt-5-mini" und nano gehen jetzt gut!
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
#        print(answer)
    finally:
        mcp.close()


if __name__ == "__main__":
    main()
