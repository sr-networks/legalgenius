#!/usr/bin/env python3
"""
Fetch German court decisions (Urteile) from the Neuris API and write
Markdown files grouped by year into data/urteile_markdown_by_year.

Notes:
- This script targets the official Rechtsinformationen Bund (Neuris) API.
- Default endpoints are reasonable guesses based on public docs. If the API
  changes, pass the correct endpoints via CLI flags.
- No API key is required for many endpoints; if you have one, pass via
  --api-key and it will be sent as Authorization: Bearer <key>.

Example:
  # Fetch decisions from 2000..current year and merge into data/
  python scrapers/fetch_urteile_neuris.py --from-year 2000 --out data/urteile_markdown_by_year

  # With explicit endpoints (if defaults differ):
  python scrapers/fetch_urteile_neuris.py \
    --base-url https://api.rechtsinformationen.bund.de \
    --search-path /v1/search \
    --detail-path /v1/documents/{id} \
    --from-year 2010 --to-year 2024

Behavior:
- Paginates the search endpoint per year to avoid overly large result sets.
- For each item, fetches details to extract content fields when needed.
- De-duplicates by stable document id or URL.
- Merges with existing yearly Markdown files; new items are appended
  to the end of the year's file (keeps existing order intact).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
import time

import requests


# ---------- Data model and rendering (aligned with export_urteile_markdown_by_year.py) ----------

@dataclass(frozen=True)
class Decision:
    id: str
    url: str
    title: str
    date: Optional[dt.date]
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
        if self.date:
            return str(self.date.year)
        return "unknown"


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
    if dec.date:
        meta.append(dec.date.isoformat())
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


def parse_date(s: Optional[str]) -> Optional[dt.date]:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%d.%m.%Y", "%Y"):
        try:
            d = dt.datetime.strptime(s, fmt).date()
            if fmt == "%Y":
                return dt.date(d.year, 1, 1)
            return d
        except Exception:
            continue
    return None


def safe_get(obj: Dict[str, Any], keys: Iterable[str], default: str = "") -> str:
    for k in keys:
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return default


def list_search(
    base_url: str,
    search_path: str,
    headers: Dict[str, str],
    query_params: Dict[str, Any],
    *, timeout: int,
) -> Dict[str, Any]:
    url = base_url.rstrip("/") + search_path
    resp = requests.get(url, params=query_params, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"Search error {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def fetch_detail(
    base_url: str,
    detail_path: str,
    headers: Dict[str, str],
    doc_id: str,
    *, timeout: int,
) -> Dict[str, Any]:
    path = detail_path.replace("{id}", doc_id)
    url = base_url.rstrip("/") + path
    resp = requests.get(url, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"Detail error {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def decision_from_item(item: Dict[str, Any], detail: Dict[str, Any], base_url: str) -> Decision:
    # Try multiple common keys to be resilient to schema variations
    # ID handling (Hydra '@id' path or explicit id fields)
    raw_id = item.get("@id") or item.get("id") or item.get("documentId") or detail.get("id") or detail.get("documentId") or ""
    if isinstance(raw_id, str) and raw_id.startswith("/"):
        # Extract trailing segment, e.g., '/v1/case-law/KORE123' -> 'KORE123'
        did = raw_id.rstrip("/").split("/")[-1]
        url = raw_id  # will be prepended by base below
    else:
        did = str(raw_id)
        url = safe_get(item, ["url", "source", "documentUrl"]) or safe_get(detail, ["url", "source", "documentUrl"]) or ""

    title = (
        safe_get(item, ["headline", "title", "documentTitle"]) or
        safe_get(detail, ["headline", "title", "documentTitle"]) or ""
    )
    date_s = safe_get(item, ["decisionDate", "date", "publishedAt"]) or safe_get(detail, ["decisionDate", "date", "publishedAt"]) or ""
    date = parse_date(date_s)
    court = safe_get(item, ["courtName", "court", "courtType"]) or safe_get(detail, ["courtName", "court", "courtType"]) or ""
    file_num = (
        (item.get("fileNumbers")[0] if isinstance(item.get("fileNumbers"), list) and item.get("fileNumbers") else "") or
        safe_get(item, ["fileNumber", "file_number", "aktenzeichen"]) or
        safe_get(detail, ["fileNumber", "file_number", "aktenzeichen"]) or ""
    )
    decision_type = safe_get(item, ["documentType", "type", "decisionType"]) or safe_get(detail, ["documentType", "type", "decisionType"]) or ""

    # Content fields
    leitsatz = safe_get(detail, ["leitsatz", "headnote", "headnotes"]) or ""
    tenor = safe_get(detail, ["tenor", "ruling"]) or ""
    content = safe_get(detail, ["content", "fullText", "text"]) or ""

    # References
    laws: List[str] = []
    cases: List[str] = []
    refs = detail.get("references") or item.get("references") or {}
    if isinstance(refs, dict):
        if isinstance(refs.get("laws"), list):
            laws = [str(x) for x in refs.get("laws") if x]
        if isinstance(refs.get("cases"), list):
            cases = [str(x) for x in refs.get("cases") if x]

    # Normalize URL to absolute if possible
    if isinstance(url, str) and url.startswith("/"):
        url = base_url.rstrip("/") + url

    return Decision(
        id=did or url or title,
        url=url,
        title=title,
        date=date,
        file_number=file_num,
        court=court,
        decision_type=decision_type,
        leitsatz=leitsatz,
        tenor=tenor,
        content=content,
        laws=tuple(laws),
        cases=tuple(cases),
    )


def merge_into_year_files(out_dir: Path, decisions: List[Decision]) -> None:
    # Load existing year files to build a set of known identifiers per year
    existing_ids_by_year: Dict[str, set[str]] = {}
    for md in out_dir.glob("*.md"):
        year = md.stem
        if not year.isdigit() and year != "unknown":
            continue
        known: set[str] = set()
        try:
            text = md.read_text(encoding="utf-8")
        except Exception:
            continue
        # Heuristic: capture IDs from Quelle URL lines if present
        for line in text.splitlines():
            if line.startswith("- Quelle:"):
                known.add(line.split(":", 1)[1].strip())
        existing_ids_by_year[year] = known

    # Group new decisions per year and append to files
    per_year: Dict[str, List[Decision]] = {}
    for d in decisions:
        per_year.setdefault(d.year, []).append(d)

    out_dir.mkdir(parents=True, exist_ok=True)
    for year, items in per_year.items():
        target = out_dir / f"{year}.md"
        # Initialize file if missing with minimal header
        if not target.exists():
            header = ["---\n", json.dumps({"year": year, "count": 0, "types": {}}, ensure_ascii=False, indent=2) + "\n", "---\n\n", f"# Entscheidungen {year}\n\n"]
            target.write_text("".join(header), encoding="utf-8")
        # Append new items that aren't duplicates
        known = existing_ids_by_year.get(year, set())
        appended = 0
        with target.open("a", encoding="utf-8") as f:
            for d in items:
                dup_key = d.url or d.id
                if dup_key and dup_key in known:
                    continue
                f.write(render_decision_md(d))
                if dup_key:
                    known.add(dup_key)
                appended += 1
        if appended:
            print(f"Appended {appended} decisions to {target}")


def fetch_for_year(
    base_url: str,
    search_path: str,
    detail_path: str,
    headers: Dict[str, str],
    year: int,
    page_param: str,
    size_param: str,
    page_size: int,
    collection_param: Optional[str],
    collection_value: Optional[str],
    from_param: Optional[str],
    to_param: Optional[str],
    extra_params: Dict[str, Any],
    sleep_seconds: float = 0.0,
    *,
    max_pages: Optional[int] = None,
    no_detail: bool = False,
    timeout: int = 60,
) -> List[Decision]:
    decisions: List[Decision] = []
    page = 0
    total = None
    while True:
        params: Dict[str, Any] = {
            page_param: page,
            size_param: page_size,
        }
        # Date window
        if from_param:
            params[from_param] = f"{year}-01-01"
        if to_param:
            params[to_param] = f"{year}-12-31"
        if collection_param and collection_value:
            params[collection_param] = collection_value
        params.update(extra_params)

        data = list_search(base_url, search_path, headers, params, timeout=timeout)

        raw_items = (
            data.get("member")
            or data.get("results")
            or data.get("items")
            or data.get("documents")
            or data.get("content")
            or (data if isinstance(data, list) else [])
        )
        # Hydra 'member' entries may wrap the actual item under 'item'
        items: List[Dict[str, Any]] = []
        for it in raw_items:
            if isinstance(it, dict) and "item" in it and isinstance(it["item"], dict):
                items.append(it["item"])
            else:
                items.append(it)

        if total is None:
            total = data.get("totalItems") or data.get("total") or data.get("totalHits") or data.get("totalElements") or None
            if total is not None:
                print(f"{year}: total={total}")

        if not isinstance(items, list) or not items:
            break

        for it in items:
            # Determine id for detail call: prefer '@id' trailing segment
            doc_id = None
            raw_id = it.get("@id")
            if isinstance(raw_id, str) and raw_id.startswith("/"):
                doc_id = raw_id.rstrip("/").split("/")[-1]
            if not doc_id:
                doc_id = str(it.get("id") or it.get("documentId") or it.get("uuid") or "").strip()
            if not doc_id:
                # Skip if no stable id present
                continue
            if no_detail:
                detail = {}
            else:
                try:
                    detail = fetch_detail(base_url, detail_path, headers, doc_id, timeout=timeout)
                except Exception as e:
                    print(f"Warn: detail failed for id={doc_id}: {e}")
                    detail = {}
            decisions.append(decision_from_item(it, detail, base_url))

        # Stop if last page
        if len(items) < page_size:
            break
        # Optional page limit
        if max_pages is not None and page + 1 >= max_pages:
            break
        page += 1
        if sleep_seconds:
            time.sleep(sleep_seconds)

    return decisions


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch court decisions from Neuris API and write yearly Markdown files")
    p.add_argument("--base-url", default="https://testphase.rechtsinformationen.bund.de", help="API base URL")
    p.add_argument("--search-path", default="/v1/case-law", help="Search endpoint path")
    p.add_argument("--detail-path", default="/v1/case-law/{id}", help="Detail endpoint path (use {id} placeholder)")
    p.add_argument("--from-year", type=int, default=2000, help="Start year (inclusive)")
    p.add_argument("--to-year", type=int, default=dt.date.today().year, help="End year (inclusive)")
    p.add_argument("--out", default="data/urteile_markdown_by_year", help="Output directory")
    p.add_argument("--page-size", type=int, default=100, help="Page size for search pagination")
    p.add_argument("--page-param", default="pageIndex", help="Query parameter name for page number")
    p.add_argument("--size-param", default="size", help="Query parameter name for page size")
    p.add_argument("--collection-param", default="", help="Query parameter to restrict to a collection (leave blank to skip)")
    p.add_argument("--collection-value", default="", help="Value for collection param")
    p.add_argument("--from-param", default="decisionDateFrom", help="Query parameter name for from-date (set blank to skip)")
    p.add_argument("--to-param", default="decisionDateTo", help="Query parameter name for to-date (set blank to skip)")
    p.add_argument("--query", default=None, help="Optional search query string (API-dependent)")
    p.add_argument("--extra", action="append", default=[], help="Extra query param in key=value form; can be repeated")
    p.add_argument("--api-key", default=None, help="API key for Authorization header (optional)")
    p.add_argument("--sleep", type=float, default=0.0, help="Seconds to sleep between pages to be polite")
    p.add_argument("--max-pages", type=int, default=None, help="Limit number of pages per year (for testing)")
    p.add_argument("--no-detail", action="store_true", help="Do not fetch detail; write meta without full text")
    p.add_argument("--timeout", type=int, default=60, help="HTTP timeout in seconds")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    headers: Dict[str, str] = {"Accept": "application/json"}
    if args.api_key:
        headers["Authorization"] = f"Bearer {args.api_key}"

    # Parse extra params
    extra: Dict[str, Any] = {}
    for kv in args.extra or []:
        if "=" in kv:
            k, v = kv.split("=", 1)
            extra[k] = v

    out_dir = Path(args.out)
    all_decisions: List[Decision] = []
    for year in range(int(args.from_year), int(args.to_year) + 1):
        print(f"Fetching {year}...")
        try:
            decs = fetch_for_year(
                base_url=args.base_url,
                search_path=args.search_path,
                detail_path=args.detail_path,
                headers=headers,
                year=year,
                page_param=args.page_param,
                size_param=args.size_param,
                page_size=int(args.page_size),
                collection_param=(args.collection_param or None),
                collection_value=(args.collection_value or None),
                from_param=(args.from_param or None),
                to_param=(args.to_param or None),
                extra_params=({"q": args.query} if args.query else {}) | extra,
                sleep_seconds=float(args.sleep),
                max_pages=args.max_pages,
                no_detail=bool(args.no_detail),
                timeout=int(args.timeout),
            )
        except Exception as e:
            print(f"Error fetching {year}: {e}")
            continue
        print(f"  {len(decs)} decisions")
        all_decisions.extend(decs)

    if not all_decisions:
        print("No decisions fetched; nothing to write.")
        return 0

    merge_into_year_files(out_dir, all_decisions)
    print(f"Merged {len(all_decisions)} decisions into {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
