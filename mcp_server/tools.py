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
import requests

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


def nearest_header(lines: List[str], start_index: int) -> str | None:
    """Walk upward to find the nearest preceding Markdown header."""
    for i in range(start_index, -1, -1):
        if re.match(r"^\s{0,3}#{1,6}\s+\S", lines[i]):
            return lines[i].strip()
    return None


def search_rg(
    query: str,
    file_list: List[str] | None = None,
    max_results: int | None = None,
    context_lines: int | None = None,
    regex: bool = False,
    case_sensitive: bool = False,
) -> dict:
    """Search for a pattern using ripgrep and return structured matches with context.

    Parameters:
    - query: String pattern passed to ripgrep
    - file_list: Optional list of relative file paths to restrict search
    - max_results: Optional cap on number of matches (defaults to 20)
    - context_lines: Number of context lines around each match (default 2)
    - regex: Whether to treat query as regex (default False)
    - case_sensitive: Whether search is case sensitive (default False)

    Returns: { "matches": [ { file, line, text, context, section } ] }
    """
    max_results = 20 if (max_results is None) else int(max_results)
    context_lines = 2 if (context_lines is None) else int(context_lines)
    
    rg_path = shutil.which("rg")
    if not rg_path:
        return {"error": "ripgrep (rg) not found on PATH", "matches": []}

    # Handle Boolean OR queries by converting to regex
    search_pattern = query
    if " OR " in query.upper():
        # Convert "term1 OR term2" to regex alternation "term1|term2"
        parts = [part.strip() for part in re.split(r'\s+OR\s+', query, flags=re.IGNORECASE)]
        if not regex:
            # Escape regex special chars for literal search
            parts = [re.escape(part) for part in parts]
        search_pattern = "|".join(parts)
        regex = True  # Force regex mode for OR queries
    
    # Build ripgrep command
    args = [
        rg_path,
        "--no-heading",
        "--line-number", 
        "--with-filename",
        f"-C{context_lines}",
        "--max-count", str(max_results),
        "--json",
        "--color", "never",
    ]
    
    if not case_sensitive:
        args.append("-i")
    if regex:
        args.append("-P")  # Use Perl regex for alternation
    else:
        args.append("-F")  # Fixed string search
        
    # Determine search files
    search_files: List[Path] = []
    if file_list:
        for rel in file_list:
            try:
                abs_p = _sandbox.resolve_inside(rel)
                if abs_p.is_file() and abs_p.suffix.lower() in ALLOWED_EXTENSIONS:
                    # Direct file
                    search_files.append(abs_p)
                elif abs_p.is_dir():
                    # Directory - search all files within
                    for p in abs_p.rglob("*"):
                        if p.is_file() and p.suffix.lower() in ALLOWED_EXTENSIONS:
                            search_files.append(p)
                elif rel == "." or rel == "./":
                    # Explicit request for entire corpus
                    for p in _sandbox.root.rglob("*"):
                        if p.is_file() and p.suffix.lower() in ALLOWED_EXTENSIONS:
                            search_files.append(p)
                else:
                    # Handle glob patterns like 'urteile_markdown_by_year/*.md'
                    if "*" in rel or "?" in rel:
                        for p in _sandbox.root.glob(rel):
                            if p.is_file() and p.suffix.lower() in ALLOWED_EXTENSIONS:
                                search_files.append(p)
            except (PermissionError, OSError):
                continue
    else:
        # Fallback: search all files in sandbox
        for p in _sandbox.root.rglob("*"):
            if p.is_file() and p.suffix.lower() in ALLOWED_EXTENSIONS:
                search_files.append(p)
    
    if not search_files:
        return {"matches": []}
        
    args.append(search_pattern)
    args += [str(f) for f in search_files]
    
    # Run ripgrep
    proc = subprocess.run(args, capture_output=True, text=True, cwd=_sandbox.root)
    if proc.returncode not in (0, 1):  # 1 means "no matches"
        return {"error": proc.stderr.strip() or "ripgrep error", "matches": []}
    
    # Parse JSON output
    raw_events = []
    for line in proc.stdout.splitlines():
        if line.strip():
            try:
                raw_events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    # Process events to build matches with context
    file_cache: Dict[str, List[str]] = {}
    blocks: Dict[str, Dict[int, Dict[str, any]]] = {}
    
    # Group events by file and line
    for ev in raw_events:
        t = ev.get("type")
        data = ev.get("data", {})
        if t == "match":
            path = data.get("path", {}).get("text", "")
            line_num = data.get("line_number", 0)
            text = data.get("lines", {}).get("text", "")
            blocks.setdefault(path, {}).setdefault(line_num, {
                "file": path,
                "line": line_num,
                "text": text.rstrip("\n"),
                "context": {}
            })
        elif t == "context":
            path = data.get("path", {}).get("text", "")
            line_num = data.get("line_number", 0)
            text = data.get("lines", {}).get("text", "")
            blocks.setdefault(path, {})[line_num] = {
                "file": path,
                "line": line_num,
                "text": text.rstrip("\n"),
                "is_context_only": True
            }
    
    matches: List[Dict[str, any]] = []
    
    # Build matches with context windows
    for path, per_file in blocks.items():
        if not per_file:
            continue
            
        # Load file for header detection
        if path not in file_cache:
            try:
                abs_path = _sandbox.resolve_inside(path)
                with abs_path.open("r", encoding="utf-8", errors="ignore") as fh:
                    file_cache[path] = fh.readlines()
            except Exception:
                file_cache[path] = []
        
        # Process actual matches (not context-only lines)
        match_lines = [ln for ln, rec in per_file.items() if not rec.get("is_context_only")]
        match_lines.sort()
        
        for ln in match_lines:
            # Build context window
            start = max(1, ln - context_lines)
            end = ln + context_lines
            context_rows = []
            
            for j in range(start, end + 1):
                if j in per_file:
                    txt = per_file[j].get("text", "")
                else:
                    # Fallback to file cache
                    lines = file_cache.get(path, [])
                    idx = j - 1
                    if 0 <= idx < len(lines):
                        txt = lines[idx].rstrip("\n")
                    else:
                        continue
                context_rows.append({"line": j, "text": txt})
            
            # Find nearest header
            section = None
            lines_cache = file_cache.get(path, [])
            if lines_cache:
                section = nearest_header(lines_cache, ln - 2)  # 0-based index
            
            # Highlight query in main text
            main_text = per_file[ln]["text"]
            try:
                if regex:
                    pat = re.compile(query, 0 if case_sensitive else re.IGNORECASE)
                else:
                    pat = re.compile(re.escape(query), 0 if case_sensitive else re.IGNORECASE)
                hl_text = pat.sub(lambda m: f"**{m.group(0)}**", main_text)
            except re.error:
                hl_text = main_text
            
            # Convert absolute path to relative
            try:
                abs_path = _sandbox.resolve_inside(path)
                rel_path = abs_path.relative_to(_sandbox.root).as_posix()
            except Exception:
                rel_path = path
            
            # Calculate byte range for this line
            line_start_byte = _sandbox.line_start_offset(abs_path, ln)
            line_end_byte = line_start_byte + len(main_text.encode("utf-8"))
            
            matches.append({
                "file": rel_path,
                "line": ln,
                "text": hl_text,
                "context": context_rows,
                "section": section,
                "byte_range": [line_start_byte, line_end_byte]
            })
            
            if len(matches) >= max_results:
                break
    
    # Sort matches to prioritize newer files (higher years first)
    def extract_year_from_path(match):
        """Extract year from file path for sorting, defaulting to 0 for non-year files"""
        path = match.get("file", "")
        # Look for patterns like "2022.md", "2021.md" in the path
        import re
        year_match = re.search(r'/(\d{4})\.md$', path)
        if year_match:
            return int(year_match.group(1))
        # For non-year files, assign a high value to keep them at top
        return 9999
    
    matches.sort(key=extract_year_from_path, reverse=True)
    
    return {"matches": matches[:max_results]}


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
            # Auto-detect multiple keywords and treat as AND conjunction
            words = query.split()
            if len(words) > 1:
                # Multiple words - treat as AND conjunction
                term_sets = [words]
            else:
                # Single word or phrase
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


