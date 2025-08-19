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
                ln = args.get("start")
                le = args.get("end")
                return f"tool: {tool}\npath: {path}\nresult: {text}\nline: {ln}-{le}"
            if tool == "search_rg":
                matches = (result or {}).get("matches", [])
                q = args.get("query")
                f = args.get("file_list")
                l = args.get("line")
                lines: List[str] = [f"tool: {tool}", f"query: {q}", f"file_list: {f}", f"matches: {len(matches)}, line: {l}"]
                for m in matches[:5]:
                    p = m.get("file")
                    ln = m.get("line")
                    txt = m.get("text", "")[:100]
                    sec = m.get("section", "")
                    ctx_len = len(m.get("context", []))
                    byte_range = m.get("byte_range", [])
                    lines.append(f"  {p}:{ln} [{ctx_len} context lines] {txt}")
                    if sec:
                        lines.append(f"    Section: {sec[:80]}")
                    if byte_range:
                        lines.append(f"    Byte range: {byte_range[0]}-{byte_range[1]}")
                return "\n".join(lines)
            if tool in ("file_search", "list_paths"):
                files = (result or {}).get("files", [])
                q = args.get("query") or args.get("subdir")
                g = args.get("glob")
                header = f"tool: {tool}\nquery: {q}\nglob: {g}\nfiles ({len(files)}):"
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
#    "2) list_paths: Argumente {subdir?: Zeichenkette}. Rückgabe {files: Zeichenkette[]} der erlaubten Dateien unterhalb von subdir. Für das Wurzelverzeichnis verwende '.'. Unterverzeichnis gesetze enthält die Bundesgesetze, urteile_markdown_by_year die Rechtsprechung.\n"
    "3) search_rg (ripgrep): Argumente {query: Schlagwort, file_list?: Zeichenkette[], max_results?: Zahl, context_lines?: Zahl, regex?: bool, case_sensitive?: bool}. Rückgabe {matches: [{file, line, text, context, section, byte_range}]}. Liefert strukturierte Treffer mit Kontext, nächstem Header und Byte-Positionen für read_file_range.\n"
    "4) read_file_range: Argumente {path, start, end, context?, max_lines?}. Rückgabe: Textausschnitt um den Treffer (max. 20 Zeilen standardmäßig).\n"
)

SYSTEM_PROMPT = (
    "Du bist ein Recherche-Agent für deutsches Recht. Ziel: Beantworte die Nutzerfrage mithilfe der bereitgestellten Werkzeuge.\n"
    "Richtlinien:\n"
    "- Überlege zuerst, welche Rechtsquellen, Gesetze oder Verfahren relevant sein könnten."
    "- Denke über passende Suchbegriffe nach, die zur Frage und zum Rechtskorpus passen."
    "- Der Rechtskorpus besteht aus allen Gesetzen und Urteilen in Deutschland."
    "- Sie sind in mehreren Unterordnern abgelegt, auf die du mit den Werkzeugen zugreifen kannst."
#    "- Nutze zuerst list_paths, um verfügbare Dateien zu sichten"abs
    "- Verwende zuerst file_search um alle relevanten Dateien zu finden, die die wichtigen Schlagwörter aus der Frage und dem rechtlichen Kontext enthalten." 
    "- Es sind AND und OR Verknüpfungen mehrerer Suchbegriffe möglich. "
    "- Danach benutze search_rg für präzise Fundstellen in einer oder meherer Dateien. "
    "- Reflektiere dann die Ergebnisse und ob sie für eine Antwort ausreichen."
    "- Falls nicht ausreichend, erweitere die Suche, erhöhe ggf. max_results/context_lines und versuche die Werkzeuge erneut.\n"
    "- Bei Gesetzen: Verwende IMMER OR-Verknüpfungen für Vollname und Abkürzung (z.B. 'Bürgerliches Gesetzbuch OR BGB', 'Rechtsanwaltsvergütungsgesetz OR RVG')."
    "- Suche auch mit search_rg in der neueren Rechtsprechung im Ordner urteile_markdown_by_year."
    "- Verwende mehrere Suchstrategien: Einzelwörter, exakte Phrasen, und verwandte Begriffe."
    "- Nutze search_rg Ergebnisse: Die byte_range Werte können direkt an read_file_range weitergegeben werden für präzise Textausschnitte."
    "- Wenn ausreichend, erzeuge final_answer mit kurzer Textstelle und Zitation (Pfad + Zeilennummer).\n"
    "- Antworte immer auf Deutsch!"
    "- Bei Abbruch wegen Limit: final_answer mit kurzer Erklärung, was versucht wurde und warum keine Antwort gefunden wurde.\n\n"
    + TOOL_SUMMARY
)


#def summarize_files(files: List[str], limit: int = 20) -> str:
#    if not files:
#        return "No files."
#    return "Top files:\n" + "\n".join(f"- {p}" for p in files[:limit])


