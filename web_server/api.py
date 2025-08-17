import os
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI

# Reuse existing agent implementation
from client.agent_cli import MCPClient, run_agent, load_config

app = FastAPI(title="LegalGenius API", version="0.1.0")

# CORS for local React dev server (Vite default: 5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://127.0.0.1:63142"],
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
        answer = run_agent(
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
        return {"answer": answer, "provider": llm["provider"], "model": model}
    except Exception as e:
        return {"error": str(e)}


@app.post("/ask")
def ask(req: AskRequest) -> Dict[str, Any]:
    global MCP, OPENAI_CLIENT, RESOLVED_PROVIDER, RESOLVED_MODEL
    if not MCP or not OPENAI_CLIENT:
        raise HTTPException(status_code=503, detail="Server is not ready")

    # Allow request-level override of provider/model
    try:
        llm = _resolve_llm(provider=req.provider or RESOLVED_PROVIDER, model_override=req.model)
        client = llm["client"]
        model = llm["model"]
        referer = req.referer if req.referer is not None else llm.get("referer")
        site_title = req.site_title if req.site_title is not None else llm.get("site_title")
        answer = run_agent(
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
        return {"answer": answer}
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
        llm = _resolve_llm(provider=req.provider or RESOLVED_PROVIDER, model_override=req.model)
        client = llm["client"]
        model = llm["model"]
        referer = req.referer if req.referer is not None else llm.get("referer")
        site_title = req.site_title if req.site_title is not None else llm.get("site_title")
        outputs: list[Dict[str, Any]] = []
        for q in req.queries:
            ans = run_agent(
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
            outputs.append({"query": q, "answer": ans})
        return {"results": outputs}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
