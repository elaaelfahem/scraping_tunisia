"""
Scraper for TunisiaYP (tunisiayp.com) — Tunisia Yellow Pages.

Strategy
--------
TunisiaYP renders server-side HTML. No JS rendering needed.
We use two approaches:
  1. Browse by location: GET /location/{City}  (paginated: /location/{City}/2, …)
  2. Browse by category in city: GET /category/{Category}/city:{City}

Each listing page contains `.company` cards with:
  - h3 > a  → company name + detail link
  - .address → full address text
  - .s (with .fa-phone icon) → phone number
  - .s (with .fa-calendar icon) → established year
  - .s (with .fa-globe icon)  → has website (detail page only)
  - .s (with .fa-envelope icon) → has email (detail page only)

We scrape listing pages, then optionally visit detail pages for
phone, website, email, and description.
"""

import logging
import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup, Tag

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


class TunisiaYPScraper:
    """Scraper for tunisiayp.com (Tunisia Yellow Pages).

    Uses static HTTP scraping — no browser required.
    """

    BASE_URL = "https://www.tunisiayp.com"

    def search(
        self,
        keyword: str,
        city: str,
        area: Optional[str] = None,
        max_pages: int = 5,
        enrich_details: bool = False,
    ) -> list[dict]:
        """Search for companies on TunisiaYP.

        Args:
            keyword: Business category or keyword (e.g. "Restaurants", "Information_technology").
            city: City name (e.g. "Tunis", "Sfax").
            area: Optional sub-area to filter results by address.
            max_pages: Maximum number of listing pages to scrape.
            enrich_details: If True, visit each company's detail page for extra data.

        Returns:
            List of company dicts.
        """
        results: list[dict] = []

        # Strategy 1: Try category-based URL first (most relevant for keyword searches)
        if keyword:
            category_slug = keyword.replace(" ", "_").title()
            cat_results = self._scrape_category(category_slug, city, max_pages)
            if cat_results:
                results.extend(cat_results)

        # Strategy 2: Always also scrape by location to catch companies not in category
        if not results:
            location_results = self._scrape_location(city, max_pages)
            results.extend(location_results)

        # Filter by area if specified
        if area:
            area_lower = area.lower()
            results = [
                r for r in results
                if area_lower in (r.get("address") or "").lower()
            ]

        # Optionally enrich with detail page data
        if enrich_details and results:
            results = self._enrich_results(results)

        logger.info(f"[TunisiaYP] Total results: {len(results)}")
        return results

    # ── Location-based browsing ──────────────────────────────────────────────

    def _scrape_location(self, city: str, max_pages: int) -> list[dict]:
        """Scrape /location/{City} pages."""
        results: list[dict] = []
        city_slug = city.strip().replace(" ", "_").title()

        for page_num in range(1, max_pages + 1):
            if page_num == 1:
                url = f"{self.BASE_URL}/location/{city_slug}"
            else:
                url = f"{self.BASE_URL}/location/{city_slug}/{page_num}"

            logger.info(f"[TunisiaYP] Fetching location page {page_num}: {url}")
            items = self._fetch_and_parse(url)

            if not items:
                logger.info(f"[TunisiaYP] No items on page {page_num}, stopping.")
                break

            results.extend(items)
            logger.info(f"[TunisiaYP] Page {page_num}: {len(items)} companies")
            time.sleep(1)  # Respectful delay

        return results

    # ── Category + city browsing ─────────────────────────────────────────────

    def _scrape_category(self, category: str, city: str, max_pages: int) -> list[dict]:
        """Scrape /category/{Category}/city:{City} pages."""
        results: list[dict] = []
        city_slug = city.strip().replace(" ", "_").title()

        for page_num in range(1, max_pages + 1):
            base_path = f"/category/{category}/city:{city_slug}"
            if page_num == 1:
                url = f"{self.BASE_URL}{base_path}"
            else:
                url = f"{self.BASE_URL}{base_path}/{page_num}"

            logger.info(f"[TunisiaYP] Fetching category page {page_num}: {url}")
            items = self._fetch_and_parse(url)

            if not items:
                break

            results.extend(items)
            logger.info(f"[TunisiaYP] Category page {page_num}: {len(items)} companies")
            time.sleep(1)

        return results

    # ── Core fetch + parse ───────────────────────────────────────────────────

    def _fetch_and_parse(self, url: str) -> list[dict]:
        """Fetch a page and extract company cards."""
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                logger.warning(f"[TunisiaYP] HTTP {resp.status_code} for {url}")
                return []

            soup = BeautifulSoup(resp.text, "lxml")
            return self._parse_listing_page(soup)

        except Exception as e:
            logger.error(f"[TunisiaYP] Fetch error for {url}: {e}")
            return []

    def _parse_listing_page(self, soup: BeautifulSoup) -> list[dict]:
        """Parse company cards from a TunisiaYP listing page."""
        items: list[dict] = []
        cards = soup.select("div.company")

        for card in cards:
            # Skip ad cards
            if "company_ad" in card.get("class", []):
                continue
            # Skip datahub promo cards
            if "datahub-promo" in card.get("class", []):
                continue

            item = self._parse_card(card)
            if item and item.get("name"):
                items.append(item)

        return items

    def _parse_card(self, card: Tag) -> Optional[dict]:
        """Extract data from a single .company card."""
        # Company name + detail URL
        name_el = card.select_one(".company_header h3 a")
        if not name_el:
            return None

        name = name_el.get_text(strip=True)
        if not name or len(name) < 2:
            return None

        detail_path = name_el.get("href", "")
        detail_url = f"{self.BASE_URL}{detail_path}" if detail_path else ""

        # Address
        address_el = card.select_one(".address")
        address = address_el.get_text(strip=True) if address_el else ""

        # Extract data from .s (info) spans
        phone = ""
        established = ""
        has_email = False
        has_website = False
        has_map = False

        info_divs = card.select("div.s")
        for div in info_divs:
            icon = div.select_one("i.fa")
            span = div.select_one("span")
            if not icon or not span:
                continue

            icon_classes = icon.get("class", [])
            text = span.get_text(strip=True)

            if "fa-phone" in icon_classes:
                phone = text
            elif "fa-calendar" in icon_classes:
                established = text
            elif "fa-envelope" in icon_classes:
                has_email = True
            elif "fa-globe" in icon_classes:
                has_website = True
            elif "fa-map-marker" in icon_classes:
                has_map = True

        # GPS coordinates from hidden map marker
        latitude = None
        longitude = None
        map_marker = card.select_one(".mapmarker")
        if map_marker:
            lat_str = map_marker.get("data-ltd", "")
            lng_str = map_marker.get("data-lng", "")
            try:
                latitude = float(lat_str) if lat_str else None
                longitude = float(lng_str) if lng_str else None
            except ValueError:
                pass

        return {
            "name": name,
            "address": address,
            "phone": phone,
            "established": established,
            "detail_url": detail_url,
            "has_email": has_email,
            "has_website": has_website,
            "latitude": latitude,
            "longitude": longitude,
            "source": "tunisiayp",
        }

    # ── Detail page enrichment ───────────────────────────────────────────────

    def _enrich_results(self, results: list[dict]) -> list[dict]:
        """Visit each company detail page to get email, website, description."""
        enriched: list[dict] = []

        for i, item in enumerate(results):
            detail_url = item.get("detail_url", "")
            if not detail_url:
                enriched.append(item)
                continue

            try:
                logger.info(f"[TunisiaYP] Enriching [{i+1}/{len(results)}] {item['name']}")
                resp = requests.get(detail_url, headers=HEADERS, timeout=15)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "lxml")
                    extra = self._parse_detail_page(soup)
                    item.update(extra)
                time.sleep(0.5)
            except Exception as e:
                logger.debug(f"[TunisiaYP] Detail enrichment failed for {item['name']}: {e}")

            enriched.append(item)

        return enriched

    def _parse_detail_page(self, soup: BeautifulSoup) -> dict:
        """Extract additional fields from company detail page."""
        extra: dict = {}

        # Website link
        website_el = soup.select_one("a[data-act='website']")
        if website_el:
            extra["website"] = website_el.get("href", "")

        # Email (usually obfuscated or behind login, but try)
        email_el = soup.select_one("a[data-act='email'], a[href^='mailto:']")
        if email_el:
            href = email_el.get("href", "")
            if href.startswith("mailto:"):
                extra["email"] = href.replace("mailto:", "")

        # Description
        desc_el = soup.select_one(".company_description, .description, #company_description")
        if desc_el:
            extra["description"] = desc_el.get_text(strip=True)

        # Categories / keywords
        cats = []
        for cat_el in soup.select(".company_categories a, .keywords a"):
            cats.append(cat_el.get_text(strip=True))
        if cats:
            extra["categories"] = ", ".join(cats)

        # Social media links
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href.startswith("http"):
                continue
            if "facebook.com" in href and not extra.get("facebook_url"):
                if not any(x in href for x in ["/sharer", "/share", "/dialog"]):
                    extra["facebook_url"] = href
            elif "linkedin.com" in href and not extra.get("linkedin_url"):
                if "/company/" in href or "/in/" in href:
                    extra["linkedin_url"] = href

        return extra


# ── Standalone test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    scraper = TunisiaYPScraper()
    results = scraper.search("Information_technology", city="Tunis", max_pages=2)
    print(f"\n=== {len(results)} companies found ===")
    for r in results[:10]:
        print(json.dumps(r, ensure_ascii=False, indent=2))
