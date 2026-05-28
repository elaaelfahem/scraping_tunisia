import re
import json
import logging
import httpx
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any
from urllib.parse import urlparse, urljoin

logger = logging.getLogger(__name__)


class WebsiteScraper:
    """
    Scrapes a company's website to extract contact info and social links.
    """

    SOCIAL_PATTERNS = {
        "facebook_url": r"https?://(?:www\.)?facebook\.com/(?!sharer|share|dialog|plugins|tr\b)[\w\.-]+",
        "linkedin_url": r"https?://(?:www\.)?linkedin\.com/(?:company|in)/[\w\.-]+",
        "instagram_url": r"https?://(?:www\.)?instagram\.com/[\w\.-]+",
        "twitter_url": r"https?://(?:www\.)?(?:twitter|x)\.com/[\w\.-]+",
    }

    EMAIL_PATTERN = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    PHONE_PATTERN = r'(?:\+216|00216|[ \(\)])?[24579][0-9](?:[ \(\)])?[0-9]{3}(?:[ \(\)])?[0-9]{3}'

    _EMAIL_PREFIXES = ["contact", "info", "commercial", "direction", "admin", "hello", "support", "accueil"]

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    async def scrape_website(self, url: str) -> Dict[str, Any]:
        """Extract info from the given URL and potentially secondary pages."""
        if not url:
            return {}

        if not url.startswith("http"):
            url = "http://" + url

        results = {
            "email": None,
            "phone": None,
            "facebook_url": None,
            "linkedin_url": None,
            "instagram_url": None,
            "twitter_url": None,
            "description": None,
        }

        try:
            async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout, follow_redirects=True, verify=False) as client:
                # 1. Scrape homepage
                await self._scrape_page(client, url, results)

                # 2. Secondary pages (Contact, About) if still missing
                if not results["email"] or not results["facebook_url"] or not results["linkedin_url"]:
                    soup = await self._get_soup(client, url)
                    if soup:
                        for page_url in self._find_secondary_links(soup, url):
                            if any(not results[k] for k in ["email", "facebook_url", "linkedin_url", "phone"]):
                                logger.info(f"Checking secondary page: {page_url}")
                                await self._scrape_page(client, page_url, results)

                # 3. Last resort: guess from domain
                slug = self._domain_slug(url)
                if slug:
                    if not results["email"]:
                        guessed = self._guess_email_from_domain(url)
                        if guessed:
                            logger.info(f"Guessed email for {url}: {guessed}")
                            results["email"] = guessed
                    if not results["linkedin_url"]:
                        guessed = await self._guess_linkedin(client, slug)
                        if guessed:
                            logger.info(f"Guessed LinkedIn for {url}: {guessed}")
                            results["linkedin_url"] = guessed
                    if not results["facebook_url"]:
                        guessed = await self._guess_facebook(client, slug)
                        if guessed:
                            logger.info(f"Guessed Facebook for {url}: {guessed}")
                            results["facebook_url"] = guessed

                return results

        except Exception as e:
            logger.error(f"Error scraping {url}: {e}")
            return results

    async def _scrape_page(self, client: httpx.AsyncClient, url: str, results: Dict[str, Any]):
        try:
            response = await client.get(url)
            if response.status_code != 200:
                return

            html = response.text
            soup = BeautifulSoup(html, "lxml")

            # Description
            if not results.get("description"):
                meta_desc = soup.find("meta", attrs={"name": "description"}) or \
                            soup.find("meta", attrs={"property": "og:description"})
                if meta_desc:
                    results["description"] = meta_desc.get("content", "").strip()

            # Email
            emails = re.findall(self.EMAIL_PATTERN, html)
            if emails:
                valid = [e for e in emails if not e.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp'))]
                if valid and not results["email"]:
                    results["email"] = valid[0]

            # Phone
            phones = re.findall(self.PHONE_PATTERN, html)
            if phones and not results["phone"]:
                clean = re.sub(r'[^0-9+]', '', phones[0])
                if len(clean) >= 8:
                    results["phone"] = clean

            # Social links — three layers, most reliable first
            self._extract_from_jsonld(soup, results)   # JSON-LD sameAs (best)
            self._extract_from_anchors(soup, results)  # explicit <a> tags
            for key, pattern in self.SOCIAL_PATTERNS.items():  # raw HTML regex fallback
                if not results.get(key):
                    matches = re.findall(pattern, html)
                    if matches:
                        results[key] = matches[0].rstrip("/")

        except Exception:
            pass

    def _extract_from_jsonld(self, soup: BeautifulSoup, results: Dict[str, Any]):
        """Parse JSON-LD Organization sameAs fields — most reliable source of social URLs."""
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(tag.string or "")
                entries = data if isinstance(data, list) else [data]
                for entry in entries:
                    same_as = entry.get("sameAs", [])
                    if isinstance(same_as, str):
                        same_as = [same_as]
                    for u in same_as:
                        self._classify_social_url(u, results)
            except Exception:
                continue

    def _extract_from_anchors(self, soup: BeautifulSoup, results: Dict[str, Any]):
        """Scan <a> tags directly — catches encoded/formatted URLs that regex misses."""
        for a in soup.find_all("a", href=True):
            self._classify_social_url(a["href"], results)

    def _classify_social_url(self, url: str, results: Dict[str, Any]):
        url = url.strip()
        if not url.startswith("http"):
            return
        for key, pattern in self.SOCIAL_PATTERNS.items():
            if not results.get(key) and re.match(pattern, url):
                results[key] = url.rstrip("/")
                break

    def _domain_slug(self, url: str) -> Optional[str]:
        """'https://www.vermeg.com/...' → 'vermeg'"""
        try:
            host = urlparse(url).hostname or ""
            if host.startswith("www."):
                host = host[4:]
            slug = host.split(".")[0]
            return slug if len(slug) > 2 else None
        except Exception:
            return None

    async def _guess_linkedin(self, client: httpx.AsyncClient, slug: str) -> Optional[str]:
        """Try linkedin.com/company/{slug} — valid if the final URL still contains the slug."""
        candidate = f"https://www.linkedin.com/company/{slug}"
        try:
            resp = await client.head(candidate, timeout=6)
            if f"/company/{slug}" in str(resp.url).lower():
                return candidate
        except Exception:
            pass
        return None

    async def _guess_facebook(self, client: httpx.AsyncClient, slug: str) -> Optional[str]:
        """Try facebook.com/{slug} — invalid if redirected to login or FB homepage."""
        candidate = f"https://www.facebook.com/{slug}"
        try:
            resp = await client.head(candidate, timeout=6)
            final = str(resp.url).rstrip("/")
            if "login" in final or final in ("https://www.facebook.com", "https://facebook.com"):
                return None
            return candidate
        except Exception:
            pass
        return None

    def _guess_email_from_domain(self, url: str) -> Optional[str]:
        """Try common email prefixes for the website's domain, verified by MX record."""
        try:
            domain = urlparse(url).hostname
            if not domain:
                return None
            if domain.startswith("www."):
                domain = domain[4:]
            import dns.resolver
            try:
                dns.resolver.resolve(domain, "MX")
            except Exception:
                return None  # Domain has no MX record — skip
            return f"{self._EMAIL_PREFIXES[0]}@{domain}"
        except Exception:
            pass
        return None

    async def _get_soup(self, client: httpx.AsyncClient, url: str) -> Optional[BeautifulSoup]:
        try:
            response = await client.get(url)
            if response.status_code == 200:
                return BeautifulSoup(response.text, "lxml")
        except Exception:
            pass
        return None

    def _find_secondary_links(self, soup: BeautifulSoup, base_url: str) -> list[str]:
        links = []
        keywords = ["contact", "about", "propos", "equipe", "team", "mention"]
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            text = a.get_text().lower()
            if any(k in href or k in text for k in keywords):
                if href.startswith("/"):
                    links.append(urljoin(base_url, a["href"]))
                elif href.startswith("http"):
                    links.append(a["href"])
        return list(set(links))[:3]


if __name__ == "__main__":
    import asyncio
    scraper = WebsiteScraper()
    async def test():
        res = await scraper.scrape_website("https://www.vermeg.com")
        print(res)
    asyncio.run(test())