#def summarize_hits(hits: List[Dict[str, Any]], limit: int = 5) -> str:
#    if not hits:
#        return "No hits."
#    lines: List[str] = []
#    for h in hits[:limit]:
#        path = h.get("path")
#        ln = h.get("lines", {}).get("line_number")
#        text = (h.get("lines", {}).get("text") or "").strip()
#        lines.append(f"- {path}#L{ln}: {text[:180]}")
#    return "Top hits:\n" + "\n".join(lines)


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
                        "query": {"type": "string", "description": "Boolean query (AND/OR, parentheses)"},
                        "glob": {"type": "string", "description": "Glob pattern to match files"},
                        "max_results": {"type": "integer", "minimum": 10, "description": "Maximum number of results"},
                    },
                    "required": ["query"],
                },
            },
        },
#        {
#            "type": "function",
#            "function": {
#                "name": "list_paths",
#                "description": "List allowed files under a subdirectory (relative to sandbox root).",
#                "parameters": {
#                    "type": "object",
#                    "properties": {
#                        "subdir": {"type": "string"},
#                    },
#                    "required": ["subdir"],
#                },
#            },
#        },
        {
            "type": "function",
            "function": {
                "name": "search_rg",
                "description": "Search lines using ripgrep. Optional file_list narrows search. Begin with only one keyword. Refine withg multiple keywords with AND/OR or regex alternations if results are too broad. ",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Single keyword"},
                        "file_list": {"type": "array", "items": {"type": "string"}, "description": "File patterns: specific files, folders (e.g. 'gesetze/', 'urteile_markdown_by_year/'), or './' for entire corpus"},
                        "max_results": {"type": "integer", "minimum": 10, "description": "Maximum number of results per file"},
                        "context_lines": {"type": "integer", "minimum": 1, "maximum": 10, "description": "Number of context lines"},
                        "regex": {"type": "boolean", "description": "Whether to treat query as regex pattern (default False)"},
                        "case_sensitive": {"type": "boolean", "description": "Whether search is case sensitive (default False)"},
                    },
                    "required": ["query","file_list"],
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
#                        "context": {"type": "integer", "minimum": 0},
#                        "max_lines": {"type": "integer", "description": "Maximum number of lines to return (default 20)"},
                    },
                    "required": ["path", "start", "end"],
                },
            },
        },
    ]


