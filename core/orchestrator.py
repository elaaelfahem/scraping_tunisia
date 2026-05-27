import asyncio
import logging
import os
import re
from typing import Optional
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()

from playwright.async_api import async_playwright
from scrapers.maps_scraper import GoogleMapsScraper
from scrapers.rne_scraper import RNEScraper
from scrapers.tunisiayp_scraper import TunisiaYPScraper
from scrapers.b2bmap_scraper import B2BMapScraper
from scrapers.bizpages_scraper import BizPagesScraper
from scrapers.kompass_scraper import KompassScraper
from scrapers.website_scraper import WebsiteScraper
from scrapers.tunisieindex_scraper import TunisieIndexScraper
from scrapers.afrikta_scraper import AfrikaScraper
from scrapers.tunisieguide_scraper import TunisieGuideScraper
from scrapers.tunisieindustrie_scraper import TunisieIndustrieScraper
from scrapers.b2btn_scraper import B2BTnScraper
from scrapers.tunannu_scraper import TunAnnuScraper
from scrapers.pagex_scraper import PageXScraper
from scrapers.ccis_scraper import CCISScraper
from scrapers.annuario_scraper import AnnuarioScraper
from scrapers.scribd_scraper import ScribdScraper
from core.deduplication import DataIntegrator
from core.filters import filter_companies, sanitize_company_data
from core.database import Base, Company
from sqlalchemy import func

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tunisian_companies.db")
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ── Normalization helpers ─────────────────────────────────────────────────

def _normalize_area(area: Optional[str]) -> Optional[str]:
    """Normalize area/delegation names for consistent storage.
    E.g. 'marsa' -> 'La Marsa', 'la marsa' -> 'La Marsa'.
    """
    if not area:
        return None
    area = area.strip()
    if not area:
        return None

    # Common Tunisian area aliases -> canonical names
    ALIASES: dict[str, str] = {
        "marsa": "La Marsa",
        "la marsa": "La Marsa",
        "goulette": "La Goulette",
        "la goulette": "La Goulette",
        "soukra": "La Soukra",
        "la soukra": "La Soukra",
        "manouba": "La Manouba",
        "la manouba": "La Manouba",
        "centre ville": "Centre Ville",
        "bab bhar": "Bab Bhar",
        "lac": "Lac",
        "lac 1": "Lac 1",
        "lac 2": "Lac 2",
    }

    key = area.lower()
    if key in ALIASES:
        return ALIASES[key]

    # Default: title-case
    return area.title()


