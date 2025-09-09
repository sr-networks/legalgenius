import os
import json
import time
from pathlib import Path
from uuid import uuid4
from typing import Optional, Dict, Any, Generator, List

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import OpenAI

# Reuse existing agent implementation
from client.agent_cli import MCPClient, run_agent, load_config, _build_tools_spec, SYSTEM_PROMPT, build_dispatch_functions
from .models import init_db, get_db, get_or_create_user, deduct_tokens, set_credits, UserCredit
from sqlalchemy.orm import Session
from jose import jwt
import requests
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
CLERK_JWKS_URL: Optional[str] = os.environ.get("CLERK_JWKS_URL")
CLERK_ISSUER: Optional[str] = os.environ.get("CLERK_ISSUER")
ADMIN_EMAILS: list[str] = [e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()]
ADMIN_USER_IDS: list[str] = [e.strip() for e in os.environ.get("ADMIN_USER_IDS", "").split(",") if e.strip()]
_JWKS_CACHE: Optional[dict] = None


class AuthedUser(BaseModel):
    user_id: str
    email: Optional[str] = None
    is_admin: bool = False

# ---- JSONL logging (./logs/api) ----
LOG_DIR = Path("./logs/api")
SESSIONS_DIR = Path("./logs/sessions")

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


def _session_start() -> str:
    """Create a new session id and ensure directory exists"""
    try:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return uuid4().hex


def _session_log(session_id: str, event: Dict[str, Any]) -> None:
    """Append a JSONL event to the per-session log file"""
    try:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        fpath = SESSIONS_DIR / f"{session_id}.jsonl"
        event = {"ts": time.time(), "session_id": session_id, **event}
        with fpath.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
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
    # Initialize DB
    try:
        init_db()
    except Exception:
        pass
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


# ---- Auth helpers (Clerk JWT) ----
def _load_jwks() -> Optional[dict]:
    global _JWKS_CACHE
    if not CLERK_JWKS_URL:
        return None
    try:
        if _JWKS_CACHE is None:
            resp = requests.get(CLERK_JWKS_URL, timeout=5)
            resp.raise_for_status()
            _JWKS_CACHE = resp.json()
        return _JWKS_CACHE
    except Exception:
        return None


def _verify_bearer_token(authorization: Optional[str]) -> Optional[dict]:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1]
    # If Clerk config is missing, allow dev mode without strict verification
    if not CLERK_JWKS_URL or not CLERK_ISSUER:
        try:
            return jwt.get_unverified_claims(token)
        except Exception:
            return None
    jwks = _load_jwks()
    if not jwks:
        return None
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        key = None
        for k in jwks.get("keys", []):
            if k.get("kid") == kid:
                key = k
                break
        if not key:
            return None
        claims = jwt.decode(token, key, options={
            "verify_aud": False,  # simplify
            "verify_at_hash": False,
        }, issuer=CLERK_ISSUER, algorithms=[key.get("alg", "RS256")])
        return claims
    except Exception:
        return None


def get_current_user(Authorization: Optional[str] = Header(default=None)) -> AuthedUser:
    claims = _verify_bearer_token(Authorization)
    if not claims:
        raise HTTPException(status_code=401, detail="Unauthorized")
    # Clerk standard claims
    user_id = claims.get("sub") or claims.get("user_id") or claims.get("sid")
    email = None
    # Try common places for primary email
    email = (
        (claims.get("email") if isinstance(claims.get("email"), str) else None)
        or (claims.get("primary_email_address_id") if isinstance(claims.get("primary_email_address_id"), str) else None)
    )
    # Clerk often provides email addresses in custom claims
    if not email:
        emails = claims.get("email_addresses")
        if isinstance(emails, list) and emails:
            # choose the first
            maybe = emails[0]
            if isinstance(maybe, dict):
                email = maybe.get("email_address")
            elif isinstance(maybe, str):
                email = maybe
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token: no subject")
    is_admin = False
    try:
        is_admin = bool((email and email.lower() in ADMIN_EMAILS) or (user_id in ADMIN_USER_IDS))
    except Exception:
        is_admin = False
    return AuthedUser(user_id=user_id, email=email, is_admin=is_admin)


# ---- Credit models / endpoints ----
class SetCreditsRequest(BaseModel):
    user_id: str
    euro_balance_cents: Optional[int] = None
    email: Optional[str] = None


@app.get("/me")
def me(user: AuthedUser = Depends(get_current_user)) -> Dict[str, Any]:
    return {"user_id": user.user_id, "email": user.email, "is_admin": user.is_admin}


@app.get("/me/credits")
def my_credits(user: AuthedUser = Depends(get_current_user), db: Session = Depends(get_db)) -> Dict[str, Any]:
    uc = get_or_create_user(db, user.user_id, user.email)
    return {"ok": True, "credits": uc.as_dict()}


@app.post("/admin/set_credits")
def admin_set_credits(req: SetCreditsRequest, user: AuthedUser = Depends(get_current_user), db: Session = Depends(get_db)) -> Dict[str, Any]:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    uc = set_credits(db, req.user_id, euro_balance_cents=req.euro_balance_cents, email=req.email)
    return {"ok": True, "credits": uc.as_dict()}