def run_agent(
    query: str,
    mcp: MCPClient,
    cfg: dict,
    client: OpenAI,
    model: str,
    referer: Optional[str],
    site_title: Optional[str],
    provider: str = "openrouter",
    tools_mode: str = "auto",
) -> str:
    tools = _build_tools_spec() if tools_mode != "off" else []
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

    def dispatch_search_rg(query: str, file_list: Optional[List[str]] = None, max_results: Optional[int] = None, context_lines: Optional[int] = None, regex: Optional[bool] = None, case_sensitive: Optional[bool] = None) -> str:
        res = mcp.call_tool("search_rg", {
            "query": query,
            "file_list": file_list,
            "max_results": max_results or 20,
            "context_lines": context_lines or 2,
            "regex": regex or False,
            "case_sensitive": case_sensitive or False,
        })
        return json.dumps(res, ensure_ascii=False)

    def dispatch_list_paths(subdir: Optional[str] = None) -> str:
        res = mcp.call_tool("list_paths", {
            "subdir": subdir,
        })
        return json.dumps(res, ensure_ascii=False)

    def dispatch_read_file_range(path: str, start: int, end: int, context: Optional[int] = None, max_lines: Optional[int] = None) -> str:
        res = mcp.call_tool("read_file_range", {
            "path": path,
            "start": int(start),
            "end": int(end),
            "context": context or cfg.get("context_bytes", 300),
            "max_lines": max_lines or 20,
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
    max_steps = 50  # Further reduced to prevent hanging
    while True:
        if steps >= max_steps:
            # Provide fallback answer based on LLM knowledge with clear disclaimer
            fallback_messages = [
                {"role": "system", "content": "Du bist ein Experte für deutsches Recht. Beantworte die folgende Frage basierend auf deinem allgemeinen Rechtswissen. WICHTIG: Beginne deine Antwort mit einem deutlichen Hinweis, dass diese Antwort NICHT auf spezifischen Rechtsquellen oder aktuellen Gesetzen basiert, sondern auf allgemeinem Rechtswissen."},
                {"role": "user", "content": f"Frage: {query}"}
            ]
            try:
                fallback_resp = client.chat.completions.create(
                    model=model,
                    messages=fallback_messages,
                    temperature=0.0,
                    extra_headers=extra_headers or None,
                    max_tokens=800,
                )
                fallback_answer = fallback_resp.choices[0].message.content or ""
                return f"⚠️ **HINWEIS: Diese Antwort basiert NICHT auf spezifischen Rechtsquellen, sondern auf allgemeinem Rechtswissen, da die maximale Anzahl von Rechercheschritten erreicht wurde.**\n\n{fallback_answer}"
            except Exception as e:
                return f"Konnte keine zufriedenstellende Antwort finden. Die maximale Anzahl von Rechercheschritten wurde erreicht und auch die Fallback-Antwort konnte nicht generiert werden: {e}"
        print("\nSTEP", steps)
        used_any_tool = any(m.get("role") == "tool" for m in messages)
        # Ollama's OpenAI-compatible API may not support non-standard values like "required".
        if provider in ("ollama"):
            tool_choice_val = "auto"
        else:
            tool_choice_val = "auto" if used_any_tool else "required"

        steps += 1
#        print (messages)
        try:
            create_kwargs = dict(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice_val,
                extra_headers=extra_headers or None,
                timeout=30,  # Add 30 second timeout
            )
            resp = client.chat.completions.create(**create_kwargs)
#            print ("RESP", resp)
        except Exception as e:
            return f"LLM create failed: {e}"

        # Guard against empty or malformed responses
        if not getattr(resp, "choices", None) or not resp.choices:
            # Retry next loop iteration
            time.sleep(0.2)
            continue

        msg = resp.choices[0].message
        out_text = getattr(msg, "content", None) or getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None) or ""
#        if out_text:
#            print(out_text, "\n")
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
    # "anthropic/claude-sonnet-4"
    parser.add_argument("--model", default=None, help="Model id (provider-specific)")
    parser.add_argument("--api-key", default=None, help="API key. If omitted, uses provider-specific env (OPENROUTER_API_KEY, NEBIUS_API_KEY, or OLLAMA_API_KEY).")
    parser.add_argument("--base-url", default=None, help="OpenAI-compatible base URL (overrides provider default)")
    parser.add_argument("--referer", default=os.environ.get("OPENROUTER_SITE_URL"), help="HTTP-Referer header (your site URL)")
    parser.add_argument("--site-title", default=os.environ.get("OPENROUTER_SITE_TITLE"), help="X-Title header (your site title)")
    parser.add_argument("--provider", choices=["openrouter", "nebius", "ollama"], default=os.environ.get("LLM_PROVIDER", "nebius"), help="LLM backend: nebius (default), openrouter, or ollama")
    
    args = parser.parse_args()

    # Resolve provider-specific defaults
    openrouter_default_model = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4")
    ollama_default_model = os.environ.get("OLLAMA_MODEL", "qwen3:4b")

    if args.provider == "openrouter":
        resolved_base_url = args.base_url
        resolved_api_key = args.api_key or os.environ.get("OPENROUTER_API_KEY")
        resolved_model = args.model or openrouter_default_model
        if not resolved_api_key:
            print("Missing OpenRouter API key. Set OPENROUTER_API_KEY or pass --api-key.", file=sys.stderr)
            raise SystemExit(2)
    elif args.provider == "nebius":
        # Nebius: OpenAI-compatible endpoint
        # Prefer an explicit --base-url if provided and not the OpenRouter default; otherwise use NEBIUS_BASE_URL or the public default
        default_nebius_base = os.environ.get("NEBIUS_BASE_URL", "https://api.studio.nebius.com/v1/")
        resolved_base_url = (
            args.base_url
            if args.base_url not in (None, "", os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"))
            else default_nebius_base
        )
        # Use provided --api-key if set; otherwise fall back to NEBIUS_API_KEY
        resolved_api_key = args.api_key or os.environ.get("NEBIUS_API_KEY")
        # Require a Nebius-supported model id via --model or NEBIUS_MODEL
        resolved_model = args.model or os.environ.get("NEBIUS_MODEL")
        if not resolved_api_key:
            print("Missing Nebius API key. Set NEBIUS_API_KEY or pass --api-key.", file=sys.stderr)
            raise SystemExit(2)
        if not resolved_model:
            print("Missing Nebius model. Set NEBIUS_MODEL or pass --model with a Nebius-supported model id.", file=sys.stderr)
            raise SystemExit(2)
    else:
        # Ollama typically runs at this base URL and does not require a real API key.
        default_or_base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        # If a custom base-url is provided, use it; otherwise use Ollama default.
        resolved_base_url = args.base_url or default_or_base
        resolved_api_key = args.api_key or os.environ.get("OLLAMA_API_KEY", "ollama")
        # Choose Ollama model if not explicitly provided.
        resolved_model = args.model or ollama_default_model

    # Determine tools mode: explicit flag has priority; otherwise default by provider
#    if args.tools in ("auto", "off"):
#        resolved_tools_mode = args.tools
#    else:
#        resolved_tools_mode = "auto" if args.provider == "openrouter" else "off"

    cfg = load_config()
    server_cmd_env = os.environ.get("MCP_SERVER_CMD")
    server_cmd = server_cmd_env.split() if server_cmd_env else None

    env = os.environ.copy()
    env["PYTHONPATH"] = env.get("PYTHONPATH") or str(Path.cwd())
    env.setdefault("LEGAL_DOC_ROOT", cfg.get("legal_doc_root", "./data/"))

    mcp = MCPClient(server_cmd=server_cmd, env=env)
    try:
        client = OpenAI(base_url=resolved_base_url, api_key=resolved_api_key)
        answer = run_agent(
            args.query,
            mcp,
            cfg,
            client,
            model=resolved_model,
            referer=args.referer if args.provider == "openrouter" else None,
            site_title=args.site_title if args.provider == "openrouter" else None,
            provider=args.provider,
            tools_mode="auto",
        )
        print(answer)
    finally:
        mcp.close()


if __name__ == "__main__":
    main()