async def run_orchestration(
    city: str,
    sector: str = "All",
    area: Optional[str] = None,
    output_file: str = "companies.xlsx",
    sources: Optional[list[str]] = None,
    enrich_website: bool = True,
) -> str:
    """
    Run all scrapers for the given city/area/sector and export results.
    Returns path to the exported file.
    """
    if sources is None:
        sources = [
            "maps", "rne", "tunisiayp", "b2bmap", "bizpages", "kompass",
            "tunisieindex", "afrikta", "tunisieguide", "tunisieindustrie",
            "b2btn", "tunannu", "pagex", "ccis", "annuario_it_tn", "scribd",
        ]

    is_all_sectors = not sector or sector.lower() == "all"
    
    # If "All" is selected, we iterate through broad keywords to get better coverage
    # because most scrapers require a keyword to return results.
    BROAD_KEYWORDS = ["Entreprises", "Services", "Industrie", "Commerce", "Boutique"] if is_all_sectors else [sector]

    location_label = f"{area}, {city}" if area else city
    logger.info(f"=== Starting scrape: '{sector}' in '{location_label}' ===")
    logger.info(f"Active sources: {sources}")

    from core.database import run_migrations
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)
    db = SessionLocal()
    integrator = DataIntegrator(db)

    # ── Google Maps ──────────────────────────────────────────────────────────
    if "maps" in sources:
        logger.info("[Step 1/7] Google Maps")
        maps_scraper = GoogleMapsScraper()
        for kw in BROAD_KEYWORDS:
            query = f"{kw} in {location_label}, Tunisia"
            logger.info(f"  -> Searching keyword: {kw}")
            maps_results = filter_companies(
                await maps_scraper.search_companies(query, city=city, area=area)
            )
            for item in maps_results:
                raw_area = area or item.get("area") or item.get("delegation")
                category = item.get("category") or item.get("type") or ""
                integrator.add_or_update_company({
                    "name": item.get("name", ""),
                    "city": city,
                    "area": _normalize_area(raw_area),
                    "sector": category or (None if is_all_sectors else kw),
                    "field": category,  # Maps "type" is the activity field
                    "address": item.get("address", ""),
                    "phone": item.get("phone", ""),
                    "website": item.get("website", ""),
                    "rating": float(item["rating"]) if item.get("rating") else None,
                    "review_count": _parse_int(item.get("reviews")),
                    "latitude": item.get("latitude"),
                    "longitude": item.get("longitude"),
                    "google_maps_url": item.get("google_maps_url", ""),
                    "source_data": {"google_maps": item},
                })

    # ── RNE ─────────────────────────────────────────────────────────────────
    if "rne" in sources:
        logger.info("[Step 2/7] RNE")
        rne_scraper = RNEScraper()
        # Pass city so the scraper uses the Gouvernorat dropdown to filter at source.
        # RNE results only contain name fields (no address), so address-based
        # filtering is skipped — city filtering is handled inside the scraper.
        rne_results = await rne_scraper.scrape_by_keyword(BROAD_KEYWORDS[0], city=city)
        for item in rne_results:
            if not item.get("legal_name"):
                continue
            raw_area = area or item.get("area") or item.get("delegation")
            # Avoid empty registration_number — unique constraint would fail
            reg_num = (item.get("registration_number") or "").strip() or None
            integrator.add_or_update_company({
                "name": item["legal_name"],
                "legal_name": item["legal_name"],
                "registration_number": reg_num,
                "address": item.get("address", ""),
                "city": city,
                "area": _normalize_area(raw_area),
                "sector": item.get("sector") or item.get("category") or (None if is_all_sectors else sector),
                "field": item.get("field") or item.get("activity"),
                "source_data": {"rne": item},
            })

    # ── TunisiaYP ────────────────────────────────────────────────────────────
    if "tunisiayp" in sources:
        logger.info("[Step 3/7] TunisiaYP")
        typ_scraper = TunisiaYPScraper()
        for kw in BROAD_KEYWORDS[:3]: # Limit for Yellow Pages
            typ_results = filter_companies(typ_scraper.search(kw, city, area, enrich_details=True))
            for item in typ_results:
                raw_area = area or item.get("area") or item.get("delegation")
                category = item.get("category") or item.get("sector") or ""
                integrator.add_or_update_company({
                    "name": item["name"],
                    "city": city,
                    "area": _normalize_area(raw_area),
                    "sector": category or (None if is_all_sectors else kw),
                    "field": category,
                    "address": item.get("address", ""),
                    "phone": item.get("phone", ""),
                    "email": item.get("email", ""),
                    "website": item.get("website", ""),
                    "facebook_url": item.get("facebook_url", ""),
                    "linkedin_url": item.get("linkedin_url", ""),
                    "source_data": {"tunisiayp": item},
                })

    # ── B2BMap ───────────────────────────────────────────────────────────────
    if "b2bmap" in sources:
        logger.info("[Step 4/7] B2BMap")
        b2b_scraper = B2BMapScraper()
        for kw in BROAD_KEYWORDS[:2]:
            b2b_results = filter_companies(b2b_scraper.search(kw, city, area))
            for item in b2b_results:
                raw_area = area or item.get("area") or item.get("delegation")
                category = item.get("sector") or item.get("category") or ""
                integrator.add_or_update_company({
                    "name": item["name"],
                    "city": city,
                    "area": _normalize_area(raw_area),
                    "sector": category or (None if is_all_sectors else kw),
                    "field": category,
                    "address": item.get("address", ""),
                    "phone": item.get("phone", ""),
                    "email": item.get("email", ""),
                    "website": item.get("website", ""),
                    "facebook_url": item.get("facebook_url", ""),
                    "linkedin_url": item.get("linkedin_url", ""),
                    "source_data": {"b2bmap": item},
                })

    # ── BizPages ─────────────────────────────────────────────────────────────
    if "bizpages" in sources:
        logger.info("[Step 5/7] BizPages")
        biz_scraper = BizPagesScraper()
        for kw in BROAD_KEYWORDS[:2]:
            biz_results = filter_companies(biz_scraper.search(kw, city, area))
            for item in biz_results:
                raw_area = area or item.get("area") or item.get("delegation")
                category = item.get("sector") or item.get("category") or ""
                integrator.add_or_update_company({
                    "name": item["name"],
                    "city": city,
                    "area": _normalize_area(raw_area),
                    "sector": category or (None if is_all_sectors else kw),
                    "field": category,
                    "address": item.get("address", ""),
                    "phone": item.get("phone", ""),
                    "email": item.get("email", ""),
                    "website": item.get("website", ""),
                    "source_data": {"bizpages": item},
                })

    # ── Kompass ──────────────────────────────────────────────────────────────
    if "kompass" in sources:
        logger.info("[Step 6/7] Kompass")
        kompass_scraper = KompassScraper()
        for kw in BROAD_KEYWORDS[:2]:
            kompass_results = filter_companies(kompass_scraper.search(kw, city, area))
            for item in kompass_results:
                raw_area = area or item.get("area") or item.get("delegation")
                category = item.get("sector") or item.get("category") or ""
                integrator.add_or_update_company({
                    "name": item["name"],
                    "city": city,
                    "area": _normalize_area(raw_area),
                    "sector": category or (None if is_all_sectors else kw),
                    "field": category,
                    "address": item.get("address", ""),
                    "phone": item.get("phone", ""),
                    "website": item.get("website", ""),
                    "facebook_url": item.get("facebook_url", ""),
                    "linkedin_url": item.get("linkedin_url", ""),
                    "employee_count": item.get("employee_count", ""),
                    "source_data": {"kompass": item},
                })

    # ── TunisieIndex ─────────────────────────────────────────────────────────
    if "tunisieindex" in sources:
        logger.info("[Step 8] TunisieIndex")
        ti_scraper = TunisieIndexScraper()
        for kw in BROAD_KEYWORDS[:2]:
            ti_results = filter_companies(ti_scraper.search(kw, city, area))
            for item in ti_results:
                raw_area = area or item.get("area") or item.get("delegation")
                category = item.get("sector") or item.get("category") or ""
                integrator.add_or_update_company({
                    "name": item["name"],
                    "city": city,
                    "area": _normalize_area(raw_area),
                    "sector": category or (None if is_all_sectors else kw),
                    "field": category,
                    "address": item.get("address", ""),
                    "phone": item.get("phone", ""),
                    "website": item.get("website", ""),
                    "source_data": {"tunisieindex": item},
                })

    # ── Afrikta ───────────────────────────────────────────────────────────────
    if "afrikta" in sources:
        logger.info("[Step 9] Afrikta")
        afrikta_scraper = AfrikaScraper()
        for kw in BROAD_KEYWORDS[:2]:
            afrikta_results = filter_companies(afrikta_scraper.search(kw, city, area))
            for item in afrikta_results:
                raw_area = area or item.get("area") or item.get("delegation")
                category = item.get("sector") or item.get("category") or ""
                integrator.add_or_update_company({
                    "name": item["name"],
                    "city": city,
                    "area": _normalize_area(raw_area),
                    "sector": category or (None if is_all_sectors else kw),
                    "field": category,
                    "address": item.get("address", ""),
                    "phone": item.get("phone", ""),
                    "website": item.get("website", ""),
                    "facebook_url": item.get("facebook_url", ""),
                    "linkedin_url": item.get("linkedin_url", ""),
                    "source_data": {"afrikta": item},
                })

    # ── TunisieGuide ──────────────────────────────────────────────────────────
    if "tunisieguide" in sources:
        logger.info("[Step 10] TunisieGuide")
        tg_scraper = TunisieGuideScraper()
        for kw in BROAD_KEYWORDS[:2]:
            tg_results = filter_companies(tg_scraper.search(kw, city, area))
            for item in tg_results:
                raw_area = area or item.get("area") or item.get("delegation")
                category = item.get("sector") or item.get("category") or ""
                integrator.add_or_update_company({
                    "name": item["name"],
                    "city": city,
                    "area": _normalize_area(raw_area),
                    "sector": category or (None if is_all_sectors else kw),
                    "field": category,
                    "address": item.get("address", ""),
                    "phone": item.get("phone", ""),
                    "email": item.get("email", ""),
                    "website": item.get("website", ""),
                    "facebook_url": item.get("facebook_url", ""),
                    "linkedin_url": item.get("linkedin_url", ""),
                    "source_data": {"tunisieguide": item},
                })

    # ── TunisieIndustrie ──────────────────────────────────────────────────────
    if "tunisieindustrie" in sources:
        logger.info("[Step 11] TunisieIndustrie")
        tind_scraper = TunisieIndustrieScraper()
        for kw in BROAD_KEYWORDS[:2]:
            tind_results = filter_companies(tind_scraper.search(kw, city, area))
            for item in tind_results:
                raw_area = area or item.get("area") or item.get("city")
                category = item.get("sector") or item.get("category") or ""
                integrator.add_or_update_company({
                    "name": item["name"],
                    "city": city,
                    "area": _normalize_area(raw_area),
                    "sector": category or (None if is_all_sectors else kw),
                    "field": category,
                    "address": item.get("address", ""),
                    "phone": item.get("phone", ""),
                    "email": item.get("email", ""),
                    "employee_count": item.get("employee_count", ""),
                    "source_data": {"tunisieindustrie": item},
                })

    # ── B2B.tn ────────────────────────────────────────────────────────────────
    if "b2btn" in sources:
        logger.info("[Step 12] B2B.tn")
        b2btn_scraper = B2BTnScraper()
        for kw in BROAD_KEYWORDS[:2]:
            b2btn_results = filter_companies(await b2btn_scraper.search(kw, city, area))
            for item in b2btn_results:
                raw_area = area or item.get("area") or item.get("delegation")
                category = item.get("sector") or item.get("category") or ""
                integrator.add_or_update_company({
                    "name": item["name"],
                    "city": city,
                    "area": _normalize_area(raw_area),
                    "sector": category or (None if is_all_sectors else kw),
                    "field": category,
                    "address": item.get("address", ""),
                    "phone": item.get("phone", ""),
                    "email": item.get("email", ""),
                    "website": item.get("website", ""),
                    "facebook_url": item.get("facebook_url", ""),
                    "linkedin_url": item.get("linkedin_url", ""),
                    "source_data": {"b2btn": item},
                })

    # ── TunAnnu ───────────────────────────────────────────────────────────────
    if "tunannu" in sources:
        logger.info("[Step 13] TunAnnu")
        tunannu_scraper = TunAnnuScraper()
        for kw in BROAD_KEYWORDS[:2]:
            tunannu_results = filter_companies(tunannu_scraper.search(kw, city, area))
            for item in tunannu_results:
                raw_area = area or item.get("area") or item.get("delegation")
                category = item.get("sector") or item.get("category") or ""
                integrator.add_or_update_company({
                    "name": item["name"],
                    "city": city,
                    "area": _normalize_area(raw_area),
                    "sector": category or (None if is_all_sectors else kw),
                    "field": category,
                    "address": item.get("address", ""),
                    "phone": item.get("phone", ""),
                    "email": item.get("email", ""),
                    "website": item.get("website", ""),
                    "source_data": {"tunannu": item},
                })

    # ── PageX ─────────────────────────────────────────────────────────────────
    if "pagex" in sources:
        logger.info("[Step 14] PageX.tn")
        pagex_scraper = PageXScraper()
        for kw in BROAD_KEYWORDS[:2]:
            pagex_results = filter_companies(pagex_scraper.search(kw, city, area))
            for item in pagex_results:
                raw_area = area or item.get("area") or item.get("delegation")
                category = item.get("sector") or item.get("category") or ""
                integrator.add_or_update_company({
                    "name": item["name"],
                    "city": city,
                    "area": _normalize_area(raw_area),
                    "sector": category or (None if is_all_sectors else kw),
                    "field": category,
                    "address": item.get("address", ""),
                    "phone": item.get("phone", ""),
                    "email": item.get("email", ""),
                    "website": item.get("website", ""),
                    "source_data": {"pagex": item},
                })

    # ── CCIS ──────────────────────────────────────────────────────────────────
    if "ccis" in sources:
        logger.info("[Step 15] CCIS (Chambre de Commerce Sfax)")
        ccis_scraper = CCISScraper()
        for kw in BROAD_KEYWORDS[:2]:
            ccis_results = filter_companies(ccis_scraper.search(kw, city, area))
            for item in ccis_results:
                raw_area = area or item.get("area") or item.get("delegation")
                category = item.get("sector") or item.get("category") or ""
                integrator.add_or_update_company({
                    "name": item["name"],
                    "city": city,
                    "area": _normalize_area(raw_area),
                    "sector": category or (None if is_all_sectors else kw),
                    "field": category,
                    "address": item.get("address", ""),
                    "phone": item.get("phone", ""),
                    "email": item.get("email", ""),
                    "website": item.get("website", ""),
                    "source_data": {"ccis": item},
                })

    # ── Annuario Italia-Tunisia ───────────────────────────────────────────────
    if "annuario_it_tn" in sources:
        logger.info("[Step 16] Annuario Imprese Italia-Tunisia")
        ann_scraper = AnnuarioScraper()
        for kw in BROAD_KEYWORDS[:1]:
            ann_results = filter_companies(ann_scraper.search(kw, city, area))
            for item in ann_results:
                raw_area = area or item.get("area") or item.get("city")
                category = item.get("sector") or item.get("category") or ""
                integrator.add_or_update_company({
                    "name": item["name"],
                    "city": city,
                    "area": _normalize_area(raw_area),
                    "sector": category or (None if is_all_sectors else kw),
                    "field": category,
                    "address": item.get("address", ""),
                    "phone": item.get("phone", ""),
                    "email": item.get("email", ""),
                    "website": item.get("website", ""),
                    "source_data": {"annuario_it_tn": item},
                })

    # ── Scribd document ───────────────────────────────────────────────────────
    if "scribd" in sources:
        logger.info("[Step 17] Scribd company list document")
        scribd_scraper = ScribdScraper()
        scribd_results = filter_companies(await scribd_scraper.search(
            BROAD_KEYWORDS[0], city, area
        ))
        for item in scribd_results:
            raw_area = area or item.get("area") or item.get("delegation")
            integrator.add_or_update_company({
                "name": item["name"],
                "city": city,
                "area": _normalize_area(raw_area),
                "sector": item.get("sector") or (None if is_all_sectors else sector),
                "address": item.get("address", ""),
                "phone": item.get("phone", ""),
                "email": item.get("email", ""),
                "source_data": {"scribd": item},
            })

    # Fetch all companies in this city/area that were potentially updated
    query = db.query(Company).filter(Company.city == city)
    normalized_area = _normalize_area(area)
    if normalized_area:
        query = query.filter(Company.area == normalized_area)

    all_companies = query.all()

    # ── Website Enrichment ──────────────────────────────────────────────────
    if enrich_website:
        logger.info("[Step 7/7] Website enrichment")
        web_scraper = WebsiteScraper()

        # Phase A: Try to discover websites for companies that don't have one
        companies_no_website = [c for c in all_companies if not c.website]
        if companies_no_website:
            logger.info(f"  -> {len(companies_no_website)} companies have no website; attempting Google discovery")
            for company in companies_no_website:
                discovered_url = await _discover_website(company.name, city)
                if discovered_url:
                    company.website = discovered_url
                    logger.info(f"  -> Discovered website for {company.name}: {discovered_url}")
            db.commit()

        # Phase B: Scrape known websites for email/social
        for company in all_companies:
            # Re-try if never enriched, or if enriched but still missing all contact/social
            has_contact = company.email or company.facebook_url or company.linkedin_url
            already_enriched = company.website_enriched and has_contact
            if company.website and not already_enriched:
                logger.info(f"Enriching website: {company.website} for {company.name}")
                web_data = await web_scraper.scrape_website(company.website)
                if web_data:
                    company.email = company.email or web_data.get("email")
                    company.phone = company.phone or web_data.get("phone")
                    company.facebook_url = company.facebook_url or web_data.get("facebook_url")
                    company.linkedin_url = company.linkedin_url or web_data.get("linkedin_url")
                    company.instagram_url = company.instagram_url or web_data.get("instagram_url")
                    company.twitter_url = company.twitter_url or web_data.get("twitter_url")
                    company.description = company.description or web_data.get("description")
                    company.website_enriched = True
                    company.website_enriched_at = func.now()
        db.commit()

    # ── Export ───────────────────────────────────────────────────────────────
    output_path = _export(db, city, area, sector, output_file)
    db.close()

    logger.info(f"=== Done. Exported to '{output_path}' ===")
    return output_path


