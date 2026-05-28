
"""
Scraper for the Tunisian Registre National des Entreprises (RNE).

Strategy
--------
The RNE portal is an Angular SPA that uses INFINITE SCROLL — there are no
paginator buttons. Each time the user scrolls to the bottom, 10 more rows are
appended to the results table. We replicate this by:

  1. Navigate to root and wait for Angular to bootstrap.
  2. Click "Recherche" → "Recherche sociétés".
  3. Fill DÉNOMINATION (and optionally GOUVERNORAT) and dispatch Angular events.
  4. Click Recherche and wait for the first 10 rows.
  5. Repeatedly scroll to the bottom and wait for more rows to appear.
  6. Stop when the row count stops growing (all results loaded).
  7. Extract all rows at once.
"""

import asyncio
import logging
import sys
from typing import Optional

from playwright.async_api import async_playwright, Page

# ── UTF-8 console output (Windows cp1252 chokes on Arabic/French) ─────────────
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logger = logging.getLogger(__name__)

ROOT_URL = "https://www.registre-entreprises.tn/rne-public/"

# Tunisian governorate names as they appear in the RNE UI (French)
CITY_TO_GOVERNORATE: dict[str, str] = {
    "tunis": "Tunis",
    "ariana": "Ariana",
    "ben arous": "Ben Arous",
    "manouba": "Manouba",
    "nabeul": "Nabeul",
    "zaghouan": "Zaghouan",
    "bizerte": "Bizerte",
    "beja": "Béja",
    "béja": "Béja",
    "jendouba": "Jendouba",
    "le kef": "Le Kef",
    "kef": "Le Kef",
    "siliana": "Siliana",
    "sousse": "Sousse",
    "monastir": "Monastir",
    "mahdia": "Mahdia",
    "sfax": "Sfax",
    "kairouan": "Kairouan",
    "kasserine": "Kasserine",
    "sidi bouzid": "Sidi Bouzid",
    "gabes": "Gabès",
    "gabès": "Gabès",
    "mednine": "Médenine",
    "médenine": "Médenine",
    "tataouine": "Tataouine",
    "gafsa": "Gafsa",
    "tozeur": "Tozeur",
    "kebili": "Kébili",
    "kébili": "Kébili",
}

# Safety cap — 5 000 companies per query (500 scrolls × 10 rows)
MAX_SCROLL_ROUNDS = 500
SCROLL_WAIT_SEC = 1.5          # seconds to wait after each scroll
MAX_EMPTY_SCROLLS = 5          # stop after this many consecutive scrolls with no new rows


