import re
import unicodedata
from pathlib import Path

import pandas as pd
import streamlit as st

def check_password():
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False

    if not st.session_state.password_correct:
        password = st.text_input("Enter password", type="password")

        if password:
            if password == st.secrets["APP_PASSWORD"]:
                st.session_state.password_correct = True
                st.rerun()
            else:
                st.error("Incorrect password")

        st.stop()

check_password()

DATA_DIR = Path(__file__).parent / "data"


# -----------------------------
# Basic file helpers
# -----------------------------

def clean_column_name(col):
    col = str(col).strip().lower()
    col = re.sub(r"[^a-z0-9]+", "_", col)
    return col.strip("_")


def load_csv(file_name):
    path = DATA_DIR / file_name

    try:
        df = pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig")
    except UnicodeDecodeError:
        df = pd.read_csv(path, sep=None, engine="python", encoding="latin1")

    df.columns = [clean_column_name(c) for c in df.columns]
    return df.fillna("")


def load_optional_csv(file_name):
    path = DATA_DIR / file_name

    if not path.exists():
        return pd.DataFrame()

    return load_csv(file_name)


def find_column(df, possible_names):
    if df.empty:
        return None

    for name in possible_names:
        clean_name = clean_column_name(name)
        if clean_name in df.columns:
            return clean_name

    return None


def safe_get(row, col):
    if col is None:
        return ""
    return str(row.get(col, "")).strip()


# -----------------------------
# Text helpers
# -----------------------------

