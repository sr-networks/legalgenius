#!/usr/bin/env python3
"""
Load case file from openlegaldata
and extract from it (cases.jsonl) and write one Markdown file per year.

- Input: JSON Lines, each line a JSON object with keys observed such as:
  {"url": str, "title": str, "date": str, "file_number": str, "court": (str|obj),
   "type": str, "leitsatz": str, "tenor": str, "content": str,
   "references": {"laws": [str], "cases": [str]}}

- Year derivation order:
  1) Parse 'date' if present using known patterns (YYYY-MM-DD, DD.MM.YYYY, YYYY)
  2) Else parse date embedded in 'title' (DD.MM.YYYY)
  3) Else year = 'unknown'

- Output: out_dir/<year>.md with all decisions for that year in date-desc order.
- Also writes out_dir/index.md summarizing counts per year.

Standard library only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
import urllib.request
import urllib.parse
import gzip
import shutil
import ssl

DATE_PATTERNS = [
    (re.compile(r"^(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})$"), "%Y-%m-%d"),
    (re.compile(r"^(?P<d>\d{2})\.(?P<m>\d{2})\.(?P<y>\d{4})$"), "%d.%m.%Y"),
    (re.compile(r"^(?P<y>\d{4})$"), "%Y"),
]
TITLE_DATE_RE = re.compile(r"(\d{2}\.\d{2}\.\d{4})")


@dataclass(frozen=True)
class Decision:
    url: str
    title: str
    date_str: str
    parsed_date: Optional[dt.date]
    file_number: str
    court: str
    decision_type: str
    leitsatz: str
    tenor: str
    content: str
    laws: Tuple[str, ...]
    cases: Tuple[str, ...]

    @property
    def year(self) -> str:
        if self.parsed_date:
            return str(self.parsed_date.year)
        # Try to infer from date_str if it looks like a year
        if self.date_str and len(self.date_str) == 4 and self.date_str.isdigit():
            return self.date_str
        # Fallback: unknown
        return "unknown"


def parse_date(s: Optional[str], title: Optional[str]) -> Tuple[str, Optional[dt.date]]:
    s = (s or "").strip()
    # Try date field
    for rx, fmt in DATE_PATTERNS:
        if s and rx.match(s):
            try:
                return s, dt.datetime.strptime(s, fmt).date()
            except Exception:
                pass
    # Try to extract from title
    if title:
        m = TITLE_DATE_RE.search(title)
        if m:
            ds = m.group(1)
            try:
                return ds, dt.datetime.strptime(ds, "%d.%m.%Y").date()
            except Exception:
                pass
    # Unknown
    return s, None


def sanitize(s: Optional[str]) -> str:
    if s is None:
        return ""
    return str(s).replace("\r\n", "\n").replace("\r", "\n").strip()


def load_decisions(jsonl_path: Path) -> List[Decision]:
    decisions: List[Decision] = []
    seen_urls: set[str] = set()
    with jsonl_path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj: Dict = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"Skipping invalid JSON at line {i}: {e}", file=sys.stderr)
                continue
            url = sanitize(obj.get("url"))
            if url and url in seen_urls:
                continue
            title = sanitize(obj.get("title"))
            date_str, parsed = parse_date(sanitize(obj.get("date")), title)
            file_num = sanitize(obj.get("file_number"))
            decision_type = sanitize(obj.get("type"))
            # court can be a string or an object; prefer name if available
            court_obj = obj.get("court")
            if isinstance(court_obj, dict):
                court = sanitize(court_obj.get("name")) or sanitize(str(court_obj))
            else:
                court = sanitize(court_obj)
            leitsatz = sanitize(obj.get("leitsatz"))
            tenor = sanitize(obj.get("tenor"))
            content = sanitize(obj.get("content"))
            refs = obj.get("references") or {}
            laws = tuple(refs.get("laws") or [])
            cases = tuple(refs.get("cases") or [])
            decisions.append(Decision(
                url=url,
                title=title,
                date_str=date_str,
                parsed_date=parsed,
                file_number=file_num,
                court=court,
                decision_type=decision_type,
                leitsatz=leitsatz,
                tenor=tenor,
                content=content,
                laws=laws,
                cases=cases,
            ))
            if url:
                seen_urls.add(url)
    return decisions


def download_gz(url: str, dest_gz: Path, *, cafile: Optional[str] = None, insecure: bool = False, timeout: int = 60) -> None:
    dest_gz.parent.mkdir(parents=True, exist_ok=True)
    ctx = ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()
    try:
        with urllib.request.urlopen(url, context=ctx, timeout=timeout) as resp, dest_gz.open("wb") as out:
            shutil.copyfileobj(resp, out)
    except Exception as e:
        # If verification fails and insecure mode requested, retry without verification
        if insecure and isinstance(getattr(e, "reason", None), ssl.SSLError):
            print("Warning: retrying download without SSL certificate verification (--insecure)", file=sys.stderr)
            unverified = ssl._create_unverified_context()
            with urllib.request.urlopen(url, context=unverified, timeout=timeout) as resp, dest_gz.open("wb") as out:
                shutil.copyfileobj(resp, out)
        else:
            raise


def gunzip_to(src_gz: Path, dest_jsonl: Path) -> None:
    dest_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(src_gz, "rb") as f_in, dest_jsonl.open("wb") as f_out:
        shutil.copyfileobj(f_in, f_out)


def sort_key(dec: Decision):
    # Sort by date desc (None last), then by title
    date_key = dec.parsed_date or dt.date.min
    return (-date_key.toordinal(), dec.title)


def render_decision_md(dec: Decision) -> str:
    lines: List[str] = []
    h = dec.title or dec.file_number or dec.url or "Entscheidung"
    lines.append(f"### {h}\n")
    meta: List[str] = []
    if dec.decision_type:
        meta.append(dec.decision_type)
    if dec.court:
        meta.append(dec.court)
    if dec.file_number:
        meta.append(dec.file_number)
    if dec.parsed_date:
        meta.append(dec.parsed_date.isoformat())
    elif dec.date_str:
        meta.append(dec.date_str)
    if meta:
        lines.append("- " + " | ".join(meta) + "\n")
    if dec.url:
        lines.append(f"- Quelle: {dec.url}\n")
    if dec.leitsatz:
        lines.append("\n#### Leitsatz\n\n")
        lines.append(dec.leitsatz + "\n")
    if dec.tenor:
        lines.append("\n#### Tenor\n\n")
        lines.append(dec.tenor + "\n")
    if dec.laws:
        lines.append("\n#### Normen/Links\n\n")
        for l in dec.laws:
            lines.append(f"- {l}\n")
    if dec.cases:
        lines.append("\n#### Verweise auf Entscheidungen\n\n")
        for c in dec.cases:
            lines.append(f"- {c}\n")
    if dec.content:
        lines.append("\n#### Entscheidungstext\n\n")
        lines.append(dec.content + "\n")
    lines.append("\n")
    return "".join(lines)


def write_year_files(out_dir: Path, decisions: List[Decision]) -> Dict[str, int]:
    groups: Dict[str, List[Decision]] = defaultdict(list)
    for d in decisions:
        groups[d.year].append(d)
    counts: Dict[str, int] = {}
    out_dir.mkdir(parents=True, exist_ok=True)

    for year, items in groups.items():
        items_sorted = sorted(items, key=sort_key)
        # Count decision types for this year
        type_counts: Dict[str, int] = {}
        for d in items_sorted:
            if d.decision_type:
                type_counts[d.decision_type] = type_counts.get(d.decision_type, 0) + 1
        # Create an ordered dict-like for JSON output sorted by count desc then name
        types_ordered = {k: v for k, v in sorted(type_counts.items(), key=lambda kv: (-kv[1], kv[0]))}
        lines: List[str] = []
        lines.append("---\n")
        meta = {"year": year, "count": len(items_sorted), "types": types_ordered}
        lines.append(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
        lines.append("---\n\n")
        lines.append(f"# Entscheidungen {year}\n\n")
        if types_ordered:
            lines.append("## Entscheidungstypen\n\n")
            for t, c in types_ordered.items():
                lines.append(f"- {t}: {c}\n")
            lines.append("\n")
        for d in items_sorted:
            lines.append(render_decision_md(d))
        (out_dir / f"{year}.md").write_text("".join(lines), encoding="utf-8")
        counts[year] = len(items_sorted)
    # index
    index_lines: List[str] = ["# Index: Entscheidungen nach Jahr\n\n"]
    for year in sorted(counts.keys(), reverse=True):
        index_lines.append(f"- [{year}]({year}.md) — {counts[year]} Entscheidungen\n")
    (out_dir / "index.md").write_text("".join(index_lines), encoding="utf-8")
    return counts


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export JSONL decisions to yearly Markdown files")
    p.add_argument("--input", default="./cases.jsonl", help="Path to cases.jsonl")
    p.add_argument("--out", default="urteile_markdown_by_year", help="Output directory")
    p.add_argument(
        "--download",
        action="store_true",
        help="If input is missing, download and decompress Open Legal Data dump into --input",
    )
    p.add_argument(
        "--download-url",
        default="https://static.openlegaldata.io/dumps/de/2020-12-10/cases.jsonl.gz",
        help="URL to cases.jsonl.gz (default: official OLD dump)",
    )
    p.add_argument(
        "--cafile",
        default=None,
        help="Path to CA bundle to use for HTTPS verification (e.g., /etc/ssl/cert.pem)",
    )
    p.add_argument(
        "--insecure",
        action="store_true",
        help="Allow download without SSL certificate verification (NOT recommended)",
    )
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    jsonl_path = Path(args.input)
    if not jsonl_path.exists():
        if getattr(args, "download", False):
            try:
                # Determine destination .gz path from URL name inside the input directory
                url_path = urllib.parse.urlparse(args.download_url).path
                gz_name = Path(url_path).name or "cases.jsonl.gz"
                gz_path = jsonl_path.parent / gz_name
                print(f"Downloading dump: {args.download_url} -> {gz_path}")
                download_gz(args.download_url, gz_path, cafile=args.cafile, insecure=args.insecure)
                print(f"Decompressing: {gz_path} -> {jsonl_path}")
                gunzip_to(gz_path, jsonl_path)
            except Exception as e:
                print(f"Failed to download/decompress dump: {e}", file=sys.stderr)
                return 3
        else:
            print(f"Input not found: {jsonl_path}", file=sys.stderr)
            return 2
    print(f"Loading: {jsonl_path}")
    decisions = load_decisions(jsonl_path)
    print(f"Parsed {len(decisions)} decisions")
    counts = write_year_files(Path(args.out), decisions)
    total = sum(counts.values())
    print(f"Wrote {len(counts)} year files, {total} entries -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