@app.post("/test")
def test(req: AskRequest, user: AuthedUser = Depends(get_current_user), db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Legal research endpoint with limited steps"""
    global MCP
    if not MCP:
        return {"error": "MCP server not ready"}
    
    try:
        # Ensure user exists in DB
        uc = get_or_create_user(db, user.user_id, user.email)
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
        # Deduct tokens (separate in/out)
        try:
            usage = result.get("token_usage", {})
            updated = deduct_tokens(db, user.user_id, usage.get("total_tokens_sent", 0), usage.get("total_tokens_received", 0))
            # Include updated credits snapshot
            return {
                "answer": result["answer"],
                "provider": llm["provider"],
                "model": model,
                "token_usage": result["token_usage"],
                "credits": updated.as_dict(),
            }
        except Exception:
            # If deduction failed, still return basic info
            return {
                "answer": result["answer"],
                "provider": llm["provider"],
                "model": model,
                "token_usage": result["token_usage"],
            }
    except Exception as e:
        return {"error": str(e)}


@app.post("/ask")
def ask(req: AskRequest, user: AuthedUser = Depends(get_current_user), db: Session = Depends(get_db)) -> Dict[str, Any]:
    global MCP, OPENAI_CLIENT, RESOLVED_PROVIDER, RESOLVED_MODEL
    if not MCP or not OPENAI_CLIENT:
        raise HTTPException(status_code=503, detail="Server is not ready")

    # Allow request-level override of provider/model
    try:
        start_ts = time.time()
        # Ensure user exists and has some balance (soft check)
        uc = get_or_create_user(db, user.user_id, user.email)
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
        # Deduct tokens and attach credits snapshot
        try:
            usage = result.get("token_usage", {})
            updated = deduct_tokens(db, user.user_id, usage.get("total_tokens_sent", 0), usage.get("total_tokens_received", 0))
            resp["credits"] = updated.as_dict()
        except Exception:
            pass
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
    session_id: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    user: Optional[AuthedUser] = None,
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
        
        # Announce session and initial status
        yield f"data: {json.dumps({'type': 'session', 'session_id': session_id, 'timestamp': time.time()})}\n\n"
        _session_log(session_id, {"type": "session", "query": query, "provider": provider, "model": resolved_model})
        thinking_evt = {'type': 'thinking', 'message': 'Analysiere die Frage und plane die Suche...'}
        yield f"data: {json.dumps({**thinking_evt, 'timestamp': time.time()})}\n\n"
        _session_log(session_id, thinking_evt)
        
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
            step_evt = {'type': 'step', 'message': f'Schritt {steps + 1}: Verarbeite Anfrage...'}
            yield f"data: {json.dumps({**step_evt, 'timestamp': time.time()})}\n\n"
            _session_log(session_id, step_evt)
            
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
                    # Per-step deduction if user provided
                    try:
                        if user:
                            from .models import SessionLocal
                            db = SessionLocal()
                            try:
                                updated = deduct_tokens(db, user.user_id, tokens_sent, tokens_received)
                                # Emit updated credits snapshot
                                yield f"data: {json.dumps({'type': 'credits', 'credits': updated.as_dict(), 'timestamp': time.time()})}\n\n"
                                # If euro balance went negative, stop early
                                if updated.euro_balance_cents < 0:
                                    err_evt = {'type': 'error', 'message': 'Guthaben erschöpft. Bitte laden Sie Ihr Konto auf.'}
                                    yield f"data: {json.dumps({**err_evt, 'timestamp': time.time()})}\n\n"
                                    return
                            finally:
                                db.close()
                    except Exception:
                        pass
                
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
                            
                            # Stream and persist tool events
                            events = mcp.get_and_clear_events()
                            for event in events:
                                tool_evt = {'type': 'tool_event', 'event': event}
                                yield f"data: {json.dumps({**tool_evt, 'timestamp': time.time()})}\n\n"
                                _session_log(session_id, tool_evt)
                                
                        except Exception as e:
                            result_text = json.dumps({"error": str(e)}, ensure_ascii=False)
                            tool_err = {'type': 'tool_event', 'event': {'type': 'tool_error', 'tool': name, 'error': str(e)}}
                            yield f"data: {json.dumps({**tool_err, 'timestamp': time.time()})}\n\n"
                            _session_log(session_id, tool_err)
                            
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_text,
                    })
                continue
                
            # Final response
            final_answer = msg.content or ""
            final_evt = {'type': 'final_answer', 'message': final_answer}
            yield f"data: {json.dumps({**final_evt, 'timestamp': time.time()})}\n\n"
            _session_log(session_id, final_evt)
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
            err_evt = {'type': 'error', 'message': 'Maximale Anzahl Schritte erreicht'}
            yield f"data: {json.dumps({**err_evt, 'timestamp': time.time()})}\n\n"
            _session_log(session_id, err_evt)
            
    except Exception as e:
        err_evt = {'type': 'error', 'message': f'Systemfehler: {str(e)}'}
        yield f"data: {json.dumps({**err_evt, 'timestamp': time.time()})}\n\n"
        _session_log(session_id, err_evt)
    finally:
        mcp.close()
        
    complete_evt = {'type': 'complete'}
    yield f"data: {json.dumps({**complete_evt, 'timestamp': time.time()})}\n\n"
    _session_log(session_id, complete_evt)


@app.post("/stream")
def stream_ask(req: AskRequest, user: AuthedUser = Depends(get_current_user)):
    """Streaming endpoint for real-time agent responses"""
    session_id = _session_start()
    def event_publisher():
        try:
            for event in stream_agent_response(
                query=req.query,
                provider=req.provider or RESOLVED_PROVIDER,
                model=req.model or RESOLVED_MODEL,
                session_id=session_id,
                user=user,
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


@app.get("/sessions/{session_id}")
def get_session(session_id: str) -> Dict[str, Any]:
    """Return all events recorded for a given session (for permanent log pane)."""
    try:
        fpath = SESSIONS_DIR / f"{session_id}.jsonl"
        if not fpath.exists():
            raise HTTPException(status_code=404, detail="Session not found")
        events: List[Dict[str, Any]] = []
        with fpath.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except Exception:
                    continue
        return {"session_id": session_id, "events": events}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
