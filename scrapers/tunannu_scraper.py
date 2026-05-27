"""
Scraper for TunAnnu (tunannu.com).

NOTE: tunannu.com only shows registration and login forms with no public directory.
This scraper returns an empty list immediately.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class TunAnnuScraper:
    """Stub scraper — tunannu.com requires login, no public listings."""

    def search(
        self,
        keyword: str,
        city: str,
        area: Optional[str] = None,
        max_pages: int = 5,
    ) -> list[dict]:
        logger.warning("[TunAnnu] tunannu.com requires login — no public directory available. Skipping.")
        return []
