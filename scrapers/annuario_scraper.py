"""
Scraper for Annuario Imprese Italia-Tunisia (annuarioimpreseitaliatunisia.com).

Base URL:  /annuario-imprese/
Filter by governorate: /governatorato/{Governorate-Name}/
Company card: div.custom-post-item
Title: h3.post-title
Data fields: <p><strong>Label:</strong> Value</p> pattern
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
    "Accept-Language": "it-IT,it;q=0.9,fr;q=0.8,en;q=0.7",
}

BASE_URL = "https://www.annuarioimpreseitaliatunisia.com"
LISTING_URL = f"{BASE_URL}/annuario-imprese/"

# Tunisian governorate names as used in the site URLs
GOUV_SLUGS: dict[str, str] = {
    "tunis":      "Tunis",
    "ariana":     "Ariana",
    "ben arous":  "Ben%20Arous",
    "manouba":    "Manouba",
    "nabeul":     "Nabeul",
    "bizerte":    "Bizerte",
    "sfax":       "Sfax",
    "sousse":     "Sousse",
    "monastir":   "Monastir",
    "mahdia":     "Mahdia",
    "kairouan":   "Kairouan",
    "jendouba":   "Jendouba",
    "zaghouan":   "Zaghouan",
    "gabes":      "Gabes",
    "medenine":   "Medenine",
}


class AnnuarioScraper:
    """Scraper for annuarioimpreseitaliatunisia.com — Italian companies in Tunisia."""

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
        gouv_slug = GOUV_SLUGS.get(city_lower, city.strip())

        try:
            # Try filtered by governorate first
            results = self._scrape_pages(gouv_slug, max_pages, session)
            if not results:
                # Fall back to full listing
                results = self._scrape_pages(None, max_pages, session)
        except Exception as e:
            logger.error(f"[Annuario] Error: {e}")

        # Filter results to matching city
        city_match = city.lower()
        results = [
            r for r in results
            if city_match in (r.get("city") or "").lower()
            or city_match in (r.get("address") or "").lower()
            or not r.get("city")
        ]

        if area:
            area_lower = area.lower()
            results = [r for r in results if area_lower in (r.get("address") or "").lower()]

        logger.info(f"[Annuario] Total: {len(results)}")
        return results

    def _scrape_pages(self, gouv_slug: Optional[str], max_pages: int, session: requests.Session) -> list[dict]:
        results: list[dict] = []
        if gouv_slug:
            base = f"{BASE_URL}/governatorato/{gouv_slug}/"
        else:
            base = LISTING_URL

        for page_num in range(1, max_pages + 1):
            url = base if page_num == 1 else f"{base}page/{page_num}/"
            logger.info(f"[Annuario] Fetching page {page_num}: {url}")
            try:
                resp = session.get(url, timeout=15)
                if resp.status_code != 200:
                    break
                soup = BeautifulSoup(resp.text, "lxml")
                items = self._parse_page(soup)
                if not items:
                    break
                results.extend(items)
                logger.info(f"[Annuario] Page {page_num}: {len(items)} items")
                time.sleep(1)
                if not self._has_next_page(soup):
                    break
            except Exception as e:
                logger.warning(f"[Annuario] Page {page_num} error: {e}")
                break
        return results

    def _parse_page(self, soup: BeautifulSoup) -> list[dict]:
        cards = soup.select("div.custom-post-item")
        if not cards:
            return []

        items = []
        for card in cards:
            name_el = card.select_one("h3.post-title")
            if not name_el:
                continue
            name = name_el.get_text(strip=True)
            if not name or len(name) < 2:
                continue

            data = self._parse_labeled_fields(card)
            items.append({
                "name": name,
                "sector": data.get("settore") or data.get("sector") or "",
                "address": data.get("indirizzo") or data.get("address") or "",
                "city": data.get("governatorato") or data.get("governorate") or "",
                "phone": data.get("telefono") or data.get("phone") or "",
                "email": data.get("email") or "",
                "website": data.get("sito") or data.get("website") or "",
                "source": "annuario_it_tn",
            })
        return items

    def _parse_labeled_fields(self, card) -> dict:
        """Parse <p><strong>Label:</strong> Value</p> pattern."""
        data: dict = {}
        for p in card.find_all("p"):
            strong = p.find("strong")
            if not strong:
                continue
            label = strong.get_text(strip=True).rstrip(":").strip().lower()
            # Remove the strong element to get just the value
            strong.extract()
            value = p.get_text(strip=True)

            # For links (phone, email, website)
            link = p.find("a") if not value else None
            if not value and link:
                value = link.get("href", "").replace("tel:", "").replace("mailto:", "")

            data[label] = value

        # Also try to get phone/email from links
        phone_link = card.select_one("a[href^='tel:']")
        if phone_link and "telefono" not in data:
            data["telefono"] = phone_link.get("href", "").replace("tel:", "")

        email_link = card.select_one("a[href^='mailto:']")
        if email_link and "email" not in data:
            data["email"] = email_link.get("href", "").replace("mailto:", "")

        # Governorate from category link
        gouv_link = card.select_one("a[href*='/governatorato/']")
        if gouv_link and "governatorato" not in data:
            data["governatorato"] = gouv_link.get_text(strip=True)

        return data

    def _has_next_page(self, soup: BeautifulSoup) -> bool:
        return bool(soup.select_one("a.next, a[rel='next'], .next-page"))


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    scraper = AnnuarioScraper()
    results = scraper.search("industrie", city="Tunis")
    print(f"\n=== {len(results)} companies found ===")
    for r in results[:5]:
        print(json.dumps(r, ensure_ascii=False, indent=2))