def _export(db, city: str, area: Optional[str], sector: str, output_file: str) -> str:
    """Export matching companies to Excel or CSV."""
    query = db.query(Company).filter(Company.city == city)
    if area:
        query = query.filter(Company.area == area)

    companies = query.all()
    logger.info(f"Exporting {len(companies)} companies")

    rows = []
    for c in companies:
        sources_used = list((c.source_data or {}).keys())
        rows.append({
            "Company Name": c.name,
            "Legal Name": c.legal_name or "",
            "Registration #": c.registration_number or "",
            "City": c.city or "",
            "Area": c.area or "",
            "Address": c.address or "",
            "Sector": c.sector or "",
            "Field / Activity": c.field or "",
            "Phone": c.phone or "",
            "Email": c.email or "",
            "Website": c.website or "",
            "LinkedIn": c.linkedin_url or "",
            "Facebook": c.facebook_url or "",
            "Instagram": c.instagram_url or "",
            "Twitter/X": c.twitter_url or "",
            "Google Maps": c.google_maps_url or "",
            "Rating": c.rating or "",
            "Review Count": c.review_count or "",
            "Employee Count": c.employee_count or "",
            "Sources": ", ".join(sources_used),
            "Last Updated": str(c.last_scraped_at or ""),
        })

    df = pd.DataFrame(rows)

    if output_file.endswith(".csv"):
        df.to_csv(output_file, index=False, encoding="utf-8-sig")
    else:
        if not output_file.endswith(".xlsx"):
            output_file += ".xlsx"
        with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Companies")
            ws = writer.sheets["Companies"]
            # Auto-fit column widths
            for col in ws.columns:
                max_len = max(len(str(cell.value or "")) for cell in col)
                ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 60)

    return output_file


