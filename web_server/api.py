import os
import json
import time
from pathlib import Path
from typing import Optional, Dict, Any, Generator, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import OpenAI

# Reuse existing agent implementation
from client.agent_cli import MCPClient, run_agent, load_config, _build_tools_spec, SYSTEM_PROMPT, build_dispatch_functions
import sys
from io import StringIO
import re

app = FastAPI(title="LegalGenius API", version="0.1.0")

def _parse_origins(env_val: Optional[str]) -> list[str]:
    if not env_val:
        return []
    return [o.strip() for o in env_val.split(",") if o.strip()]

# CORS configuration (driven by API_ALLOW_ORIGINS)
default_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
allow_origins = _parse_origins(os.environ.get("API_ALLOW_ORIGINS")) or default_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load config and ensure env vars
CFG = load_config()
os.environ.setdefault("LEGAL_DOC_ROOT", CFG.get("legal_doc_root", "./data/"))
# Ensure project root is importable for the MCP server subprocess
os.environ.setdefault("PYTHONPATH", str(Path.cwd()))

# Global singletons
MCP: Optional[MCPClient] = None
OPENAI_CLIENT: Optional[OpenAI] = None
RESOLVED_PROVIDER: str = os.environ.get("LLM_PROVIDER", "nebius")
RESOLVED_MODEL: Optional[str] = None
RESOLVED_REFERER: Optional[str] = None
RESOLVED_SITE_TITLE: Optional[str] = None

# ---- JSONL logging (./logs/api) ----
LOG_DIR = Path("./logs/api")

def _log_interaction(event: Dict[str, Any]) -> None:
    """Append a single JSON event to a daily-rotated JSONL file in ./logs/api.
    Fail-safe: swallow errors to avoid impacting API responses.
    """
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        fname = LOG_DIR / f"interactions-{time.strftime('%Y-%m-%d')}.jsonl"
        with fname.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        # Do not raise logging errors
        pass


class AskRequest(BaseModel):
    query: str
    provider: Optional[str] = None
    model: Optional[str] = None
    referer: Optional[str] = None
    site_title: Optional[str] = None


class BatchAskRequest(BaseModel):
    queries: list[str]
    provider: Optional[str] = None
    model: Optional[str] = None
    referer: Optional[str] = None
    site_title: Optional[str] = None


def _resolve_llm(provider: Optional[str], model_override: Optional[str]) -> Dict[str, Any]:
    provider = (provider or os.environ.get("LLM_PROVIDER") or "nebius").lower()

    # Defaults mirrored from client/agent_cli.py
    openrouter_default_model = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4")
    ollama_default_model = os.environ.get("OLLAMA_MODEL", "qwen3:4b")
    nebius_default_model = os.environ.get("NEBIUS_MODEL", "zai-org/GLM-4.5")

    if provider == "openrouter":
        base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        api_key = os.environ.get("OPENROUTER_API_KEY")
        model = model_override or os.environ.get("OPENROUTER_MODEL", "Qwen/Qwen3-235B-A22B-Instruct-2507")
        if not api_key:
            raise HTTPException(status_code=400, detail="Missing OPENROUTER_API_KEY")
        client = OpenAI(base_url=base_url, api_key=api_key)
        referer = os.environ.get("OPENROUTER_SITE_URL")
        site_title = os.environ.get("OPENROUTER_SITE_TITLE")
        return {
            "provider": provider,
            "client": client,
            "model": model or openrouter_default_model,
            "referer": referer,
            "site_title": site_title,
        }

    if provider == "nebius":
        base_url_env = os.environ.get("NEBIUS_BASE_URL", "https://api.studio.nebius.com/v1/")
        # Allow overriding base_url via OPENROUTER_BASE_URL only if explicitly set and not default
        base_url = os.environ.get("BASE_URL", base_url_env)
        api_key = os.environ.get("NEBIUS_API_KEY")
        model = model_override or os.environ.get("NEBIUS_MODEL") or nebius_default_model
        if not api_key:
            raise HTTPException(status_code=400, detail="Missing NEBIUS_API_KEY")
        if not model:
            raise HTTPException(status_code=400, detail="Missing NEBIUS_MODEL or model override")
        client = OpenAI(base_url=base_url, api_key=api_key)
        return {
            "provider": provider,
            "client": client,
            "model": model,
            "referer": None,
            "site_title": None,
        }

    if provider == "ollama":
        base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        api_key = os.environ.get("OLLAMA_API_KEY", "ollama")
        model = model_override or os.environ.get("OLLAMA_MODEL", "qwen3:4b")
        client = OpenAI(base_url=base_url, api_key=api_key)
        return {
            "provider": provider,
            "client": client,
            "model": model or ollama_default_model,
            "referer": None,
            "site_title": None,
        }

    raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")


