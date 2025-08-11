"""
Sandboxed tools for MCP: search and read legal documents under a fixed root.

Public APIs:
- search_rg(query, glob?, max_results?) -> dict with hits
  Requires ripgrep ("rg") to be available on PATH. This function returns the
  exact byte range of the first submatch on a line but does not include any
  additional context text. To retrieve an excerpt around a match, call
  read_file_range(path, start, end, context?) using the returned byte_range.

- read_file_range(path, start, end, context?) -> dict with text snippet
  Returns a decoded UTF-8 slice around the requested byte range with optional
  symmetric context (default defined in configuration).

- list_paths(subdir?) -> dict with file list
  Lists files below the sandbox root that match allowed extensions.

Security: All filesystem access is restricted to the configured legal document
root and limited to allowed extensions (.txt, .md). Path breakout attempts are
rejected.
"""

import os
import re
import json
import subprocess
import shutil
from pathlib import Path
from typing import Dict, List
import fnmatch

import yaml

ALLOWED_EXTENSIONS = {".txt", ".md"}


class Sandbox:
    """Restricts filesystem operations to a fixed root and exposes helpers.

    Guarantees that all resolved paths stay within the configured root and
    provides utilities for listing files and translating line numbers to
    absolute byte offsets for precise slicing.
    """
    def __init__(self, root: Path):
        self.root = root.resolve()
        self._line_offset_cache: Dict[Path, List[int]] = {}

    def resolve_inside(self, relative_path: str) -> Path:
        candidate = (self.root / relative_path).resolve()
        if not str(candidate).startswith(str(self.root)):
            raise PermissionError("Path breakout attempt detected")
        return candidate

    def list_paths(self, subdir: str = ".") -> List[str]:
        base = self.resolve_inside(subdir)
        results: List[str] = []
        for p in base.rglob("*"):
            if p.is_file() and p.suffix.lower() in ALLOWED_EXTENSIONS:
                rel = p.relative_to(self.root).as_posix()
                results.append(rel)
        return results

    def _build_line_offset_cache(self, path: Path) -> List[int]:
        # Returns list mapping 1-based line numbers to absolute byte start offsets
        # offsets[line_number] = byte_start_of_line
        if path in self._line_offset_cache:
            return self._line_offset_cache[path]
        offsets: List[int] = [0]  # placeholder to align indices so we can use 1-based line numbers
        byte_index = 0
        with path.open("rb") as f:
            for chunk in f.read().splitlines(keepends=True):
                offsets.append(byte_index)
                byte_index += len(chunk)
        # Ensure at least one line
        if len(offsets) == 1:
            offsets.append(0)
        self._line_offset_cache[path] = offsets
        return offsets

    def line_start_offset(self, path: Path, line_number: int) -> int:
        offsets = self._build_line_offset_cache(path)
        if line_number < 1:
            line_number = 1
        if line_number >= len(offsets):
            line_number = len(offsets) - 1
        return offsets[line_number]


class Config:
    """Runtime configuration for tools.

    Fields:
    - legal_doc_root: Base directory containing the legal documents
    - glob: Default glob for searching files
    - max_results: Default maximum number of search results
    - context_bytes: Default context size for read_file_range
    """
    def __init__(self, path: Path | None = None):
        # Defaults
        self.legal_doc_root = "./data/"
        self.glob = "**/*.{txt,md}"
        self.max_results = 50
        self.context_bytes = 300

        # Load from YAML if present
        if path and path.exists():
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            self.legal_doc_root = data.get("legal_doc_root", self.legal_doc_root)
            self.glob = data.get("glob", self.glob)
            self.max_results = int(data.get("max_results", self.max_results))
            self.context_bytes = int(data.get("context_bytes", self.context_bytes))

        # Environment override takes precedence
        env_root = os.environ.get("LEGAL_DOC_ROOT")
        if env_root:
            self.legal_doc_root = env_root

        # Normalize
        self.legal_doc_root = str(Path(self.legal_doc_root).resolve())


def load_config() -> Config:
    cfg_path = Path("configs/config.yaml")
    return Config(cfg_path if cfg_path.exists() else None)


_config = load_config()
_sandbox = Sandbox(Path(_config.legal_doc_root))


def _rg_json_stream(args: List[str]) -> List[dict]:
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=_sandbox.root,
        text=True,
        encoding="utf-8",
    )
    results: List[dict] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            results.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    proc.wait()
    return results


