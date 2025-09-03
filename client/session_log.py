from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class SessionLogger:
    """
    Minimal session logger that persists tool-call logs and assistant messages
    to a rolling log file under logs/ (created if needed).

    - Plain text for easy tail/less viewing
    - JSON lines for structured inspection (same file, prefixed with 'JSON: ')
    """

    def __init__(self, log_dir: Optional[Path] = None, session_name: Optional[str] = None):
        base = log_dir or Path("logs")
        base.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = session_name or f"session_{ts}.log"
        self.path = base / name
        self._fh = self.path.open("a", encoding="utf-8")

    def _ts(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def log_tool(self, tool: str, args: Dict[str, Any], result: Dict[str, Any]) -> None:
        self._fh.write(f"[{self._ts()}] TOOL {tool}\n")
        self._fh.write(f"ARGS: {json.dumps(args, ensure_ascii=False)}\n")
        self._fh.write(f"RESULT: {json.dumps(result, ensure_ascii=False)[:4000]}\n")
        self._fh.write("-" * 60 + "\n")
        self._fh.write("JSON: " + json.dumps({
            "ts": self._ts(),
            "type": "tool",
            "tool": tool,
            "args": args,
            "result": result,
        }, ensure_ascii=False) + "\n")
        self._fh.flush()

    def log_message(self, role: str, content: str) -> None:
        self._fh.write(f"[{self._ts()}] {role.upper()}\n{content}\n")
        self._fh.write("-" * 60 + "\n")
        self._fh.write("JSON: " + json.dumps({
            "ts": self._ts(),
            "type": "message",
            "role": role,
            "content": content,
        }, ensure_ascii=False) + "\n")
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass

