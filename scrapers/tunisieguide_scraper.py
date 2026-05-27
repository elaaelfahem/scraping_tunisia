"""
Scraper for TunisieGuide (tunisieguide.com) — GeoDirectory WordPress business directory.

Search URL: /recherche/?geodir_search=1&stype=gd_place&s={keyword}&snear={city}
Company card: div.geodir-post.gd_place
Pagination: ?paged={n}
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
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

BASE_URL = "https://www.tunisieguide.com"
SEARCH_URL = f"{BASE_URL}/recherche/"


class TunisieGuideScraper:
    """Scraper for tunisieguide.com (GeoDirectory-powered)."""

    def search(
        self,
        keyword: str,
        city: str,
        area: Optional[str] = None,
        max_pages: int = 5,
    ) -> list[dict]:
        results: list[dict] = []
        session = requests.Session()
        session.headers.update(HEADERS)

        try:
            results = self._scrape_pages(keyword, city, max_pages, session)
            if results:
                results = self._enrich_results(results, session)
        except Exception as e:
            logger.error(f"[TunisieGuide] Error: {e}")

        if area:
            area_lower = area.lower()
            results = [r for r in results if area_lower in (r.get("address") or "").lower()]

        logger.info(f"[TunisieGuide] Total: {len(results)}")
        return results

    def _scrape_pages(self, keyword: str, city: str, max_pages: int, session: requests.Session) -> list[dict]:
        results: list[dict] = []
        base_params = {
            "geodir_search": "1",
            "stype": "gd_place",
            "s": keyword,
            "snear": city,
        }

        for page_num in range(1, max_pages + 1):
            params = dict(base_params)
            if page_num > 1:
                params["paged"] = page_num

            logger.info(f"[TunisieGuide] Search page {page_num}")
            try:
                resp = session.get(SEARCH_URL, params=params, timeout=15)
                if resp.status_code != 200:
                    break
                soup = BeautifulSoup(resp.text, "lxml")
                items = self._parse_page(soup)
                if not items:
                    break
                results.extend(items)
                time.sleep(1)
                if not self._has_next_page(soup, page_num):
                    break
            except Exception as e:
                logger.warning(f"[TunisieGuide] Page {page_num} error: {e}")
                break

        return results

    def _parse_page(self, soup: BeautifulSoup) -> list[dict]:
        # GeoDirectory cards
        cards = soup.select("div.geodir-post.gd_place, div.gd_place, .geodir-post")
        if not cards:
            return []

        items = []
        for card in cards:
            # Title
            name_el = card.select_one("h2.geodir-entry-title a, h3.geodir-entry-title a, .geodir-entry-title a")
            if not name_el:
                continue
            name = name_el.get_text(strip=True)
            if not name or len(name) < 2:
                continue
            detail_url = name_el.get("href", "")

            # Category/sector
            sector = ""
            for sel in [".geodir_post_meta [class*=category] a", ".gd-category a", ".cat-links a", "[class*='category'] a"]:
                el = card.select_one(sel)
                if el:
                    sector = el.get_text(strip=True)
                    break

            # Address/location — GeoDirectory stores address in various meta fields
            address = ""
            for sel in [".geodir-field-address", ".geodir-field-city", "[class*='geodir-field-address']", ".gd-location"]:
                el = card.select_one(sel)
                if el:
                    address = el.get_text(separator=" ", strip=True)
                    break

            if not address:
                # Pull city from content text (e.g. "à Sfax à Sfax" pattern)
                content_el = card.select_one(".geodir-post-content-container, .card-body")
                if content_el:
                    text = content_el.get_text()
                    m = re.search(r"à\s+(\w[\w\s]+)", text)
                    if m:
                        address = m.group(1).strip()

            # Phone
            phone = ""
            phone_el = card.select_one("a[href^='tel:'], .geodir-field-phone a, [class*='phone'] a")
            if phone_el:
                phone = phone_el.get("href", "").replace("tel:", "") or phone_el.get_text(strip=True)

            # Website
            website = ""
            for sel in [".geodir-field-website a", "a[href^='http']:not([href*='tunisieguide'])"]:
                el = card.select_one(sel)
                if el:
                    href = el.get("href", "")
                    if href.startswith("http") and "tunisieguide" not in href:
                        website = href
                        break

            items.append({
                "name": name,
                "sector": sector,
                "address": address,
                "phone": phone,
                "website": website,
                "facebook_url": "",
                "linkedin_url": "",
                "detail_url": detail_url,
                "source": "tunisieguide",
            })
        return items

    def _enrich_results(self, results: list[dict], session: requests.Session) -> list[dict]:
        """Visit GeoDirectory detail pages to extract website and social links."""
        for i, item in enumerate(results):
            detail_url = item.get("detail_url", "")
            if not detail_url:
                continue
            try:
                logger.info(f"[TunisieGuide] Enriching [{i+1}/{len(results)}] {item['name']}")
                resp = session.get(detail_url, timeout=15)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "lxml")

                    if not item.get("website"):
                        for sel in [".geodir-field-website a", ".gd-website a",
                                    "a[href^='http']:not([href*='tunisieguide'])"]:
                            el = soup.select_one(sel)
                            if el:
                                href = el.get("href", "")
                                if href.startswith("http") and "tunisieguide" not in href:
                                    item["website"] = href
                                    break

                    for a in soup.find_all("a", href=True):
                        href = a["href"].strip()
                        if not href.startswith("http"):
                            continue
                        if "facebook.com" in href and not item.get("facebook_url"):
                            if not any(x in href for x in ["/sharer", "/share", "/dialog"]):
                                item["facebook_url"] = href
                        elif "linkedin.com" in href and not item.get("linkedin_url"):
                            if "/company/" in href or "/in/" in href:
                                item["linkedin_url"] = href
                time.sleep(0.5)
            except Exception as e:
                logger.debug(f"[TunisieGuide] Enrichment failed for {item['name']}: {e}")
        return results

    def _has_next_page(self, soup: BeautifulSoup, current_page: int) -> bool:
        next_el = soup.select_one("a.next, a[rel='next'], .geodir-paging-next a")
        return bool(next_el)


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    scraper = TunisieGuideScraper()
    results = scraper.search("informatique", city="Tunis")
    print(f"\n=== {len(results)} companies found ===")
    for r in results[:5]:
        print(json.dumps(r, ensure_ascii=False, indent=2))
