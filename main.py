#!/usr/bin/env python3
"""
Tunisian Company Scraper — CLI entry point.

Usage examples:
    python main.py --city Tunis --sector "Software"
    python main.py --city Sfax --area "Centre" --sector "Restaurants" --output sfax_restaurants.xlsx
    python main.py --city Sousse --sector "Hôtels" --sources maps tunisiayp kompass
"""
import asyncio
import argparse
import logging
import os
import sys
from dotenv import load_dotenv

load_dotenv()


def main():
    parser = argparse.ArgumentParser(
        description="Scrape and gather Tunisian company data by city, area, and sector.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--city", required=True,
        help="Governorate / city (e.g. Tunis, Sousse, Sfax, Monastir)",
    )
    parser.add_argument(
        "--area", default=None,
        help="Area / delegation / district (e.g. 'Centre Ville', 'La Marsa', 'Lac 1')",
    )
    parser.add_argument(
        "--sector", default="All",
        help="Industry or keyword (e.g. Software, Restaurants). Default: 'All' (scrapes all companies in area)",
    )
    parser.add_argument(
        "--output", default="companies.xlsx",
        help="Output file path (.xlsx or .csv). Default: companies.xlsx",
    )
    ALL_SOURCES = [
        "maps", "rne", "tunisiayp", "b2bmap", "bizpages", "kompass",
        "tunisieindex", "afrikta", "tunisieguide", "tunisieindustrie",
        "b2btn", "tunannu", "pagex", "ccis", "annuario_it_tn", "scribd",
    ]
    parser.add_argument(
        "--sources",
        nargs="+",
        choices=ALL_SOURCES,
        default=ALL_SOURCES,
        help="Data sources to use (default: all sources)",
    )

    parser.add_argument(
        "--website", action="store_true", default=True,
        help="Enable website scraping (enabled by default).",
    )
    parser.add_argument(
        "--no-website", action="store_false", dest="website",
        help="Disable website scraping",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show detailed logs",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Warn if SerpAPI key missing
    if "maps" in args.sources and not os.getenv("SERPAPI_KEY"):
        print(
            "\n[WARNING] SERPAPI_KEY not set in .env — Google Maps will use browser scraping "
            "(slower, may hit CAPTCHAs). Get a free key at serpapi.com and add it to .env.\n"
        )

    from core.orchestrator import run_orchestration

    output_path = asyncio.run(
        run_orchestration(
            city=args.city,
            area=args.area,
            sector=args.sector,
            output_file=args.output,
            sources=args.sources,
            enrich_website=args.website,
        )
    )

    print(f"\nDone! Results saved to: {output_path}")


if __name__ == "__main__":
    main()
