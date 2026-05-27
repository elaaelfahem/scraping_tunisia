import re
import logging
import httpx
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class WebsiteScraper:
    """
    Scrapes a company's website to extract contact info and social links.
    """

    # Common social media patterns
    SOCIAL_PATTERNS = {
        "facebook_url": r"https?://(?:www\.)?facebook\.com/[\w\.-]+",
        "linkedin_url": r"https?://(?:www\.)?linkedin\.com/(?:company|in)/[\w\.-]+",
        "instagram_url": r"https?://(?:www\.)?instagram\.com/[\w\.-]+",
        "twitter_url": r"https?://(?:www\.)?(?:twitter|x)\.com/[\w\.-]+",
    }

    # Regex for emails
    EMAIL_PATTERN = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    
    # Regex for Tunisian phone numbers (common formats)
    PHONE_PATTERN = r'(?:\+216|00216|[ \(\)])?[24579][0-9](?:[ \(\)])?[0-9]{3}(?:[ \(\)])?[0-9]{3}'

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
                # 1. Scrape Homepage
                await self._scrape_page(client, url, results)
                
                # 2. If info still missing, find and scrape secondary pages (Contact, About)
                if not results["email"] or not results["facebook_url"]:
                    soup = await self._get_soup(client, url)
                    if soup:
                        secondary_links = self._find_secondary_links(soup, url)
                        for page_url in secondary_links:
                            if any(x not in results or not results[x] for x in ["email", "facebook_url", "phone"]):
                                logger.info(f"Checking secondary page: {page_url}")
                                await self._scrape_page(client, page_url, results)

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

            # Extract Description (if not already found)
            if not results.get("description"):
                meta_desc = soup.find("meta", attrs={"name": "description"}) or \
                            soup.find("meta", attrs={"property": "og:description"})
                if meta_desc:
                    results["description"] = meta_desc.get("content", "").strip()

            # Extract Emails
            emails = re.findall(self.EMAIL_PATTERN, html)
            if emails:
                valid_emails = [e for e in emails if not e.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp'))]
                if valid_emails and not results["email"]:
                    results["email"] = valid_emails[0]

            # Extract Phones
            phones = re.findall(self.PHONE_PATTERN, html)
            if phones and not results["phone"]:
                # Clean up the phone number
                clean_phone = re.sub(r'[^0-9+]', '', phones[0])
                if len(clean_phone) >= 8:
                    results["phone"] = clean_phone

            # Extract Social Links
            for key, pattern in self.SOCIAL_PATTERNS.items():
                if not results.get(key):
                    matches = re.findall(pattern, html)
                    if matches:
                        results[key] = matches[0]

        except Exception:
            pass

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
                    from urllib.parse import urljoin
                    links.append(urljoin(base_url, a["href"]))
                elif href.startswith("http"):
                    links.append(a["href"])
        return list(set(links))[:3] # Limit to top 3 relevant links

if __name__ == "__main__":
    import asyncio
    scraper = WebsiteScraper()
    async def test():
        res = await scraper.scrape_website("https://www.vermeg.com")
        print(res)
    asyncio.run(test())