class RNEScraper:
    """Scraper for the Tunisian Registre National des Entreprises (RNE).

    Uses Playwright to drive the Angular SPA via infinite scroll.
    """

    def __init__(self) -> None:
        self.base_url = ROOT_URL

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    async def scrape_by_keyword(
        self,
        keyword: str,
        city: Optional[str] = None,
        max_rows: int = 5000,
    ) -> list[dict]:
        """Search RNE by company name keyword and optional city/governorate.

        Returns a list of company dicts with keys:
            legal_name, commercial_name, arabic_commercial_name,
            arabic_denomination
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
            )
            page = await context.new_page()

            logger.info(f"[RNE] Searching keyword='{keyword}' city='{city}'")
            print(f"[RNE] Searching keyword='{keyword}' city='{city}'")

            try:
                results = await self._run_search(page, keyword, city, max_rows)
                logger.info(f"[RNE] Total extracted: {len(results)} companies")
                print(f"[RNE] Total extracted: {len(results)} companies")
                return results

            except Exception as exc:
                logger.error(f"[RNE] Fatal error: {exc}", exc_info=True)
                print(f"[RNE] Fatal error: {exc}")
                try:
                    await page.screenshot(path="rne_error.png")
                except Exception:
                    pass
                return []

            finally:
                await browser.close()

    # ─────────────────────────────────────────────────────────────────────────
    # Internal navigation + search
    # ─────────────────────────────────────────────────────────────────────────

    async def _run_search(
        self, page: Page, keyword: str, city: Optional[str], max_rows: int
    ) -> list[dict]:
        """Navigate to the search form, fill it, and collect all rows via scroll."""

        # Step 1 — Load root, wait for Angular
        logger.info("[RNE] Navigating to root URL…")
        await page.goto(self.base_url, wait_until="domcontentloaded", timeout=30_000)
        logger.info("[RNE] Waiting for Angular nav to render…")
        await page.wait_for_selector("li:has-text('Recherche')", timeout=15_000)

        # Step 2 — Open the Recherche menu
        logger.info("[RNE] Clicking 'Recherche' menu…")
        await page.click("li:has-text('Recherche')", timeout=10_000)

        # Step 3 — Click "Recherche sociétés"
        await page.wait_for_selector(".sub-menu-container", timeout=8_000)
        await page.click(".sub-menu-item:has-text('Recherche soci')", timeout=5_000)

        # Step 4 — Wait for DÉNOMINATION input
        logger.info("[RNE] Waiting for search form…")
        denom_locator = page.locator(
            "mat-form-field:has-text('DÉNOMINATION') input, "
            "mat-form-field:has-text('Dénomination') input"
        ).first
        await denom_locator.wait_for(state="visible", timeout=12_000)

        # Step 5 — Fill DÉNOMINATION
        logger.info(f"[RNE] Filling DÉNOMINATION = '{keyword}'")
        await denom_locator.fill(keyword)
        await self._dispatch_angular_events(denom_locator)

        # Step 6 — Optionally fill GOUVERNORAT
        if city:
            gov_name = CITY_TO_GOVERNORATE.get(city.lower(), city.title())
            await self._fill_gouvernorat(page, gov_name)

        await asyncio.sleep(0.5)

        # Step 7 — Click Recherche button (retry if still disabled)
        recherche_btn = page.locator("button:has-text('Recherche')").first
        for attempt in range(3):
            is_disabled = await recherche_btn.get_attribute("disabled") is not None
            if not is_disabled:
                break
            logger.debug(f"[RNE] Button disabled, retrying event dispatch (attempt {attempt+1})…")
            await self._dispatch_angular_events(denom_locator)
            await asyncio.sleep(0.8)

        logger.info("[RNE] Clicking Recherche button…")
        await recherche_btn.click()

        # Step 8 — Wait for first results batch
        logger.info("[RNE] Waiting for results table…")
        await page.wait_for_selector("table tbody tr", timeout=20_000)
        await asyncio.sleep(1)

        # Log the result count reported by the server
        result_label = await self._read_result_count(page)
        logger.info(f"[RNE] Server reports: {result_label}")
        print(f"[RNE] Server reports: {result_label}")

        # Step 9 — Infinite scroll to load all rows
        all_rows = await self._scroll_and_collect(page, max_rows)
        return all_rows

    # ─────────────────────────────────────────────────────────────────────────
    # Infinite scroll collection
    # ─────────────────────────────────────────────────────────────────────────

    async def _scroll_and_collect(self, page: Page, max_rows: int) -> list[dict]:
        """Keep scrolling to the bottom until no new rows appear, then extract."""
        prev_count = 0
        empty_scroll_count = 0

        for round_num in range(MAX_SCROLL_ROUNDS):
            current_count = await page.locator("table tbody tr").count()

            if current_count >= max_rows:
                logger.info(f"[RNE] Reached max_rows cap ({max_rows}). Stopping scroll.")
                break

            if current_count > prev_count:
                logger.info(f"[RNE] Scroll {round_num}: {current_count} rows loaded…")
                print(f"[RNE] Rows loaded: {current_count}", end="\r")
                empty_scroll_count = 0
            else:
                empty_scroll_count += 1
                if empty_scroll_count >= MAX_EMPTY_SCROLLS:
                    logger.info(
                        f"[RNE] No new rows after {MAX_EMPTY_SCROLLS} consecutive scrolls. Done."
                    )
                    break

            prev_count = current_count

            # Scroll to the very bottom of the page
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(SCROLL_WAIT_SEC)

        final_count = await page.locator("table tbody tr").count()
        print(f"\n[RNE] Extracting {final_count} rows…")
        logger.info(f"[RNE] Extracting {final_count} rows from DOM…")

        return await self._extract_all_rows(page)

    # ─────────────────────────────────────────────────────────────────────────
    # DOM extraction
    # ─────────────────────────────────────────────────────────────────────────

    async def _extract_all_rows(self, page: Page) -> list[dict]:
        """Extract every visible row from the results table."""
        return await page.evaluate("""
            () => {
                const rows = document.querySelectorAll('table tbody tr');
                const text = el => el ? (el.innerText || el.textContent || '').trim() : '';
                return Array.from(rows)
                    .map(row => {
                        const cells = row.querySelectorAll('td');
                        return {
                            legal_name:             text(cells[0]),
                            commercial_name:        text(cells[1]),
                            arabic_commercial_name: text(cells[2]),
                            arabic_denomination:    text(cells[3]),
                        };
                    })
                    .filter(r => r.legal_name !== '');
            }
        """)

    async def _read_result_count(self, page: Page) -> str:
        """Return the server-side result count string, e.g. '10/95735'."""
        try:
            # The count appears in text like "Résultat de la recherche: 10/95735"
            el = page.locator("text=/Résultat de la recherche/").first
            if await el.is_visible():
                full_text = await el.inner_text()
                # Extract the "X/Y" portion
                import re
                m = re.search(r"(\d+/\d+)", full_text)
                return m.group(1) if m else full_text.strip()
        except Exception:
            pass
        return "unknown"

    # ─────────────────────────────────────────────────────────────────────────
    # Angular form helpers
    # ─────────────────────────────────────────────────────────────────────────

    async def _dispatch_angular_events(self, locator) -> None:
        """Dispatch input/change/keyup so Angular reactive form registers value."""
        await locator.evaluate(
            "el => {"
            "  el.dispatchEvent(new Event('input', { bubbles: true }));"
            "  el.dispatchEvent(new Event('change', { bubbles: true }));"
            "  el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));"
            "}"
        )

    async def _fill_gouvernorat(self, page: Page, gov_name: str) -> None:
        """Fill the Gouvernorat autocomplete/select field if present."""
        try:
            gov_locator = page.locator(
                "mat-form-field:has-text('GOUVERNORAT') input, "
                "mat-form-field:has-text('Gouvernorat') input"
            ).first
            if not await gov_locator.is_visible():
                logger.debug("[RNE] Gouvernorat field not visible — skipping.")
                return

            logger.info(f"[RNE] Setting Gouvernorat = '{gov_name}'")
            await gov_locator.click()
            await gov_locator.fill(gov_name)
            await self._dispatch_angular_events(gov_locator)
            await asyncio.sleep(0.8)

            # If Angular renders a dropdown option, click it
            try:
                option = page.locator(f"mat-option:has-text('{gov_name}')").first
                if await option.is_visible():
                    await option.click()
                    logger.debug(f"[RNE] mat-option selected: {gov_name}")
            except Exception:
                pass

        except Exception as exc:
            logger.debug(f"[RNE] Gouvernorat fill skipped: {exc}")


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    async def _test():
        scraper = RNEScraper()
        # Test with a specific city so it exercises the Gouvernorat field too
        results = await scraper.scrape_by_keyword("STE", city="Tunis", max_rows=50)
        print(f"\n=== {len(results)} companies scraped ===")
        for r in results[:5]:
            # Encode safely for Windows console
            safe = {k: v.encode("utf-8", errors="replace").decode("utf-8") for k, v in r.items()}
            print(json.dumps(safe, ensure_ascii=False))

    asyncio.run(_test())