def _parse_boolean_query_to_dnf(query: str) -> tuple[bool, List[List[str]]]:
    """Parse a boolean query with AND/OR and parentheses into DNF.

    Returns (used_boolean, dnf) where dnf is a list of conjunctions, each a list of terms.
    Only AND/OR are supported; NOT is not supported.
    Terms are non-operator tokens (may include unicode).
    """
    # Tokenize: parentheses, operators, or terms
    token_re = re.compile(r"\(|\)|\bAND\b|\bOR\b|[^()\s]+", re.IGNORECASE)
    raw_tokens = token_re.findall(query or "")
    if not raw_tokens:
        return (False, [])

    tokens: List[str] = raw_tokens
    pos = 0

    def peek() -> str | None:
        nonlocal pos
        return tokens[pos] if pos < len(tokens) else None

    def consume() -> str | None:
        nonlocal pos
        tok = peek()
        if tok is not None:
            pos += 1
        return tok

    def is_op(tok: str, name: str) -> bool:
        return tok is not None and tok.upper() == name

    # Each parser returns DNF: List[Set[str]] represented as list of list[str]
    def parse_expr() -> List[List[str]]:
        terms = parse_term()
        while is_op(peek(), "OR"):
            consume()  # OR
            rhs = parse_term()
            terms.extend(rhs)
        return terms

    def parse_term() -> List[List[str]]:
        factors = parse_factor()
        while is_op(peek(), "AND"):
            consume()  # AND
            rhs = parse_factor()
            # distribute AND over existing conjunctions
            new_conjs: List[List[str]] = []
            for a in factors:
                for b in rhs:
                    new_conjs.append(list(dict.fromkeys(a + b)))
            factors = new_conjs
        return factors

    def parse_factor() -> List[List[str]]:
        tok = peek()
        if tok is None:
            return [[]]
        if tok == "(":
            consume()
            inner = parse_expr()
            if peek() == ")":
                consume()
            return inner
        # term
        if tok.upper() in ("AND", "OR", ")"):
            # Unexpected operator; skip
            consume()
            return [[]]
        term = consume()
        return [[term]] if term else [[]]

    dnf = parse_expr()
    used_boolean = any(t.upper() in ("AND", "OR") or t in ("(", ")") for t in raw_tokens)
    # Clean empty conjunctions
    dnf = [conj for conj in dnf if any(t for t in conj)]
    return (used_boolean, dnf)


def search_rg(
    query: str,
    file_list: List[str] | None = None,
    max_results: int | None = None,
    context_bytes: int | None = None,
    context_lines: int | None = None,
) -> dict:
    """Search for a pattern using ripgrep and return structured matches.

    Parameters:
    - query: String pattern passed to ripgrep
    - file_list: Optional list of relative file paths to restrict search to
      specific files. When omitted or empty, the entire corpus is searched
      using the default glob from configuration.
    - max_results: Optional cap on number of matches (defaults to 20)
    - context_bytes: Optional number of extra bytes to include on both sides
      of each match in a preview snippet (takes precedence over lines)
    - context_lines: Optional number of extra lines to include before and after
      the match in a preview snippet (used only if context_bytes is not set)

    Returns: { "hits": [ { path, lines: {text, line_number}, byte_range: [start, end] } ] }

    Notes:
    - Requires ripgrep (command "rg") on PATH. There is no Python fallback.
    - To retrieve a custom preview, pass either context_bytes or context_lines.
      If neither is provided, only the matching line is returned.
    """
    # Support boolean query with AND/OR and parentheses at line scope
    use_pcre = False
    pattern = query
    used_boolean, dnf = _parse_boolean_query_to_dnf(query)
    if used_boolean and dnf:
        use_pcre = True
        # Build alternation of lookahead conjunctions
        conj_patterns: List[str] = []
        for conj in dnf:
            lookaheads = "".join(f"(?=.*{re.escape(term)})" for term in conj if term)
            conj_patterns.append(lookaheads + ".*")
        pattern = "|".join(conj_patterns) if conj_patterns else pattern
    max_results = 20 if (max_results is None) else int(max_results)

    rg_path = shutil.which("rg")
    hits: List[dict] = []
    if not rg_path:
        raise RuntimeError(
            "ripgrep (rg) is required for search_rg but was not found on PATH. "
            "Please install ripgrep and ensure 'rg' is available."
        )

    # Use ripgrep JSON
    args = [
        rg_path,
        "--json",
        "--line-number",
        "--with-filename",
        "--color=never",
    ]
    if use_pcre:
        args.append("-P")
    # If file_list provided, validate and pass paths directly to ripgrep
    search_paths: List[str]
    if file_list:
        validated: List[str] = []
        for rel in file_list:
            try:
                abs_p = _sandbox.resolve_inside(rel)
            except PermissionError:
                continue
            if abs_p.suffix.lower() not in ALLOWED_EXTENSIONS:
                continue
            validated.append(Path(rel).as_posix())
        search_paths = validated or ["."]
        args += [pattern, *search_paths]
    else:
        # Default: search corpus via configured glob
        args += [
            "-g",
            _config.glob,
            pattern,
            ".",
        ]
    stream = _rg_json_stream(args)

    for item in stream:
        if item.get("type") != "match":
            continue
        data = item.get("data", {})
        path_text = data.get("path", {}).get("text")
        if not path_text:
            continue
        # security: ensure within sandbox and allowed extension
        rel_path = Path(path_text)
        try:
            abs_path = _sandbox.resolve_inside(rel_path.as_posix())
        except PermissionError:
            continue
        if abs_path.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue

        line_number = int(data.get("line_number", 0))
        line_text = data.get("lines", {}).get("text", "")
        submatches = data.get("submatches", [])
        if not submatches:
            continue
        first_sm = submatches[0]
        sm_start = int(first_sm.get("start", 0))
        sm_end = int(first_sm.get("end", sm_start))

        line_start_abs = _sandbox.line_start_offset(abs_path, line_number)
        byte_range = [line_start_abs + sm_start, line_start_abs + sm_end]

        hit: dict = {
            "path": rel_path.as_posix(),
            "lines": {"text": line_text, "line_number": line_number},
            "byte_range": byte_range,
        }

        # Optional preview context
        if context_bytes and context_bytes > 0:
            # Use internal reader to generate a bytes-based preview
            preview = read_file_range(
                path=hit["path"],
                start=byte_range[0],
                end=byte_range[1],
                context=int(context_bytes),
            )
            hit["preview"] = {
                "mode": "bytes",
                "start": preview["start"],
                "end": preview["end"],
                "text": preview["text"],
            }
        elif context_lines and context_lines > 0:
            # Build a line-based preview around the match
            try:
                file_text = abs_path.read_text(encoding="utf-8", errors="replace")
                all_lines = file_text.splitlines(keepends=True)
                start_idx = max(0, line_number - 1 - int(context_lines))
                end_idx = min(len(all_lines), line_number + int(context_lines))
                preview_text = "".join(all_lines[start_idx:end_idx])
                hit["preview"] = {
                    "mode": "lines",
                    "start_line": start_idx + 1,
                    "end_line": end_idx,
                    "text": preview_text,
                }
            except Exception:
                # Ignore preview errors and still return the hit
                pass

        hits.append(hit)
        if len(hits) >= max_results:
            break
    return {"hits": hits}


