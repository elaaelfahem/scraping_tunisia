"""
Scraper for B2B.tn (b2b.tn) — Tunisia B2B business directory.

b2b.tn is a React Single-Page Application with no server-side rendering and no
accessible REST API. Playwright is required to execute the JavaScript and interact
with the search UI.
"""

import asyncio
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


class B2BTnScraper:
    """Playwright-based scraper for b2b.tn."""

    BASE_URL = "https://b2b.tn"

    async def search(
        self,
        keyword: str,
        city: str,
        area: Optional[str] = None,
        max_pages: int = 3,
    ) -> list[dict]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("[B2BTn] Playwright not installed. Run: pip install playwright && playwright install chromium")
            return []

        results: list[dict] = []
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    ),
                    locale="fr-FR",
                )
                page = await context.new_page()

                search_url = f"{self.BASE_URL}/fr/entreprises/?q={keyword}&ville={city}"
                logger.info(f"[B2BTn] Navigating to {search_url}")
                await page.goto(search_url, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(2000)

                for page_num in range(1, max_pages + 1):
                    html = await page.content()
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(html, "lxml")
                    items = self._parse_page(soup)
                    if not items:
                        break
                    results.extend(items)

                    # Try to navigate to next page
                    next_btn = await page.query_selector("a[aria-label='Next'], button.next-page, .pagination .next")
                    if not next_btn:
                        break
                    await next_btn.click()
                    await page.wait_for_timeout(2000)

                await browser.close()
        except Exception as e:
            logger.error(f"[B2BTn] Playwright error: {e}")

        if area:
            area_lower = area.lower()
            results = [r for r in results if area_lower in (r.get("address") or "").lower()]

        logger.info(f"[B2BTn] Total: {len(results)}")
        return results

    def _parse_page(self, soup) -> list[dict]:
        from bs4 import BeautifulSoup

        cards = soup.select("li.place-item, .place-item, .place-wrapper")
        if not cards:
            for sel in [
                ".company-card", ".entreprise-card", ".listing-item", ".company-item",
                "article", ".card", "div[class*='company']", "div[class*='entreprise']",
            ]:
                cards = soup.select(sel)
                if cards:
                    break

        items = []
        for card in cards:
            name_el = card.select_one("h2.title-place, .title-place, h2, h3, h4, .company-name, .name, strong")
            if not name_el:
                continue
            name = name_el.get_text(strip=True)
            if not name or len(name) < 2 or len(name) > 150:
                continue

            link_el = card.select_one("a[href*='/entreprise/'], a[href]")
            detail_url = link_el.get("href", "") if link_el else ""
            if detail_url and not detail_url.startswith("http"):
                detail_url = f"https://b2b.tn{detail_url}"

            sector = ""
            for sel in [".sector", ".category", ".activite", ".secteur"]:
                el = card.select_one(sel)
                if el:
                    sector = el.get_text(strip=True)
                    break

            address = ""
            addr_icon = card.select_one("i.fa-map-marker")
            if addr_icon and addr_icon.parent:
                address = addr_icon.parent.get_text(strip=True).replace("Adresse:", "").replace("address:", "").strip()
            
            if not address:
                for sel in [".address", ".adresse", ".location", ".ville"]:
                    el = card.select_one(sel)
                    if el:
                        address = el.get_text(strip=True)
                        break

            phone = ""
            phone_icon = card.select_one("i.fa-phone")
            if phone_icon and phone_icon.parent:
                phone = phone_icon.parent.get_text(strip=True).replace("Tél :", "").replace("Tel:", "").strip()
            
            if not phone:
                phone_el = card.select_one("a[href^='tel:'], .phone")
                if phone_el:
                    phone = phone_el.get("href", "").replace("tel:", "") or phone_el.get_text(strip=True)

            email = ""
            email_el = card.select_one("a[href^='mailto:']")
            if email_el:
                email = email_el.get("href", "").replace("mailto:", "")

            website = ""
            web_el = card.select_one("a[href^='http']:not([href*='b2b'])")
            if web_el:
                website = web_el.get("href", "")

            facebook_url = ""
            linkedin_url = ""
            for a in card.find_all("a", href=True):
                href = a["href"].strip()
                if "facebook.com" in href and not facebook_url:
                    if not any(x in href for x in ["/sharer", "/share", "/dialog"]):
                        facebook_url = href
                elif "linkedin.com" in href and not linkedin_url:
                    if "/company/" in href or "/in/" in href:
                        linkedin_url = href

            items.append({
                "name": name,
                "sector": sector,
                "address": address,
                "phone": phone,
                "email": email,
                "website": website,
                "facebook_url": facebook_url,
                "linkedin_url": linkedin_url,
                "detail_url": detail_url,
                "source": "b2btn",
            })
        return items


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    scraper = B2BTnScraper()
    results = asyncio.run(scraper.search("informatique", city="Tunis"))
    print(f"\n=== {len(results)} companies found ===")
    for r in results[:5]:
        print(json.dumps(r, ensure_ascii=False, indent=2))