def normalize_text(text):
    text = str(text).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("-", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def contains_term(text, term):
    text = normalize_text(text)
    term = normalize_text(term)

    if " " in term:
        return term in text

    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def tokenize(text):
    text = normalize_text(text)
    words = re.findall(r"[a-zA-Z]+", text)

    stopwords = {
        "and", "the", "of", "in", "to", "for", "with", "by", "a", "an",
        "company", "companies", "group", "business", "provider",
        "leading", "specialized", "specialist", "solution", "solutions",
        "website", "home", "contact", "privacy", "policy", "cookie", "cookies",
        "from", "that", "this", "their", "more", "into", "your",
        "about", "also", "will", "shall", "were", "been", "page",
        "read", "learn", "data", "news", "article", "market", "markets",
        "spain", "spanish", "madrid", "barcelona", "investment", "capital",
        "management", "growth"
    }

    return set(w for w in words if len(w) > 2 and w not in stopwords)


# -----------------------------
# Sector logic
# -----------------------------

def detect_categories(text):
    text = normalize_text(text)

    categories = {
        "restaurants_hospitality": [
            "restaurant", "restaurants", "restaurante", "restaurantes",
            "hospitality", "hosteleria", "catering", "food service",
            "foodservice", "horeca", "cafe", "coffee shop", "bar chain"
        ],

        "food_beverage": [
            "food", "alimentacion", "beverage", "drinks", "bebidas",
            "snacks", "meat", "bakery", "dairy", "frozen food"
        ],

        "healthcare": [
            "healthcare", "salud", "sanitario", "medical", "medicina",
            "clinic", "hospital", "pharma", "pharmaceutical",
            "farmaceutico", "dental", "veterinary", "diagnostic"
        ],

        "technology_software": [
            "software", "saas", "technology", "tecnologia", "digital",
            "platform", "plataforma", "cloud", "cyber", "analytics",
            "fintech", "payments", "data analytics", "artificial intelligence"
        ],

        "industrial_manufacturing": [
            "industrial", "industria", "manufacturing", "fabricacion",
            "manufactura", "machinery", "automation", "engineering",
            "materials", "packaging", "components", "equipment"
        ],

        "business_services": [
            "outsourcing", "facility", "facilities", "maintenance",
            "mantenimiento", "cleaning", "limpieza", "security",
            "staffing", "consulting", "bpo", "professional services"
        ],

        "consumer_retail": [
            "consumer", "consumo", "retail", "fashion", "ecommerce",
            "e commerce", "stores", "tiendas", "brand", "brands"
        ],

        "energy_infrastructure": [
            "energy", "energia", "renewable", "renovable", "solar",
            "wind", "infrastructure", "infraestructura", "utilities",
            "waste", "recycling", "water", "environmental"
        ],

        "logistics_transport": [
            "logistics", "logistica", "transport", "transportation",
            "supply chain", "shipping", "delivery", "warehouse",
            "warehousing", "freight"
        ],

        "education_training": [
            "education", "educacion", "training", "formacion",
            "school", "university", "learning", "academy"
        ],

        "construction_real_estate": [
            "construction", "construccion", "real estate", "inmobiliario",
            "property", "building", "obra", "obras", "assets",
            "development", "developer"
        ],

        "financial_services": [
            "finance", "financial", "insurance", "banking",
            "credit", "lending", "payments", "fintech"
        ],
    }

    detected = set()

    for category, keywords in categories.items():
        for keyword in keywords:
            if contains_term(text, keyword):
                detected.add(category)
                break

    # Important rule:
    # A restaurant opportunity should match restaurant/hospitality funds,
    # not generic food or consumer funds unless the restaurant category is also present.
    if "restaurants_hospitality" in detected:
        detected.discard("food_beverage")
        detected.discard("consumer_retail")

    return detected


def format_categories(categories):
    labels = {
        "restaurants_hospitality": "Restaurants / Hospitality",
        "food_beverage": "Food & Beverage",
        "healthcare": "Healthcare",
        "technology_software": "Technology / Software",
        "industrial_manufacturing": "Industrial / Manufacturing",
        "business_services": "Business Services",
        "consumer_retail": "Consumer / Retail",
        "energy_infrastructure": "Energy / Infrastructure",
        "logistics_transport": "Logistics / Transport",
        "education_training": "Education / Training",
        "construction_real_estate": "Construction / Real Estate",
        "financial_services": "Financial Services",
    }

    return ", ".join(labels.get(c, c) for c in sorted(categories))


# -----------------------------
# Specific characteristics
# -----------------------------

def detect_specific_terms(text):
    text = normalize_text(text)

    terms = [
        # restaurants / hospitality
        "restaurant", "restaurants", "restaurante", "restaurantes",
        "hospitality", "hosteleria", "catering", "horeca",
        "coffee", "cafe", "fast casual", "franchise",

        # food
        "food", "beverage", "drinks", "snacks", "bakery", "meat", "dairy",

        # tech
        "saas", "software", "cloud", "cyber", "fintech",
        "payments", "platform", "analytics", "ai",

        # healthcare
        "dental", "veterinary", "clinic", "hospital",
        "pharma", "pharmaceutical", "diagnostic",

        # logistics
        "logistics", "warehouse", "transport", "delivery",
        "supply chain", "freight",

        # energy / infrastructure
        "solar", "renewable", "waste", "recycling", "water",

        # industrial
        "packaging", "automation", "machinery", "equipment",
        "engineering", "materials",

        # business services
        "maintenance", "cleaning", "facility", "security",
        "staffing", "outsourcing",

        # consumer
        "retail", "ecommerce", "fashion", "brand", "stores",

        # education
        "education", "training", "school", "learning",

        # construction / real estate
        "construction", "real estate", "property", "building",
        "infrastructure"
    ]

    detected = set()

    for term in terms:
        if contains_term(text, term):
            detected.add(normalize_text(term))

    return detected


def detect_geography(text):
    text = normalize_text(text)

    geographies = {
        "spain": [
            "spain", "spanish", "espana", "madrid", "barcelona",
            "valencia", "sevilla", "bilbao"
        ],
        "iberia": [
            "iberia", "iberian", "spain", "portugal", "espana"
        ],
        "portugal": [
            "portugal", "lisbon", "porto"
        ],
        "europe": [
            "europe", "european", "europa"
        ],
        "latin_america": [
            "latin america", "latam", "mexico", "colombia",
            "chile", "argentina", "peru"
        ],
    }

    detected = set()

    for geo, keywords in geographies.items():
        for keyword in keywords:
            if contains_term(text, keyword):
                detected.add(geo)
                break

    return detected


# -----------------------------
# Website enrichment
# -----------------------------

def get_enrichment_text(enrichment, enrichment_columns, name, source_type=None):
    if enrichment.empty:
        return ""

    name_col = enrichment_columns.get("name")
    source_col = enrichment_columns.get("source_type")
    keywords_col = enrichment_columns.get("keywords")
    preview_col = enrichment_columns.get("text_preview")

    if not name_col:
        return ""

    filtered = enrichment[
        enrichment[name_col].astype(str).str.lower().str.strip()
        == str(name).lower().strip()
    ]

    if source_type and source_col:
        filtered = filtered[
            filtered[source_col].astype(str).str.lower().str.strip()
            == str(source_type).lower().strip()
        ]

    if filtered.empty:
        return ""

    text_parts = []

    for _, row in filtered.iterrows():
        if keywords_col:
            text_parts.append(str(row.get(keywords_col, "")))
        if preview_col:
            text_parts.append(str(row.get(preview_col, ""))[:500])

    return " ".join(text_parts)


# -----------------------------
# Main scoring logic
# -----------------------------

def score_match(opportunity, fund, portfolio_companies, enrichment, columns, enrichment_columns):
    fund_name = safe_get(fund, columns["fund_name"])
    opportunity_name = safe_get(opportunity, columns["opp_company"])

    opp_sector = safe_get(opportunity, columns["opp_sector"])
    opp_subsector = safe_get(opportunity, columns["opp_subsector"])
    opp_description = safe_get(opportunity, columns["opp_description"])

    fund_sector = safe_get(fund, columns["fund_sector"])

    fund_enrichment_text = get_enrichment_text(
        enrichment,
        enrichment_columns,
        fund_name,
        source_type="PE Fund"
    )

    opportunity_enrichment_text = get_enrichment_text(
        enrichment,
        enrichment_columns,
        opportunity_name,
        source_type="Opportunity"
    )

    opportunity_text = " ".join([
        opportunity_name,
        opp_sector,
        opp_subsector,
        opp_description,
        opportunity_enrichment_text[:800],
    ])

    fund_focus_text = " ".join([
        fund_name,
        fund_sector,
    ])

    portfolio_text = ""

    if columns["portfolio_fund"] and columns["portfolio_activity"]:
        related_portfolio = portfolio_companies[
            portfolio_companies[columns["portfolio_fund"]].astype(str).str.lower().str.strip()
            == fund_name.lower().strip()
        ]

        portfolio_text = " ".join(
            related_portfolio[columns["portfolio_activity"]].astype(str).tolist()
        )

    # Detect sector categories
    opportunity_categories = detect_categories(opportunity_text)
    fund_categories = detect_categories(fund_focus_text)
    portfolio_categories = detect_categories(portfolio_text)
    website_categories = detect_categories(fund_enrichment_text)

    sector_matches = opportunity_categories & fund_categories
    portfolio_sector_matches = opportunity_categories & portfolio_categories
    website_sector_matches = opportunity_categories & website_categories

    # HARD GATE:
    # If the PE fund does not match the opportunity sector through fund focus or portfolio,
    # it should not be considered.
    if len(sector_matches) == 0 and len(portfolio_sector_matches) == 0:
        return {
            "score": 0,
            "reason": "Not considered because the sector does not match.",
            "sector_match": "",
            "portfolio_signal": 0,
            "specific_signal": 0,
            "website_signal": 0,
            "geography_signal": 0,
        }

    # Detect additional characteristics
    opportunity_specific = detect_specific_terms(opportunity_text)
    fund_specific = detect_specific_terms(fund_focus_text + " " + portfolio_text)
    website_specific = detect_specific_terms(fund_enrichment_text)

    specific_matches = opportunity_specific & fund_specific
    website_specific_matches = opportunity_specific & website_specific

    opportunity_geo = detect_geography(opportunity_text)
    fund_geo = detect_geography(fund_focus_text + " " + fund_enrichment_text)

    geography_matches = opportunity_geo & fund_geo

    # Scoring system:
    # 100 = all important characteristics match
    score = 0

    # 1. Required sector foundation
    # Same sector through fund focus is strongest.
    # Same sector through portfolio also qualifies, but slightly less.
    if len(sector_matches) > 0:
        score += 50
    elif len(portfolio_sector_matches) > 0:
        score += 40

    # 2. Portfolio evidence
    if len(portfolio_sector_matches) > 0:
        score += 25

    # 3. Specific subsector / characteristic match
    if len(specific_matches) > 0:
        score += min(len(specific_matches) * 5, 15)

    # 4. Website evidence
    if len(website_sector_matches) > 0 or len(website_specific_matches) > 0:
        score += 5

    # 5. Geography / market fit
    if len(geography_matches) > 0:
        score += 5

    score = round(min(score, 100), 1)

    reasons = []

    if len(sector_matches) > 0:
        reasons.append("Sector focus match: " + format_categories(sector_matches) + ".")

    if len(portfolio_sector_matches) > 0:
        reasons.append("Portfolio evidence match: " + format_categories(portfolio_sector_matches) + ".")

    if len(specific_matches) > 0:
        reasons.append("Specific characteristics match: " + ", ".join(sorted(specific_matches)[:6]) + ".")

    if len(website_sector_matches) > 0:
        reasons.append("Website confirms sector: " + format_categories(website_sector_matches) + ".")

    if len(website_specific_matches) > 0:
        reasons.append("Website confirms specific terms: " + ", ".join(sorted(website_specific_matches)[:5]) + ".")

    if len(geography_matches) > 0:
        reasons.append("Geography / market fit: " + ", ".join(sorted(geography_matches)) + ".")

    return {
        "score": score,
        "reason": " ".join(reasons),
        "sector_match": format_categories(sector_matches | portfolio_sector_matches),
        "portfolio_signal": len(portfolio_sector_matches),
        "specific_signal": len(specific_matches),
        "website_signal": len(website_sector_matches | website_specific_matches),
        "geography_signal": len(geography_matches),
    }


# -----------------------------
# Streamlit app
# -----------------------------

st.set_page_config(page_title="PE Matcher", layout="wide")

st.title("PE Intelligence Copilot")
st.write(
    "Version 2.0: Hard sector gate. Funds are only considered when the sector matches. "
    "The score increases when portfolio, specific characteristics, website evidence, and geography also match."
)


pe_funds = load_csv("pe_funds.csv")
portfolio_companies = load_csv("portfolio_companies.csv")
opportunities = load_csv("opportunities.csv")
website_enrichment = load_optional_csv("website_enrichment.csv")


columns = {
    "fund_name": find_column(pe_funds, ["fund_name", "fund", "name", "pe_fund"]),
    "fund_sector": find_column(pe_funds, ["sector_focus", "sector", "sectors", "preferred_sectors"]),

    "portfolio_fund": find_column(portfolio_companies, ["fund_name", "fund", "pe_fund"]),
    "portfolio_company": find_column(portfolio_companies, ["company", "portfolio_company", "name"]),
    "portfolio_activity": find_column(portfolio_companies, ["activity", "sector", "description", "business_description"]),

    "opp_company": find_column(opportunities, ["company", "name", "opportunity"]),
    "opp_sector": find_column(opportunities, ["sector", "industry"]),
    "opp_subsector": find_column(opportunities, ["subsector", "sub_sector"]),
    "opp_description": find_column(opportunities, ["description", "business_description"]),
}


enrichment_columns = {
    "source_type": find_column(website_enrichment, ["source_type"]),
    "name": find_column(website_enrichment, ["name"]),
    "url": find_column(website_enrichment, ["url", "website", "link"]),
    "keywords": find_column(website_enrichment, ["keywords"]),
    "text_preview": find_column(website_enrichment, ["text_preview", "preview"]),
}


missing = [
    key for key, value in columns.items()
    if value is None and key not in ["portfolio_company"]
]

if missing:
    st.error("Some required columns were not found.")
    st.write("Missing columns:", missing)
    st.write("PE Funds columns:", list(pe_funds.columns))
    st.write("Portfolio Companies columns:", list(portfolio_companies.columns))
    st.write("Opportunities columns:", list(opportunities.columns))
    st.stop()


st.sidebar.header("Data Loaded")
st.sidebar.write(f"PE Funds: {len(pe_funds)}")
st.sidebar.write(f"Portfolio Companies: {len(portfolio_companies)}")
st.sidebar.write(f"Opportunities: {len(opportunities)}")

if not website_enrichment.empty:
    st.sidebar.write(f"Website Enrichment: {len(website_enrichment)}")
else:
    st.sidebar.warning("No website enrichment file found.")


tab1, tab2, tab3 = st.tabs([
    "Opportunity → PE Funds",
    "PE Fund → Opportunities",
    "Website Enrichment"
])


# -----------------------------
# Tab 1: Opportunity to PE funds
# -----------------------------

with tab1:
    st.header("Find the best PE funds for an opportunity")

    opportunity_names = opportunities[columns["opp_company"]].astype(str).tolist()

    selected_opportunity_name = st.selectbox(
        "Select an opportunity",
        opportunity_names,
        key="opportunity_selector"
    )

    selected_opportunity = opportunities[
        opportunities[columns["opp_company"]].astype(str) == selected_opportunity_name
    ].iloc[0]

    st.subheader("Selected Opportunity")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.write("**Company**")
        st.write(safe_get(selected_opportunity, columns["opp_company"]))

    with col2:
        st.write("**Sector**")
        st.write(safe_get(selected_opportunity, columns["opp_sector"]))

    with col3:
        st.write("**Subsector**")
        st.write(safe_get(selected_opportunity, columns["opp_subsector"]))

    st.write("**Description**")
    st.write(safe_get(selected_opportunity, columns["opp_description"]))

    detected_opp_categories = detect_categories(
        " ".join([
            safe_get(selected_opportunity, columns["opp_company"]),
            safe_get(selected_opportunity, columns["opp_sector"]),
            safe_get(selected_opportunity, columns["opp_subsector"]),
            safe_get(selected_opportunity, columns["opp_description"]),
        ])
    )

    st.write("**Detected Sector Category**")
    st.write(format_categories(detected_opp_categories) if detected_opp_categories else "No clear category detected.")

    opportunity_website_text = get_enrichment_text(
        website_enrichment,
        enrichment_columns,
        selected_opportunity_name,
        source_type="Opportunity"
    )

    if opportunity_website_text:
        with st.expander("Website / Source Keywords for This Opportunity"):
            st.write(opportunity_website_text[:1500])

    if st.button("Find Best PE Matches", key="find_pe_matches"):
        results = []

        for _, fund in pe_funds.iterrows():
            match = score_match(
                selected_opportunity,
                fund,
                portfolio_companies,
                website_enrichment,
                columns,
                enrichment_columns
            )

            results.append({
                "PE Fund": safe_get(fund, columns["fund_name"]),
                "Sector Focus": safe_get(fund, columns["fund_sector"]),
                "Matched Sector": match["sector_match"],
                "Match Score": match["score"],
                "Portfolio Signal": match["portfolio_signal"],
                "Specific Signal": match["specific_signal"],
                "Website Signal": match["website_signal"],
                "Geography Signal": match["geography_signal"],
                "Reason": match["reason"],
            })

        results_df = pd.DataFrame(results)

        # Hide funds that did not pass the sector gate
        results_df = results_df[results_df["Match Score"] > 0]
        results_df = results_df.sort_values("Match Score", ascending=False).head(10)

        st.subheader("Top PE Matches")

        if results_df.empty:
            st.warning("No PE funds passed the sector gate for this opportunity.")
        else:
            st.dataframe(results_df, use_container_width=True)


# -----------------------------
# Tab 2: PE fund to opportunities
# -----------------------------

with tab2:
    st.header("Find the best opportunities for a PE fund")

    fund_names = pe_funds[columns["fund_name"]].astype(str).tolist()

    selected_fund_name = st.selectbox(
        "Select a PE fund",
        fund_names,
        key="fund_selector"
    )

    selected_fund = pe_funds[
        pe_funds[columns["fund_name"]].astype(str) == selected_fund_name
    ].iloc[0]

    st.subheader("Selected PE Fund")

    col1, col2 = st.columns(2)

    with col1:
        st.write("**PE Fund**")
        st.write(safe_get(selected_fund, columns["fund_name"]))

    with col2:
        st.write("**Sector Focus**")
        st.write(safe_get(selected_fund, columns["fund_sector"]))

    fund_website_text = get_enrichment_text(
        website_enrichment,
        enrichment_columns,
        selected_fund_name,
        source_type="PE Fund"
    )

    if fund_website_text:
        with st.expander("Website Keywords for This PE Fund"):
            st.write(fund_website_text[:1500])

    if columns["portfolio_fund"] and columns["portfolio_company"]:
        related_portfolio = portfolio_companies[
            portfolio_companies[columns["portfolio_fund"]].astype(str).str.lower().str.strip()
            == selected_fund_name.lower().strip()
        ]

        st.write("**Portfolio Companies Found**")
        st.write(len(related_portfolio))

        if len(related_portfolio) > 0:
            st.dataframe(
                related_portfolio.head(20),
                use_container_width=True
            )

    if st.button("Find Best Opportunities", key="find_opportunity_matches"):
        results = []

        for _, opportunity in opportunities.iterrows():
            match = score_match(
                opportunity,
                selected_fund,
                portfolio_companies,
                website_enrichment,
                columns,
                enrichment_columns
            )

            results.append({
                "Opportunity": safe_get(opportunity, columns["opp_company"]),
                "Sector": safe_get(opportunity, columns["opp_sector"]),
                "Subsector": safe_get(opportunity, columns["opp_subsector"]),
                "Matched Sector": match["sector_match"],
                "Match Score": match["score"],
                "Portfolio Signal": match["portfolio_signal"],
                "Specific Signal": match["specific_signal"],
                "Website Signal": match["website_signal"],
                "Geography Signal": match["geography_signal"],
                "Reason": match["reason"],
                "Description": safe_get(opportunity, columns["opp_description"]),
            })

        results_df = pd.DataFrame(results)

        # Hide opportunities that do not pass the sector gate
        results_df = results_df[results_df["Match Score"] > 0]
        results_df = results_df.sort_values("Match Score", ascending=False).head(20)

        st.subheader("Top Opportunities")

        if results_df.empty:
            st.warning("No opportunities passed the sector gate for this PE fund.")
        else:
            st.dataframe(results_df, use_container_width=True)


# -----------------------------
# Tab 3: Website enrichment data
# -----------------------------

with tab3:
    st.header("Website Enrichment Data")

    if website_enrichment.empty:
        st.warning("No website enrichment data found. Run enrich_websites.py first.")
    else:
        st.write("This data was generated from the public links already present in your CSV files.")
        st.dataframe(website_enrichment, use_container_width=True)
        