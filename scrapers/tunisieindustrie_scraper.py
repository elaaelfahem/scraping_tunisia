"""
Scraper for TunisieIndustrie (tunisieindustrie.nat.tn/fr/dbi.asp).

Form fields (POST to dbi.asp):
  secteur, branche, Denomination, Gouvernorat, delegation, action=search
Results come back as an HTML table inside the same ASP page.
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
    "Accept-Language": "fr-FR,fr;q=0.9,ar;q=0.8",
    "Referer": "https://www.tunisieindustrie.nat.tn/fr/dbi.asp",
}

DBI_URL = "https://www.tunisieindustrie.nat.tn/fr/dbi.asp"

# Gouvernorat numeric IDs as used in the dbi.asp select field
GOUVERNORAT_MAP: dict[str, str] = {
    "tunis":       "01",
    "bizerte":     "02",
    "beja":        "03",
    "jendouba":    "04",
    "le kef":      "05",
    "kasserine":   "06",
    "gafsa":       "07",
    "medenine":    "08",
    "gabes":       "09",
    "sfax":        "10",
    "kairouan":    "11",
    "sousse":      "12",
    "nabeul":      "13",
    "monastir":    "14",
    "mahdia":      "15",
    "siliana":     "16",
    "sidi bouzid": "17",
    "zaghouan":    "18",
    "tozeur":      "19",
    "tataouine":   "20",
    "kebili":      "21",
    "ariana":      "22",
    "ben arous":   "23",
    "manouba":     "24",
}


class TunisieIndustrieScraper:
    """Scraper for the official Tunisian industrial enterprise database."""

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

        gouv = GOUVERNORAT_MAP.get(city.lower(), city.strip())

        try:
            # Get the form page first to capture any hidden session tokens
            form_hidden = self._get_hidden_fields(session)
            results = self._search_and_paginate(keyword, gouv, form_hidden, max_pages, session)
        except Exception as e:
            logger.error(f"[TunisieIndustrie] Error: {e}")

        if area:
            area_lower = area.lower()
            results = [r for r in results if area_lower in (r.get("address") or "").lower()]

        logger.info(f"[TunisieIndustrie] Total: {len(results)}")
        return results

    def _get_hidden_fields(self, session: requests.Session) -> dict:
        hidden: dict = {}
        try:
            resp = session.get(DBI_URL, timeout=15)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")
                for inp in soup.find_all("input", type="hidden"):
                    name = inp.get("name", "")
                    if name:
                        hidden[name] = inp.get("value", "")
        except Exception as e:
            logger.warning(f"[TunisieIndustrie] Could not fetch form: {e}")
        return hidden

    def _search_and_paginate(
        self,
        keyword: str,
        gouvernorat: str,
        form_hidden: dict,
        max_pages: int,
        session: requests.Session,
    ) -> list[dict]:
        results: list[dict] = []

        payload = {
            **form_hidden,
            "action": "search",
            "Gouvernorat": gouvernorat,
            "Denomination": "",
            "secteur": "",
            "branche": "",
            "produit": "",
            "District": "",
            "delegation": "",
            "pays": "",
            "regime": "",
        }

        for page_num in range(1, max_pages + 1):
            if page_num > 1:
                payload["page"] = page_num

            logger.info(f"[TunisieIndustrie] Fetching page {page_num} (gouvernorat={gouvernorat})")
            try:
                resp = session.post(DBI_URL, data=payload, timeout=20)
                if resp.status_code != 200:
                    break

                soup = BeautifulSoup(resp.text, "lxml")
                items = self._parse_results(soup)
                if not items:
                    break
                results.extend(items)
                logger.info(f"[TunisieIndustrie] Page {page_num}: {len(items)} companies")
                time.sleep(1.5)

                if not self._has_next_page(soup, page_num):
                    break
            except Exception as e:
                logger.warning(f"[TunisieIndustrie] Page {page_num} error: {e}")
                break

        return results

    def _parse_results(self, soup: BeautifulSoup) -> list[dict]:
        items = []
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue
            headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
            if not headers or len(headers) < 2:
                continue

            col_map = self._map_columns(headers)
            if "name" not in col_map:
                continue

            for row in rows[1:]:
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue
                name = self._cell_text(cells, col_map.get("name"))
                if not name or len(name) < 2:
                    continue
                items.append({
                    "name": name,
                    "sector": self._cell_text(cells, col_map.get("sector")),
                    "address": self._cell_text(cells, col_map.get("address")),
                    "city": self._cell_text(cells, col_map.get("city")),
                    "phone": self._cell_text(cells, col_map.get("phone")),
                    "email": self._cell_text(cells, col_map.get("email")),
                    "employee_count": self._cell_text(cells, col_map.get("employees")),
                    "source": "tunisieindustrie",
                })
        return items

    def _map_columns(self, headers: list[str]) -> dict:
        col_map: dict = {}
        for i, h in enumerate(headers):
            # Normalize: strip accents and lowercase for matching
            hn = h.encode("ascii", "ignore").decode().lower()
            if any(k in hn for k in ["raison", "nomination", "nom", "soci", "entreprise"]):
                col_map.setdefault("name", i)
            elif any(k in hn for k in ["activit", "secteur", "branche"]):
                col_map.setdefault("sector", i)
            elif any(k in hn for k in ["adresse", "address", "si"]) and "t" not in hn[:3]:
                col_map.setdefault("address", i)
            elif any(k in hn for k in ["gouvernorat", "l gation", "gation", "ville", "district", "r gion"]):
                col_map.setdefault("city", i)
            elif any(k in hn for k in ["t l", "phone", "tel"]):
                col_map.setdefault("phone", i)
            elif "email" in hn or "mail" in hn or "courriel" in hn:
                col_map.setdefault("email", i)
            elif any(k in hn for k in ["emploi", "effectif", "personnel"]):
                col_map.setdefault("employees", i)
        return col_map

    @staticmethod
    def _cell_text(cells: list, index: Optional[int]) -> str:
        if index is None or index >= len(cells):
            return ""
        return cells[index].get_text(strip=True)

    def _has_next_page(self, soup: BeautifulSoup, current_page: int) -> bool:
        next_link = soup.find("a", string=re.compile(str(current_page + 1)))
        return bool(next_link)


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    scraper = TunisieIndustrieScraper()
    results = scraper.search("industrie", city="Sfax")
    print(f"\n=== {len(results)} companies found ===")
    for r in results[:5]:
        print(json.dumps(r, ensure_ascii=False, indent=2))
