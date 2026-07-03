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


def parse_number(value):
    """Return a float from values like 5, "5", "€5m", "5,5", or blank."""
    if value is None:
        return None

    text = str(value).strip()
    if text == "" or text.lower() in {"nan", "none", "n/a", "na", "nd", "n.d."}:
        return None

    # Keep only digits, minus signs, commas, and dots.
    text = text.replace("€", "").replace("$", "")
    text = text.replace("m€", "").replace("€m", "")
    text = text.replace("mm", "").replace("mn", "")
    text = re.sub(r"[^0-9,\.\-]", "", text)

    if text == "" or text == "-":
        return None

    # European decimal handling: "5,5" -> "5.5".
    # If both comma and dot exist, assume commas are thousands separators.
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    elif "," in text and "." in text:
        text = text.replace(",", "")

    try:
        return float(text)
    except ValueError:
        return None


def format_metric(value):
    if value is None:
        return "n.a."
    if abs(value - round(value)) < 0.001:
        return f"€{int(round(value))}m"
    return f"€{value:.1f}m"


def format_range(min_value, max_value):
    if min_value is None and max_value is None:
        return "not defined"
    if min_value is None:
        return f"≤ {format_metric(max_value)}"
    if max_value is None:
        return f"≥ {format_metric(min_value)}"
    return f"{format_metric(min_value)}–{format_metric(max_value)}"


def get_number(row, col):
    if col is None:
        return None
    return parse_number(row.get(col, ""))


def range_fit(value, min_value, max_value, label):
    """Score how well an opportunity metric fits a fund range."""
    if value is None:
        return {
            "scored": False,
            "ratio": 0,
            "status": "Missing opportunity data",
            "detail": f"{label}: opportunity value is missing.",
        }

    if min_value is None and max_value is None:
        return {
            "scored": False,
            "ratio": 0,
            "status": "Fund range missing",
            "detail": f"{label}: fund range is not defined.",
        }

    in_range = True
    if min_value is not None and value < min_value:
        in_range = False
    if max_value is not None and value > max_value:
        in_range = False

    if in_range:
        return {
            "scored": True,
            "ratio": 1.0,
            "status": "Match",
            "detail": f"{label}: {format_metric(value)} fits fund range {format_range(min_value, max_value)}.",
        }

    # Partial score if the opportunity is close to the target range.
    if min_value is not None and value < min_value:
        distance = (min_value - value) / max(min_value, 1)
        ratio = max(0, 1 - distance)
        status = "Near below range" if ratio >= 0.60 else "Below range"
        return {
            "scored": True,
            "ratio": ratio,
            "status": status,
            "detail": f"{label}: {format_metric(value)} is below fund range {format_range(min_value, max_value)}.",
        }

    if max_value is not None and value > max_value:
        distance = (value - max_value) / max(max_value, 1)
        ratio = max(0, 1 - distance)
        status = "Near above range" if ratio >= 0.60 else "Above range"
        return {
            "scored": True,
            "ratio": ratio,
            "status": status,
            "detail": f"{label}: {format_metric(value)} is above fund range {format_range(min_value, max_value)}.",
        }

    return {
        "scored": True,
        "ratio": 0,
        "status": "No match",
        "detail": f"{label}: no match.",
    }


def add_weighted_score(score_data, weight, fit_result):
    if not fit_result["scored"]:
        return
    score_data["possible"] += weight
    score_data["earned"] += weight * fit_result["ratio"]


