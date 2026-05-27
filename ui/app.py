import io
import os
import subprocess
import sys
import time

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.tunisia_locations import GOVERNORATES, get_delegations, search_location

st.set_page_config(
    page_title="Tunisian Company Scraper",
    layout="wide",
    page_icon="🇹🇳",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .metric-card {
        background: #f8f9fa;
        border-radius: 10px;
        padding: 16px 20px;
        border-left: 4px solid #e63946;
        margin-bottom: 8px;
    }
    .metric-label { font-size: 0.78rem; color: #6c757d; font-weight: 600; text-transform: uppercase; }
    .metric-value { font-size: 2rem; font-weight: 700; color: #212529; margin: 4px 0 0 0; }
    .source-badge {
        display: inline-block; background: #e9ecef; border-radius: 4px;
        padding: 2px 8px; margin: 2px; font-size: 0.75rem; color: #495057;
    }
    .stDataFrame { border: 1px solid #dee2e6; border-radius: 8px; }
    .progress-info { background: #d1ecf1; border-radius: 6px; padding: 10px 14px;
                     border-left: 4px solid #17a2b8; margin: 8px 0; }
</style>
""", unsafe_allow_html=True)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tunisian_companies.db")
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tunisian_companies.db")

ALL_SOURCES = [
    "maps", "rne", "tunisiayp", "b2bmap", "bizpages", "kompass",
    "tunisieindex", "afrikta", "tunisieguide", "tunisieindustrie",
    "b2btn", "pagex", "ccis", "annuario_it_tn",
]

SOURCE_LABELS = {
    "maps": "Google Maps",
    "rne": "RNE (Gov)",
    "tunisiayp": "TunisiaYP",
    "b2bmap": "B2BMap",
    "bizpages": "BizPages",
    "kompass": "Kompass",
    "tunisieindex": "TunisieIndex",
    "afrikta": "Afrikta",
    "tunisieguide": "TunisieGuide",
    "tunisieindustrie": "TunisieIndustrie",
    "b2btn": "B2B.tn",
    "pagex": "PageX.tn",
    "ccis": "CCIS Sfax",
    "annuario_it_tn": "Annuario IT-TN",
    "scribd": "Scribd",
    "tunannu": "TunAnnu",
}

DEFAULT_SOURCES = ["maps", "b2bmap", "tunisiayp", "kompass", "tunisieindex", "b2btn", "pagex", "rne"]


@st.cache_resource
def get_engine():
    if DATABASE_URL.startswith("sqlite"):
        return create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    return create_engine(DATABASE_URL)


engine = get_engine()


def load_companies(city=None, area=None, sector=None, name_search=None, source=None):
    query = """
        SELECT
            name            AS "Company Name",
            legal_name      AS "Legal Name",
            city            AS "Governorate",
            area            AS "Area",
            sector          AS "Sector",
            field           AS "Field / Activity",
            address         AS "Address",
            phone           AS "Phone",
            email           AS "Email",
            website         AS "Website",
            linkedin_url    AS "LinkedIn",
            facebook_url    AS "Facebook",
            google_maps_url AS "Google Maps",
            employee_count  AS "Employees",
            rating          AS "Rating",
            review_count    AS "Reviews",
            source_data     AS "_source_data",
            last_scraped_at AS "Last Updated"
        FROM companies WHERE 1=1
    """
    params: dict = {}
    if city and city != "All":
        query += " AND city = :city"
        params["city"] = city
    if area and area != "All":
        query += " AND area = :area"
        params["area"] = area
    if sector and sector != "All":
        query += " AND sector = :sector"
        params["sector"] = sector
    if name_search and name_search.strip():
        query += " AND LOWER(name) LIKE :name"
        params["name"] = f"%{name_search.lower()}%"
    query += " ORDER BY name"
    try:
        with engine.connect() as conn:
            return pd.read_sql(text(query), conn, params=params)
    except Exception:
        return pd.DataFrame()


def load_db_filters():
    try:
        with engine.connect() as conn:
            cities = [r[0] for r in conn.execute(
                text("SELECT DISTINCT city FROM companies WHERE city IS NOT NULL ORDER BY city")
            ).fetchall()]
            areas = [r[0] for r in conn.execute(
                text("SELECT DISTINCT area FROM companies WHERE area IS NOT NULL AND area != '' ORDER BY area")
            ).fetchall()]
            sectors = [r[0] for r in conn.execute(
                text("SELECT DISTINCT sector FROM companies WHERE sector IS NOT NULL AND sector != '' ORDER BY sector")
            ).fetchall()]
            sources_raw = [r[0] for r in conn.execute(
                text("SELECT DISTINCT source_data FROM companies WHERE source_data IS NOT NULL")
            ).fetchall()]
        return cities, areas, sectors
    except Exception:
        return [], [], []


def load_stats():
    try:
        with engine.connect() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM companies")).scalar() or 0
            with_phone = conn.execute(text("SELECT COUNT(*) FROM companies WHERE phone IS NOT NULL AND phone != ''")).scalar() or 0
            with_email = conn.execute(text("SELECT COUNT(*) FROM companies WHERE email IS NOT NULL AND email != ''")).scalar() or 0
            with_website = conn.execute(text("SELECT COUNT(*) FROM companies WHERE website IS NOT NULL AND website != ''")).scalar() or 0
            by_city = pd.read_sql(text(
                "SELECT city, COUNT(*) as count FROM companies WHERE city IS NOT NULL GROUP BY city ORDER BY count DESC LIMIT 15"
            ), conn)
            by_sector = pd.read_sql(text(
                "SELECT sector, COUNT(*) as count FROM companies WHERE sector IS NOT NULL AND sector != '' GROUP BY sector ORDER BY count DESC LIMIT 15"
            ), conn)
            by_source = pd.read_sql(text(
                "SELECT source_data, COUNT(*) as count FROM companies WHERE source_data IS NOT NULL GROUP BY source_data ORDER BY count DESC"
            ), conn)
        return total, with_phone, with_email, with_website, by_city, by_sector, by_source
    except Exception:
        empty = pd.DataFrame()
        return 0, 0, 0, 0, empty, empty, empty


# ── SIDEBAR ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🇹🇳 Tunisian Scraper")
    st.divider()

    # Quick DB stats
    try:
        with engine.connect() as conn:
            n = conn.execute(text("SELECT COUNT(*) FROM companies")).scalar() or 0
        st.metric("Total companies in DB", f"{n:,}")
    except Exception:
        st.caption("Database not initialized yet")

    st.divider()
    st.caption("SERPAPI_KEY: " + ("✅ Set" if os.getenv("SERPAPI_KEY") else "❌ Missing — add to .env"))

# ── TABS ─────────────────────────────────────────────────────────────────────
tab_scrape, tab_dashboard, tab_results, tab_export = st.tabs([
    "🚀 Scrape", "📊 Dashboard", "📋 Results", "📥 Export"
])


# ═══════════════════════════════════════════════════════════════════════════
# TAB 1 — SCRAPE
# ═══════════════════════════════════════════════════════════════════════════
with tab_scrape:
    st.subheader("Launch a New Scrape")
    st.caption("Configure your search, pick sources, and start collecting companies.")

    col_form, col_info = st.columns([3, 2])

    with col_form:
        with st.form("scrape_form"):
            st.markdown("##### 📍 Location")
            location_query = st.text_input(
                "Quick search",
                placeholder="Type a city or area to search…",
                help="Start typing to get suggestions — then select from the dropdowns below.",
            )

            gov_options = ["— select —"] + GOVERNORATES
            selected_gov = st.selectbox("Governorate", gov_options)

            delegation_options = ["All (entire governorate)"]
            if selected_gov != "— select —":
                delegation_options += get_delegations(selected_gov)
            selected_delegation = st.selectbox("Area / Delegation", delegation_options)

            st.markdown("##### 🔍 Search")
            target_sector = st.text_input(
                "Sector / Keyword",
                value="All",
                placeholder="e.g. Software, Restaurants, Textile. Leave 'All' for everything.",
            )
            output_name = st.text_input("Output filename", "companies.xlsx", help="Saved in the project root directory.")

            st.markdown("##### 🌐 Data Sources")
            selected_sources = st.multiselect(
                "Sources to scrape",
                ALL_SOURCES,
                default=DEFAULT_SOURCES,
                format_func=lambda s: SOURCE_LABELS.get(s, s),
            )

            st.markdown("##### ⚙️ Options")
            enable_web_scrape = st.checkbox(
                "Crawl company websites for email & social links",
                value=True,
                help="Visits each company's website to extract emails, LinkedIn, Facebook, etc.",
            )

            submitted = st.form_submit_button("▶ Start Scrape", use_container_width=True, type="primary")

    with col_info:
        st.markdown("##### ℹ️ Source Guide")
        source_descriptions = {
            "maps": ("Google Maps", "Best for local businesses with addresses, phones, ratings"),
            "rne": ("RNE", "Official Tunisian company registry — legal names only"),
            "tunisiayp": ("TunisiaYP", "Yellow Pages — good phone coverage"),
            "b2bmap": ("B2BMap", "B2B directory — addresses & descriptions"),
            "bizpages": ("BizPages", "International directory — emails via reverse-engineering"),
            "kompass": ("Kompass", "European B2B — requires SerpAPI key"),
            "tunisieindex": ("TunisieIndex", "Category directory — wide coverage"),
            "afrikta": ("Afrikta", "Pan-African directory — websites & social"),
            "tunisieguide": ("TunisieGuide", "GeoDirectory — location-based"),
            "tunisieindustrie": ("TunisieIndustrie", "Official industrial database (gov.tn)"),
            "b2btn": ("B2B.tn", "Tunisian B2B platform — good phone & address"),
            "pagex": ("PageX.tn", "Local directory — phone & address"),
            "ccis": ("CCIS Sfax", "Sfax Chamber of Commerce members"),
            "annuario_it_tn": ("Annuario IT-TN", "Italian companies in Tunisia"),
        }
        for src in selected_sources:
            if src in source_descriptions:
                name, desc = source_descriptions[src]
                st.markdown(f"**{name}** — {desc}")

        if not selected_sources:
            st.info("Select at least one source to scrape.")

    # Handle location search suggestions (outside form)
    if location_query.strip():
        suggestions = search_location(location_query)
        if suggestions:
            st.caption("📍 Suggestions:")
            for gov, deleg in suggestions[:5]:
                label = f"**{gov}** › {deleg}" if deleg else f"**{gov}**"
                st.caption(f"  → {label}")

    # Handle form submission
    if submitted:
        if selected_gov == "— select —":
            st.error("Please select a governorate.")
        elif not selected_sources:
            st.error("Please select at least one data source.")
        else:
            sector_val = target_sector.strip() if target_sector.strip() else "All"
            city = selected_gov
            area = selected_delegation if selected_delegation != "All (entire governorate)" else ""

            src_args = " ".join(selected_sources)
            area_arg = f'--area "{area}"' if area else ""
            website_arg = "--website" if enable_web_scrape else "--no-website"

            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cmd = (
                f'python main.py --city "{city}" {area_arg} '
                f'--sector "{sector_val}" --output "{output_name}" '
                f'--sources {src_args} {website_arg}'
            )

            st.info(f"**Starting scrape:** {city}{' › ' + area if area else ''} — *{sector_val}*")
            st.code(cmd, language="bash")

            try:
                subprocess.Popen(cmd, shell=True, cwd=project_root)
                st.success(
                    f"✅ Scrape launched for **{city}{' › ' + area if area else ''}** | Sector: **{sector_val}** | "
                    f"{len(selected_sources)} sources active.\n\n"
                    "Switch to the **📊 Dashboard** or **📋 Results** tab and refresh the page to see data as it arrives."
                )
                st.balloons()
            except Exception as e:
                st.error(f"Failed to start scrape: {e}")

    st.divider()
    st.markdown("##### 💡 Tips")
    st.markdown(
        "- For **broad prospecting**: use `All` sector with Maps + B2BMap + TunisiaYP + PageX\n"
        "- For **specific industries**: enter the sector name (e.g. *Textile*, *Software*) and add TunisieIndustrie + Kompass\n"
        "- **RNE** gives you official legal names but no contact info — combine with other sources\n"
        "- After scraping, go to **📋 Results** to filter, review, and download"
    )


# ═══════════════════════════════════════════════════════════════════════════
# TAB 2 — DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════
with tab_dashboard:
    st.subheader("Database Overview")

    if st.button("🔄 Refresh", key="refresh_dash"):
        st.cache_data.clear()
        st.rerun()

    total, with_phone, with_email, with_website, by_city, by_sector, by_source = load_stats()

    if total == 0:
        st.info("No data yet. Run a scrape from the **🚀 Scrape** tab to populate the database.")
    else:
        # KPI row
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Total Companies", f"{total:,}")
        k2.metric("Have Phone", f"{with_phone:,}", f"{with_phone/total*100:.0f}%")
        k3.metric("Have Email", f"{with_email:,}", f"{with_email/total*100:.0f}%")
        k4.metric("Have Website", f"{with_website:,}", f"{with_website/total*100:.0f}%")

        st.divider()

        # Data completeness bar
        st.markdown("#### Data Completeness")
        completeness = pd.DataFrame({
            "Field": ["Phone", "Email", "Website", "LinkedIn", "Facebook"],
        })
        try:
            with engine.connect() as conn:
                for field, col in [("Phone", "phone"), ("Email", "email"), ("Website", "website"),
                                    ("LinkedIn", "linkedin_url"), ("Facebook", "facebook_url")]:
                    n_field = conn.execute(
                        text(f"SELECT COUNT(*) FROM companies WHERE {col} IS NOT NULL AND {col} != ''")
                    ).scalar() or 0
                    completeness.loc[completeness["Field"] == field, "Count"] = n_field
                    completeness.loc[completeness["Field"] == field, "Pct"] = round(n_field / total * 100, 1) if total else 0
        except Exception:
            pass

        st.bar_chart(completeness.set_index("Field")["Pct"], horizontal=True)

        chart_col1, chart_col2 = st.columns(2)

        with chart_col1:
            st.markdown("#### Companies by Governorate")
            if not by_city.empty:
                st.bar_chart(by_city.set_index("city")["count"])
            else:
                st.caption("No city data yet.")

        with chart_col2:
            st.markdown("#### Top Sectors")
            if not by_sector.empty:
                st.bar_chart(by_sector.set_index("sector")["count"])
            else:
                st.caption("No sector data yet.")

        # Source breakdown
        st.markdown("#### Coverage by Source")
        if not by_source.empty:
            try:
                # Parse source_data keys from JSON string column
                with engine.connect() as conn:
                    rows = conn.execute(text("SELECT source_data FROM companies WHERE source_data IS NOT NULL")).fetchall()
                import json
                source_counts: dict[str, int] = {}
                for (raw,) in rows:
                    try:
                        if isinstance(raw, str):
                            keys = list(json.loads(raw).keys())
                        elif isinstance(raw, dict):
                            keys = list(raw.keys())
                        else:
                            continue
                        for k in keys:
                            source_counts[k] = source_counts.get(k, 0) + 1
                    except Exception:
                        pass
                if source_counts:
                    src_df = pd.DataFrame(
                        [(SOURCE_LABELS.get(k, k), v) for k, v in sorted(source_counts.items(), key=lambda x: -x[1])],
                        columns=["Source", "Companies"],
                    )
                    st.bar_chart(src_df.set_index("Source")["Companies"])
            except Exception:
                st.caption("Source breakdown unavailable.")


# ═══════════════════════════════════════════════════════════════════════════
# TAB 3 — RESULTS
# ═══════════════════════════════════════════════════════════════════════════
with tab_results:
    st.subheader("Browse Companies")

    db_cities, db_areas, db_sectors = load_db_filters()

    # Filter bar
    f1, f2, f3, f4, f5 = st.columns([2, 2, 2, 2, 1])
    filter_city = f1.selectbox("Governorate", ["All"] + (db_cities or GOVERNORATES), key="res_city")
    area_opts = ["All"] + ([a for a in db_areas] if filter_city == "All" else get_delegations(filter_city))
    filter_area = f2.selectbox("Area", area_opts, key="res_area")
    filter_sector = f3.selectbox("Sector", ["All"] + db_sectors, key="res_sector")
    name_search = f4.text_input("Search name", placeholder="Type to filter…", key="res_name")
    f5.write("")
    f5.write("")
    refresh_btn = f5.button("🔄", help="Refresh results", key="refresh_results")

    if refresh_btn:
        st.cache_data.clear()

    df_full = load_companies(
        city=filter_city if filter_city != "All" else None,
        area=filter_area if filter_area != "All" else None,
        sector=filter_sector if filter_sector != "All" else None,
        name_search=name_search,
    )

    if df_full.empty:
        st.info("No companies match your filters. Try broadening the search or run a scrape first.")
    else:
        # Drop internal column
        df_display = df_full.drop(columns=["_source_data"], errors="ignore")

        # Column visibility toggle
        with st.expander("⚙️ Column visibility", expanded=False):
            all_cols = list(df_display.columns)
            default_visible = ["Company Name", "Governorate", "Area", "Sector", "Address",
                               "Phone", "Email", "Website", "Rating"]
            visible_cols = st.multiselect("Show columns", all_cols, default=[c for c in default_visible if c in all_cols])
        if visible_cols:
            df_display = df_display[visible_cols]

        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Shown", f"{len(df_display):,}")
        if "Phone" in df_display.columns:
            r2.metric("With Phone", int(df_display["Phone"].notna().sum()))
        if "Email" in df_display.columns:
            r3.metric("With Email", int(df_display["Email"].notna().sum()))
        if "Website" in df_display.columns:
            r4.metric("With Website", int(df_display["Website"].notna().sum()))

        # Make URLs clickable using column_config
        col_cfg = {}
        for col_name, url_col in [("Website", "Website"), ("LinkedIn", "LinkedIn"),
                                   ("Facebook", "Facebook"), ("Google Maps", "Google Maps")]:
            if col_name in df_display.columns:
                col_cfg[col_name] = st.column_config.LinkColumn(col_name, display_text="🔗 Open")

        st.dataframe(
            df_display,
            use_container_width=True,
            height=520,
            column_config=col_cfg,
        )

        st.caption(f"Showing {len(df_display):,} companies • Use the **📥 Export** tab to download")


# ═══════════════════════════════════════════════════════════════════════════
# TAB 4 — EXPORT
# ═══════════════════════════════════════════════════════════════════════════
with tab_export:
    st.subheader("Export Data")

    db_cities_ex, db_areas_ex, db_sectors_ex = load_db_filters()

    ex1, ex2, ex3 = st.columns(3)
    ex_city = ex1.selectbox("Governorate", ["All"] + (db_cities_ex or GOVERNORATES), key="ex_city")
    ex_area_opts = ["All"] + ([a for a in db_areas_ex] if ex_city == "All" else get_delegations(ex_city))
    ex_area = ex2.selectbox("Area", ex_area_opts, key="ex_area")
    ex_sector = ex3.selectbox("Sector", ["All"] + db_sectors_ex, key="ex_sector")

    df_export = load_companies(
        city=ex_city if ex_city != "All" else None,
        area=ex_area if ex_area != "All" else None,
        sector=ex_sector if ex_sector != "All" else None,
    )
    df_export = df_export.drop(columns=["_source_data"], errors="ignore")

    st.metric("Records to export", f"{len(df_export):,}")

    if not df_export.empty:
        d1, d2 = st.columns(2)

        # CSV
        csv_bytes = df_export.to_csv(index=False).encode("utf-8-sig")
        city_slug = ex_city.lower().replace(" ", "_") if ex_city != "All" else "all"
        sector_slug = ex_sector.lower().replace(" ", "_") if ex_sector != "All" else "all"
        d1.download_button(
            "📥 Download CSV",
            data=csv_bytes,
            file_name=f"tunisia_{city_slug}_{sector_slug}.csv",
            mime="text/csv",
            use_container_width=True,
        )

        # Excel with auto-fit columns
        xl_buf = io.BytesIO()
        with pd.ExcelWriter(xl_buf, engine="openpyxl") as writer:
            df_export.to_excel(writer, index=False, sheet_name="Companies")
            ws = writer.sheets["Companies"]
            for col in ws.columns:
                max_len = max((len(str(cell.value or "")) for cell in col), default=10)
                ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 55)
        d2.download_button(
            "📥 Download Excel",
            data=xl_buf.getvalue(),
            file_name=f"tunisia_{city_slug}_{sector_slug}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

        st.markdown("**Preview (first 10 rows)**")
        st.dataframe(df_export.head(10), use_container_width=True)
    else:
        st.info("No data matches the selected filters.")