def file_search(
    query: str | None = None,
    glob: str | None = None,
    case_sensitive: bool = False,
    max_results: int | None = None,
) -> dict:
    """Return files whose path/filename matches a boolean path query.

    Parameters:
    - query: Boolean expression with AND/OR and parentheses applied to the
      file contents at whole-file scope. A file matches if any conjunction is
      satisfied and all its terms appear somewhere in the file. NOT is not
      supported. If omitted or empty, returns files matching the glob up to
      max_results.
    - glob: Optional glob to limit which files are considered (defaults to config.glob)
    - case_sensitive: Path matching case sensitivity (default False)
    - max_results: Optional cap on returned files (defaults to config.max_results)

    Returns: { "files": [relative_paths...] }
    """
    considered_glob = glob or _config.glob
    limit = max_results or _config.max_results

    used_boolean = False
    dnf: List[List[str]] = []
    if query:
        used_boolean, dnf = _parse_boolean_query_to_dnf(query)

    matched: List[str] = []
    # Expand glob like **/*.{md,txt}
    patterns: List[str]
    if "{" in considered_glob and "}" in considered_glob:
        prefix = considered_glob.split("{")[0]
        suffix = considered_glob.split("}")[-1]
        inner = considered_glob[considered_glob.find("{") + 1:considered_glob.find("}")]
        variants = [s.strip() for s in inner.split(",") if s.strip()]
        patterns = [f"{prefix}{v}{suffix}" for v in variants]
    else:
        patterns = [considered_glob]

    # Content-based file search over entire file (default and only mode)
    term_sets: List[List[str]] = []
    if query:
        used_bool, dnf2 = _parse_boolean_query_to_dnf(query)
        if used_bool and dnf2:
            term_sets = dnf2
        else:
            term_sets = [[query]]
    for file_path in _sandbox.root.rglob("*"):
        if not file_path.is_file() or file_path.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        rel = file_path.relative_to(_sandbox.root).as_posix()
        if patterns and not any(fnmatch.fnmatchcase(rel, p) for p in patterns):
            continue
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        hay = content if case_sensitive else content.lower()
        matched_conj = False
        for conj in term_sets or [[]]:
            conj_terms = [t if case_sensitive else t.lower() for t in conj if t]
            if all(term in hay for term in conj_terms):
                matched_conj = True
                break
        if matched_conj:
            matched.append(rel)
            if len(matched) >= limit:
                break
    return {"files": matched}


def read_file_range(path: str, start: int, end: int, context: int | None = None) -> dict:
    """Read and return a UTF-8 decoded slice around a byte range.

    Parameters:
    - path: File path relative to the sandbox root
    - start, end: Absolute byte offsets for the match range
    - context: Optional number of extra bytes to include on both sides
      (defaults to Config.context_bytes when None)
    """
    context = _config.context_bytes if context is None else int(context)
    abs_path = _sandbox.resolve_inside(path)
    start = max(0, int(start) - context)
    end = int(end) + context
    data: bytes
    with abs_path.open("rb") as f:
        file_bytes = f.read()
    start = max(0, min(start, len(file_bytes)))
    end = max(start, min(end, len(file_bytes)))
    text = file_bytes[start:end].decode("utf-8", errors="replace")
    return {"path": Path(path).as_posix(), "start": start, "end": end, "text": text}


def list_paths(subdir: str = ".") -> dict:
    """List files within the sandbox root under a subdirectory."""
    files = _sandbox.list_paths(subdir)
    return {"files": files}
