"""
Scraper for a specific Scribd document containing a Tunisian company list.

Document: https://fr.scribd.com/document/659246391/Liste-des-Entrprises

Scribd renders content via JavaScript and requires authentication for full access.
This scraper attempts to:
1. Fetch the document page and extract any JSON data embedded in the page scripts.
2. Parse visible preview text from the document viewer.
3. Return structured company records from whatever text is accessible.

Because this is a static document (not a live searchable directory), the
`search()` method fetches all accessible content and then filters by keyword/city.
"""

import json
import logging
import re
from typing import Optional
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

SCRIBD_URL = "https://fr.scribd.com/document/659246391/Liste-des-Entrprises"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class ScribdScraper:
    """Fetches a Scribd document's accessible preview text and extracts company records."""

    async def search(
        self,
        keyword: str,
        city: str,
        area: Optional[str] = None,
        max_pages: int = 1,  # Not paginated — single document
    ) -> list[dict]:
        raw_entries = await self._fetch_document()

        if not raw_entries:
            logger.warning(
                "[Scribd] Could not extract content from Scribd document. "
                "Scribd requires authentication for full access. "
                "Consider exporting the PDF manually and using the import tool."
            )
            return []

        # Filter by city and keyword
        city_lower = city.lower()
        kw_lower = keyword.lower()
        results = []
        for entry in raw_entries:
            name = (entry.get("name") or "").lower()
            address = (entry.get("address") or "").lower()
            sector = (entry.get("sector") or "").lower()

            if city_lower and city_lower not in address and city_lower not in name:
                continue
            if kw_lower and kw_lower not in "all" and kw_lower not in name and kw_lower not in sector:
                pass  # Keep entry even if keyword doesn't match — document is a general list

            if area and area.lower() not in address:
                continue

            results.append(entry)

        logger.info(f"[Scribd] Accessible entries: {len(raw_entries)}, filtered: {len(results)}")
        return results

    async def _fetch_document(self) -> list[dict]:
        """Attempt to extract company data from the Scribd document page using async Playwright."""
        entries: list[dict] = []
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("[Scribd] Playwright is not installed. Skipping.")
            return entries

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    locale="fr-FR"
                )
                page = await context.new_page()
                logger.info(f"[Scribd] Navigating to {SCRIBD_URL} via Playwright")
                await page.goto(SCRIBD_URL, wait_until="load", timeout=30000)
                await page.wait_for_timeout(5000)

                html = await page.content()
                soup = BeautifulSoup(html, "lxml")

                # Strategy 2: Extract visible text from document viewer elements
                entries = self._extract_from_viewer(soup)
                if not entries:
                    # Strategy 3: Parse any plain-text content blocks
                    entries = self._extract_from_text(soup)

                await browser.close()
        except Exception as e:
            logger.error(f"[Scribd] Playwright fetch error: {e}")

        return entries

    def _extract_from_json_scripts(self, soup: BeautifulSoup) -> list[dict]:
        """Look for embedded JSON in <script> tags that contains document text."""
        entries: list[dict] = []
        for script in soup.find_all("script"):
            src = script.string or ""
            if not src or len(src) < 100:
                continue

            # Scribd embeds document text in various JSON structures
            for pattern in [
                r'"text"\s*:\s*"([^"]{20,})"',
                r'"content"\s*:\s*"([^"]{20,})"',
                r'"page_text"\s*:\s*"([^"]{20,})"',
            ]:
                matches = re.findall(pattern, src)
                for m in matches:
                    text = m.replace("\\n", "\n").replace("\\r", "").strip()
                    parsed = self._parse_text_block(text)
                    entries.extend(parsed)

            if entries:
                break

        return entries

    def _extract_from_viewer(self, soup: BeautifulSoup) -> list[dict]:
        """Extract text from the document viewer's text layers."""
        entries: list[dict] = []
        text_blocks = []

        for sel in [".text_layer", ".page-text", ".textLayer", "[class*='page']", ".abspos"]:
            elements = soup.select(sel)
            for el in elements:
                t = el.get_text(separator="\n", strip=True)
                if t:
                    text_blocks.append(t)

        full_text = "\n".join(text_blocks)
        if full_text.strip():
            entries = self._parse_text_block(full_text)

        return entries

    def _extract_from_text(self, soup: BeautifulSoup) -> list[dict]:
        """Fall back to any paragraph or div text content."""
        entries: list[dict] = []
        body = soup.find("body")
        if not body:
            return entries

        text = body.get_text(separator="\n", strip=True)
        if len(text) > 200:
            entries = self._parse_text_block(text)

        return entries

    def _parse_text_block(self, text: str) -> list[dict]:
        """Parse raw text to find company name / phone / address patterns.

        Typical format in Tunisian company lists:
            Company Name
            Address, City, ZIP
            Tel: +216 XX XXX XXX
        """
        entries: list[dict] = []
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

        i = 0
        while i < len(lines):
            line = lines[i]

            # Skip very short or obviously non-company lines
            if len(line) < 4 or len(line) > 200:
                i += 1
                continue

            # Heuristic: a company name is a reasonably-capitalized short line
            # that doesn't look like a header or phone number
            is_likely_company = (
                not re.match(r"^\d", line)  # doesn't start with digit
                and not re.match(r"^[+\-\(\)]", line)  # not phone-like
                and len(line.split()) >= 2  # at least 2 words
                and len(line) < 100
                and not re.match(r"^(Page|Liste|Entreprise|Société|Tunisi|www\.|http)", line, re.I)
            )

            if not is_likely_company:
                i += 1
                continue

            name = line
            address = ""
            phone = ""
            email = ""
            sector = ""

            # Look at the next few lines for associated data
            for j in range(i + 1, min(i + 5, len(lines))):
                nxt = lines[j]
                if re.search(r"(\+216|216|\b[24579]\d[\s.-]?\d{3}[\s.-]?\d{3})", nxt):
                    phone_match = re.search(r"(\+?216\s*)?[24579]\d[\s.-]?\d{3}[\s.-]?\d{3}", nxt)
                    if phone_match:
                        phone = phone_match.group(0).strip()
                elif re.search(r"@", nxt):
                    email_match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", nxt)
                    if email_match:
                        email = email_match.group(0)
                elif re.search(r"\d{4}", nxt) or re.search(r"(Tunis|Sfax|Sousse|Monastir|Bizerte|Nabeul)", nxt, re.I):
                    if not address:
                        address = nxt

            if name:
                entries.append({
                    "name": name,
                    "address": address,
                    "phone": phone,
                    "email": email,
                    "sector": sector,
                    "source": "scribd",
                })

            i += 1

        return entries


if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    scraper = ScribdScraper()
    results = asyncio.run(scraper.search("", city="Tunis"))
    print(f"\n=== {len(results)} entries found ===")
    for r in results[:5]:
        print(json.dumps(r, ensure_ascii=False, indent=2))
