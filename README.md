# Tunisian Company Scraper

A multi-source scraper that aggregates Tunisian company data from 14 public directories and government databases. Filter by city, area, and sector. Results are deduplicated and exported to Excel or CSV.

---

## Data Sources

| Source | Data |
|---|---|
| Google Maps (SerpAPI) | Name, category, address, phone, website, rating, GPS |
| RNE (Registre National des Entreprises) | Legal name, commercial name, Arabic name |
| TunisiaYP | Name, address, phone, coordinates |
| B2BMap | Name, sector, address, phone, email, website |
| BizPages | Name, sector, address, phone, email, website |
| Kompass | Name, sector, address, phone, employee count |
| TunisieIndex | Name, sector, phone, email, website, address |
| Afrikta | Name, sector, address, website, Facebook, LinkedIn |
| TunisieGuide | Name, sector, address, phone, website, social links |
| TunisieIndustrie (gov) | Name, sector, address, phone, email, employee count |
| B2B.tn | Name, sector, address, phone, email, website, social links |
| PageX.tn | Name, sector, address, phone |
| CCIS Sfax | Name, sector, address, phone, email, website |
| Annuario Italia-Tunisia | Name, sector, address, phone, email, website |

---

## Requirements

- Python 3.10+
- [Playwright](https://playwright.dev/python/) (for RNE, B2B.tn, Google Maps fallback)
- A [SerpAPI key](https://serpapi.com) (free tier: 100 searches/month)

---

## Installation

```bash
# 1. Clone the repo
git clone https://github.com/elaaelfahem/scraping_tunisia.git
cd scraping_tunisia

# 2. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install Playwright browsers
playwright install chromium

# 5. Configure environment
copy .env.example .env        # Windows
# cp .env.example .env        # Linux/Mac
# Then open .env and set your SERPAPI_KEY
```

---

## Configuration

Edit `.env`:

```env
SERPAPI_KEY=your_serpapi_key_here
DATABASE_URL=sqlite:///./tunisian_companies.db
```

Get a free SerpAPI key at [serpapi.com](https://serpapi.com) (100 free searches/month).

---

## Usage

### CLI

```bash
# Specific city + sector
python main.py --city Tunis --sector "Software"

# With area filter
python main.py --city Sfax --area "Centre" --sector "Restaurants"

# All sectors in a city
python main.py --city Sousse --sector All

# Custom output file
python main.py --city Tunis --sector "Informatique" --output tunis_it.xlsx

# Specific sources only
python main.py --city Tunis --sector "Software" --sources maps rne tunisiayp kompass

# Skip website enrichment (faster, uses fewer SerpAPI credits)
python main.py --city Tunis --sector "Software" --no-website
```

**Available sources:**
`maps` `rne` `tunisiayp` `b2bmap` `bizpages` `kompass` `tunisieindex` `afrikta` `tunisieguide` `tunisieindustrie` `b2btn` `pagex` `ccis` `annuario_it_tn`

### Streamlit UI

```bash
streamlit run ui/app.py
```

Opens a browser interface to run searches and download results without using the command line.

### Docker

```bash
docker-compose up
```

Runs the Streamlit UI with a PostgreSQL database backend. Access at `http://localhost:8501`.

---

## Output Fields

| Field | Description |
|---|---|
| Company Name | Trading name |
| Legal Name | Official registered name (from RNE) |
| Registration # | Tax/company registration number |
| City | Governorate |
| Area | Delegation / district |
| Address | Full street address |
| Sector | Industry category |
| Field / Activity | Business activity description |
| Phone | Contact phone number |
| Email | Contact email address |
| Website | Company website URL |
| LinkedIn | LinkedIn company page |
| Facebook | Facebook page |
| Instagram | Instagram profile |
| Google Maps | Google Maps listing URL |
| Rating | Google Maps rating (1–5) |
| Review Count | Number of Google reviews |
| Employee Count | Staff headcount (where available) |
| Sources | Which scrapers found this company |
| Last Updated | Timestamp of last scrape |

---

## SerpAPI Cost Estimate

SerpAPI is used for Google Maps results, Kompass bypass, and optional website discovery.

| Usage | Calls/month | Est. cost |
|---|---|---|
| Light (5 targeted scrapes) | ~250 | ~$1.90 |
| Moderate (20 scrapes) | ~2,000 | ~$15 |
| Heavy (50 scrapes) | ~7,500 | ~$56 |

Use `--no-website` to disable website auto-discovery and cut API usage by ~80%.

---

## Project Structure

```
├── main.py                  # CLI entry point
├── requirements.txt
├── docker-compose.yml
├── .env.example
├── core/
│   ├── orchestrator.py      # Runs all scrapers, stores results
│   ├── database.py          # SQLAlchemy models
│   ├── deduplication.py     # Fuzzy-match deduplication
│   ├── filters.py           # City/area/sector filtering
│   └── tunisia_locations.py # Tunisian city/area reference data
├── scrapers/
│   ├── maps_scraper.py
│   ├── rne_scraper.py
│   ├── tunisiayp_scraper.py
│   └── ...                  # One file per source
└── ui/
    └── app.py               # Streamlit interface
```
