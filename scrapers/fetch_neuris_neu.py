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
        params: Dict[str, Any] = {"pageIndex": page, "size": min(size, 100)}
        if court:
            params["court"] = court
        if date_from:
            params["decisionDateFrom"] = date_from
        if date_to:
            params["decisionDateTo"] = date_to
        if search_term:
            params["searchTerm"] = search_term
        if sort:
            params["sort"] = sort
        return self._make_request("/v1/case-law", params)

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
    ) -> None:
        self.logger.info("Starting to scrape all court decisions ...")
        page = 0
        total = 0
        page_size = 100
        seen_ids: set[str] = set()

        while True:
            data = self.get_decisions_list(
                page=page,
                size=page_size,
                court=court_filter,
                date_from=date_from,
                date_to=date_to,
                search_term=search_term,
                sort="-date",
            )
            if not data:
                break
            members = data.get("member", [])
            decisions = [m.get("item", {}) for m in members if isinstance(m, dict) and m.get("item")]
            if not decisions:
                break

            for item in decisions:
                raw_id = item.get("@id", "")
                decision_id = raw_id.split("/")[-1] if raw_id else ""
                if not decision_id:
                    continue
                if decision_id in seen_ids:
                    continue
                seen_ids.add(decision_id)

                detail = self.get_decision_metadata(decision_id) or {}
                item.update(detail)

                # Fetch XML and extract Randnummern
                xml_text = self.get_decision_xml(decision_id)
                if xml_text:
                    item["randnummern"] = self.extract_randnummern(xml_text)

                self.save_decision_markdown(item)
                total += 1

            if len(decisions) < page_size:
                break
            page += 1
            if max_pages is not None and page >= max_pages:
                break

        self.logger.info(f"Completed. Total decisions saved: {total}")


def main() -> None:
    scraper = UrteileAPIScraper()
    # Fetch all pages; no filters. Adjust if needed.
    scraper.scrape_all_decisions()


if __name__ == "__main__":
    main()
