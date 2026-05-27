import asyncio
import logging
import os
import re
import time
from typing import Optional
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
import urllib3

# Suppress insecure request warnings from verify=False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
}


class KompassScraper:
    """Scraper for Kompass Tunisia.

    Uses SerpAPI Google search to bypass DataDome bot protection.
    Falls back to direct HTTP scraping of tn.kompass.com and kompass.com if no SerpAPI key is set.
    """

    KOMPASS_TN_URL = "https://tn.kompass.com"
    KOMPASS_GLOBAL_URL = "https://kompass.com/en/b/tunisia/"

    def search(self, keyword: str, city: str, area: Optional[str] = None) -> list[dict]:
        results = []
        
        # Try SerpAPI / Google search first to bypass DataDome
        api_key = os.getenv("SERPAPI_KEY", "")
        if api_key:
            logger.info(f"[Kompass] Using SerpAPI / Google search to bypass DataDome for '{keyword}' in '{city}'")
            results = self._scrape_via_serpapi(keyword, city, api_key)
            if results:
                logger.info(f"[Kompass/SerpAPI] Successfully found {len(results)} results")

        # Fallback to direct HTTP scraping if SerpAPI is not configured or returned no results
        if not results:
            logger.info(f"[Kompass] SerpAPI not configured or returned 0 results; falling back to direct requests.")
            try:
                # Try Tunisia-specific Kompass domain first
                results = self._scrape_kompass_tn(keyword, city)
                if not results:
                    results = self._scrape_kompass_global(keyword, city)
            except Exception as e:
                logger.error(f"[Kompass] Direct Scrape Error: {e}")

        if area:
            area_lower = area.lower()
            results = [r for r in results if area_lower in (r.get("address") or "").lower()]

        return results

    def _scrape_via_serpapi(self, keyword: str, city: str, api_key: str) -> list[dict]:
        url = "https://serpapi.com/search.json"
        params = {
            "engine": "google",
            "q": f"site:tn.kompass.com {keyword} {city}",
            "api_key": api_key,
            "hl": "fr",
            "gl": "tn"
        }
        
        results = []
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            
            organic_results = data.get("organic_results", [])
            for res in organic_results:
                title = res.get("title", "")
                link = res.get("link", "")
                snippet = res.get("snippet", "")
                
                # Verify if this is a company profile or catalog/category page
                if not ("/c/" in link or "/co/" in link):
                    continue
                
                name = self._clean_name(title)
                if not name or len(name) < 2:
                    continue
                
                # Sector/Activity
                sector = ""
                parts = re.split(r"\s*[-|–|\|]\s*", title)
                if len(parts) > 1:
                    sector = parts[1].replace("Kompass", "").strip()
                
                # Phone extraction
                phone = ""
                phone_match = re.search(r"(\+216\s*)?[24579]\d[\s.-]?\d{3}[\s.-]?\d{3}", snippet)
                if phone_match:
                    phone = phone_match.group(0).strip()
                
                # Address extraction
                address = ""
                addr_match = re.search(r"(\d{4}\s+[^.]+ Tunisie)", snippet)
                if addr_match:
                    address = addr_match.group(1).strip()
                else:
                    city_match = re.search(rf"([^,–]+{city}[^–.]+)", snippet, re.IGNORECASE)
                    if city_match:
                        address = city_match.group(1).strip()
                
                results.append({
                    "name": name,
                    "sector": sector,
                    "address": address or f"{city}, Tunisie",
                    "phone": phone,
                    "website": "",
                    "facebook_url": "",
                    "linkedin_url": "",
                    "employee_count": "",
                    "source": "kompass",
                    "profile_url": link
                })
        except Exception as e:
            logger.debug(f"[Kompass/SerpAPI] Failed: {e}")
            
        return results

    def _scrape_detail_page(self, profile_url: str) -> dict:
        """Visit a Kompass profile page to extract website and social links."""
        data = {"website": "", "facebook_url": "", "linkedin_url": ""}
        if not profile_url:
            return data
        try:
            resp = requests.get(profile_url, headers=HEADERS, timeout=15, verify=False)
            if resp.status_code != 200:
                logger.debug(f"[Kompass] Detail page {profile_url} → HTTP {resp.status_code}")
                return data
            soup = BeautifulSoup(resp.text, "lxml")

            kompass_domains = {"kompass.com", "tn.kompass.com"}
            for a in soup.select("a[href^='http']"):
                href = a.get("href", "")
                domain = urlparse(href).netloc.lower().lstrip("www.")
                if domain and not any(domain.endswith(kd) for kd in kompass_domains):
                    data["website"] = href
                    break

            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if "facebook.com" in href and not data["facebook_url"]:
                    if not any(x in href for x in ["/sharer", "/share", "/dialog"]):
                        data["facebook_url"] = href
                elif "linkedin.com" in href and not data["linkedin_url"]:
                    if "/company/" in href or "/in/" in href:
                        data["linkedin_url"] = href
        except Exception as e:
            logger.debug(f"[Kompass] Detail scrape error for {profile_url}: {e}")
        return data

    def _enrich_results(self, results: list[dict]) -> list[dict]:
        """Visit Kompass profile pages to fill website and social links."""
        for i, item in enumerate(results):
            profile_url = item.get("profile_url", "")
            if not profile_url:
                continue
            logger.info(f"[Kompass] Enriching [{i+1}/{len(results)}] {item['name']}")
            detail = self._scrape_detail_page(profile_url)
            for key, val in detail.items():
                if val and not item.get(key):
                    item[key] = val
            time.sleep(0.5)
        return results

    def _clean_name(self, title: str) -> str:
        """Extract clean company name from Google Search title."""
        if not title:
            return ""
        # Strip common suffixes
        title = re.sub(r"\s*[-|–]\s*Kompass.*$", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\s*[-|–]\s*Articles.*$", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\s*[-|–]\s*Hôtels.*$", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\s*[-|–]\s*Entreprises.*$", "", title, flags=re.IGNORECASE)
        # Get the first part before dash/pipe
        parts = re.split(r"\s*[-|–|\|]\s*", title)
        name = parts[0].strip()
        return name

    def _scrape_kompass_tn(self, keyword: str, city: str) -> list[dict]:
        results = []
        city_slug = city.lower().replace(" ", "-")
        kw_slug = keyword.lower().replace(" ", "+")

        candidate_urls = [
            f"{self.KOMPASS_TN_URL}/a/{kw_slug}/{city_slug}/",
            f"{self.KOMPASS_TN_URL}/search?q={kw_slug}&city={city}",
            f"{self.KOMPASS_TN_URL}/en/{kw_slug}/?country=TN&city={city}",
        ]

        for url in candidate_urls:
            try:
                resp = requests.get(url, headers=HEADERS, timeout=15, verify=False)
                if resp.status_code == 403:
                    logger.warning(f"[Kompass] Access to {url} blocked by Cloudflare (HTTP 403).")
                    break
                if resp.status_code == 200 and len(resp.text) > 500:
                    soup = BeautifulSoup(resp.text, "lxml")
                    items = self._parse_kompass_page(soup)
                    if items:
                        logger.info(f"[Kompass TN] {len(items)} results from {url}")
                        results.extend(items)

                        for page_num in range(2, 6):
                            page_url = url + f"&p={page_num}" if "?" in url else url + f"?p={page_num}"
                            try:
                                r = requests.get(page_url, headers=HEADERS, timeout=15, verify=False)
                                if r.status_code == 403:
                                    break
                                more = self._parse_kompass_page(BeautifulSoup(r.text, "lxml"))
                                if not more:
                                    break
                                results.extend(more)
                            except Exception:
                                break
                        break
            except Exception as e:
                logger.debug(f"[Kompass TN] {url} failed: {e}")

        return results

    def _scrape_kompass_global(self, keyword: str, city: str) -> list[dict]:
        results = []
        url = f"{self.KOMPASS_GLOBAL_URL}?q={keyword}&city={city}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15, verify=False)
            if resp.status_code == 403:
                logger.warning(f"[Kompass] Access to {url} blocked by Cloudflare (HTTP 403).")
                return []
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")
                items = self._parse_kompass_page(soup)
                if items:
                    logger.info(f"[Kompass Global] {len(items)} results")
                    results.extend(items)
        except Exception as e:
            logger.debug(f"[Kompass Global] failed: {e}")

        return results

    def _parse_kompass_page(self, soup: BeautifulSoup) -> list[dict]:
        items = []

        card_selectors = [
            ".company-card", ".listing-company", ".result-company",
            ".k-company", ".companyCard", "article.company",
            "[class*='company-item']", "[class*='companyItem']",
        ]

        cards = []
        for sel in card_selectors:
            cards = soup.select(sel)
            if cards:
                break

        if not cards:
            return self._generic_kompass_parse(soup)

        for card in cards:
            name_el = card.select_one("h2, h3, .company-name, .name, strong")
            name = name_el.get_text(strip=True) if name_el else ""
            if not name or len(name) < 2:
                continue

            activity_el = card.select_one(".activity, .sector, .category, .industry, [class*='activity']")
            activity = activity_el.get_text(strip=True) if activity_el else ""

            address_el = card.select_one(".address, [class*='addr'], [class*='location']")
            address = address_el.get_text(strip=True) if address_el else ""

            phone_el = card.select_one("[href^='tel:'], .phone, [class*='phone']")
            if phone_el:
                phone = phone_el.get("href", "").replace("tel:", "") or phone_el.get_text(strip=True)
            else:
                phone = ""

            website_el = card.select_one("a[href^='http']:not([href*='kompass'])")
            website = website_el.get("href", "") if website_el else ""

            employees_el = card.select_one(".employees, [class*='employee'], [class*='staff']")
            employees = employees_el.get_text(strip=True) if employees_el else ""

            items.append({
                "name": name,
                "sector": activity,
                "address": address,
                "phone": phone,
                "website": website,
                "employee_count": employees,
                "source": "kompass",
            })

        return items

    def _generic_kompass_parse(self, soup: BeautifulSoup) -> list[dict]:
        items = []
        for el in soup.find_all(["h2", "h3"]):
            text = el.get_text(strip=True)
            if len(text) < 3 or len(text) > 120:
                continue
            parent = el.parent
            address_el = parent.find(class_=re.compile(r"addr|location|city", re.I))
            phone_el = parent.find("a", href=re.compile(r"^tel:"))
            items.append({
                "name": text,
                "address": address_el.get_text(strip=True) if address_el else "",
                "phone": phone_el.get("href", "").replace("tel:", "") if phone_el else "",
                "source": "kompass",
            })
        return items


if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    scraper = KompassScraper()
    results = scraper.search("software", city="Tunis")
    print(f"\n=== {len(results)} companies found ===")
    for r in results[:10]:
        print(json.dumps(r, ensure_ascii=False, indent=2))