def classify_recommendation(score, data_completeness, sector_status):
    if sector_status == "No match":
        return "Weak fit / wrong sector"
    if data_completeness < 50:
        return "Review manually / low data"
    if score >= 75:
        return "Strong match"
    if score >= 55:
        return "Review"
    return "Weak fit"


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

    # Opportunity fields
    opp_sector = safe_get(opportunity, columns["opp_sector"])
    opp_subsector = safe_get(opportunity, columns["opp_subsector"])
    opp_description = safe_get(opportunity, columns["opp_description"])
    opp_business_model = safe_get(opportunity, columns["opp_business_model"])
    opp_characteristics = safe_get(opportunity, columns["opp_characteristics"])
    opp_country = safe_get(opportunity, columns["opp_country"])
    opp_deal_type = safe_get(opportunity, columns["opp_deal_type"])

    opp_ebitda = get_number(opportunity, columns["opp_ebitda"])
    opp_revenue = get_number(opportunity, columns["opp_revenue"])
    opp_ticket = get_number(opportunity, columns["opp_ticket"])

    # Fund fields
    fund_primary_sector = safe_get(fund, columns["fund_sector"])
    fund_secondary_sector = safe_get(fund, columns["fund_secondary_sector"])
    fund_business_model = safe_get(fund, columns["fund_business_model"])
    fund_preferred = safe_get(fund, columns["fund_preferred_characteristics"])
    fund_avoid = safe_get(fund, columns["fund_avoid"])
    fund_geography = safe_get(fund, columns["fund_geography"])
    fund_transaction_type = safe_get(fund, columns["fund_transaction_type"])
    fund_notes = safe_get(fund, columns["fund_notes"])

    fund_ebitda_min = get_number(fund, columns["fund_ebitda_min"])
    fund_ebitda_max = get_number(fund, columns["fund_ebitda_max"])
    fund_revenue_min = get_number(fund, columns["fund_revenue_min"])
    fund_revenue_max = get_number(fund, columns["fund_revenue_max"])
    fund_ticket_min = get_number(fund, columns["fund_ticket_min"])
    fund_ticket_max = get_number(fund, columns["fund_ticket_max"])

    # Website enrichment
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
        opp_business_model,
        opp_characteristics,
        opp_country,
        opp_deal_type,
        opportunity_enrichment_text[:800],
    ])

    fund_focus_text = " ".join([
        fund_name,
        fund_primary_sector,
        fund_secondary_sector,
        fund_business_model,
        fund_preferred,
        fund_geography,
        fund_transaction_type,
        fund_notes,
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

    weights = {
        "ebitda": 25,
        "revenue": 20,
        "ticket": 20,
        "sector": 25,
        "characteristics": 10,
    }

    score_data = {"earned": 0.0, "possible": 0.0}

    # 1. Financial fit
    ebitda_fit = range_fit(opp_ebitda, fund_ebitda_min, fund_ebitda_max, "EBITDA")
    revenue_fit = range_fit(opp_revenue, fund_revenue_min, fund_revenue_max, "Revenue")
    ticket_fit = range_fit(opp_ticket, fund_ticket_min, fund_ticket_max, "Ticket")

    add_weighted_score(score_data, weights["ebitda"], ebitda_fit)
    add_weighted_score(score_data, weights["revenue"], revenue_fit)
    add_weighted_score(score_data, weights["ticket"], ticket_fit)

    # 2. Sector fit
    opportunity_categories = detect_categories(opportunity_text)
    fund_categories = detect_categories(fund_focus_text)
    portfolio_categories = detect_categories(portfolio_text)
    website_categories = detect_categories(fund_enrichment_text)

    sector_matches = opportunity_categories & fund_categories
    portfolio_sector_matches = opportunity_categories & portfolio_categories
    website_sector_matches = opportunity_categories & website_categories

    sector_possible = len(opportunity_categories) > 0 and (
        len(fund_categories) > 0 or len(portfolio_categories) > 0 or len(website_categories) > 0
    )

    sector_ratio = 0
    if len(sector_matches) > 0:
        sector_ratio = 1.0
        sector_status = "Match"
        sector_detail = "Sector: fund focus matches " + format_categories(sector_matches) + "."
    elif len(portfolio_sector_matches) > 0:
        sector_ratio = 0.80
        sector_status = "Portfolio match"
        sector_detail = "Sector: portfolio companies show exposure to " + format_categories(portfolio_sector_matches) + "."
    elif len(website_sector_matches) > 0:
        sector_ratio = 0.60
        sector_status = "Website match"
        sector_detail = "Sector: website text shows exposure to " + format_categories(website_sector_matches) + "."
    elif sector_possible:
        sector_status = "No match"
        sector_detail = "Sector: no clear match. Opportunity is " + format_categories(opportunity_categories) + "."
    else:
        sector_status = "Not scored"
        sector_detail = "Sector: not enough sector data to score."

    if sector_possible:
        score_data["possible"] += weights["sector"]
        score_data["earned"] += weights["sector"] * sector_ratio

    # 3. Characteristics fit
    opportunity_specific = detect_specific_terms(opportunity_text)
    fund_specific = detect_specific_terms(fund_focus_text + " " + portfolio_text)
    website_specific = detect_specific_terms(fund_enrichment_text)
    avoid_specific = detect_specific_terms(fund_avoid)

    specific_matches = opportunity_specific & fund_specific
    website_specific_matches = opportunity_specific & website_specific
    avoid_matches = opportunity_specific & avoid_specific

    opportunity_geo = detect_geography(opportunity_text)
    fund_geo = detect_geography(fund_focus_text + " " + fund_enrichment_text)
    geography_matches = opportunity_geo & fund_geo

    characteristics_possible = len(opportunity_text.strip()) > 0 and len(fund_focus_text.strip()) > 0
    characteristics_ratio = 0

    if len(specific_matches) > 0:
        characteristics_ratio += 0.55
    if len(website_specific_matches) > 0:
        characteristics_ratio += 0.15
    if len(geography_matches) > 0:
        characteristics_ratio += 0.15

    # Explicit B2B / B2C and deal-type signals
    if opp_business_model and fund_business_model and normalize_text(opp_business_model) in normalize_text(fund_business_model):
        characteristics_ratio += 0.10
    if opp_deal_type and fund_transaction_type and normalize_text(opp_deal_type) in normalize_text(fund_transaction_type):
        characteristics_ratio += 0.10

    if len(avoid_matches) > 0:
        characteristics_ratio -= 0.30

    characteristics_ratio = max(0, min(characteristics_ratio, 1.0))

    if len(avoid_matches) > 0:
        characteristics_status = "Risk / avoid signal"
    elif characteristics_ratio >= 0.70:
        characteristics_status = "Match"
    elif characteristics_ratio >= 0.35:
        characteristics_status = "Partial match"
    elif characteristics_possible:
        characteristics_status = "Weak match"
    else:
        characteristics_status = "Not scored"

    characteristics_parts = []
    if len(specific_matches) > 0:
        characteristics_parts.append("matched terms: " + ", ".join(sorted(specific_matches)[:8]))
    if len(website_specific_matches) > 0:
        characteristics_parts.append("website confirms: " + ", ".join(sorted(website_specific_matches)[:6]))
    if len(geography_matches) > 0:
        characteristics_parts.append("geography: " + ", ".join(sorted(geography_matches)))
    if len(avoid_matches) > 0:
        characteristics_parts.append("avoid/risk terms: " + ", ".join(sorted(avoid_matches)[:6]))

    if characteristics_parts:
        characteristics_detail = "Characteristics: " + "; ".join(characteristics_parts) + "."
    else:
        characteristics_detail = "Characteristics: no strong qualitative match found."

    if characteristics_possible:
        score_data["possible"] += weights["characteristics"]
        score_data["earned"] += weights["characteristics"] * characteristics_ratio

    # Final scores
    total_weight = sum(weights.values())
    if score_data["possible"] > 0:
        fit_score = (score_data["earned"] / score_data["possible"]) * 100
    else:
        fit_score = 0

    data_completeness = (score_data["possible"] / total_weight) * 100

    # Adjusted score rewards both quality of fit and data completeness.
    match_score = fit_score * (data_completeness / 100)

    # If sector clearly does not match, cap the score even when financials fit.
    if sector_status == "No match":
        match_score = min(match_score, 45)

    match_score = round(match_score, 1)
    fit_score = round(fit_score, 1)
    data_completeness = round(data_completeness, 1)

    recommendation = classify_recommendation(match_score, data_completeness, sector_status)

    matched_sector = format_categories(sector_matches | portfolio_sector_matches | website_sector_matches)

    reasons = [
        ebitda_fit["detail"],
        revenue_fit["detail"],
        ticket_fit["detail"],
        sector_detail,
        characteristics_detail,
    ]

    return {
        "score": match_score,
        "fit_score": fit_score,
        "data_completeness": data_completeness,
        "recommendation": recommendation,
        "reason": " ".join(reasons),
        "matched_sector": matched_sector,
        "ebitda_fit": ebitda_fit["status"] + " — " + ebitda_fit["detail"],
        "revenue_fit": revenue_fit["status"] + " — " + revenue_fit["detail"],
        "ticket_fit": ticket_fit["status"] + " — " + ticket_fit["detail"],
        "sector_fit": sector_status + " — " + sector_detail,
        "characteristics_fit": characteristics_status + " — " + characteristics_detail,
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
    "Version 3.0: Financial and strategic matching. The app now scores EBITDA, revenue, "
    "ticket size, sector fit, and qualitative characteristics, then shows where each fund matches or does not match."
)
pe_funds = load_csv("pe_funds_database.csv")
portfolio_companies = load_csv("portfolio_companies.csv")
opportunities = load_csv("opportunities.csv")
website_enrichment = load_optional_csv("website_enrichment.csv")


columns = {
    # PE fund database columns
    "fund_name": find_column(pe_funds, ["fund_name", "fund", "name", "pe_fund"]),
    "fund_sector": find_column(pe_funds, ["primary_sectors", "sector_focus", "sector", "sectors", "preferred_sectors", "sector_focus_original"]),
    "fund_secondary_sector": find_column(pe_funds, ["secondary_sectors", "secondary_sector", "other_sectors"]),
    "fund_business_model": find_column(pe_funds, ["business_model_preference", "business_model", "model_preference"]),
    "fund_preferred_characteristics": find_column(pe_funds, ["preferred_characteristics", "characteristics", "preferences", "investment_criteria"]),
    "fund_avoid": find_column(pe_funds, ["avoid", "avoids", "negative_criteria", "not_interested"]),
    "fund_geography": find_column(pe_funds, ["geography", "country", "region", "regions"]),
    "fund_transaction_type": find_column(pe_funds, ["transaction_type", "deal_type", "investment_type"]),
    "fund_notes": find_column(pe_funds, ["notes", "comments", "description"]),

    "fund_ebitda_min": find_column(pe_funds, ["ebitda_min", "min_ebitda", "ebitda_minimum"]),
    "fund_ebitda_max": find_column(pe_funds, ["ebitda_max", "max_ebitda", "ebitda_maximum"]),
    "fund_revenue_min": find_column(pe_funds, ["revenue_min", "min_revenue", "sales_min", "turnover_min"]),
    "fund_revenue_max": find_column(pe_funds, ["revenue_max", "max_revenue", "sales_max", "turnover_max"]),
    "fund_ticket_min": find_column(pe_funds, ["ticket_min", "min_ticket", "equity_ticket_min", "investment_min"]),
    "fund_ticket_max": find_column(pe_funds, ["ticket_max", "max_ticket", "equity_ticket_max", "investment_max"]),

    # Portfolio company columns
    "portfolio_fund": find_column(portfolio_companies, ["fund_name", "fund", "pe_fund"]),
    "portfolio_company": find_column(portfolio_companies, ["company", "portfolio_company", "name"]),
    "portfolio_activity": find_column(portfolio_companies, ["activity", "sector", "description", "business_description"]),

    # Opportunity columns
    "opp_company": find_column(opportunities, ["company", "name", "opportunity", "company_name"]),
    "opp_sector": find_column(opportunities, ["sector", "industry", "primary_sector"]),
    "opp_subsector": find_column(opportunities, ["subsector", "sub_sector", "secondary_sector"]),
    "opp_description": find_column(opportunities, ["description", "business_description", "activity", "summary"]),
    "opp_ebitda": find_column(opportunities, ["ebitda", "ebitda_m", "ebitda_m_eur", "ebitda_million", "ebitda_millions", "company_ebitda"]),
    "opp_revenue": find_column(opportunities, ["revenue", "revenues", "sales", "turnover", "revenue_m", "revenue_m_eur", "revenue_million"]),
    "opp_ticket": find_column(opportunities, ["ticket", "ticket_size", "equity_ticket", "investment_needed", "equity_needed", "deal_size", "enterprise_value", "valuation", "ev"]),
    "opp_business_model": find_column(opportunities, ["business_model", "model", "b2b_b2c"]),
    "opp_characteristics": find_column(opportunities, ["characteristics", "key_characteristics", "tags", "keywords", "notes"]),
    "opp_country": find_column(opportunities, ["country", "geography", "location", "region"]),
    "opp_deal_type": find_column(opportunities, ["deal_type", "transaction_type", "process_type"]),
}


enrichment_columns = {
    "source_type": find_column(website_enrichment, ["source_type"]),
    "name": find_column(website_enrichment, ["name"]),
    "url": find_column(website_enrichment, ["url", "website", "link"]),
    "keywords": find_column(website_enrichment, ["keywords"]),
    "text_preview": find_column(website_enrichment, ["text_preview", "preview"]),
}


required_columns = ["fund_name", "fund_sector", "opp_company", "opp_sector", "opp_description"]

missing = [
    key for key in required_columns
    if columns.get(key) is None
]

if missing:
    st.error("Some required columns were not found.")
    st.write("Missing required columns:", missing)
    st.write("PE Funds columns:", list(pe_funds.columns))
    st.write("Portfolio Companies columns:", list(portfolio_companies.columns))
    st.write("Opportunities columns:", list(opportunities.columns))
    st.stop()

optional_missing = [
    key for key, value in columns.items()
    if value is None and key not in required_columns
]

if optional_missing:
    st.sidebar.warning("Some optional columns were not found. They will be marked as not scored.")
    with st.sidebar.expander("Optional missing columns"):
        st.write(optional_missing)


st.sidebar.header("Data Loaded")
st.sidebar.write(f"PE Funds: {len(pe_funds)}")
st.sidebar.write(f"Portfolio Companies: {len(portfolio_companies)}")
st.sidebar.write(f"Opportunities: {len(opportunities)}")

tab1, tab2 = st.tabs([
    "Opportunity → PE Funds",
    "PE Fund → Opportunities"
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

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.write("**Company**")
        st.write(safe_get(selected_opportunity, columns["opp_company"]))

    with col2:
        st.write("**Sector**")
        st.write(safe_get(selected_opportunity, columns["opp_sector"]))

    with col3:
        st.write("**Subsector**")
        st.write(safe_get(selected_opportunity, columns["opp_subsector"]))

    with col4:
        st.write("**Financials**")
        st.write("EBITDA:", format_metric(get_number(selected_opportunity, columns["opp_ebitda"])))
        st.write("Revenue:", format_metric(get_number(selected_opportunity, columns["opp_revenue"])))
        st.write("Ticket:", format_metric(get_number(selected_opportunity, columns["opp_ticket"])))

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
                "Recommendation": match["recommendation"],
                "Match Score": match["score"],
                "Fit Score": match["fit_score"],
                "Data Completeness": match["data_completeness"],
                "EBITDA Fit": match["ebitda_fit"],
                "Revenue Fit": match["revenue_fit"],
                "Ticket Fit": match["ticket_fit"],
                "Sector Fit": match["sector_fit"],
                "Characteristics Fit": match["characteristics_fit"],
                "Matched Sector": match["matched_sector"],
                "Primary Sectors": safe_get(fund, columns["fund_sector"]),
                "Reason": match["reason"],
            })

        results_df = pd.DataFrame(results)

        results_df = results_df.sort_values(
            ["Match Score", "Data Completeness", "Fit Score"],
            ascending=False
        ).head(20)

        st.subheader("Top PE Matches")

        if results_df.empty:
            st.warning("No PE fund matches were produced. Check whether the opportunity has sector and financial data.")
        else:
            st.dataframe(results_df, use_container_width=True)
            st.download_button(
                "Download results as CSV",
                data=results_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="opportunity_match_results.csv",
                mime="text/csv",
            )
            st.download_button(
                "Download results as CSV",
                data=results_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="pe_match_results.csv",
                mime="text/csv",
            )


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

    col1, col2, col3 = st.columns(3)

    with col1:
        st.write("**PE Fund**")
        st.write(safe_get(selected_fund, columns["fund_name"]))

    with col2:
        st.write("**Sector Focus**")
        st.write(safe_get(selected_fund, columns["fund_sector"]))

    with col3:
        st.write("**Target Ranges**")
        st.write("EBITDA:", format_range(get_number(selected_fund, columns["fund_ebitda_min"]), get_number(selected_fund, columns["fund_ebitda_max"])))
        st.write("Revenue:", format_range(get_number(selected_fund, columns["fund_revenue_min"]), get_number(selected_fund, columns["fund_revenue_max"])))
        st.write("Ticket:", format_range(get_number(selected_fund, columns["fund_ticket_min"]), get_number(selected_fund, columns["fund_ticket_max"])))

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
                "Recommendation": match["recommendation"],
                "Match Score": match["score"],
                "Fit Score": match["fit_score"],
                "Data Completeness": match["data_completeness"],
                "EBITDA Fit": match["ebitda_fit"],
                "Revenue Fit": match["revenue_fit"],
                "Ticket Fit": match["ticket_fit"],
                "Sector Fit": match["sector_fit"],
                "Characteristics Fit": match["characteristics_fit"],
                "Sector": safe_get(opportunity, columns["opp_sector"]),
                "Subsector": safe_get(opportunity, columns["opp_subsector"]),
                "Reason": match["reason"],
                "Description": safe_get(opportunity, columns["opp_description"]),
            })

        results_df = pd.DataFrame(results)

        results_df = results_df.sort_values(
            ["Match Score", "Data Completeness", "Fit Score"],
            ascending=False
        ).head(30)

        st.subheader("Top Opportunities")

        if results_df.empty:
            st.warning("No opportunity matches were produced. Check whether opportunities have sector and financial data.")
        else:
            st.dataframe(results_df, use_container_width=True)


