"""
Scraper for PageX.tn (pagex.tn) — Tunisian business directory.

City pages: /ville/{city_id}/{city_slug}
Company cards: div.professional-card (inside col-12.professional-card)
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
    "Accept-Language": "fr-FR,fr;q=0.9,ar;q=0.8",
}

BASE_URL = "https://pagex.tn"

# Discovered city IDs from the PageX homepage
CITY_IDS: dict[str, tuple[int, str]] = {
    "tunis":           (248, "tunis"),
    "ariana":          (1,   "ariana-ville"),
    "ben arous":       (17,  "ben-arous"),
    "sfax":            (171, "sfax"),
    "sousse":          (208, "sousse-medina"),
    "nabeul":          (157, "nabeul"),
    "bizerte":         (27,  "bizerte-nord"),
    "monastir":        (208, "sousse-medina"),  # fallback
    "la marsa":        (248, "tunis"),
    "la goulette":     (234, "la-goulette"),
    "la soukra":       (4,   "la-soukra"),
    "rades":           (25,  "rades"),
    "raoued":          (6,   "raoued"),
    "le kram":         (237, "le-kram"),
    "bab el bhar":     (223, "bab-el-bhar"),
    "cite el khadra":  (225, "cite-el-khadra"),
    "hammamet":        (152, "hammamet"),
    "medenine":        (128, "midoun"),
    "menzel bourguiba":(33,  "menzel-bourguiba"),
    "tabarka":         (67,  "tabarka"),
}


class PageXScraper:
    """Scraper for pagex.tn using city-based listing pages."""

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

        city_lower = city.lower().strip()
        city_info = CITY_IDS.get(city_lower)

        if not city_info:
            # Try partial match
            for key, val in CITY_IDS.items():
                if city_lower in key or key in city_lower:
                    city_info = val
                    break

        if not city_info:
            logger.warning(f"[PageX] Unknown city: '{city}', defaulting to Tunis")
            city_info = CITY_IDS["tunis"]

        city_id, city_slug = city_info

        try:
            results = self._scrape_city(city_id, city_slug, keyword, max_pages, session)
        except Exception as e:
            logger.error(f"[PageX] Error: {e}")

        # Filter by keyword in name/sector
        if keyword and keyword.lower() not in ("all", "entreprises", "services"):
            kw_lower = keyword.lower()
            filtered = [
                r for r in results
                if kw_lower in (r.get("name") or "").lower()
                or kw_lower in (r.get("sector") or "").lower()
                or kw_lower in (r.get("description") or "").lower()
            ]
            if filtered:
                results = filtered

        if area:
            area_lower = area.lower()
            results = [r for r in results if area_lower in (r.get("address") or "").lower()]

        logger.info(f"[PageX] Total: {len(results)}")
        return results

    def _scrape_city(
        self,
        city_id: int,
        city_slug: str,
        keyword: str,
        max_pages: int,
        session: requests.Session,
    ) -> list[dict]:
        results: list[dict] = []
        for page_num in range(1, max_pages + 1):
            url = f"{BASE_URL}/ville/{city_id}/{city_slug}"
            params: dict = {}
            if page_num > 1:
                params["page"] = page_num

            logger.info(f"[PageX] Fetching city page {page_num}: {url}")
            try:
                resp = session.get(url, params=params, timeout=15)
                if resp.status_code != 200:
                    break
                soup = BeautifulSoup(resp.text, "lxml")
                items = self._parse_page(soup)
                if not items:
                    break
                results.extend(items)
                time.sleep(1)
            except Exception as e:
                logger.warning(f"[PageX] Page {page_num} error: {e}")
                break
        return results

    def _parse_page(self, soup: BeautifulSoup) -> list[dict]:
        # Each company is in a div.col-12.professional-card
        cards = soup.select(".professional-card")
        if not cards:
            return []

        seen_names: set[str] = set()
        items = []
        for card in cards:
            name_el = card.select_one("h3.card-title a")
            if not name_el:
                continue
            name = name_el.get_text(strip=True)
            if not name or name in seen_names:
                continue
            seen_names.add(name)

            detail_url = name_el.get("href", "")

            sector = ""
            cat_el = card.select_one(".cat-item .cat-name")
            if cat_el:
                sector = cat_el.get_text(strip=True)

            address = ""
            addr_el = card.select_one(".listing-one__regions")
            if addr_el:
                address = addr_el.get_text(separator=" ", strip=True)

            phone = ""
            phone_el = card.select_one(".listing-one__phone a[href^='tel:']")
            if phone_el:
                phone = phone_el.get("href", "").replace("tel:", "")

            description = ""
            desc_el = card.select_one("p.card-text")
            if desc_el:
                description = desc_el.get_text(strip=True)[:200]

            items.append({
                "name": name,
                "sector": sector,
                "address": address,
                "phone": phone,
                "description": description,
                "detail_url": detail_url,
                "source": "pagex",
            })
        return items


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    scraper = PageXScraper()
    results = scraper.search("informatique", city="Tunis")
    print(f"\n=== {len(results)} companies found ===")
    for r in results[:5]:
        print(json.dumps(r, ensure_ascii=False, indent=2))
