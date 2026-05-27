import asyncio
import logging
import os
from typing import Optional
import requests
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

logger = logging.getLogger(__name__)

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")


class GoogleMapsScraper:
    """
    Google Maps scraper.
    Uses SerpAPI when SERPAPI_KEY is set (recommended — reliable, no CAPTCHA).
    Falls back to Playwright browser scraping otherwise.
    """

    SERPAPI_URL = "https://serpapi.com/search.json"

    def __init__(self):
        self.api_key = SERPAPI_KEY or os.getenv("SERPAPI_KEY", "")

    async def search_companies(
        self, query: str, city: str = "", area: Optional[str] = None
    ) -> list[dict]:
        if self.api_key:
            return self._search_via_serpapi(query, city, area)
        return await self._search_via_browser(query)

    # ── SerpAPI path ────────────────────────────────────────────────────────

    def _search_via_serpapi(
        self, query: str, city: str, area: Optional[str]
    ) -> list[dict]:
        """Use SerpAPI Google Maps engine — reliable, structured results."""
        location = f"{area}, {city}, Tunisia" if area else f"{city}, Tunisia"
        results = []
        logger.info(f"[Maps/SerpAPI] Searching '{query}' @ '{location}'")

        params = {
            "engine": "google_maps",
            "q": f"{query} in {location}",
            "type": "search",
            "api_key": self.api_key,
            "hl": "en",
        }

        try:
            resp = requests.get(self.SERPAPI_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            local_results = data.get("local_results", [])
            logger.info(f"[Maps/SerpAPI] Got {len(local_results)} results")

            for place in local_results:
                results.append({
                    "name": place.get("title", ""),
                    "category": place.get("type", ""),
                    "address": place.get("address", ""),
                    "phone": place.get("phone", ""),
                    "website": place.get("website", ""),
                    "rating": place.get("rating"),
                    "reviews": place.get("reviews"),
                    "latitude": place.get("gps_coordinates", {}).get("latitude"),
                    "longitude": place.get("gps_coordinates", {}).get("longitude"),
                    "google_maps_url": place.get("place_id_search", ""),
                    "source": "google_maps",
                })

        except Exception as e:
            logger.error(f"[Maps/SerpAPI] Error: {e}")

        return results

    # ── Browser scraping fallback ────────────────────────────────────────────

    async def _search_via_browser(self, query: str) -> list[dict]:
        """Playwright fallback when no API key is configured.
        Clicks into each result to extract phone, website, and email."""
        logger.info(f"[Maps/Browser] Searching '{query}' (no SerpAPI key — using browser)")
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()
            await Stealth().apply_stealth_async(page)

            try:
                await page.goto("https://www.google.com/maps", timeout=30000)

                for btn_text in ["Accept all", "Tout accepter", "Accept"]:
                    try:
                        await page.click(f"button:has-text('{btn_text}')", timeout=4000)
                        break
                    except Exception:
                        pass

                await page.fill("#searchboxinput", query)
                await page.keyboard.press("Enter")

                await page.wait_for_selector(".m67qEc, .Nv2PK", timeout=15000)

                # Scroll to load more results
                for _ in range(6):
                    await page.mouse.wheel(0, 5000)
                    await asyncio.sleep(1.5)

                # Get list of result elements
                result_items = await page.query_selector_all(
                    ".m67qEc, .Nv2PK, [data-result-index]"
                )
                logger.info(f"[Maps/Browser] Found {len(result_items)} result elements")

                companies: list[dict] = []
                for i, item_el in enumerate(result_items[:30]):  # Cap at 30
                    try:
                        # Click into the result to open its detail panel
                        await item_el.click()
                        await asyncio.sleep(1.5)

                        detail = await page.evaluate("""
                            () => {
                                const panel = document.querySelector('[role="main"]');
                                if (!panel) return null;

                                const name = panel.querySelector('h1, .fontHeadlineLarge, .DUwDvf')?.innerText?.trim() || '';
                                if (!name) return null;

                                // Category / type
                                const catEl = panel.querySelector('button[jsaction*="category"], .DkEaL, .fontBodyMedium [jstcache]');
                                const category = catEl?.innerText?.trim() || '';

                                // Address
                                const addrBtn = panel.querySelector('button[data-item-id="address"], [data-tooltip="Copy address"]');
                                const address = addrBtn?.innerText?.trim()
                                    || panel.querySelector('[data-item-id*="address"]')?.innerText?.trim()
                                    || '';

                                // Phone
                                const phoneBtn = panel.querySelector('button[data-item-id^="phone:"], [data-tooltip="Copy phone number"]');
                                const phone = phoneBtn?.innerText?.trim()
                                    || panel.querySelector('[data-item-id*="phone"]')?.innerText?.trim()
                                    || '';

                                // Website
                                const webBtn = panel.querySelector('a[data-item-id="authority"], a[data-tooltip="Open website"]');
                                const website = webBtn?.getAttribute('href')
                                    || panel.querySelector('[data-item-id*="authority"]')?.querySelector('a')?.getAttribute('href')
                                    || '';

                                // Rating & reviews
                                const ratingEl = panel.querySelector('.fontDisplayLarge, .F7nice span[aria-hidden]');
                                const rating = ratingEl?.innerText?.trim() || '';
                                const reviewsEl = panel.querySelector('.F7nice span[aria-label*="review"]');
                                const reviews = reviewsEl?.getAttribute('aria-label')?.match(/[\d,]+/)?.[0] || '';

                                return { name, category, address, phone, website, rating, reviews, source: 'google_maps' };
                            }
                        """)

                        if detail and detail.get("name"):
                            companies.append(detail)
                            logger.info(f"[Maps/Browser] [{i+1}] {detail['name']}")

                        # Go back to list
                        back_btn = await page.query_selector(
                            "button[aria-label='Back'], button[jsaction*='back']"
                        )
                        if back_btn:
                            await back_btn.click()
                            await asyncio.sleep(1)

                    except Exception as e:
                        logger.debug(f"[Maps/Browser] Item {i} error: {e}")
                        continue

                logger.info(f"[Maps/Browser] Extracted {len(companies)} companies with full details")
                return companies

            except Exception as e:
                logger.error(f"[Maps/Browser] Error: {e}")
                try:
                    await page.screenshot(path="debug_maps.png")
                except Exception:
                    pass
                return []
            finally:
                await browser.close()
