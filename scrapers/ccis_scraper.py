"""
Scraper for CCIS (ccis.org.tn) — Chambre de Commerce et d'Industrie de Sfax.

Company card: li.article-company (inside div.row.no-gutters)
Name:   a.company-name (text content — no href attribute)
City:   span.company-country
Sector: strong inside .article-company__header
Detail: .go-to-epage a[href]

Pagination: /annuaire-entreprises/page/{n}/  (up to 101 pages, 50/page)
Note: SSL certificate is self-signed → verify=False required.
"""

import logging
import re
import time
from typing import Optional
from urllib.parse import urlparse
import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,ar;q=0.8",
    "Referer": "https://www.ccis.org.tn/",
}

BASE_URL = "https://www.ccis.org.tn"
ANNUAIRE_URL = f"{BASE_URL}/annuaire-entreprises/"


class CCISScraper:
    """Scraper for CCIS member company directory."""

    def search(
        self,
        keyword: str,
        city: str,
        area: Optional[str] = None,
        max_pages: int = 5,
        enrich_details: bool = True,
    ) -> list[dict]:
        results: list[dict] = []
        session = requests.Session()
        session.headers.update(HEADERS)

        try:
            results = self._scrape_pages(max_pages, session)
        except Exception as e:
            logger.error(f"[CCIS] Error: {e}")

        # CCIS is Sfax-based, but filter by keyword in sector/name
        if keyword and keyword.lower() not in ("all", "entreprises", "services"):
            kw_lower = keyword.lower()
            filtered = [
                r for r in results
                if kw_lower in (r.get("name") or "").lower()
                or kw_lower in (r.get("sector") or "").lower()
            ]
            if filtered:
                results = filtered

        if enrich_details and results:
            results = self._enrich_results(results, session)

        if area:
            area_lower = area.lower()
            results = [r for r in results if area_lower in (r.get("address") or "").lower()
                       or area_lower in (r.get("city") or "").lower()]

        logger.info(f"[CCIS] Total: {len(results)}")
        return results

    def _scrape_pages(self, max_pages: int, session: requests.Session) -> list[dict]:
        results: list[dict] = []
        for page_num in range(1, max_pages + 1):
            url = ANNUAIRE_URL if page_num == 1 else f"{ANNUAIRE_URL}page/{page_num}/"
            logger.info(f"[CCIS] Fetching page {page_num}: {url}")
            try:
                resp = session.get(url, verify=False, timeout=15)
                if resp.status_code != 200:
                    break
                soup = BeautifulSoup(resp.text, "lxml")
                items = self._parse_page(soup)
                if not items:
                    break
                results.extend(items)
                logger.info(f"[CCIS] Page {page_num}: {len(items)} companies")
                time.sleep(1)
            except Exception as e:
                logger.warning(f"[CCIS] Page {page_num} error: {e}")
                break
        return results

    def _parse_page(self, soup: BeautifulSoup) -> list[dict]:
        cards = soup.select("li.article-company")
        if not cards:
            return []

        items = []
        for card in cards:
            # Name — .company-name is an <a> tag but with no href (JavaScript-driven)
            name_el = card.select_one(".company-name")
            if not name_el:
                continue
            name = name_el.get_text(strip=True)
            if not name or len(name) < 2:
                continue

            # City
            city_str = ""
            city_el = card.select_one(".company-country")
            if city_el:
                city_str = city_el.get_text(strip=True)

            # Sector — inside a <strong> tag in the header
            sector = ""
            header = card.select_one(".article-company__header")
            if header:
                strong = header.find("strong")
                if strong:
                    sector = strong.get_text(strip=True)

            # Detail URL
            detail_url = ""
            detail_el = card.select_one(".go-to-epage a")
            if detail_el:
                detail_url = detail_el.get("href", "")

            # Phone and email are often hidden behind the detail page
            phone = ""
            phone_el = card.select_one("a[href^='tel:']")
            if phone_el:
                phone = phone_el.get("href", "").replace("tel:", "")

            email = ""
            email_el = card.select_one("a[href^='mailto:']")
            if email_el:
                email = email_el.get("href", "").replace("mailto:", "")

            items.append({
                "name": name,
                "sector": sector,
                "city": city_str,
                "address": city_str,  # CCIS only exposes city, not full address in listing
                "phone": phone,
                "email": email,
                "detail_url": detail_url,
                "source": "ccis",
            })
        return items


    def _enrich_results(self, results: list[dict], session: requests.Session) -> list[dict]:
        """Visit CCIS detail pages (/details-entreprise/?e={id}) to extract phone, email, address."""
        for i, item in enumerate(results):
            detail_url = item.get("detail_url", "")
            if not detail_url:
                continue
            try:
                logger.info(f"[CCIS] Enriching [{i+1}/{len(results)}] {item['name']}")
                resp = session.get(detail_url, verify=False, timeout=15)
                if resp.status_code != 200:
                    time.sleep(0.5)
                    continue
                soup = BeautifulSoup(resp.text, "lxml")

                # Phone
                if not item.get("phone"):
                    phone_el = soup.select_one("a[href^='tel:']")
                    if phone_el:
                        item["phone"] = phone_el.get("href", "").replace("tel:", "").strip()

                # Email
                if not item.get("email"):
                    email_el = soup.select_one("a[href^='mailto:']")
                    if email_el:
                        item["email"] = email_el.get("href", "").replace("mailto:", "").strip()

                # Website
                if not item.get("website"):
                    ccis_domains = {"ccis.org.tn", "facebook.com", "linkedin.com",
                                    "instagram.com", "twitter.com", "x.com"}
                    for a in soup.find_all("a", href=True):
                        href = a["href"].strip()
                        if not href.startswith("http"):
                            continue
                        domain = urlparse(href).netloc.lower().lstrip("www.")
                        if domain and not any(domain.endswith(d) for d in ccis_domains):
                            item["website"] = href
                            break

                # Address — look for structured address blocks
                if not item.get("address") or item.get("address") == item.get("city"):
                    for sel in [".company-address", "[itemprop='address']",
                                ".adresse", ".contact-address"]:
                        el = soup.select_one(sel)
                        if el:
                            item["address"] = el.get_text(separator=" ", strip=True)
                            break

                time.sleep(0.5)
            except Exception as e:
                logger.debug(f"[CCIS] Enrichment failed for {item['name']}: {e}")
        return results


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    scraper = CCISScraper()
    results = scraper.search("industrie", city="Sfax")
    print(f"\n=== {len(results)} companies found ===")
    for r in results[:5]:
        print(json.dumps(r, ensure_ascii=False, indent=2))