def run_agent_with_token_tracking(
    query: str,
    mcp: MCPClient,
    cfg: dict,
    client: OpenAI,
    model: str,
    referer: Optional[str],
    site_title: Optional[str],
    provider: str = "openrouter",
    tools_mode: str = "auto",
) -> Dict[str, Any]:
    """Wrapper around run_agent that captures token usage from stdout"""
    
    # Capture stdout to extract token information
    old_stdout = sys.stdout
    sys.stdout = captured_output = StringIO()
    
    total_tokens_sent = 0
    total_tokens_received = 0
    step_tokens = []
    
    try:
        # Run the original agent
        answer = run_agent(
            query=query,
            mcp=mcp,
            cfg=cfg,
            client=client,
            model=model,
            referer=referer,
            site_title=site_title,
            provider=provider,
            tools_mode=tools_mode,
        )
        
        # Parse captured output for token information
        output_lines = captured_output.getvalue().split('\n')
        for line in output_lines:
            # Match pattern: [TOKENS] Step X - Y sent, Z received
            # or [TOKENS] Y sent, Z received
            token_match = re.search(r'\[TOKENS\](?:\s+Step\s+(\d+)\s+-\s+)?(\d+)\s+sent,\s+(\d+)\s+received', line)
            if token_match:
                step_num = token_match.group(1)
                sent = int(token_match.group(2))
                received = int(token_match.group(3))
                
                total_tokens_sent += sent
                total_tokens_received += received
                
                step_tokens.append({
                    "step": int(step_num) if step_num else None,
                    "tokens_sent": sent,
                    "tokens_received": received
                })
        
        return {
            "answer": answer,
            "token_usage": {
                "total_tokens_sent": total_tokens_sent,
                "total_tokens_received": total_tokens_received,
                "total_tokens": total_tokens_sent + total_tokens_received,
                "step_breakdown": step_tokens
            }
        }
        
    finally:
        # Restore stdout
        sys.stdout = old_stdout


@app.on_event("startup")
def _startup() -> None:
    global MCP, OPENAI_CLIENT, RESOLVED_PROVIDER, RESOLVED_MODEL, RESOLVED_REFERER, RESOLVED_SITE_TITLE
    MCP = MCPClient(server_cmd=None, env=os.environ.copy())
    llm = _resolve_llm(provider=os.environ.get("LLM_PROVIDER", "nebius"), model_override=None)
    OPENAI_CLIENT = llm["client"]
    RESOLVED_PROVIDER = llm["provider"]
    RESOLVED_MODEL = llm["model"]
    RESOLVED_REFERER = llm.get("referer")
    RESOLVED_SITE_TITLE = llm.get("site_title")


@app.on_event("shutdown")
def _shutdown() -> None:
    global MCP
    try:
        if MCP:
            MCP.close()
    except Exception:
        pass


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "provider": RESOLVED_PROVIDER, "model": RESOLVED_MODEL}