def read_file_range(path: str, start: int, end: int, context: int | None = None, max_lines: int | None = 20) -> dict:
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
    # Enforce maximum number of lines if requested
    if max_lines is not None:
        try:
            ml = int(max_lines)
        except Exception:
            ml = 20
        if ml > 0:
            lines = text.splitlines(keepends=True)
            if len(lines) > ml:
                text = "".join(lines[:ml])
                # Adjust end offset to match truncated UTF-8 length
                end = start + len(text.encode("utf-8"))
    return {"path": Path(path).as_posix(), "start": start, "end": end, "text": text}


def list_paths(subdir: str = ".") -> dict:
    """List files within the sandbox root under a subdirectory."""
    files = _sandbox.list_paths(subdir)
    return {"files": files}


def elasticsearch_search(
    query: str,
    document_type: str = "all",
    max_results: int = 10,
    es_host: str = "localhost",
    es_port: int = 9200
) -> dict:
    """Search legal documents using Elasticsearch for fast, comprehensive results.

    This is the preferred search method for legal research as it provides:
    - Full-text search across laws (gesetze) and court decisions (urteile)
    - German language analysis with stemming and legal terminology
    - Relevance scoring and ranking
    - Fast search across the entire legal corpus
    
    Parameters:
    - query: Search terms or phrases (e.g., "Kündigungsfrist", "BGB § 573", "fristlose Kündigung")
    - document_type: Type of documents to search - "all" (default), "gesetze" (laws), "urteile" (court decisions)
    - max_results: Maximum number of results to return (default 10)
    - es_host: Elasticsearch host (default localhost)
    - es_port: Elasticsearch port (default 9200)

    Returns: {
        "total_hits": int,
        "matches": [
            {
                "title": str,
                "document_type": "gesetz" | "urteil", 
                "file_path": str,
                "score": float,
                "content_preview": str,
                "line_matches": [{"line_number": int, "text": str}],
                "metadata": {...}
            }
        ]
    }
    
    Use this tool for:
    - Finding relevant laws and court decisions
    - Legal term searches across the entire corpus
    - Cross-referencing between legislation and jurisprudence
    - Comprehensive legal research
    """
    es_url = f"http://{es_host}:{es_port}"
    
    # Determine which indices to search
    if document_type == "gesetze":
        indices = "legal_gesetze"
    elif document_type == "urteile":
        indices = "legal_urteile"
    else:  # "all" or any other value
        indices = "legal_gesetze,legal_urteile"
    
    # Build Elasticsearch query
    search_query = {
        "query": {
            "multi_match": {
                "query": query,
                "fields": ["title^3", "content^1"],
                "type": "best_fields",
                "fuzziness": "AUTO",
                "operator": "or"
            }
        },
        "highlight": {
            "fields": {
                "title": {"number_of_fragments": 1, "fragment_size": 100},
                "content": {"number_of_fragments": 3, "fragment_size": 200}
            },
            "pre_tags": ["<em>"],
            "post_tags": ["</em>"]
        },
        "size": min(max_results, 50),  # Cap at 50 for performance
        "_source": ["title", "document_type", "file_path", "content", "date", "court", "case_number", "jurabk", "content_start_line"]
    }
    
    try:
        response = requests.post(
            f"{es_url}/{indices}/_search",
            json=search_query,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        
        if response.status_code != 200:
            return {
                "error": f"Elasticsearch error: {response.status_code} - {response.text}",
                "total_hits": 0,
                "matches": []
            }
            
        result = response.json()
        hits = result.get('hits', {})
        total_hits = hits.get('total', {}).get('value', 0)
        
        matches = []
        for hit in hits.get('hits', []):
            source = hit['_source']
            
            # Extract line matches from content
            line_matches = []
            content = source.get('content', '')
            if content:
                lines = content.split('\n')
                query_terms = query.lower().split()
                content_start_line = source.get('content_start_line', 1)
                
                for i, line in enumerate(lines[:20], 1):  # Check first 20 lines for performance
                    line_lower = line.lower()
                    if any(term in line_lower for term in query_terms):
                        actual_line_num = content_start_line + i - 1 if content_start_line else i
                        line_matches.append({
                            "line_number": actual_line_num,
                            "text": line.strip()[:200]  # Limit line length
                        })
                        if len(line_matches) >= 3:  # Limit matches per document
                            break
            
            # Create content preview from highlights or first part of content
            content_preview = ""
            if 'highlight' in hit:
                if 'content' in hit['highlight']:
                    content_preview = ' ... '.join(hit['highlight']['content'][:2])
                elif 'title' in hit['highlight']:
                    content_preview = hit['highlight']['title'][0]
            
            if not content_preview and content:
                content_preview = content[:300] + ("..." if len(content) > 300 else "")
            
            # Build metadata
            metadata = {}
            if source.get('date'):
                metadata['date'] = source['date']
            if source.get('court'):
                metadata['court'] = source['court']  
            if source.get('case_number'):
                metadata['case_number'] = source['case_number']
            if source.get('jurabk'):
                metadata['jurabk'] = source['jurabk']
                
            matches.append({
                "title": source.get('title', 'Untitled'),
                "document_type": source.get('document_type', 'unknown'),
                "file_path": source.get('file_path', ''),
                "score": hit['_score'],
                "content_preview": content_preview,
                "line_matches": line_matches,
                "metadata": metadata
            })
        
        return {
            "total_hits": total_hits,
            "matches": matches,
            "search_info": {
                "query": query,
                "document_type": document_type,
                "indices_searched": indices,
                "max_results": max_results
            }
        }
        
    except requests.exceptions.RequestException as e:
        return {
            "error": f"Connection error to Elasticsearch: {str(e)}",
            "total_hits": 0,
            "matches": [],
            "suggestion": "Please ensure Elasticsearch is running on localhost:9200"
        }
    except Exception as e:
        return {
            "error": f"Search error: {str(e)}",
            "total_hits": 0,
            "matches": []
        }
