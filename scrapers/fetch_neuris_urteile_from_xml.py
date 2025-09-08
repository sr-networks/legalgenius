#!/usr/bin/env python3
"""
Neuris case-law fetcher (with Randnummern from XML) writing Markdown files
grouped by year into ../data/urteile_markdown_by_year/<year>/.

- Lists all case-law via /v1/case-law (paginated)
- Fetches detail JSON for each item
- Tries to fetch Akoma Ntoso XML to extract Randnummern (Tatbestand/Entscheidungsgründe)
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import argparse

import requests
import xml.etree.ElementTree as ET


class UrteileAPIScraper:
    """Scraper for German court decisions from rechtsinformationen.bund.de API"""

    def __init__(self, base_url: str = "https://testphase.rechtsinformationen.bund.de"):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Python-Urteil-Scraper/1.0",
            "Accept": "application/json",
        })

        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
        self.logger = logging.getLogger(__name__)

        # Rate limiting
        self.request_delay = 0.11  # seconds
        self.last_request_time = 0.0

        # Output directory: ../data/urteile_markdown_by_year
        self.output_dir = (Path(__file__).resolve().parents[1] / "data" / "urteile_markdown_by_year").resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _rate_limit(self) -> None:
        now = time.time()
        delta = now - self.last_request_time
        if delta < self.request_delay:
            time.sleep(self.request_delay - delta)
        self.last_request_time = time.time()

    def _make_request(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        self._rate_limit()
        try:
            url = f"{self.base_url}{endpoint}"
            resp = self.session.get(url, params=params, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            self.logger.error(f"Request failed for {endpoint} params={params}: {e}")
            return None

    def get_decisions_list(
        self,
        page: int = 0,
        size: int = 100,
        court: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        search_term: Optional[str] = None,
        sort: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        # Follow API docs: parameters are pageIndex, size, dateFrom/dateTo, searchTerm, sort
        params: Dict[str, Any] = {"pageIndex": page, "size": min(size, 100)}
        if court:
            # Provide both keys for compatibility; API may accept either 'court' or 'courtName'
            params["court"] = court
            params["courtName"] = court
        if date_from:
            params["dateFrom"] = date_from
        if date_to:
            params["dateTo"] = date_to
        if search_term:
            params["searchTerm"] = search_term
        if sort:
            params["sort"] = sort
        # Debug first page params to verify filters are applied
        if page == 0:
            self.logger.debug(f"GET /v1/case-law params={params}")
        return self._make_request("/v1/case-law", params)

    def get_decisions_by_path(self, path_with_query: str) -> Optional[Dict[str, Any]]:
        """Request using a full path returned by view.next/first/last (already includes query params)."""
        # path_with_query is expected to start with '/v1/...'
        if not path_with_query.startswith("/"):
            path_with_query = "/" + path_with_query
        return self._make_request(path_with_query)

    def get_decision_metadata(self, decision_id: str) -> Optional[Dict[str, Any]]:
        return self._make_request(f"/v1/case-law/{decision_id}")

    def get_decision_xml(self, decision_id: str) -> Optional[str]:
        self._rate_limit()
        urls = [
            f"{self.base_url}/v1/case-law/{decision_id}.xml",
            f"{self.base_url}/v1/case-law/{decision_id}/xml",
        ]
        for url in urls:
            try:
                resp = self.session.get(url, headers={"Accept": "application/xml"}, timeout=60)
                if resp.status_code == 200 and resp.text.strip():
                    return resp.text
            except Exception as e:
                self.logger.warning(f"XML fetch failed for {decision_id} at {url}: {e}")
        return None

    def extract_randnummern(self, xml_text: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        try:
            ns = {"akn": "http://docs.oasis-open.org/legaldocml/ns/akn/3.0/WD17"}
            root = ET.fromstring(xml_text)

            # Tatbestand: akn:background
            for hc in root.findall('.//akn:background//akn:hcontainer[@name="randnummer"]', ns):
                num_el = hc.find('akn:num', ns)
                content_el = hc.find('akn:content', ns)
                text = ''.join((content_el.itertext() if content_el is not None else [])).strip()
                rn: Optional[int] = None
                if num_el is not None and (num_el.text or "").strip():
                    try:
                        rn = int((num_el.text or "").strip())
                    except Exception:
                        rn = None
                if text:
                    results.append({"rn": rn, "section": "Tatbestand", "text": text})

            # Entscheidungsgründe: akn:decision
            for hc in root.findall('.//akn:decision//akn:hcontainer[@name="randnummer"]', ns):
                num_el = hc.find('akn:num', ns)
                content_el = hc.find('akn:content', ns)
                text = ''.join((content_el.itertext() if content_el is not None else [])).strip()
                rn2: Optional[int] = None
                if num_el is not None and (num_el.text or "").strip():
                    try:
                        rn2 = int((num_el.text or "").strip())
                    except Exception:
                        rn2 = None
                if text:
                    results.append({"rn": rn2, "section": "Entscheidungsgründe", "text": text})

            section_order = {"Tatbestand": 0, "Entscheidungsgründe": 1}
            results.sort(key=lambda r: (section_order.get(r.get("section"), 99), r.get("rn") if isinstance(r.get("rn"), int) else 1_000_000))
        except Exception as e:
            self.logger.error(f"Failed to parse Randnummern XML: {e}")
        return results

    @staticmethod
    def sanitize_filename(name: str) -> str:
        s = re.sub(r'[<>:"/\\|?*]', '_', str(name))
        s = re.sub(r"\s+", " ", s).strip()
        return s[:200] if len(s) > 200 else s

    # Note: we intentionally omit extra "Rechtliche Bezüge" sections in Markdown output.

    def decision_to_markdown(self, decision: Dict[str, Any]) -> str:
        parts: List[str] = []

        title = decision.get("headline") or decision.get("title") or "Entscheidung"
        parts.append(f"# {title}\n\n")

        # Metadata
        parts.append("## Metadaten\n\n")
        court = decision.get("courtName") or ""
        date = decision.get("decisionDate") or ""
        file_numbers = decision.get("fileNumbers") or []
        doc_type = decision.get("documentType") or ""
        ecli = decision.get("ecli") or ""
        judicial_body = decision.get("judicialBody") or ""
        if court:
            parts.append(f"**Gericht:** {court}\n")
        if date:
            parts.append(f"**Datum:** {date}\n")
        if file_numbers:
            parts.append(f"**Aktenzeichen:** {', '.join(file_numbers)}\n")
        if doc_type:
            parts.append(f"**Dokumenttyp:** {doc_type}\n")
        if judicial_body:
            parts.append(f"**Spruchkörper:** {judicial_body}\n")
        if ecli:
            parts.append(f"**ECLI:** {ecli}\n")

        # Keywords, subject areas
        if decision.get("subjectAreas"):
            parts.append(f"**Sachgebiete:** {', '.join(decision['subjectAreas'])}\n")
        if decision.get("keywords"):
            kws = decision["keywords"]
            parts.append(f"**Schlagwörter:** {', '.join(kws) if isinstance(kws, list) else str(kws)}\n")

        parts.append("\n")

        # Basic sections from metadata (fallbacks)
        content_sections = [
            ("guidingPrinciple", "Leitsatz"),
            ("headnote", "Kopfnote"),
            ("otherHeadnote", "Weitere Kopfnote"),
            ("tenor", "Tenor"),
            ("caseFacts", "Sachverhalt"),
        ]
        randnummern = decision.get("randnummern") or []
        has_tatbestand_xml = any(r.get("section") == "Tatbestand" for r in randnummern)
        for field, title_de in content_sections:
            if field == "caseFacts" and has_tatbestand_xml:
                continue
            val = decision.get(field)
            if val and str(val).strip():
                txt = re.sub(r"\s+", " ", str(val)).strip()
                parts.append(f"## {title_de}\n\n{txt}\n\n")

        # XML Tatbestand
        if randnummern:
            tatbestand = [r for r in randnummern if r.get("section") == "Tatbestand"]
            if tatbestand:
                parts.append("## Tatbestand\n\n")
                for r in tatbestand:
                    rn = r.get("rn")
                    txt = re.sub(r"\s+", " ", r.get("text", "")).strip()
                    parts.append((f"Rn. {rn}: " if rn is not None else "") + txt + "\n\n")
                # Omit additional reference aggregation section by request.

        # Entscheidungsgründe (prefer XML Randnummern, fallback to decisionGrounds field)
        egr = [r for r in randnummern if r.get("section") == "Entscheidungsgründe"] if randnummern else []
        if egr:
            parts.append("## Entscheidungsgründe\n\n")
            for r in egr:
                rn = r.get("rn")
                txt = re.sub(r"\s+", " ", r.get("text", "")).strip()
                parts.append((f"Rn. {rn}: " if rn is not None else "") + txt + "\n\n")
            # Omit additional reference aggregation section by request.
        else:
            dg = decision.get("decisionGrounds")
            if dg and str(dg).strip():
                txt = re.sub(r"\s+", " ", str(dg)).strip()
                parts.append(f"## Entscheidungsgründe\n\n{txt}\n\n")
                # Omit additional reference aggregation section by request.

        # Footer
        parts.append("---\n\n")
        parts.append(f"*Abgerufen am: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n")
        decision_id = (decision.get("@id", "").split("/")[-1]) or decision.get("documentNumber", "") or ""
        if decision_id:
            parts.append(f"*Quelle: {self.base_url}/v1/case-law/{decision_id}*\n")
        return "".join(parts)

    def save_decision_markdown(self, decision: Dict[str, Any]) -> None:
        court = decision.get("courtName", "Unknown")
        date = decision.get("decisionDate", "Unknown")
        file_number = (
            decision.get("fileNumbers", [decision.get("documentNumber", "Unknown")])[0]
            if decision.get("fileNumbers")
            else decision.get("documentNumber", "Unknown")
        )
        filename = self.sanitize_filename(f"{date}_{court}_{file_number}.md")

        # Year
        year = "Unknown"
        if date and date != "Unknown":
            try:
                year = str(date.split("-")[0])
            except Exception:
                year = "Unknown"
        year_dir = self.output_dir / year
        year_dir.mkdir(parents=True, exist_ok=True)
        path = year_dir / filename

        md = self.decision_to_markdown(decision)
        try:
            path.write_text(md, encoding="utf-8")
            self.logger.info(f"Saved: {path}")
        except Exception as e:
            self.logger.error(f"Failed to save {path}: {e}")

    def scrape_all_decisions(
        self,
        max_pages: Optional[int] = None,
        court_filter: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        search_term: Optional[str] = None,
        courts: Optional[List[str]] = None,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        by_court: bool = False,
    ) -> None:
        """Scrape decisions segmented by court and year to maximize coverage.

        Parameters:
        - max_pages: Optional cap on number of pagination steps (debug/testing)
        - court_filter: If provided, limit to this court only (overrides `courts` list)
        - date_from/date_to: If provided together, scrape this exact range (per court)
        - search_term: Optional query filter
        - courts: Optional list of court names to segment by. If omitted, a default list
          of federal courts is used: ["BVerfG","BGH","BVerwG","BFH","BAG","BSG"].
        - year_from/year_to: Year boundaries for segmentation when date_from/to not provided.
        """
        self.logger.info("Starting to scrape all court decisions (segmented by court and year)...")
        total = 0
        seen_ids: set[str] = set()

        # Helper to normalize 'member' list into decision dicts
        def normalize_members(data_obj: Dict[str, Any]) -> List[Dict[str, Any]]:
            out: List[Dict[str, Any]] = []
            for m in data_obj.get("member", []) or []:
                if isinstance(m, dict):
                    if m.get("item") and isinstance(m.get("item"), dict):
                        out.append(m.get("item"))
                    else:
                        out.append(m)
            return out

        # Follow Hydra pagination via view.next
        def paginate_and_process(initial_data: Dict[str, Any]) -> int:
            """Paginate by incrementing pageIndex while preserving filters.

            The API's hydra view.next links drop the original query params (dateFrom/dateTo, court),
            so we cannot rely on them. Instead, we re-issue get_decisions_list() with the same
            court/date/search params and increment pageIndex until no members are returned.
            """
            nonlocal seen_ids
            processed = 0

            # Determine totalItems and compute an upper bound on pages (defensive)
            total_items = initial_data.get("totalItems") if isinstance(initial_data, dict) else None
            page_size = 100
            max_page_index = (int(total_items) // page_size + 2) if isinstance(total_items, int) else 100000

            page_idx = 0
            while page_idx < max_page_index:
                data_page = self.get_decisions_list(
                    page=page_idx,
                    size=page_size,
                    court=court_filter,
                    date_from=date_from,
                    date_to=date_to,
                    search_term=search_term,
                    sort="-date",
                ) if page_idx != 0 else initial_data

                if not data_page:
                    break

                decisions = normalize_members(data_page)
                if not decisions:
                    break

                for item in decisions:
                    raw_id = item.get("@id", "")
                    decision_id = raw_id.split("/")[-1] if raw_id else ""
                    if not decision_id or decision_id in seen_ids:
                        continue
                    seen_ids.add(decision_id)

                    detail = self.get_decision_metadata(decision_id) or {}
                    if detail:
                        item.update(detail)

                    xml_text = self.get_decision_xml(decision_id)
                    if xml_text:
                        item["randnummern"] = self.extract_randnummern(xml_text)

                    self.save_decision_markdown(item)
                    processed += 1

                # Stop if we've reached max_pages (per-page responses) if specified
                if max_pages is not None:
                    nonlocal_pages[0] += 1
                    if nonlocal_pages[0] >= max_pages:
                        break

                page_idx += 1
            return processed

        # To avoid the 10k window, segment by date range recursively until totalItems < 10000
        def process_date_range(start_date: Optional[str], end_date: Optional[str]) -> int:
            # Prepare initial request for this segment
            data0 = self.get_decisions_list(
                page=0,
                size=100,
                court=court_filter,
                date_from=start_date,
                date_to=end_date,
                search_term=search_term,
                sort="-date",
            )
            if not data0:
                return 0

            total_items = data0.get("totalItems") if isinstance(data0, dict) else None
            if isinstance(total_items, int) and total_items >= 10000:
                # Split the date range
                # Determine concrete date bounds
                fmt = "%Y-%m-%d"
                today = datetime.utcnow().strftime(fmt)
                sd = start_date or "1900-01-01"
                ed = end_date or today
                try:
                    dt_sd = datetime.strptime(sd, fmt)
                    dt_ed = datetime.strptime(ed, fmt)
                except Exception:
                    # Fallback: if parsing fails, split by year heuristically
                    try:
                        year_mid = (int(sd[:4]) + int(ed[:4])) // 2
                        left_to = f"{year_mid}-12-31"
                        right_from = f"{year_mid+1}-01-01"
                        return process_date_range(sd, left_to) + process_date_range(right_from, ed)
                    except Exception:
                        self.logger.warning("Failed to parse dates for splitting; falling back to year-wise split")
                        return 0

                if dt_sd >= dt_ed:
                    # Nothing to split
                    return paginate_and_process(data0)

                mid_ts = dt_sd.timestamp() + (dt_ed.timestamp() - dt_sd.timestamp()) / 2.0
                mid_dt = datetime.fromtimestamp(mid_ts)
                mid_date = mid_dt.strftime(fmt)
                # Avoid infinite loops on same-day ranges
                if mid_date == sd:
                    left_to = sd
                    right_from = (dt_sd.replace() if False else dt_sd).strftime(fmt)  # no-op; handled below
                    # Force right range to next day where possible
                    try:
                        from datetime import timedelta
                        right_from = (dt_sd + timedelta(days=1)).strftime(fmt)
                    except Exception:
                        right_from = sd
                    return process_date_range(sd, left_to) + process_date_range(right_from, ed)

                # Process both halves
                return process_date_range(sd, mid_date) + process_date_range(mid_date, ed)
            else:
                # Safe to paginate within this segment
                return paginate_and_process(data0)

        nonlocal_pages = [0]  # mutable counter for max_pages handling inside closure

        # Determine segmentation scope
        from datetime import datetime as _dt, timezone as _tz
        # Use timezone-aware current year to avoid deprecation warnings
        now_year = int(_dt.now(_tz.utc).strftime("%Y"))
        seg_year_from = year_from if isinstance(year_from, int) else 1950
        seg_year_to = year_to if isinstance(year_to, int) else now_year

        # Normalize reversed ranges
        if seg_year_from > seg_year_to:
            self.logger.warning(
                f"year-from ({seg_year_from}) is greater than year-to ({seg_year_to}); swapping the values"
            )
            seg_year_from, seg_year_to = seg_year_to, seg_year_from

        # Build court list (only if by_court enabled or an explicit court filter is provided)
        default_courts = ["BVerfG", "BGH", "BVerwG", "BFH", "BAG", "BSG"]
        courts_to_use: List[Optional[str]] = []
        if court_filter:
            courts_to_use = [court_filter]
        elif courts:
            courts_to_use = courts
        elif by_court:
            courts_to_use = default_courts

        # If explicit date range provided, honor it. If no court filters are specified,
        # run a single segment without a court filter to include ALL courts.
        if date_from and date_to:
            if court_filter or (courts and len(courts) > 0) or by_court:
                for crt in courts_to_use:
                    court_filter = crt  # capture into closure
                    self.logger.info(f"Segment: court={crt or 'ALL'}, range={date_from}..{date_to}")
                    seg_count = process_date_range(date_from, date_to)
                    total += seg_count
                    self.logger.info(f"Completed segment court={crt or 'ALL'} range={date_from}..{date_to}: {seg_count} decisions")
            else:
                court_filter = None  # ensure no court filter applied
                self.logger.info(f"Segment: court=ALL, range={date_from}..{date_to}")
                seg_count = process_date_range(date_from, date_to)
                total += seg_count
                self.logger.info(f"Completed segment court=ALL range={date_from}..{date_to}: {seg_count} decisions")
        else:
            # Year-based segmentation
            if courts_to_use:
                # by-court mode (or explicit courts provided)
                for crt in courts_to_use:
                    court_filter = crt  # capture into closure
                    for yr in range(seg_year_from, seg_year_to + 1):
                        yr_from = f"{yr}-01-01"
                        yr_to = f"{yr}-12-31"
                        self.logger.info(f"Segment: court={crt or 'ALL'}, year={yr}")
                        seg_count = process_date_range(yr_from, yr_to)
                        total += seg_count
                        self.logger.info(f"Completed segment court={crt or 'ALL'} year={yr}: {seg_count} decisions")
            else:
                # No court filter: run ALL courts per year
                court_filter = None
                for yr in range(seg_year_from, seg_year_to + 1):
                    yr_from = f"{yr}-01-01"
                    yr_to = f"{yr}-12-31"
                    self.logger.info(f"Segment: court=ALL, year={yr}")
                    seg_count = process_date_range(yr_from, yr_to)
                    total += seg_count
                    self.logger.info(f"Completed segment court=ALL year={yr}: {seg_count} decisions")

        self.logger.info(f"Completed. Total decisions saved: {total}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape NEURIS case-law into Markdown by year")
    parser.add_argument("--court", dest="court", help="Single court to scrape (overrides --courts)")
    parser.add_argument("--courts", dest="courts", nargs="*", help="List of courts to scrape (defaults to federal courts)")
    parser.add_argument("--year-from", dest="year_from", type=int, help="Start year for segmentation (default 1950)")
    parser.add_argument("--year-to", dest="year_to", type=int, help="End year for segmentation (default current year)")
    parser.add_argument("--date-from", dest="date_from", help="Explicit start date YYYY-MM-DD (used with --date-to)")
    parser.add_argument("--date-to", dest="date_to", help="Explicit end date YYYY-MM-DD (used with --date-from)")
    parser.add_argument("--search", dest="search_term", help="Optional search term filter")
    parser.add_argument("--max-pages", dest="max_pages", type=int, help="Max pagination steps per segment (for testing)")

    args = parser.parse_args()

    scraper = UrteileAPIScraper()
    scraper.scrape_all_decisions(
        max_pages=args.max_pages,
        court_filter=args.court,
        date_from=args.date_from,
        date_to=args.date_to,
        search_term=args.search_term,
        courts=args.courts,
        year_from=args.year_from,
        year_to=args.year_to,
    )


if __name__ == "__main__":
    main()