@app.post("/test")
def test(req: AskRequest) -> Dict[str, Any]:
    """Legal research endpoint with limited steps"""
    global MCP
    if not MCP:
        return {"error": "MCP server not ready"}
    
    try:
        llm = _resolve_llm(provider=req.provider or RESOLVED_PROVIDER, model_override=req.model)
        client = llm["client"]
        model = llm["model"]
        referer = req.referer if req.referer is not None else llm.get("referer")
        site_title = req.site_title if req.site_title is not None else llm.get("site_title")
        
        # Use agent with limited steps for legal research
        result = run_agent_with_token_tracking(
            query=req.query,
            mcp=MCP,
            cfg=CFG,
            client=client,
            model=model,
            referer=referer,
            site_title=site_title,
            provider=llm["provider"],
            tools_mode="auto",
        )
        return {
            "answer": result["answer"],
            "provider": llm["provider"],
            "model": model,
            "token_usage": result["token_usage"]
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/ask")
def ask(req: AskRequest) -> Dict[str, Any]:
    global MCP, OPENAI_CLIENT, RESOLVED_PROVIDER, RESOLVED_MODEL
    if not MCP or not OPENAI_CLIENT:
        raise HTTPException(status_code=503, detail="Server is not ready")

    # Allow request-level override of provider/model
    try:
        start_ts = time.time()
        llm = _resolve_llm(provider=req.provider or RESOLVED_PROVIDER, model_override=req.model)
        client = llm["client"]
        model = llm["model"]
        referer = req.referer if req.referer is not None else llm.get("referer")
        site_title = req.site_title if req.site_title is not None else llm.get("site_title")
        result = run_agent_with_token_tracking(
            query=req.query,
            mcp=MCP,
            cfg=CFG,
            client=client,
            model=model,
            referer=referer,
            site_title=site_title,
            provider=llm["provider"],
            tools_mode="auto",
        )
        resp = {
            "answer": result["answer"],
            "token_usage": result["token_usage"]
        }
        end_ts = time.time()
        try:
            _log_interaction({
                "timestamp": end_ts,
                "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(end_ts)),
                "duration_ms": int((end_ts - start_ts) * 1000),
                "endpoint": "ask",
                "provider": llm["provider"],
                "model": model,
                "referer": referer,
                "site_title": site_title,
                "query": req.query,
                "answer_preview": (result.get("answer") or "")[:2000],
                "token_usage": result.get("token_usage", {}),
            })
        except Exception:
            pass
        return resp
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/batch")
def batch(req: BatchAskRequest) -> Dict[str, Any]:
    global MCP, OPENAI_CLIENT, RESOLVED_PROVIDER, RESOLVED_MODEL
    if not MCP or not OPENAI_CLIENT:
        raise HTTPException(status_code=503, detail="Server is not ready")

    try:
        batch_start = time.time()
        llm = _resolve_llm(provider=req.provider or RESOLVED_PROVIDER, model_override=req.model)
        client = llm["client"]
        model = llm["model"]
        referer = req.referer if req.referer is not None else llm.get("referer")
        site_title = req.site_title if req.site_title is not None else llm.get("site_title")
        outputs: list[Dict[str, Any]] = []
        for idx, q in enumerate(req.queries):
            start_ts = time.time()
            result = run_agent_with_token_tracking(
                query=q,
                mcp=MCP,
                cfg=CFG,
                client=client,
                model=model,
                referer=referer,
                site_title=site_title,
                provider=llm["provider"],
                tools_mode="auto",
            )
            outputs.append({
                "query": q,
                "answer": result["answer"],
                "token_usage": result["token_usage"]
            })
            end_ts = time.time()
            try:
                _log_interaction({
                    "timestamp": end_ts,
                    "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(end_ts)),
                    "duration_ms": int((end_ts - start_ts) * 1000),
                    "endpoint": "batch_item",
                    "batch_size": len(req.queries),
                    "batch_index": idx,
                    "provider": llm["provider"],
                    "model": model,
                    "referer": referer,
                    "site_title": site_title,
                    "query": q,
                    "answer_preview": (result.get("answer") or "")[:2000],
                    "token_usage": result.get("token_usage", {}),
                })
            except Exception:
                pass
        return {"results": outputs}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class StreamingMCPClient(MCPClient):
    """MCP Client that can yield tool events for streaming"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tool_events = []
        
    def call_tool(self, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        # Emit tool start event
        start_time = time.time()
        self.tool_events.append({
            'type': 'tool_start',
            'tool': tool,
            'args': args,
            'timestamp': start_time
        })
        
        # Call the actual tool
        result = super().call_tool(tool, args)
        
        # Emit tool complete event
        self.tool_events.append({
            'type': 'tool_complete',
            'tool': tool,
            'args': args,
            'result': result,
            'timestamp': start_time
        })
        
        return result
    
    def get_and_clear_events(self) -> List[Dict[str, Any]]:
        events = self.tool_events.copy()
        self.tool_events.clear()
        return events


def stream_agent_response(
    query: str,
    provider: str,
    model: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None
) -> Generator[str, None, None]:
    """Stream agent response with real-time tool usage"""
    
    # Set up MCP client
    mcp = StreamingMCPClient(server_cmd=None, env=os.environ.copy())
    
    try:
        # Set up LLM client
        llm = _resolve_llm(provider=provider, model_override=model)
        client = llm["client"]
        resolved_model = llm["model"]
        referer = llm.get("referer")
        site_title = llm.get("site_title")
        start_ts = time.time()
        total_tokens_sent = 0
        total_tokens_received = 0
        final_answer_logged: Optional[str] = None
        
        # Send initial status
        yield f"data: {json.dumps({'type': 'thinking', 'message': 'Analysiere die Frage und plane die Suche...', 'timestamp': time.time()})}\n\n"
        
        # Set up tools and messages
        tools = _build_tools_spec()
        extra_headers = {}
        if referer:
            extra_headers["HTTP-Referer"] = referer
        if site_title:
            extra_headers["X-Title"] = site_title
            
        # Use shared dispatcher functions from agent_cli.py
        DISPATCH = build_dispatch_functions(mcp, CFG)
        
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Question: {query}"},
        ]
        
        steps = 0
        max_steps = 50  # Reduced for streaming
        
        while steps < max_steps:
            print("\nSTEP", steps)
            yield f"data: {json.dumps({'type': 'step', 'message': f'Schritt {steps + 1}: Verarbeite Anfrage...', 'timestamp': time.time()})}\n\n"
            
            used_any_tool = any(m.get("role") == "tool" for m in messages)
#            tool_choice_val = "auto" if used_any_tool else "required" if provider != "ollama" else "auto"
            
            steps += 1
            
            try:
                create_kwargs = dict(
                    model=resolved_model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto", #tool_choice_val,
                    extra_headers=extra_headers or None,
                    timeout=30
                )
                
                resp = client.chat.completions.create(**create_kwargs)
#                print (resp)
                # Track token usage immediately
                if resp.usage:
                    tokens_sent = resp.usage.prompt_tokens
                    tokens_received = resp.usage.completion_tokens
                    print(f"[DEBUG] Emitting token usage: {tokens_sent} sent, {tokens_received} received for step {steps}")
                    total_tokens_sent += tokens_sent
                    total_tokens_received += tokens_received
                    yield f"data: {json.dumps({'type': 'token_usage', 'tokens_sent': tokens_sent, 'tokens_received': tokens_received, 'step': steps, 'timestamp': time.time()})}\n\n"
                
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'message': f'LLM Fehler: {str(e)}', 'timestamp': time.time()})}\n\n"
                return
            
            # Process response
            if not getattr(resp, "choices", None) or not resp.choices:
                time.sleep(0.2)
                continue
                
            msg = resp.choices[0].message
            out_text = getattr(msg, "content", None) or ""
            reasoning_content = getattr(msg, "reasoning_content", None) or ""
            tool_calls = getattr(msg, "tool_calls", None)
            
            # Emit reasoning content if available
            if reasoning_content:
                yield f"data: {json.dumps({'type': 'reasoning', 'content': reasoning_content, 'timestamp': time.time()})}\n\n"
            
            # Handle function call format
            fc = getattr(msg, "function_call", None)
            if fc and not tool_calls:
                tool_calls = [{
                    "id": "fc_1",
                    "type": "function", 
                    "function": {"name": fc.name, "arguments": fc.arguments or "{}"},
                }]
                
            if tool_calls:
                # Stream tool thinking
                for tc in tool_calls:
                    tool_name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except:
                        args = {}
                        
                    yield f"data: {json.dumps({'type': 'tool_thinking', 'message': f'Verwende {tool_name}...', 'tool': tool_name, 'args': args, 'timestamp': time.time()})}\n\n"
                
                # Build assistant message  
                assistant_msg: Dict[str, Any] = {
                    "role": "assistant",
                    "content": out_text or "",
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
                
                # Execute tools and stream events
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
                            
                            # Stream tool events
                            events = mcp.get_and_clear_events()
                            for event in events:
                                yield f"data: {json.dumps({'type': 'tool_event', 'event': event, 'timestamp': time.time()})}\n\n"
                                
                        except Exception as e:
                            result_text = json.dumps({"error": str(e)}, ensure_ascii=False)
                            yield f"data: {json.dumps({'type': 'tool_event', 'event': {'type': 'tool_error', 'tool': name, 'error': str(e)}, 'timestamp': time.time()})}\n\n"
                            
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_text,
                    })
                continue
                
            # Final response
            final_answer = msg.content or ""
            yield f"data: {json.dumps({'type': 'final_answer', 'message': final_answer, 'timestamp': time.time()})}\n\n"
            # Log the interaction upon final answer
            end_ts = time.time()
            try:
                _log_interaction({
                    "timestamp": end_ts,
                    "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(end_ts)),
                    "duration_ms": int((end_ts - start_ts) * 1000),
                    "endpoint": "stream",
                    "provider": provider,
                    "model": resolved_model,
                    "referer": referer,
                    "site_title": site_title,
                    "query": query,
                    "answer_preview": (final_answer or "")[:2000],
                    "token_usage": {
                        "total_tokens_sent": total_tokens_sent,
                        "total_tokens_received": total_tokens_received,
                        "total_tokens": total_tokens_sent + total_tokens_received,
                    },
                    "steps": steps,
                })
            except Exception:
                pass
            break
            
        if steps >= max_steps:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Maximale Anzahl Schritte erreicht', 'timestamp': time.time()})}\n\n"
            
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': f'Systemfehler: {str(e)}', 'timestamp': time.time()})}\n\n"
    finally:
        mcp.close()
        
    yield f"data: {json.dumps({'type': 'complete', 'timestamp': time.time()})}\n\n"


@app.post("/stream")
def stream_ask(req: AskRequest):
    """Streaming endpoint for real-time agent responses"""
    def event_publisher():
        try:
            for event in stream_agent_response(
                query=req.query,
                provider=req.provider or RESOLVED_PROVIDER,
                model=req.model or RESOLVED_MODEL
            ):
                yield event
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': f'Stream error: {str(e)}', 'timestamp': time.time()})}\n\n"
    
    return StreamingResponse(
        event_publisher(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
        }
    )


def main() -> None:
    """Launch the API with uvicorn for production/dev usage.

    Usage after installation:
      legalgenius-api
    or
      python -m web_server.api
    """
    import uvicorn
    host = os.environ.get("API_HOST", "0.0.0.0")
    port = int(os.environ.get("API_PORT", "8000"))
    reload = os.environ.get("API_RELOAD", "false").lower() in ("1", "true", "yes")
    uvicorn.run("web_server.api:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
