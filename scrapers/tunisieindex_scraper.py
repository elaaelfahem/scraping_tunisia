"""
Scraper for TunisieIndex (tunisieindex.com) — category-based Tunisian business directory.

URL structure:
  - Categories:    //www.tunisieindex.com/annuaire-entreprises/{cat-slug}-{id}/
  - Sub-cats:      /annuaire-entreprises/{cat-slug}-{id}/{subcat-slug}-{id}/
  - Company pages: //www.tunisieindex.com/entreprises/{slug}-{id}.html
  - Pagination:    societes-classees-par-date-page-{n}.html (relative to sub-cat URL)
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

BASE_URL = "https://www.tunisieindex.com"
ANNUAIRE_URL = f"{BASE_URL}/entreprises/"


class TunisieIndexScraper:
    """Scraper for tunisieindex.com category-based directory."""

    def search(
        self,
        keyword: str,
        city: str,
        area: Optional[str] = None,
        max_pages: int = 3,
        enrich_details: bool = True,
    ) -> list[dict]:
        results: list[dict] = []
        session = requests.Session()
        session.headers.update(HEADERS)

        try:
            cat_links = self._discover_categories(session)
            matching = self._filter_categories(cat_links, keyword)
            if not matching:
                # Fall back to first top-level category when keyword is generic
                matching = cat_links[:3]

            for cat_url in matching[:4]:
                results.extend(self._scrape_category(cat_url, max_pages, session))
        except Exception as e:
            logger.error(f"[TunisieIndex] Error: {e}")

        if enrich_details and results:
            results = self._enrich_results(results, session)

        if area:
            area_lower = area.lower()
            results = [r for r in results if area_lower in (r.get("address") or "").lower()]

        logger.info(f"[TunisieIndex] Total: {len(results)}")
        return results

    # ── Category discovery ──────────────────────────────────────────────────

    def _discover_categories(self, session: requests.Session) -> list[str]:
        """Return all sub-category URLs from the main entreprises page."""
        urls: list[str] = []
        try:
            resp = session.get(ANNUAIRE_URL, timeout=15)
            if resp.status_code != 200:
                return urls
            soup = BeautifulSoup(resp.text, "lxml")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/annuaire-entreprises/" in href and "-" in href:
                    full_url = href if href.startswith("http") else f"https:{href}"
                    if full_url not in urls:
                        urls.append(full_url)
        except Exception as e:
            logger.warning(f"[TunisieIndex] Category discovery failed: {e}")
        return urls

    def _filter_categories(self, cat_urls: list[str], keyword: str) -> list[str]:
        kw_lower = keyword.lower()
        # Score each URL by how many keyword words appear in its path
        kw_words = [w for w in re.split(r"\W+", kw_lower) if len(w) > 2]
        scored = []
        for url in cat_urls:
            path = url.lower()
            score = sum(1 for w in kw_words if w in path)
            if score > 0:
                scored.append((score, url))
        scored.sort(reverse=True)
        return [u for _, u in scored]

    # ── Category page scraping ──────────────────────────────────────────────

    def _scrape_category(self, cat_url: str, max_pages: int, session: requests.Session) -> list[dict]:
        results: list[dict] = []
        for page_num in range(1, max_pages + 1):
            if page_num == 1:
                url = cat_url
            else:
                # Pagination is relative: append the page file name
                base = cat_url.rstrip("/") + "/"
                url = f"{base}societes-classees-par-date-page-{page_num}.html"

            logger.info(f"[TunisieIndex] Fetching {url}")
            try:
                resp = session.get(url, timeout=15)
                if resp.status_code != 200:
                    break
                soup = BeautifulSoup(resp.text, "lxml")
                items = self._parse_listing(soup, cat_url)
                if not items:
                    break
                results.extend(items)
                time.sleep(1)
                if not self._has_next_page(soup, page_num):
                    break
            except Exception as e:
                logger.warning(f"[TunisieIndex] Error: {e}")
                break
        return results

    def _parse_listing(self, soup: BeautifulSoup, cat_url: str) -> list[dict]:
        module = soup.find("div", id="m_Entreprises")
        if not module:
            return []

        items = []
        for a in module.find_all("a", href=True):
            href = a["href"]
            if "/entreprises/" not in href or "proposer" in href or "nouvea" in href or "populai" in href:
                continue
            if not re.search(r"-\d+\.html$", href):
                continue

            name = a.get_text(strip=True)
            if not name or len(name) < 2 or len(name) > 150:
                continue

            full_url = href if href.startswith("http") else f"https:{href}"

            # Get brief description from the next sibling table row
            description = ""
            parent_td = a.find_parent("td")
            if parent_td:
                next_row = parent_td.find_parent("tr")
                if next_row:
                    next_tr = next_row.find_next_sibling("tr")
                    if next_tr:
                        description = next_tr.get_text(strip=True)[:200]

            # Extract sector from the category URL path
            sector = self._sector_from_url(cat_url)

            items.append({
                "name": name,
                "sector": sector,
                "description": description,
                "detail_url": full_url,
                "source": "tunisieindex",
            })

        return items

    def _enrich_results(self, results: list[dict], session: requests.Session) -> list[dict]:
        """Visit each company detail page to extract phone, address, website, email."""
        for i, item in enumerate(results):
            detail_url = item.get("detail_url", "")
            if not detail_url:
                continue
            try:
                logger.info(f"[TunisieIndex] Enriching [{i+1}/{len(results)}] {item['name']}")
                resp = session.get(detail_url, timeout=15)
                if resp.status_code != 200:
                    time.sleep(0.5)
                    continue
                soup = BeautifulSoup(resp.text, "lxml")

                # Phone — look for tel: links or labeled fields
                if not item.get("phone"):
                    phone_el = soup.select_one("a[href^='tel:']")
                    if phone_el:
                        item["phone"] = phone_el.get("href", "").replace("tel:", "").strip()
                    else:
                        # Try labeled text like "Tél :" or "Tel :"
                        for p in soup.find_all(["p", "li", "td"]):
                            text = p.get_text(separator=" ")
                            m = re.search(r"T[eé]l[.\s:]*\s*(\+?[\d\s\.\-\/]{7,})", text, re.I)
                            if m:
                                item["phone"] = m.group(1).strip()
                                break

                # Email
                if not item.get("email"):
                    email_el = soup.select_one("a[href^='mailto:']")
                    if email_el:
                        item["email"] = email_el.get("href", "").replace("mailto:", "").strip()

                # Website
                if not item.get("website"):
                    for a in soup.find_all("a", href=True):
                        href = a["href"].strip()
                        if href.startswith("http") and "tunisieindex" not in href:
                            item["website"] = href
                            break

                # Address — look for the address block
                if not item.get("address"):
                    for sel in [".company-address", ".adresse", "[itemprop='address']",
                                "p:contains('Adresse')", "td:contains('Adresse')"]:
                        try:
                            el = soup.select_one(sel)
                            if el:
                                item["address"] = el.get_text(separator=" ", strip=True)
                                break
                        except Exception:
                            pass

                time.sleep(0.5)
            except Exception as e:
                logger.debug(f"[TunisieIndex] Enrichment failed for {item['name']}: {e}")
        return results

    def _has_next_page(self, soup: BeautifulSoup, current_page: int) -> bool:
        module = soup.find("div", id="m_Entreprises")
        if not module:
            return False
        next_page_num = current_page + 1
        next_link = module.find("a", href=re.compile(rf"page-{next_page_num}\.html"))
        return bool(next_link)

    @staticmethod
    def _sector_from_url(url: str) -> str:
        match = re.search(r"/annuaire-entreprises/([^/]+)/", url)
        if match:
            slug = match.group(1)
            slug = re.sub(r"-\d+$", "", slug)
            return slug.replace("-", " ").title()
        return ""


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    scraper = TunisieIndexScraper()
    results = scraper.search("informatique", city="Tunis", max_pages=2)
    print(f"\n=== {len(results)} companies found ===")
    for r in results[:5]:
        print(json.dumps(r, ensure_ascii=False, indent=2))
