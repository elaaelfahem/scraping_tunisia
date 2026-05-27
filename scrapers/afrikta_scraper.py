"""
Scraper for Afrikta (afrikta.com) — African business directory, Tunisia section.

Company cards use the ACADP WordPress plugin classes:
  .acadp-card          — card container
  .acadp-title a       — company name + detail link
  .acadp-categories .acadp-terms-links a  — sector
  .acadp-locations     — address/city text
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

BASE_URL = "https://afrikta.com"
TN_LISTING = f"{BASE_URL}/fr/annuaire-des-entreprises-africaines/tunisie/"


class AfrikaScraper:
    """Scraper for afrikta.com Tunisia listings."""

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
            logger.error(f"[Afrikta] Error: {e}")

        # Filter by city
        city_lower = city.lower()
        results = [
            r for r in results
            if city_lower in (r.get("address") or "").lower()
            or city_lower in (r.get("city") or "").lower()
            or not r.get("city")
        ]

        if area:
            area_lower = area.lower()
            results = [r for r in results if area_lower in (r.get("address") or "").lower()]

        logger.info(f"[Afrikta] Total: {len(results)}")
        return results

    def _scrape_pages(self, keyword: str, city: str, max_pages: int, session: requests.Session) -> list[dict]:
        results: list[dict] = []

        candidate_urls = [
            f"{TN_LISTING}?s={keyword}",
            f"{TN_LISTING}?keyword={keyword}&location={city}",
            TN_LISTING,
        ]

        for base_url in candidate_urls:
            for page_num in range(1, max_pages + 1):
                url = base_url if page_num == 1 else f"{base_url}&pg={page_num}"
                logger.info(f"[Afrikta] Fetching page {page_num}: {url}")
                try:
                    resp = session.get(url, timeout=15)
                    if resp.status_code != 200:
                        break
                    soup = BeautifulSoup(resp.text, "lxml")
                    items = self._parse_page(soup)
                    if not items:
                        break
                    results.extend(items)
                    logger.info(f"[Afrikta] Page {page_num}: {len(items)} items")
                    time.sleep(1)
                    if not self._has_next_page(soup):
                        break
                except Exception as e:
                    logger.warning(f"[Afrikta] Error: {e}")
                    break
            if results:
                break

        return results

    def _parse_page(self, soup: BeautifulSoup) -> list[dict]:
        cards = soup.select(".acadp-card")
        if not cards:
            return []

        items = []
        for card in cards:
            # Name + detail link
            name_el = card.select_one(".acadp-title a")
            if not name_el:
                continue
            name = name_el.get_text(strip=True)
            if not name or len(name) < 2:
                continue
            detail_url = name_el.get("href", "")

            # Sector/category
            sector = ""
            cat_el = card.select_one(".acadp-categories .acadp-terms-links a")
            if cat_el:
                sector = cat_el.get_text(strip=True)

            # Location (city/address text)
            address = ""
            loc_el = card.select_one(".acadp-locations")
            if loc_el:
                address = loc_el.get_text(separator=" ", strip=True)
                # Clean leading icon characters
                address = re.sub(r"^[^\w]+", "", address).strip()

            # Phone — may not be visible without login
            phone = ""
            phone_el = card.select_one("a[href^='tel:'], .acadp-phone")
            if phone_el:
                phone = phone_el.get("href", "").replace("tel:", "") or phone_el.get_text(strip=True)

            # Website
            website = ""
            web_el = card.select_one("a[href^='http']:not([href*='afrikta'])")
            if web_el:
                website = web_el.get("href", "")

            items.append({
                "name": name,
                "sector": sector,
                "address": address,
                "phone": phone,
                "website": website,
                "facebook_url": "",
                "linkedin_url": "",
                "detail_url": detail_url,
                "source": "afrikta",
            })
        return items

    def _enrich_results(self, results: list[dict], session: requests.Session) -> list[dict]:
        """Visit ACADP detail pages to extract website and social links."""
        for i, item in enumerate(results):
            detail_url = item.get("detail_url", "")
            if not detail_url:
                continue
            try:
                logger.info(f"[Afrikta] Enriching [{i+1}/{len(results)}] {item['name']}")
                resp = session.get(detail_url, timeout=15)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "lxml")

                    if not item.get("website"):
                        for sel in [".acadp-field-website a", "a[href^='http']:not([href*='afrikta'])"]:
                            el = soup.select_one(sel)
                            if el:
                                href = el.get("href", "")
                                if href.startswith("http") and "afrikta" not in href:
                                    item["website"] = href
                                    break

                    # Look only within the company's own fields section (avoids site-wide footer links)
                    social_scope = soup.select_one(".acadp-fields, .acadp-listing-content, .acadp-detail")
                    if social_scope:
                        for a in social_scope.find_all("a", href=True):
                            href = a["href"].strip()
                            if not href.startswith("http"):
                                continue
                            if any(x in href for x in ["/sharer", "/share", "/dialog", "shareArticle", "intent/tweet"]):
                                continue
                            if "facebook.com/" in href and not item.get("facebook_url"):
                                item["facebook_url"] = href
                            elif "linkedin.com/company/" in href and not item.get("linkedin_url"):
                                item["linkedin_url"] = href
                time.sleep(0.5)
            except Exception as e:
                logger.debug(f"[Afrikta] Enrichment failed for {item['name']}: {e}")
        return results

    def _has_next_page(self, soup: BeautifulSoup) -> bool:
        return bool(soup.select_one("a.next, a[rel='next'], .acadp-pagination .next"))


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    scraper = AfrikaScraper()
    results = scraper.search("services", city="Tunis")
    print(f"\n=== {len(results)} companies found ===")
    for r in results[:5]:
        print(json.dumps(r, ensure_ascii=False, indent=2))