def _parse_int(val) -> Optional[int]:
    if not val:
        return None
    cleaned = str(val).replace(",", "").replace("(", "").replace(")", "").strip()
    try:
        return int(cleaned)
    except ValueError:
        return None


async def _discover_website(company_name: str, city: str) -> Optional[str]:
    """Try to find a company's website via a quick Google search.
    Uses SerpAPI if available, otherwise returns None."""
    import requests as _requests
    api_key = os.getenv("SERPAPI_KEY", "")
    if not api_key:
        return None

    try:
        params = {
            "engine": "google",
            "q": f"{company_name} {city} Tunisia official site",
            "api_key": api_key,
            "num": 3,
        }
        resp = _requests.get("https://serpapi.com/search.json", params=params, timeout=10)
        if resp.status_code != 200:
            return None

        data = resp.json()
        organic = data.get("organic_results", [])
        if not organic:
            return None

        # Return the first result link that isn't a directory/social site
        skip_domains = {
            "facebook.com", "linkedin.com", "instagram.com", "twitter.com",
            "x.com", "youtube.com", "tiktok.com", "pinterest.com",
            "kompass.com", "b2bmap.com", "bizpages.org", "tunisiayp.com",
            "yellowpages.com", "yelp.com", "tripadvisor.com",
            "wikipedia.org", "wikidata.org",
        }
        for result in organic:
            link = result.get("link", "")
            if not link:
                continue
            from urllib.parse import urlparse
            domain = urlparse(link).netloc.lower().lstrip("www.")
            if domain and not any(domain.endswith(sd) for sd in skip_domains):
                return link

    except Exception as e:
        logger.debug(f"[WebDiscover] Could not find website for '{company_name}': {e}")

    return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--city", default="Tunis")
    parser.add_argument("--area", default=None)
    parser.add_argument("--sector", default="Software")
    parser.add_argument("--output", default="companies.xlsx")
    args = parser.parse_args()

    asyncio.run(run_orchestration(
        city=args.city,
        area=args.area,
        sector=args.sector,
        output_file=args.output,
    ))
