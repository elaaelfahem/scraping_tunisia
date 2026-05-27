"""
Scraper for B2BMap (b2bmap.com) — Tunisia business listings.

Strategy
--------
1. Fetch search results from:
   https://b2bmap.com/tunisia/companies?q={keyword}&city={city}
2. Parse cards with class `li.member-item`.
3. Extract name, sector, detail URL, and contact URL.
4. Fetch each company's contact-info page to parse full address, zip, phone/whatsapp (even if masked), and email.
"""

import logging
import re
import time
from typing import Optional
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class B2BMapScraper:
    """Scraper for b2bmap.com/tunisia/companies."""

    BASE_URL = "https://b2bmap.com"
    TUNISIA_URL = "https://b2bmap.com/tunisia/companies"

    def search(
        self,
        keyword: str,
        city: str,
        area: Optional[str] = None,
        max_pages: int = 5,
    ) -> list[dict]:
        """Search B2BMap for companies.

        Args:
            keyword: Business type or company name keyword.
            city: City name.
            area: Optional sub-area filter.
            max_pages: Maximum result pages to scrape.

        Returns:
            List of company dicts.
        """
        results: list[dict] = []
        session = requests.Session()
        session.headers.update(HEADERS)

        try:
            results = self._scrape_pages(keyword, city, max_pages, session)
        except Exception as e:
            logger.error(f"[B2BMap] Search error: {e}")

        # Local filtering by city, area, and keyword
        filtered: list[dict] = []
        city_lower = city.lower()
        area_lower = area.lower() if area else None
        kw_lower = keyword.lower()

        for r in results:
            name = (r.get("name") or "").lower()
            address = (r.get("address") or "").lower()
            sector = (r.get("sector") or "").lower()
            desc = (r.get("description") or "").lower()

            # Check if city matches (either in address or name)
            if city_lower not in address and city_lower not in (r.get("state") or "").lower():
                # Allow fallback if no city matches anywhere but it was listed on the page
                pass

            # Check if area matches (if specified)
            if area_lower and area_lower not in address:
                continue

            # Check if keyword matches name, sector, or description
            if (kw_lower not in name and 
                kw_lower not in sector and 
                kw_lower not in desc):
                # Don't filter out if name or sector matches partially
                pass

            filtered.append(r)

        logger.info(f"[B2BMap] Total results: {len(filtered)}")
        return filtered

    def _build_url(self, keyword: str, city: str, page: int = 1) -> str:
        # URL pattern: /tunisia/companies?q={keyword}&city={city}&page={page}
        if page == 1:
            return f"{self.TUNISIA_URL}?q={keyword}&city={city}"
        return f"{self.TUNISIA_URL}?q={keyword}&city={city}&page={page}"

    def _scrape_pages(self, keyword: str, city: str, max_pages: int, session: requests.Session) -> list[dict]:
        results: list[dict] = []

        for page_num in range(1, max_pages + 1):
            url = self._build_url(keyword, city, page_num)
            logger.info(f"[B2BMap] Fetching page {page_num}: {url}")

            try:
                resp = session.get(url, timeout=15)
                if resp.status_code != 200:
                    logger.warning(f"[B2BMap] HTTP {resp.status_code} on page {page_num}")
                    break

                soup = BeautifulSoup(resp.text, "lxml")
                cards = soup.select("li.member-item")
                if not cards:
                    break

                logger.info(f"[B2BMap] Page {page_num} has {len(cards)} card elements")

                for card in cards:
                    link_el = card.select_one(".directory-link")
                    if not link_el:
                        continue
                    
                    name = link_el.get_text(strip=True)
                    detail_url = link_el.get("href", "")
                    if not detail_url.startswith("http"):
                        detail_url = f"{self.BASE_URL}{detail_url}"

                    # Sector
                    sector = ""
                    category_el = card.find("a", href=re.compile(r"/business-directory/"))
                    if category_el:
                        sector = category_el.get_text(strip=True)

                    # Short description
                    description = ""
                    desc_el = card.select_one(".details-short-text")
                    if desc_el:
                        description = desc_el.get_text(strip=True)

                    # Contact-info URL
                    contact_url = ""
                    contact_link = card.find("a", href=re.compile(r"/contact-info$"))
                    if contact_link:
                        contact_url = contact_link.get("href", "")
                        if not contact_url.startswith("http"):
                            contact_url = f"{self.BASE_URL}{contact_url}"

                    # Fetch details from contact-info page
                    details = {}
                    if contact_url:
                        details = self._scrape_contact_details(contact_url, session)
                    elif detail_url:
                        details = self._scrape_contact_details(detail_url, session)

                    results.append({
                        "name": name,
                        "sector": sector,
                        "description": description,
                        "address": details.get("address") or "",
                        "zip_code": details.get("zip_code") or "",
                        "state": details.get("state") or "",
                        "phone": details.get("phone") or "",
                        "email": details.get("email") or "",
                        "website": details.get("website") or "",
                        "detail_url": detail_url,
                        "source": "b2bmap",
                    })

                    # Small delay between detail fetches
                    time.sleep(1)

                # Check if there is a next page
                if not self._has_next_page(soup, page_num):
                    break

            except Exception as e:
                logger.error(f"[B2BMap] Page {page_num} error: {e}")
                break

        return results

    def _scrape_contact_details(self, url: str, session: requests.Session) -> dict:
        """Fetch the contact/profile page and parse full address, phone, etc."""
        data = {
            "address": "",
            "phone": "",
            "email": "",
            "website": "",
            "state": "",
            "zip_code": "",
        }
        try:
            logger.info(f"[B2BMap] Fetching details from: {url}")
            resp = session.get(url, timeout=15)
            if resp.status_code != 200:
                return data

            soup = BeautifulSoup(resp.text, "lxml")

            # Try to parse the table/row structure first
            rows = soup.select(".d-md-table-row")
            for row in rows:
                cells = row.select(".d-md-table-cell")
                if len(cells) >= 2:
                    label = cells[0].get_text(strip=True).lower().replace(":", "").strip()
                    val = cells[1].get_text(strip=True)
                    if "address" in label:
                        data["address"] = val
                    elif "phone" in label or "whatsapp" in label or "mobile" in label:
                        if not data["phone"]:
                            data["phone"] = val
                    elif "email" in label:
                        data["email"] = val
                    elif "website" in label:
                        data["website"] = val
                    elif "zip code" in label or "zip" in label:
                        data["zip_code"] = val
                    elif "state" in label:
                        data["state"] = val

            # Also check JSON-LD as a fallback
            script = soup.find("script", type="application/ld+json")
            if script and script.string:
                try:
                    import json
                    ld = json.loads(script.string.strip())
                    if isinstance(ld, dict):
                        # Try to get phone from JSON-LD (sometimes not masked)
                        ld_phone = ld.get("telephone") or ""
                        if ld_phone and not self._is_masked(ld_phone) and not data["phone"]:
                            data["phone"] = ld_phone

                        addr = ld.get("address")
                        if isinstance(addr, dict):
                            street = addr.get("streetAddress") or ""
                            locality = addr.get("addressLocality") or ""
                            region = addr.get("addressRegion") or ""
                            country = addr.get("addressCountry") or ""
                            parts = [p for p in [street, locality, region, country] if p]
                            if not data["address"]:
                                data["address"] = ", ".join(parts)
                            if not data["state"]:
                                data["state"] = region
                            if not data["zip_code"]:
                                data["zip_code"] = addr.get("postalCode") or ""
                except Exception:
                    pass

            # Clean masked values — B2BMap replaces real data with 'xxxxx' for
            # non-authenticated users. Discard these at the source.
            data["phone"] = "" if self._is_masked(data["phone"]) else data["phone"]
            data["email"] = "" if self._is_masked(data["email"]) else data["email"]
            data["website"] = "" if self._is_masked(data["website"]) else data["website"]

        except Exception as e:
            logger.warning(f"[B2BMap] Error fetching details from {url}: {e}")

        return data

    @staticmethod
    def _is_masked(value: str) -> bool:
        """Check if a value is a masked placeholder like 'xxxxx'."""
        if not value:
            return False
        cleaned = value.strip().lower()
        # Common masks: xxxxx, *****, #####, n/a, etc.
        if re.match(r'^[x\*#\.]{3,}$', cleaned):
            return True
        if cleaned in ('n/a', 'none', 'null', 'unknown', 'not available'):
            return True
        return False

    def _has_next_page(self, soup: BeautifulSoup, current_page: int) -> bool:
        """Check if pagination has a next page link."""
        pagination = soup.find("ul", class_=re.compile(r"pagination|pager", re.I))
        if pagination:
            # Look for active/current page item and check if there's a sibling after it
            active = pagination.find(["li", "span"], class_=re.compile(r"active|current", re.I))
            if active:
                next_sibling = active.find_next_sibling("li")
                if next_sibling and not next_sibling.get_text().strip().startswith("»"):
                    return True
            # Alternative: check if there's any link with class "page-link" or text containing current_page + 1
            next_links = pagination.find_all("a")
            for link in next_links:
                if str(current_page + 1) in link.get_text():
                    return True
        return False


if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    scraper = B2BMapScraper()
    results = scraper.search("Software", city="Tunis")
    print(f"\n=== {len(results)} companies found ===")
    for r in results[:5]:
        print(json.dumps(r, ensure_ascii=False, indent=2))
