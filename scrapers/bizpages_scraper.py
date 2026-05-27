"""
Scraper for BizPages.org — international business directory.

Strategy
--------
BizPages uses a CGI-based search form:
  POST /cgi-bin/search.cgi?par=search_redir
  Form field: mainsearch_input_id = "<query>"

The search results page contains table rows with class "intextlink" linking to:
  /cgi-bin/searchredir.cgi?p={ID}

Which redirect (via JavaScript location.replace) to:
  /business--{Country}--{City}--{ID}

We follow these redirects, fetch the company profile pages, and parse details:
  - Name, address, phone from JSON-LD schema
  - Email by reversing the argument of the `reversefunct` JS call
  - External website by base64-decoding the `url` parameter of the /cgi-bin/out.cgi link
"""

import logging
import re
import time
import json
import base64
from typing import Optional
from urllib.parse import urlparse, parse_qs

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
    "Referer": "https://bizpages.org/",
}


class BizPagesScraper:
    """Scraper for bizpages.org (Tunisia section)."""

    BASE_URL = "https://bizpages.org"
    SEARCH_URL = "https://bizpages.org/cgi-bin/search.cgi?par=search_redir"

    def search(
        self,
        keyword: str,
        city: str,
        area: Optional[str] = None,
        max_pages: int = 5,
    ) -> list[dict]:
        """Search BizPages for companies.

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
            # Strategy 1: Search keyword globally, then filter country Tunisia in results
            # We try search queries in order of specificity
            queries_to_try = [
                f"{keyword} Tunisia {city}",
                f"{keyword} Tunisia",
                keyword
            ]

            for query in queries_to_try:
                logger.info(f"[BizPages] Attempting search with query: '{query}'")
                search_results = self._search_via_post(query, max_pages, session)
                if search_results:
                    results.extend(search_results)
                    break

            # Strategy 2: Always scrape the country page since it only has a few listings.
            # This ensures we don't miss anything.
            country_results = self._scrape_country_page(session)
            seen_urls = {r.get("detail_url") for r in results if r.get("detail_url")}
            for cr in country_results:
                if cr.get("detail_url") not in seen_urls:
                    results.append(cr)

        except Exception as e:
            logger.error(f"[BizPages] Search error: {e}")

        # Local filtering by keyword, city and area
        filtered: list[dict] = []
        kw_lower = keyword.lower()
        city_lower = city.lower()
        area_lower = area.lower() if area else None

        for r in results:
            address = (r.get("address") or "").lower()
            name = (r.get("name") or "").lower()
            sector = (r.get("sector") or "").lower()
            desc = (r.get("description") or "").lower()
            url_str = (r.get("detail_url") or "").lower()

            # Check if city matches (in address, url, or locality)
            if city_lower not in address and city_lower not in url_str:
                continue

            # Check if area matches (if specified)
            if area_lower and area_lower not in address:
                continue

            # Check if keyword matches name, sector, or description
            if (kw_lower not in name and 
                kw_lower not in sector and 
                kw_lower not in desc):
                continue

            filtered.append(r)

        logger.info(f"[BizPages] Total results after local filtering: {len(filtered)}")
        return filtered

    def _search_via_post(self, query: str, max_pages: int, session: requests.Session) -> list[dict]:
        """Submit the search form via POST and parse results."""
        results: list[dict] = []

        try:
            form_data = {"mainsearch_input_id": query}
            resp = session.post(
                self.SEARCH_URL,
                data=form_data,
                timeout=20,
                allow_redirects=True,
            )

            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "lxml")
            items = self._parse_search_results(soup, session)
            results.extend(items)

            # Try subsequent pages if available
            for page_num in range(2, max_pages + 1):
                next_url = self._find_next_page(soup)
                if not next_url:
                    break

                if not next_url.startswith("http"):
                    next_url = f"{self.BASE_URL}{next_url}"

                logger.info(f"[BizPages] Fetching page {page_num}: {next_url}")
                time.sleep(1)

                try:
                    resp = session.get(next_url, timeout=15)
                    if resp.status_code != 200:
                        break
                    soup = BeautifulSoup(resp.text, "lxml")
                    more_items = self._parse_search_results(soup, session)
                    if not more_items:
                        break
                    results.extend(more_items)
                except Exception:
                    break

        except Exception as e:
            logger.error(f"[BizPages] POST search failed: {e}")

        return results

    def _parse_search_results(self, soup: BeautifulSoup, session: requests.Session) -> list[dict]:
        """Parse search results from BizPages HTML."""
        items: list[dict] = []

        page_text = soup.get_text().lower()
        if "no results found" in page_text:
            return []

        # Find search result links (class="intextlink", href starts with /cgi-bin/searchredir.cgi?p=)
        result_links = soup.find_all("a", class_="intextlink", href=re.compile(r"/cgi-bin/searchredir\.cgi\?p="))
        seen_ids: set[str] = set()

        for link in result_links:
            href = link.get("href", "")
            match = re.search(r"p=(\d+)", href)
            if not match:
                continue
            item_id = match.group(1)
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)

            # Check if this cell belongs to a Tunisian company
            parent_td = link.parent
            is_tunisia = False
            if parent_td:
                country_link = parent_td.find("a", href=re.compile(r"/cc--Tunisia----|Tunisia", re.I))
                if country_link or "tunisia" in parent_td.get_text().lower():
                    is_tunisia = True
                else:
                    nav_links = parent_td.find_all("a", class_="navigationlink")
                    for nav in nav_links:
                        if "tunisia" in nav.get_text().lower() or "tunisia" in nav.get("href", "").lower():
                            is_tunisia = True
                            break

            if not is_tunisia:
                continue

            # Fetch details
            detail_url = self._follow_redirect_and_get_details(item_id, session)
            if detail_url:
                detail_data = self._scrape_detail_page(detail_url, session)
                if detail_data:
                    items.append(detail_data)
                time.sleep(1)

        return items

    def _scrape_country_page(self, session: requests.Session) -> list[dict]:
        """Fetch the Tunisia country page and parse all listings."""
        results: list[dict] = []
        try:
            url = f"{self.BASE_URL}/countries--TN--Tunisia"
            logger.info(f"[BizPages] Fetching country page: {url}")
            resp = session.get(url, timeout=20)
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "lxml")
            business_links = soup.find_all("a", href=re.compile(r"/business--Tunisia--"))
            seen_urls: set[str] = set()

            for link in business_links:
                href = link.get("href", "")
                detail_url = href if href.startswith("http") else f"{self.BASE_URL}{href}"
                if detail_url in seen_urls:
                    continue
                seen_urls.add(detail_url)

                logger.info(f"[BizPages] Scraping detail page from country list: {detail_url}")
                detail_data = self._scrape_detail_page(detail_url, session)
                if detail_data:
                    results.append(detail_data)
                time.sleep(1)

        except Exception as e:
            logger.error(f"[BizPages] Country page scraping error: {e}")

        return results

    def _follow_redirect_and_get_details(self, item_id: str, session: requests.Session) -> Optional[str]:
        """Fetch the searchredir.cgi page to find the real detail page URL."""
        try:
            url = f"{self.BASE_URL}/cgi-bin/searchredir.cgi?p={item_id}"
            resp = session.get(url, timeout=15)
            if resp.status_code == 200:
                match = re.search(r'location\.replace\("([^"]+)"\)', resp.text)
                if match:
                    redirect_path = match.group(1)
                    if redirect_path.startswith("http"):
                        return redirect_path
                    return f"{self.BASE_URL}{redirect_path}"
        except Exception as e:
            logger.error(f"[BizPages] Redirect fetch failed for ID {item_id}: {e}")
        return None

    def _scrape_detail_page(self, url: str, session: requests.Session) -> Optional[dict]:
        """Fetch and parse a company's profile page on BizPages."""
        try:
            logger.info(f"[BizPages] Fetching profile: {url}")
            resp = session.get(url, timeout=15)
            if resp.status_code != 200:
                return None

            soup = BeautifulSoup(resp.text, "lxml")
            
            name = ""
            sector = ""
            address = ""
            phone = ""
            email = ""
            website = ""
            description = ""

            # 1. Parse JSON-LD LocalBusiness schema
            script = soup.find("script", type="application/ld+json")
            if script and script.string:
                try:
                    data = json.loads(script.string.strip())
                    if isinstance(data, dict):
                        name = data.get("name") or name
                        phone = data.get("telephone") or phone
                        addr_data = data.get("address")
                        if isinstance(addr_data, dict):
                            street = addr_data.get("streetAddress") or ""
                            locality = addr_data.get("addressLocality") or ""
                            postal = addr_data.get("postalCode") or ""
                            country = addr_data.get("addressCountry") or ""
                            address_parts = [p for p in [street, postal, locality, country] if p]
                            address = ", ".join(address_parts)
                except Exception as je:
                    logger.debug(f"[BizPages] JSON-LD parse error: {je}")

            # 2. Get description from meta tag
            meta_desc = soup.find("meta", attrs={"name": re.compile(r"description", re.I)}) or \
                        soup.find("meta", attrs={"property": "og:description"})
            if meta_desc:
                description = meta_desc.get("content", "").strip()

            # 3. If name is still empty, parse from title or H1
            if not name:
                h1 = soup.find("h1")
                if h1:
                    name = h1.get_text(strip=True)
                else:
                    title = soup.find("title")
                    if title:
                        name = title.get_text(strip=True).split(",")[0].strip()

            # 4. Extract base64 encoded website
            out_link = soup.find("a", href=re.compile(r"/cgi-bin/out\.cgi\?url="))
            if out_link:
                try:
                    href = out_link.get("href", "")
                    parsed = urlparse(href)
                    url_param = parse_qs(parsed.query).get("url", [""])[0]
                    if url_param:
                        missing_padding = len(url_param) % 4
                        if missing_padding:
                            url_param += "=" * (4 - missing_padding)
                        website = base64.b64decode(url_param).decode("utf-8", errors="ignore")
                except Exception as we:
                    logger.debug(f"[BizPages] Website decode error: {we}")

            # 5. Extract obfuscated email
            email_matches = re.findall(r"reversefunct\(\s*'([^']+)'\s*\)", resp.text)
            for m in email_matches:
                reversed_str = m[::-1]
                if "@" in reversed_str:
                    email = reversed_str
                    break

            # 6. Extract sector/category (look for breadcrumbs)
            nav_links = soup.find_all("a", class_="navigationlink")
            if len(nav_links) >= 3:
                sector = nav_links[-2].get_text(strip=True)

            return {
                "name": name,
                "sector": sector,
                "address": address,
                "phone": phone,
                "email": email,
                "website": website,
                "description": description,
                "detail_url": url,
                "source": "bizpages",
            }

        except Exception as e:
            logger.error(f"[BizPages] Error parsing detail page {url}: {e}")
            return None

    def _find_next_page(self, soup: BeautifulSoup) -> Optional[str]:
        """Find the 'next page' link in the search results."""
        next_link = soup.find("a", string=re.compile(r"next|→|»|>", re.I))
        if next_link:
            return next_link.get("href")

        pagination = soup.find(class_=re.compile(r"paginat|pages", re.I))
        if pagination:
            current = pagination.find("span", class_=re.compile(r"current|active"))
            if current:
                next_sibling = current.find_next("a")
                if next_sibling:
                    return next_sibling.get("href")

        return None


if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    scraper = BizPagesScraper()
    results = scraper.search("software", city="Tunis")
    print(f"\n=== {len(results)} companies found ===")
    for r in results:
        print(json.dumps(r, ensure_ascii=False, indent=2))
