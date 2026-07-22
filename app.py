import re
import html
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
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


# -----------------------------
# Google Sheets helpers
# -----------------------------

GOOGLE_SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def google_sheets_configured():
    return "gcp_service_account" in st.secrets and "google_sheets" in st.secrets


def get_google_sheets_client():
    import gspread
    from google.oauth2.service_account import Credentials

    credentials_info = dict(st.secrets["gcp_service_account"])

    # Streamlit TOML secrets may store the key with real line breaks or with escaped \n.
    if "private_key" in credentials_info:
        credentials_info["private_key"] = credentials_info["private_key"].replace("\\n", "\n")

    credentials = Credentials.from_service_account_info(
        credentials_info,
        scopes=GOOGLE_SHEETS_SCOPES,
    )

    return gspread.authorize(credentials)


def get_google_worksheet(worksheet_key, default_name):
    """Open one worksheet from the configured Google Sheets database."""
    client = get_google_sheets_client()

    spreadsheet_name = st.secrets["google_sheets"].get(
        "spreadsheet_name",
        "PE database",
    )

    # Backward compatible: old app used worksheet_name for opportunities.
    if worksheet_key == "opportunities_worksheet_name":
        worksheet_name = st.secrets["google_sheets"].get(
            worksheet_key,
            st.secrets["google_sheets"].get("worksheet_name", default_name),
        )
    else:
        worksheet_name = st.secrets["google_sheets"].get(worksheet_key, default_name)

    spreadsheet = client.open(spreadsheet_name)
    return spreadsheet.worksheet(worksheet_name)


def sheet_to_dataframe(worksheet):
    records = worksheet.get_all_records()
    df = pd.DataFrame(records)

    if df.empty:
        return pd.DataFrame()

    df.columns = [clean_column_name(c) for c in df.columns]
    return df.fillna("")


def get_opportunities_worksheet():
    return get_google_worksheet("opportunities_worksheet_name", "pe_opportunities")


def get_pe_funds_worksheet():
    return get_google_worksheet("pe_funds_worksheet_name", "pe_funds")


def get_us_pe_funds_worksheet():
    return get_google_worksheet("us_pe_funds_worksheet_name", "us_pe_funds")


def load_opportunities_from_google_sheet():
    return sheet_to_dataframe(get_opportunities_worksheet())


def load_pe_funds_from_google_sheet():
    return sheet_to_dataframe(get_pe_funds_worksheet())


def load_us_pe_funds_from_google_sheet():
    return sheet_to_dataframe(get_us_pe_funds_worksheet())


def load_opportunities_database():
    """Use Google Sheets as the live opportunities database; fall back to CSV if needed."""
    if google_sheets_configured():
        try:
            df = load_opportunities_from_google_sheet()
            if not df.empty:
                return df, "Google Sheets", ""
            return load_csv("opportunities.csv"), "CSV fallback", "Google opportunities sheet is empty."
        except Exception as exc:
            return load_csv("opportunities.csv"), "CSV fallback", str(exc)

    return load_csv("opportunities.csv"), "CSV", "Google Sheets is not configured."


def load_pe_funds_database():
    """Use Google Sheets as the live PE funds database; fall back to CSV if needed."""
    if google_sheets_configured():
        try:
            df = load_pe_funds_from_google_sheet()
            if not df.empty:
                return df, "Google Sheets", ""
            return load_csv("pe_funds_database.csv"), "CSV fallback", "Google PE funds sheet is empty."
        except Exception as exc:
            return load_csv("pe_funds_database.csv"), "CSV fallback", str(exc)

    return load_csv("pe_funds_database.csv"), "CSV", "Google Sheets is not configured."


def load_us_pe_funds_database():
    """Use the dedicated U.S. PE worksheet; fall back to a local starter CSV."""
    fallback_name = "us_pe_funds_database.csv"
    if google_sheets_configured():
        try:
            df = load_us_pe_funds_from_google_sheet()
            if not df.empty:
                return df, "Google Sheets", ""
            fallback = load_optional_csv(fallback_name)
            return fallback, "CSV fallback", "Google U.S. PE funds sheet is empty."
        except Exception as exc:
            fallback = load_optional_csv(fallback_name)
            return fallback, "CSV fallback", str(exc)

    return load_optional_csv(fallback_name), "CSV", "Google Sheets is not configured."


def append_row_to_worksheet(worksheet, row_data):
    """Append a row using the existing sheet headers."""
    headers = worksheet.row_values(1)

    if not headers:
        raise ValueError("The Google Sheet has no header row.")

    normalized_row_data = {
        clean_column_name(key): value
        for key, value in row_data.items()
    }

    row_values = []
    for header in headers:
        clean_header = clean_column_name(header)
        row_values.append(normalized_row_data.get(clean_header, ""))

    worksheet.append_row(row_values, value_input_option="USER_ENTERED")


def append_opportunity_to_google_sheet(row_data):
    append_row_to_worksheet(get_opportunities_worksheet(), row_data)


def append_pe_fund_to_google_sheet(row_data):
    append_row_to_worksheet(get_pe_funds_worksheet(), row_data)


def append_us_pe_fund_to_google_sheet(row_data):
    append_row_to_worksheet(get_us_pe_funds_worksheet(), row_data)


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


def format_metric(value, currency_symbol="€"):
    if value is None:
        return "n.a."
    if abs(value - round(value)) < 0.001:
        return f"{currency_symbol}{int(round(value))}m"
    return f"{currency_symbol}{value:.1f}m"


def format_range(min_value, max_value, currency_symbol="€"):
    if min_value is None and max_value is None:
        return "not defined"
    if min_value is None:
        return f"≤ {format_metric(max_value, currency_symbol)}"
    if max_value is None:
        return f"≥ {format_metric(min_value, currency_symbol)}"
    return f"{format_metric(min_value, currency_symbol)}–{format_metric(max_value, currency_symbol)}"


def get_number(row, col):
    if col is None:
        return None
    return parse_number(row.get(col, ""))


def range_fit(value, min_value, max_value, label, currency_symbol="€"):
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
            "detail": f"{label}: {format_metric(value, currency_symbol)} fits fund range {format_range(min_value, max_value, currency_symbol)}.",
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
            "detail": f"{label}: {format_metric(value, currency_symbol)} is below fund range {format_range(min_value, max_value, currency_symbol)}.",
        }

    if max_value is not None and value > max_value:
        distance = (value - max_value) / max(max_value, 1)
        ratio = max(0, 1 - distance)
        status = "Near above range" if ratio >= 0.60 else "Above range"
        return {
            "scored": True,
            "ratio": ratio,
            "status": status,
            "detail": f"{label}: {format_metric(value, currency_symbol)} is above fund range {format_range(min_value, max_value, currency_symbol)}.",
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
            "spain", "spanish", "espana", "españa", "madrid", "barcelona",
            "valencia", "sevilla", "bilbao"
        ],
        "iberia": [
            "iberia", "iberian", "spain", "portugal", "espana", "españa"
        ],
        "portugal": [
            "portugal", "lisbon", "porto"
        ],
        "france": [
            "france", "french", "francia", "paris"
        ],
        "italy": [
            "italy", "italia", "italian", "milan", "milano", "rome", "roma"
        ],
        "united_kingdom": [
            "united kingdom", "uk", "britain", "british", "london"
        ],
        "united_states": [
            "united states", "usa", "us", "america", "american", "new york"
        ],
        "europe": [
            "europe", "european", "europa", "western europe", "southern europe"
        ],
        "latin_america": [
            "latin america", "latam", "mexico", "colombia",
            "chile", "argentina", "peru"
        ],
        "global": [
            "global", "worldwide", "international", "agnostic"
        ],
    }

    detected = set()

    for geo, keywords in geographies.items():
        for keyword in keywords:
            if contains_term(text, keyword):
                detected.add(geo)
                break

    return detected


def format_geographies(geographies):
    labels = {
        "spain": "Spain",
        "iberia": "Iberia",
        "portugal": "Portugal",
        "france": "France",
        "italy": "Italy",
        "united_kingdom": "United Kingdom",
        "united_states": "United States",
        "europe": "Europe",
        "latin_america": "Latin America",
        "global": "Global",
    }

    return ", ".join(labels.get(g, g) for g in sorted(geographies))


def geography_fit(opportunity_geo, fund_geo):
    """Score geography fit as a bonus, without making it a hard filter."""
    if not opportunity_geo:
        return {
            "scored": False,
            "ratio": 0,
            "status": "Missing opportunity geography",
            "detail": "Geography: opportunity geography is not clearly defined.",
            "matches": set(),
        }

    if not fund_geo:
        return {
            "scored": False,
            "ratio": 0,
            "status": "Fund geography missing",
            "detail": "Geography: fund geography is not clearly defined.",
            "matches": set(),
        }

    direct_matches = opportunity_geo & fund_geo
    if direct_matches:
        return {
            "scored": True,
            "ratio": 1.0,
            "status": "Match",
            "detail": "Geography: direct match on " + format_geographies(direct_matches) + ".",
            "matches": direct_matches,
        }

    broad_matches = set()

    # Broad region logic: a Spanish or Portuguese opportunity can fit an Iberian fund,
    # and European country opportunities can fit a Europe-focused fund.
    if "iberia" in fund_geo and (opportunity_geo & {"spain", "portugal"}):
        broad_matches.add("iberia")
    if "europe" in fund_geo and (opportunity_geo & {"spain", "portugal", "france", "italy", "united_kingdom", "iberia"}):
        broad_matches.add("europe")
    if "global" in fund_geo:
        broad_matches.add("global")
    if "latin_america" in fund_geo and (opportunity_geo & {"latin_america"}):
        broad_matches.add("latin_america")

    if broad_matches:
        return {
            "scored": True,
            "ratio": 0.85,
            "status": "Broad region match",
            "detail": "Geography: broad region match on " + format_geographies(broad_matches) + ".",
            "matches": broad_matches,
        }

    return {
        "scored": True,
        "ratio": 0,
        "status": "No match",
        "detail": (
            "Geography: no clear match. Opportunity geography is "
            + format_geographies(opportunity_geo)
            + "; fund geography is "
            + format_geographies(fund_geo)
            + "."
        ),
        "matches": set(),
    }


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

def score_match(opportunity, fund, portfolio_companies, enrichment, columns, enrichment_columns, currency_symbol="€"):
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

    # Matching weights:
    # Revenue and ticket size are intentionally NOT used in the score.
    # They remain available as reference information in the app/export.
    weights = {
        "sector": 50,
        "ebitda": 35,
        "geography": 15,
    }

    score_data = {"earned": 0.0, "possible": 0.0}

    # 1. EBITDA fit
    # Only EBITDA is scored. Revenue and ticket are reference-only.
    ebitda_fit = range_fit(opp_ebitda, fund_ebitda_min, fund_ebitda_max, "EBITDA", currency_symbol)
    add_weighted_score(score_data, weights["ebitda"], ebitda_fit)

    revenue_reference = (
        f"Reference only — opportunity revenue {format_metric(opp_revenue, currency_symbol)}; "
        f"fund revenue range {format_range(fund_revenue_min, fund_revenue_max, currency_symbol)}. Not used in score."
    )
    ticket_reference = (
        f"Reference only — opportunity ticket/EV {format_metric(opp_ticket, currency_symbol)}; "
        f"fund ticket range {format_range(fund_ticket_min, fund_ticket_max, currency_symbol)}. Not used in score."
    )

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

    # 3. Geography fit
    # Geography is scored as a smaller bonus. It is not a hard filter.
    opportunity_geo = detect_geography(opportunity_text)
    fund_geo = detect_geography(fund_focus_text + " " + fund_enrichment_text)
    geography_result = geography_fit(opportunity_geo, fund_geo)
    geography_matches = geography_result["matches"]

    add_weighted_score(score_data, weights["geography"], geography_result)

    # 4. Qualitative signals
    # These are shown for context only. They do NOT influence the match score.
    opportunity_specific = detect_specific_terms(opportunity_text)
    fund_specific = detect_specific_terms(fund_focus_text + " " + portfolio_text)
    website_specific = detect_specific_terms(fund_enrichment_text)
    avoid_specific = detect_specific_terms(fund_avoid)

    specific_matches = opportunity_specific & fund_specific
    website_specific_matches = opportunity_specific & website_specific
    avoid_matches = opportunity_specific & avoid_specific

    if len(avoid_matches) > 0:
        characteristics_status = "Risk / avoid signal"
    elif len(specific_matches) > 0 or len(website_specific_matches) > 0:
        characteristics_status = "Reference signal"
    else:
        characteristics_status = "No strong reference signal"

    characteristics_parts = []
    if len(specific_matches) > 0:
        characteristics_parts.append("matched reference terms: " + ", ".join(sorted(specific_matches)[:8]))
    if len(website_specific_matches) > 0:
        characteristics_parts.append("website confirms: " + ", ".join(sorted(website_specific_matches)[:6]))
    if len(avoid_matches) > 0:
        characteristics_parts.append("avoid/risk terms: " + ", ".join(sorted(avoid_matches)[:6]))

    if characteristics_parts:
        characteristics_detail = "Qualitative signals, not scored: " + "; ".join(characteristics_parts) + "."
    else:
        characteristics_detail = "Qualitative signals, not scored: no strong qualitative match found."

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
        sector_detail,
        ebitda_fit["detail"],
        geography_result["detail"],
        revenue_reference,
        ticket_reference,
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
        "revenue_reference": revenue_reference,
        "ticket_reference": ticket_reference,
        "sector_fit": sector_status + " — " + sector_detail,
        "geography_fit": geography_result["status"] + " — " + geography_result["detail"],
        "characteristics_fit": characteristics_status + " — " + characteristics_detail,
        "portfolio_signal": len(portfolio_sector_matches),
        "specific_signal": len(specific_matches),
        "website_signal": len(website_sector_matches | website_specific_matches),
        "geography_signal": len(geography_matches),
    }



# -----------------------------
# News search helpers
# -----------------------------

NEWS_SIGNAL_KEYWORDS = {
    "Acquisition / completed deal": [
        "acquires", "acquired", "acquisition", "buyout", "takes stake", "stake in",
        "compra", "adquiere", "adquisicion", "adquisición", "participacion", "participación",
        "rachète", "rachete", "acquiert", "prise de participation", "majorité", "minorité",
        "acquisisce", "compra", "rileva", "partecipazione",
        "majority stake", "minority stake", "investment in", "invierte en", "investit dans", "investe in"
    ],
    "Sale process / investor wanted": [
        "seeks investor", "seeking investor", "searches for investor", "looking for investor",
        "busca inversor", "busca socio", "busca comprador", "proceso de venta",
        "sale process", "for sale", "explores sale", "explora venta", "sell stake",
        "venta de", "poner a la venta", "mandato de venta",
        "cherche investisseur", "cherche repreneur", "mise en vente", "processus de vente",
        "mandat de vente", "à vendre", "cession",
        "cerca investitore", "cerca compratore", "processo di vendita", "in vendita"
    ],
    "Advisor / mandate signal": [
        "hires adviser", "hires advisor", "appoints adviser", "appoints advisor",
        "contrata asesor", "contrata a", "mandates", "mandata", "mandato",
        "mandate", "advisor", "adviser",
        "mandate", "mandaté", "mandatee", "banque d'affaires", "conseil m&a",
        "incarica", "advisor", "mandato",
        "lazard", "rothschild", "alantra", "az capital", "kpmg", "pwc", "deloitte", "ey",
        "clearwater", "dc advisory", "natixis", "goetzpartners", "nomura", "jefferies"
    ],
    "PE fund activity": [
        "private equity", "pe fund", "fondo de private equity", "capital privado",
        "capital riesgo", "fondo de capital riesgo",
        "raises fund", "closes fund", "fundraising", "levanta fondo", "cierra fondo",
        "new fund", "nuevo fondo",
        "capital-investissement", "fonds d'investissement", "levee de fonds", "levée de fonds",
        "private equity", "fondo", "raccolta", "fundraising"
    ],
    "Strategic growth signal": [
        "expansion", "expands", "growth plan", "strategic plan", "raises debt",
        "refinancing", "international expansion", "crecimiento", "expansion", "expansión",
        "plan estrategico", "plan estratégico", "refinanciacion", "refinanciación",
        "croissance externe", "développement", "refinancement",
        "crescita", "espansione", "piano strategico", "rifinanziamento"
    ],
}

SOURCE_TIER_KEYWORDS = {
    "Spain Tier 1": ["eleconomista", "el economista", "capital riesgo"],
    "Spain Tier 2": ["expansion", "expansión", "elconfidencial", "el confidencial"],
    "France Priority": ["cfnews", "les echos", "capital finance", "fusacq", "magazine des affaires"],
    "US / UK Priority": ["reuters", "bloomberg", "financial times", "ft.com", "wall street journal", "wsj", "pe hub", "pitchbook"],
    "Italy Priority": ["bebeez", "il sole 24 ore", "milanofinanza", "milano finanza", "borsaitaliana", "aifi"],
}

PRIORITY_SOURCE_DOMAINS = {
    "Spain": ["eleconomista.es", "expansion.com", "elconfidencial.com"],
    "France": ["cfnews.net", "lesechos.fr", "fusacq.com"],
    "United States": ["reuters.com", "bloomberg.com", "pehub.com", "pitchbook.com"],
    "United Kingdom": ["ft.com", "reuters.com", "cityam.com"],
    "Italy": ["bebeez.it", "ilsole24ore.com", "milanofinanza.it"],
}

MARKET_SETTINGS = {
    "Spain": {
        "hl": "es-ES",
        "gl": "ES",
        "ceid": "ES:es",
        "country_terms": ["España", "Spain"],
        "queries": {
            "General M&A / PE": [
                "España capital riesgo adquisición when:{days}d",
                "España private equity compra empresa when:{days}d",
                "España fusiones adquisiciones capital riesgo when:{days}d",
                "site:eleconomista.es/capital-riesgo adquisición OR compra when:{days}d",
                "site:eleconomista.es/capital-riesgo busca comprador OR proceso de venta when:{days}d",
            ],
            "Restaurants / Hospitality": [
                "España restaurantes adquisición capital riesgo when:{days}d",
                "España hostelería busca inversor when:{days}d",
                "España restaurantes proceso de venta when:{days}d",
                "España cafeterías adquisición inversión when:{days}d",
            ],
            "Food & Beverage / Consumer": [
                "España alimentación adquisición capital riesgo when:{days}d",
                "España bebidas adquisición inversión when:{days}d",
                "España gran consumo busca inversor when:{days}d",
                "España empresa alimentación proceso de venta when:{days}d",
            ],
            "Investor wanted / sale signals": [
                '"busca inversor" empresa España when:{days}d',
                '"busca socio" empresa España inversión when:{days}d',
                '"busca comprador" empresa España when:{days}d',
                '"proceso de venta" empresa España when:{days}d',
                '"explora venta" empresa España when:{days}d',
                '"prepara su venta" empresa España when:{days}d',
            ],
            "Advisors / deal mandates": [
                'Alantra venta empresa España when:{days}d',
                'Lazard venta empresa España when:{days}d',
                'Rothschild venta empresa España when:{days}d',
                'KPMG corporate finance venta empresa España when:{days}d',
                'Deloitte corporate finance venta empresa España when:{days}d',
                'AZ Capital venta empresa España when:{days}d',
            ],
            "Fundraising / PE funds": [
                "España capital riesgo nuevo fondo when:{days}d",
                "España fondo capital privado levanta fondo when:{days}d",
                "España private equity fundraising when:{days}d",
            ],
        },
    },
    "France": {
        "hl": "fr-FR",
        "gl": "FR",
        "ceid": "FR:fr",
        "country_terms": ["France", "Français", "française"],
        "queries": {
            "General M&A / PE": [
                "France capital-investissement acquisition entreprise when:{days}d",
                "France private equity rachète entreprise when:{days}d",
                "France fusion acquisition fonds investissement when:{days}d",
                "site:cfnews.net acquisition capital-investissement when:{days}d",
                "site:fusacq.com cession acquisition entreprise when:{days}d",
            ],
            "Restaurants / Hospitality": [
                "France restauration acquisition capital-investissement when:{days}d",
                "France hôtellerie acquisition fonds investissement when:{days}d",
                "France restauration cherche investisseur when:{days}d",
                "France cafés restaurants cession when:{days}d",
            ],
            "Food & Beverage / Consumer": [
                "France agroalimentaire acquisition capital-investissement when:{days}d",
                "France boissons acquisition fonds investissement when:{days}d",
                "France marque consumer cherche investisseur when:{days}d",
                "France entreprise agroalimentaire cession when:{days}d",
            ],
            "Investor wanted / sale signals": [
                '"cherche investisseur" entreprise France when:{days}d',
                '"cherche repreneur" entreprise France when:{days}d',
                '"processus de vente" entreprise France when:{days}d',
                '"mise en vente" entreprise France when:{days}d',
                '"mandat de vente" entreprise France when:{days}d',
            ],
            "Advisors / deal mandates": [
                'Rothschild mandat vente entreprise France when:{days}d',
                'Lazard mandat vente entreprise France when:{days}d',
                'KPMG corporate finance cession entreprise France when:{days}d',
                'Deloitte corporate finance cession entreprise France when:{days}d',
                'Natixis Partners cession entreprise France when:{days}d',
            ],
            "Fundraising / PE funds": [
                "France capital-investissement nouveau fonds when:{days}d",
                "France fonds private equity levée de fonds when:{days}d",
                "France private equity fundraising when:{days}d",
            ],
        },
    },
    "United States": {
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
        "country_terms": ["United States", "US", "USA"],
        "queries": {
            "General M&A / PE": [
                "US private equity acquisition company when:{days}d",
                "US M&A private equity acquisition when:{days}d",
                "US private equity buys company when:{days}d",
            ],
            "Restaurants / Hospitality": [
                "US restaurant acquisition private equity when:{days}d",
                "US hospitality acquisition private equity when:{days}d",
                "US restaurant chain seeks investor when:{days}d",
            ],
            "Food & Beverage / Consumer": [
                "US food beverage acquisition private equity when:{days}d",
                "US consumer brand acquisition private equity when:{days}d",
                "US food company sale process when:{days}d",
            ],
            "Investor wanted / sale signals": [
                '"seeking investor" company US when:{days}d',
                '"sale process" company private equity US when:{days}d',
                '"explores sale" company US private equity when:{days}d',
                '"hires advisor" sale process company US when:{days}d',
            ],
            "Advisors / deal mandates": [
                'Lazard sale process company US when:{days}d',
                'Rothschild sale process company US when:{days}d',
                'Jefferies sale process company US when:{days}d',
                'Deloitte corporate finance sale company US when:{days}d',
            ],
            "Fundraising / PE funds": [
                "US private equity raises fund when:{days}d",
                "US private equity closes fund when:{days}d",
                "US lower middle market private equity fund when:{days}d",
            ],
        },
    },
    "United Kingdom": {
        "hl": "en-GB",
        "gl": "GB",
        "ceid": "GB:en",
        "country_terms": ["United Kingdom", "UK", "Britain"],
        "queries": {
            "General M&A / PE": [
                "UK private equity acquisition company when:{days}d",
                "UK M&A private equity acquisition when:{days}d",
                "UK private equity buys company when:{days}d",
            ],
            "Restaurants / Hospitality": [
                "UK restaurant acquisition private equity when:{days}d",
                "UK hospitality acquisition private equity when:{days}d",
                "UK restaurant chain sale process when:{days}d",
            ],
            "Food & Beverage / Consumer": [
                "UK food beverage acquisition private equity when:{days}d",
                "UK consumer brand acquisition private equity when:{days}d",
                "UK food company sale process when:{days}d",
            ],
            "Investor wanted / sale signals": [
                '"seeking investor" company UK when:{days}d',
                '"sale process" company private equity UK when:{days}d',
                '"explores sale" company UK private equity when:{days}d',
                '"hires advisor" sale process company UK when:{days}d',
            ],
            "Advisors / deal mandates": [
                'Lazard sale process company UK when:{days}d',
                'Rothschild sale process company UK when:{days}d',
                'PwC corporate finance sale company UK when:{days}d',
                'Deloitte corporate finance sale company UK when:{days}d',
            ],
            "Fundraising / PE funds": [
                "UK private equity raises fund when:{days}d",
                "UK private equity closes fund when:{days}d",
                "UK lower mid-market private equity fund when:{days}d",
            ],
        },
    },
    "Italy": {
        "hl": "it-IT",
        "gl": "IT",
        "ceid": "IT:it",
        "country_terms": ["Italia", "Italy"],
        "queries": {
            "General M&A / PE": [
                "Italia private equity acquisizione società when:{days}d",
                "Italia fondo acquisisce azienda when:{days}d",
                "Italia M&A private equity acquisizione when:{days}d",
                "site:bebeez.it acquisizione private equity when:{days}d",
            ],
            "Restaurants / Hospitality": [
                "Italia ristorazione acquisizione private equity when:{days}d",
                "Italia hospitality acquisizione fondo when:{days}d",
                "Italia ristoranti cerca investitore when:{days}d",
            ],
            "Food & Beverage / Consumer": [
                "Italia alimentare acquisizione private equity when:{days}d",
                "Italia food beverage acquisizione fondo when:{days}d",
                "Italia azienda alimentare processo vendita when:{days}d",
            ],
            "Investor wanted / sale signals": [
                '"cerca investitore" azienda Italia when:{days}d',
                '"cerca compratore" azienda Italia when:{days}d',
                '"processo di vendita" azienda Italia when:{days}d',
                '"mandato di vendita" azienda Italia when:{days}d',
            ],
            "Advisors / deal mandates": [
                'Rothschild mandato vendita azienda Italia when:{days}d',
                'Lazard mandato vendita azienda Italia when:{days}d',
                'KPMG corporate finance vendita azienda Italia when:{days}d',
                'Deloitte corporate finance vendita azienda Italia when:{days}d',
            ],
            "Fundraising / PE funds": [
                "Italia private equity nuovo fondo when:{days}d",
                "Italia fondo private equity fundraising when:{days}d",
                "Italia private equity raccolta fondo when:{days}d",
            ],
        },
    },
}

COMPOSITE_MARKETS = {
    "Spain": ["Spain"],
    "France": ["France"],
    "United States": ["United States"],
    "United Kingdom": ["United Kingdom"],
    "Italy": ["Italy"],
    "Spain + France": ["Spain", "France"],
    "US + UK": ["United States", "United Kingdom"],
    "Europe": ["Spain", "France", "United Kingdom", "Italy"],
    "All markets": ["Spain", "France", "United States", "United Kingdom", "Italy"],
}

SECTOR_SEARCH_TERMS = {
    "Restaurants / Hospitality": {
        "Spain": "restaurantes hostelería hoteles catering cafeterías",
        "France": "restauration hôtellerie hôtels cafés traiteur",
        "United States": "restaurants hospitality hotels catering coffee chains",
        "United Kingdom": "restaurants hospitality hotels catering coffee chains",
        "Italy": "ristorazione hospitality hotel catering caffetterie",
    },
    "Food & Beverage": {
        "Spain": "alimentación bebidas agroalimentario food beverage",
        "France": "agroalimentaire alimentation boissons food beverage",
        "United States": "food beverage food manufacturing consumer foods",
        "United Kingdom": "food beverage food manufacturing consumer foods",
        "Italy": "alimentare bevande agroalimentare food beverage",
    },
    "Consumer / Retail": {
        "Spain": "consumo retail comercio marcas moda ecommerce",
        "France": "consommation retail commerce marques mode ecommerce",
        "United States": "consumer retail brands fashion ecommerce",
        "United Kingdom": "consumer retail brands fashion ecommerce",
        "Italy": "consumer retail commercio marchi moda ecommerce",
    },
    "Healthcare": {
        "Spain": "salud sanitario clínicas dental farmacéutico veterinario diagnóstico",
        "France": "santé médical cliniques dentaire pharmaceutique vétérinaire diagnostic",
        "United States": "healthcare medical clinics dental pharmaceutical veterinary diagnostics",
        "United Kingdom": "healthcare medical clinics dental pharmaceutical veterinary diagnostics",
        "Italy": "sanità sanitario cliniche dentale farmaceutico veterinario diagnostica",
    },
    "Technology / Software": {
        "Spain": "tecnología software SaaS ciberseguridad fintech datos inteligencia artificial",
        "France": "technologie logiciel SaaS cybersécurité fintech données intelligence artificielle",
        "United States": "technology software SaaS cybersecurity fintech data artificial intelligence",
        "United Kingdom": "technology software SaaS cybersecurity fintech data artificial intelligence",
        "Italy": "tecnologia software SaaS cybersecurity fintech dati intelligenza artificiale",
    },
    "Industrial / Manufacturing": {
        "Spain": "industrial fabricación manufactura maquinaria automatización componentes packaging",
        "France": "industrie fabrication manufacturier machines automatisation composants emballage",
        "United States": "industrial manufacturing machinery automation components packaging",
        "United Kingdom": "industrial manufacturing machinery automation components packaging",
        "Italy": "industria manifattura macchinari automazione componenti packaging",
    },
    "Business Services": {
        "Spain": "servicios empresariales outsourcing mantenimiento facility staffing consultoría seguridad",
        "France": "services aux entreprises externalisation maintenance facility staffing conseil sécurité",
        "United States": "business services outsourcing facilities maintenance staffing consulting security",
        "United Kingdom": "business services outsourcing facilities maintenance staffing consulting security",
        "Italy": "servizi alle imprese outsourcing facility manutenzione staffing consulenza sicurezza",
    },
    "Energy / Infrastructure": {
        "Spain": "energía renovables solar eólica infraestructura utilities residuos agua medioambiente",
        "France": "énergie renouvelable solaire éolien infrastructure utilities déchets eau environnement",
        "United States": "energy renewables solar wind infrastructure utilities waste water environmental",
        "United Kingdom": "energy renewables solar wind infrastructure utilities waste water environmental",
        "Italy": "energia rinnovabili solare eolico infrastrutture utilities rifiuti acqua ambiente",
    },
    "Logistics / Transport": {
        "Spain": "logística transporte distribución almacenes supply chain freight movilidad",
        "France": "logistique transport distribution entrepôts supply chain fret mobilité",
        "United States": "logistics transport distribution warehousing supply chain freight mobility",
        "United Kingdom": "logistics transport distribution warehousing supply chain freight mobility",
        "Italy": "logistica trasporti distribuzione magazzini supply chain freight mobilità",
    },
    "Education / Training": {
        "Spain": "educación formación academias escuelas edtech aprendizaje",
        "France": "éducation formation écoles académies edtech apprentissage",
        "United States": "education training schools academies edtech learning",
        "United Kingdom": "education training schools academies edtech learning",
        "Italy": "educazione formazione scuole accademie edtech apprendimento",
    },
    "Construction / Real Estate": {
        "Spain": "construcción inmobiliario real estate materiales edificios property services",
        "France": "construction immobilier real estate matériaux bâtiments services immobiliers",
        "United States": "construction real estate building materials property services",
        "United Kingdom": "construction real estate building materials property services",
        "Italy": "costruzioni immobiliare real estate materiali edilizia property services",
    },
    "Financial Services": {
        "Spain": "servicios financieros seguros pagos crédito lending wealth management fintech",
        "France": "services financiers assurance paiements crédit gestion de patrimoine fintech",
        "United States": "financial services insurance payments lending wealth management fintech",
        "United Kingdom": "financial services insurance payments lending wealth management fintech",
        "Italy": "servizi finanziari assicurazioni pagamenti credito wealth management fintech",
    },
}

MARKET_RESEARCH_PHRASES = {
    "Spain": {
        "country": "España",
        "deal": [
            "adquisición private equity",
            "busca inversor OR proceso de venta",
            "inversión crecimiento expansión",
            "fusiones adquisiciones empresas",
            "tendencias mercado regulación innovación",
        ],
        "company": [
            "adquisición OR inversión OR venta",
            "expansión OR crecimiento OR resultados",
            "alianza OR contrato OR lanzamiento",
            "competidores OR tendencias OR regulación",
        ],
    },
    "France": {
        "country": "France",
        "deal": [
            "acquisition capital-investissement",
            "cherche investisseur OR processus de vente",
            "investissement croissance développement",
            "fusion acquisition entreprise",
            "tendances marché réglementation innovation",
        ],
        "company": [
            "acquisition OR investissement OR cession",
            "croissance OR développement OR résultats",
            "partenariat OR contrat OR lancement",
            "concurrents OR tendances OR réglementation",
        ],
    },
    "United States": {
        "country": "United States",
        "deal": [
            "private equity acquisition",
            "seeks investor OR sale process",
            "investment growth expansion",
            "M&A company acquisition",
            "market trends regulation innovation",
        ],
        "company": [
            "acquisition OR investment OR sale",
            "growth OR expansion OR results",
            "partnership OR contract OR launch",
            "competitors OR trends OR regulation",
        ],
    },
    "United Kingdom": {
        "country": "United Kingdom",
        "deal": [
            "private equity acquisition",
            "seeks investor OR sale process",
            "investment growth expansion",
            "M&A company acquisition",
            "market trends regulation innovation",
        ],
        "company": [
            "acquisition OR investment OR sale",
            "growth OR expansion OR results",
            "partnership OR contract OR launch",
            "competitors OR trends OR regulation",
        ],
    },
    "Italy": {
        "country": "Italia",
        "deal": [
            "acquisizione private equity",
            "cerca investitore OR processo di vendita",
            "investimento crescita espansione",
            "fusioni acquisizioni aziende",
            "tendenze mercato regolamentazione innovazione",
        ],
        "company": [
            "acquisizione OR investimento OR vendita",
            "crescita OR espansione OR risultati",
            "partnership OR contratto OR lancio",
            "concorrenti OR tendenze OR regolamentazione",
        ],
    },
}

SECTOR_NEWS_GROUPS = list(SECTOR_SEARCH_TERMS.keys())

NEWS_QUERY_GROUPS = [
    "General M&A / PE",
    "Company / Sector Conversation Material",
    *SECTOR_NEWS_GROUPS,
    "Investor wanted / sale signals",
    "Advisors / deal mandates",
    "Fundraising / PE funds",
]


def build_sector_search_queries(market, selected_group, days_back):
    sector_terms = SECTOR_SEARCH_TERMS[selected_group][market]
    market_profile = MARKET_RESEARCH_PHRASES[market]
    country = market_profile["country"]

    return [
        f"{country} {sector_terms} {phrase} when:{days_back}d"
        for phrase in market_profile["deal"]
    ]


def build_company_context_queries(market, research_context, days_back):
    research_context = research_context or {}
    name = str(research_context.get("name", "")).strip()
    sector = str(research_context.get("sector", "")).strip()
    subsector = str(research_context.get("subsector", "")).strip()
    description = str(research_context.get("description", "")).strip()
    geography = str(research_context.get("geography", "")).strip()

    market_profile = MARKET_RESEARCH_PHRASES[market]
    country = market_profile["country"]
    queries = []

    if name:
        queries.append(f'"{name}" when:{days_back}d')
        for phrase in market_profile["company"]:
            queries.append(f'"{name}" {phrase} when:{days_back}d')

    context_text = " ".join(part for part in [sector, subsector] if part).strip()
    description_terms = sorted(tokenize(description))[:6]
    if description_terms:
        context_text = " ".join([context_text, *description_terms]).strip()

    if context_text:
        queries.append(
            f"{country} {context_text} private equity acquisition investment when:{days_back}d"
        )
        queries.append(
            f"{country} {context_text} competitors market trends growth when:{days_back}d"
        )

    if geography and geography.lower() not in normalize_text(country):
        queries.append(
            f"{geography} {context_text or name} acquisition investment growth when:{days_back}d"
        )

    # Preserve order while removing duplicates and blanks.
    return list(dict.fromkeys(query for query in queries if query.strip()))


def strip_html(text):
    text = html.unescape(str(text or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def classify_news_signal(title, summary=""):
    text = normalize_text(f"{title} {summary}")

    matches = []
    for signal, keywords in NEWS_SIGNAL_KEYWORDS.items():
        for keyword in keywords:
            if contains_term(text, keyword):
                matches.append(signal)
                break

    if matches:
        return "; ".join(matches[:2])

    return "Other / review manually"


def classify_source_tier(source, title="", link=""):
    text = normalize_text(f"{source} {title} {link}")

    for tier, keywords in SOURCE_TIER_KEYWORDS.items():
        for keyword in keywords:
            if normalize_text(keyword) in text:
                return tier

    return "Other indexed source"


def source_priority_score(source_tier, signal_type):
    score = 0

    if source_tier == "Spain Tier 1":
        score += 50
    elif source_tier in {"Spain Tier 2", "France Priority", "US / UK Priority", "Italy Priority"}:
        score += 35
    else:
        score += 10

    if "Sale process" in signal_type or "Advisor" in signal_type:
        score += 35
    elif "Acquisition" in signal_type:
        score += 30
    elif "PE fund activity" in signal_type:
        score += 20
    elif "Company / sector intelligence" in signal_type or "Sector intelligence" in signal_type:
        score += 15
    elif "Strategic growth" in signal_type:
        score += 10

    return score


def priority_label(score):
    if score >= 80:
        return "High"
    if score >= 55:
        return "Medium"
    return "Review"


def clean_google_news_title(title):
    title = strip_html(title)
    if " - " in title:
        return title.rsplit(" - ", 1)[0].strip()
    return title


def parse_news_date(date_text):
    if not date_text:
        return ""
    try:
        return parsedate_to_datetime(date_text).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(date_text)


def build_review_summary(signal_type, source_tier):
    if "Sale process" in signal_type:
        return "Potential sale process or investor-seeking signal. Review the original article to confirm the target company, seller, advisor, process stage, and whether a buyer/investor is being actively sought."
    if "Advisor" in signal_type:
        return "Potential mandate/advisor signal. Review the article to confirm whether an M&A advisor has been hired and whether this indicates an upcoming sale, acquisition, refinancing, or fundraising process."
    if "Acquisition" in signal_type:
        return "Potential completed acquisition or investment. Review the article to confirm buyer, seller, target, transaction type, sector, geography, and any valuation or financial details."
    if "PE fund activity" in signal_type:
        return "Potential private equity fund activity. Review the article to identify the fund, strategy, fundraising status, sector focus, and possible future investment implications."
    if "Company / sector intelligence" in signal_type:
        return "Relevant company or sector development for conversation preparation. Review the original source and extract verified facts on strategy, growth, products, partnerships, competitors, regulation, and recent market developments."
    if "Sector intelligence" in signal_type:
        return "Relevant sector development that may indicate acquisition targets, investment themes, competitive activity, or useful conversation material. Review the original source and confirm the companies and facts involved."
    if "Strategic growth" in signal_type:
        return "Potential growth or expansion signal. Review the article to assess whether the company may need capital, consider M&A, or become relevant as a future opportunity."
    return "Review manually. The result was returned by the search but the app did not detect a clear M&A or PE signal from the title/snippet alone."


def build_review_action(signal_type):
    if "Sale process" in signal_type or "Advisor" in signal_type:
        return "Open source and consider adding as potential opportunity if confirmed."
    if "Acquisition" in signal_type:
        return "Open source and update market intelligence; add buyer/target if relevant."
    if "PE fund activity" in signal_type:
        return "Open source and update PE fund intelligence if relevant."
    if "Company / sector intelligence" in signal_type:
        return "Open source and use verified facts as company or sector conversation material."
    if "Sector intelligence" in signal_type:
        return "Open source and assess whether the company, theme, or transaction should enter the opportunity pipeline."
    return "Open source and review relevance manually."


def find_database_mentions(title, summary, opportunities, pe_funds, columns, us_pe_funds=None, us_columns=None):
    text = normalize_text(f"{title} {summary}")
    mentions = []

    opp_col = columns.get("opp_company")
    if opp_col and not opportunities.empty:
        for name in opportunities[opp_col].astype(str).dropna().unique():
            name_clean = str(name).strip()
            if len(name_clean) >= 4 and normalize_text(name_clean) in text:
                mentions.append(f"Opportunity: {name_clean}")

    fund_col = columns.get("fund_name")
    if fund_col and not pe_funds.empty:
        for name in pe_funds[fund_col].astype(str).dropna().unique():
            name_clean = str(name).strip()
            if len(name_clean) >= 4 and normalize_text(name_clean) in text:
                mentions.append(f"PE Fund: {name_clean}")

    us_fund_col = (us_columns or {}).get("fund_name")
    if us_pe_funds is not None and us_fund_col and not us_pe_funds.empty:
        for name in us_pe_funds[us_fund_col].astype(str).dropna().unique():
            name_clean = str(name).strip()
            if len(name_clean) >= 4 and normalize_text(name_clean) in text:
                mentions.append(f"U.S. PE Fund: {name_clean}")

    return "; ".join(dict.fromkeys(mentions)) if mentions else ""


def add_english_review_columns(
    news_df,
    opportunities,
    pe_funds,
    columns,
    us_pe_funds=None,
    us_columns=None,
):
    if news_df.empty:
        return news_df

    df = news_df.copy()
    df["Original Snippet"] = df["Summary"].apply(strip_html)
    df["Source Tier"] = df.apply(
        lambda row: classify_source_tier(row.get("Source", ""), row.get("Title", ""), row.get("Link", "")),
        axis=1,
    )
    df["Priority Score"] = df.apply(
        lambda row: source_priority_score(row.get("Source Tier", ""), row.get("Signal Type", "")),
        axis=1,
    )
    df["Priority"] = df["Priority Score"].apply(priority_label)
    df["English Summary"] = df.apply(
        lambda row: build_review_summary(row.get("Signal Type", ""), row.get("Source Tier", "")),
        axis=1,
    )
    df["Why It Matters"] = df["English Summary"]
    df["Review Action"] = df["Signal Type"].apply(build_review_action)
    df["Database Mentions"] = df.apply(
        lambda row: find_database_mentions(
            row.get("Title", ""),
            row.get("Original Snippet", ""),
            opportunities,
            pe_funds,
            columns,
            us_pe_funds=us_pe_funds,
            us_columns=us_columns,
        ),
        axis=1,
    )

    return df.sort_values(
        ["Priority Score", "Published"],
        ascending=[False, False],
    ).reset_index(drop=True)


NEWS_RESULT_COLUMNS = [
    "Market",
    "Search Query",
    "Signal Type",
    "Title",
    "Source",
    "Published",
    "Link",
    "Summary",
]


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_google_news(query, market, hl="es-ES", gl="ES", ceid="ES:es", max_results=20):
    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl={hl}&gl={gl}&ceid={ceid}"

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            xml_data = response.read()
    except Exception as exc:
        return pd.DataFrame([{
            "Market": market,
            "Search Query": query,
            "Signal Type": "Search error",
            "Title": f"Could not load news feed: {exc}",
            "Source": "",
            "Published": "",
            "Link": "",
            "Summary": "",
        }])

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as exc:
        return pd.DataFrame([{
            "Market": market,
            "Search Query": query,
            "Signal Type": "Parse error",
            "Title": f"Could not parse news feed: {exc}",
            "Source": "",
            "Published": "",
            "Link": "",
            "Summary": "",
        }])

    rows = []
    for item in root.findall(".//item")[:max_results]:
        raw_title = item.findtext("title", default="")
        title = clean_google_news_title(raw_title)
        link = item.findtext("link", default="")
        published = parse_news_date(item.findtext("pubDate", default=""))
        summary = strip_html(item.findtext("description", default=""))

        source = ""
        source_node = item.find("source")
        if source_node is not None and source_node.text:
            source = source_node.text.strip()
        elif " - " in raw_title:
            source = raw_title.rsplit(" - ", 1)[-1].strip()

        rows.append({
            "Market": market,
            "Search Query": query,
            "Signal Type": classify_news_signal(title, summary),
            "Title": title,
            "Source": source,
            "Published": published,
            "Link": link,
            "Summary": summary,
        })

    # Keep the expected columns even when Google News returns zero articles.
    # Without this, an empty DataFrame has no "Signal Type" column and the
    # research-group relabeling step raises a KeyError.
    return pd.DataFrame(rows, columns=NEWS_RESULT_COLUMNS)


def build_news_search_jobs(
    selected_market,
    selected_group,
    days_back,
    custom_query,
    source_focus,
    research_context=None,
):
    jobs = []
    markets = COMPOSITE_MARKETS[selected_market]
    research_context = research_context or {}
    research_target = str(research_context.get("name", "")).strip() or selected_group

    for market in markets:
        settings = MARKET_SETTINGS[market]

        if selected_group == "Company / Sector Conversation Material":
            base_queries = build_company_context_queries(
                market,
                research_context,
                days_back,
            )
        elif selected_group in SECTOR_SEARCH_TERMS:
            base_queries = build_sector_search_queries(
                market,
                selected_group,
                days_back,
            )
        else:
            preset_queries = settings["queries"].get(selected_group, [])
            base_queries = [
                query.format(days=days_back)
                for query in preset_queries
            ]

        if custom_query.strip():
            base_queries.insert(0, f"{custom_query.strip()} when:{days_back}d")

        base_queries = list(dict.fromkeys(query for query in base_queries if query.strip()))

        if source_focus == "Priority sources only":
            domains = PRIORITY_SOURCE_DOMAINS.get(market, [])
            source_filtered_queries = []
            # Limit combinations so broad multi-market searches remain usable.
            for domain in domains[:4]:
                for query in base_queries[:3]:
                    source_filtered_queries.append(f"{query} site:{domain}")
            base_queries = source_filtered_queries or base_queries

        elif source_focus == "Priority sources first":
            domains = PRIORITY_SOURCE_DOMAINS.get(market, [])
            priority_queries = []
            for domain in domains[:3]:
                for query in base_queries[:2]:
                    priority_queries.append(f"{query} site:{domain}")
            base_queries = priority_queries + base_queries

        for query in list(dict.fromkeys(base_queries)):
            jobs.append({
                "market": market,
                "query": query,
                "hl": settings["hl"],
                "gl": settings["gl"],
                "ceid": settings["ceid"],
                "research_group": selected_group,
                "research_target": research_target,
            })

    # Sequential RSS calls can become slow on very broad searches.
    return jobs[:80]


def search_news_jobs(jobs, max_results_per_query):
    frames = []

    for job in jobs:
        frame = fetch_google_news(
            job["query"],
            market=job["market"],
            hl=job["hl"],
            gl=job["gl"],
            ceid=job["ceid"],
            max_results=max_results_per_query,
        ).copy()

        # Defensive fallback for cached/legacy responses or unexpected feeds.
        for column in NEWS_RESULT_COLUMNS:
            if column not in frame.columns:
                frame[column] = ""

        frame["Research Group"] = job.get("research_group", "")
        frame["Research Target"] = job.get("research_target", "")

        if job.get("research_group") == "Company / Sector Conversation Material":
            frame.loc[
                frame["Signal Type"] == "Other / review manually",
                "Signal Type",
            ] = "Company / sector intelligence"
        elif job.get("research_group") in SECTOR_SEARCH_TERMS:
            frame.loc[
                frame["Signal Type"] == "Other / review manually",
                "Signal Type",
            ] = "Sector intelligence / opportunity signal"

        frames.append(frame)

    if not frames:
        return pd.DataFrame()

    results = pd.concat(frames, ignore_index=True)

    if "Link" in results.columns:
        results = results.drop_duplicates(subset=["Link"], keep="first")
    if "Title" in results.columns:
        results = results.drop_duplicates(subset=["Title"], keep="first")

    return results.reset_index(drop=True)

# -----------------------------
# Streamlit app
# -----------------------------

st.set_page_config(page_title="PE Matcher", layout="wide")

st.title("PE Intelligence Copilot")
st.write(
    "Version 3.5: Added a dedicated U.S. private equity database and matching section. Opportunities and PE funds "
    "can be read from Google Sheets and added directly from the website. Matching scores sector/subsector fit, "
    "EBITDA fit, and geography fit. Revenue and ticket size remain reference-only."
)
pe_funds, pe_funds_source, pe_funds_load_warning = load_pe_funds_database()
us_pe_funds, us_pe_funds_source, us_pe_funds_load_warning = load_us_pe_funds_database()
portfolio_companies = load_csv("portfolio_companies.csv")
opportunities, opportunities_source, opportunities_load_warning = load_opportunities_database()
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


def build_fund_column_map(funds_df, base_columns):
    """Reuse the opportunity/portfolio mapping while resolving fund fields for another worksheet."""
    mapped = dict(base_columns)
    mapped.update({
        "fund_name": find_column(funds_df, ["fund_name", "fund", "name", "pe_fund"]),
        "fund_sector": find_column(funds_df, ["primary_sectors", "sector_focus", "sector", "sectors", "preferred_sectors", "sector_focus_original"]),
        "fund_secondary_sector": find_column(funds_df, ["secondary_sectors", "secondary_sector", "other_sectors"]),
        "fund_business_model": find_column(funds_df, ["business_model_preference", "business_model", "model_preference"]),
        "fund_preferred_characteristics": find_column(funds_df, ["preferred_characteristics", "characteristics", "preferences", "investment_criteria"]),
        "fund_avoid": find_column(funds_df, ["avoid", "avoids", "negative_criteria", "not_interested"]),
        "fund_geography": find_column(funds_df, ["geography", "country", "region", "regions"]),
        "fund_transaction_type": find_column(funds_df, ["transaction_type", "deal_type", "investment_type"]),
        "fund_notes": find_column(funds_df, ["notes", "comments", "description"]),
        "fund_ebitda_min": find_column(funds_df, ["ebitda_min", "min_ebitda", "ebitda_minimum"]),
        "fund_ebitda_max": find_column(funds_df, ["ebitda_max", "max_ebitda", "ebitda_maximum"]),
        "fund_revenue_min": find_column(funds_df, ["revenue_min", "min_revenue", "sales_min", "turnover_min"]),
        "fund_revenue_max": find_column(funds_df, ["revenue_max", "max_revenue", "sales_max", "turnover_max"]),
        "fund_ticket_min": find_column(funds_df, ["ticket_min", "min_ticket", "equity_ticket_min", "investment_min"]),
        "fund_ticket_max": find_column(funds_df, ["ticket_max", "max_ticket", "equity_ticket_max", "investment_max"]),
    })
    return mapped


us_columns = build_fund_column_map(us_pe_funds, columns)

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
st.sidebar.write(f"U.S. PE Funds: {len(us_pe_funds)}")
st.sidebar.write(f"Portfolio Companies: {len(portfolio_companies)}")
st.sidebar.write(f"Opportunities: {len(opportunities)}")
st.sidebar.write(f"Opportunities source: {opportunities_source}")
st.sidebar.write(f"PE funds source: {pe_funds_source}")
st.sidebar.write(f"U.S. PE funds source: {us_pe_funds_source}")
if opportunities_load_warning:
    with st.sidebar.expander("Opportunities source warning"):
        st.write(opportunities_load_warning)
if pe_funds_load_warning:
    with st.sidebar.expander("PE funds source warning"):
        st.write(pe_funds_load_warning)
if us_pe_funds_load_warning:
    with st.sidebar.expander("U.S. PE funds source warning"):
        st.write(us_pe_funds_load_warning)

tab1, tab2, tab_us, tab3, tab4, tab5 = st.tabs([
    "Opportunity → PE Funds",
    "PE Fund → Opportunities",
    "U.S. PE Section",
    "News Search",
    "Add Opportunity",
    "Add PE Fund"
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
                "Revenue Reference": match["revenue_reference"],
                "Ticket Reference": match["ticket_reference"],
                "Sector Fit": match["sector_fit"],
                "Geography Fit": match["geography_fit"],
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
# Dedicated U.S. PE section
# -----------------------------

with tab_us:
    st.header("U.S. Private Equity")
    st.write(
        "Match an opportunity only against the dedicated U.S. private equity universe. "
        "The worksheet combines major global platforms with middle- and lower-middle-market firms. "
        "Blank financial ranges mean the firm does not publish one standardized threshold."
    )

    if us_pe_funds.empty or us_columns.get("fund_name") is None or us_columns.get("fund_sector") is None:
        st.warning("The U.S. PE database is empty or its required columns were not found.")
    else:
        us_view, us_match, us_add = st.tabs([
            "Browse U.S. PE Funds",
            "Opportunity → U.S. PE Funds",
            "Add U.S. PE Fund",
        ])

        with us_view:
            tier_filter = st.selectbox(
                "Fund tier",
                ["All", "Mega / large-cap", "Middle market", "Lower middle market"],
                key="us_tier_filter",
            )
            displayed_us_funds = us_pe_funds.copy()
            notes_col = us_columns.get("fund_notes")
            if tier_filter != "All" and notes_col:
                tier_terms = {
                    "Mega / large-cap": "mega|large-cap|large cap",
                    "Middle market": "middle market|upper middle|large middle",
                    "Lower middle market": "lower middle|lower / core",
                }
                displayed_us_funds = displayed_us_funds[
                    displayed_us_funds[notes_col].astype(str).str.contains(
                        tier_terms[tier_filter], case=False, regex=True, na=False
                    )
                ]
            st.dataframe(displayed_us_funds, use_container_width=True, hide_index=True)
            st.download_button(
                "Download U.S. PE database as CSV",
                data=displayed_us_funds.to_csv(index=False).encode("utf-8-sig"),
                file_name="us_pe_funds_database.csv",
                mime="text/csv",
            )

        with us_match:
            us_opportunity_names = opportunities[columns["opp_company"]].astype(str).tolist()
            selected_us_opportunity_name = st.selectbox(
                "Select an opportunity for the U.S. market",
                us_opportunity_names,
                key="us_opportunity_selector",
            )
            selected_us_opportunity = opportunities[
                opportunities[columns["opp_company"]].astype(str) == selected_us_opportunity_name
            ].iloc[0]

            st.caption(
                "Financial values are interpreted as USD millions in this section. "
                "Use U.S. opportunities or convert the financial fields before relying on the score."
            )

            if st.button("Find Best U.S. PE Matches", key="find_us_pe_matches"):
                us_results = []
                for _, fund in us_pe_funds.iterrows():
                    match = score_match(
                        selected_us_opportunity,
                        fund,
                        portfolio_companies,
                        website_enrichment,
                        us_columns,
                        enrichment_columns,
                        currency_symbol="$",
                    )
                    us_results.append({
                        "U.S. PE Fund": safe_get(fund, us_columns["fund_name"]),
                        "Recommendation": match["recommendation"],
                        "Match Score": match["score"],
                        "Fit Score": match["fit_score"],
                        "Data Completeness": match["data_completeness"],
                        "EBITDA Fit": match["ebitda_fit"],
                        "Sector Fit": match["sector_fit"],
                        "Geography Fit": match["geography_fit"],
                        "Revenue Reference": match["revenue_reference"],
                        "Ticket Reference": match["ticket_reference"],
                        "Primary Sectors": safe_get(fund, us_columns["fund_sector"]),
                        "Transaction Type": safe_get(fund, us_columns["fund_transaction_type"]),
                        "Notes": safe_get(fund, us_columns["fund_notes"]),
                    })

                us_results_df = pd.DataFrame(us_results).sort_values(
                    ["Match Score", "Data Completeness", "Fit Score"], ascending=False
                ).head(30)
                st.subheader("Top U.S. PE Matches")
                st.dataframe(us_results_df, use_container_width=True, hide_index=True)
                st.download_button(
                    "Download U.S. match results as CSV",
                    data=us_results_df.to_csv(index=False).encode("utf-8-sig"),
                    file_name="us_pe_match_results.csv",
                    mime="text/csv",
                )


        with us_add:
            st.subheader("Add a New U.S. PE Fund")
            st.write(
                "Add a fund directly to the live `us_pe_funds` Google Sheet. "
                "EBITDA is used in matching; revenue and ticket/enterprise value remain reference-only."
            )

            if us_pe_funds_source != "Google Sheets":
                st.warning(
                    "The app is not currently reading U.S. PE funds from Google Sheets. "
                    "Check the Google Sheet connection before submitting this form."
                )

            with st.form("add_us_pe_fund_form", clear_on_submit=True):
                st.markdown("**Required information**")
                us_f1, us_f2, us_f3 = st.columns(3)

                with us_f1:
                    us_new_fund_name = st.text_input("U.S. Fund Name *", key="us_new_fund_name")
                    us_new_website = st.text_input("Website", key="us_new_website")
                    us_new_geography = st.text_input(
                        "Geography",
                        value="United States; North America",
                        key="us_new_geography",
                    )

                with us_f2:
                    us_new_primary_sectors = st.text_area(
                        "Primary Sectors *",
                        height=90,
                        key="us_new_primary_sectors",
                    )
                    us_new_secondary_sectors = st.text_area(
                        "Secondary Sectors",
                        height=90,
                        key="us_new_secondary_sectors",
                    )

                with us_f3:
                    us_new_ebitda_min = st.text_input(
                        "EBITDA Min ($m)",
                        placeholder="Example: 5",
                        key="us_new_ebitda_min",
                    )
                    us_new_ebitda_max = st.text_input(
                        "EBITDA Max ($m)",
                        placeholder="Example: 25",
                        key="us_new_ebitda_max",
                    )
                    us_new_transaction_type = st.text_input(
                        "Transaction Type",
                        key="us_new_transaction_type",
                    )

                st.markdown("**Reference ranges**")
                us_r1, us_r2 = st.columns(2)
                with us_r1:
                    us_new_revenue_min = st.text_input("Revenue Min ($m)", key="us_new_revenue_min")
                    us_new_revenue_max = st.text_input("Revenue Max ($m)", key="us_new_revenue_max")
                with us_r2:
                    us_new_ticket_min = st.text_input(
                        "Ticket / EV Min ($m)",
                        key="us_new_ticket_min",
                    )
                    us_new_ticket_max = st.text_input(
                        "Ticket / EV Max ($m)",
                        key="us_new_ticket_max",
                    )

                st.markdown("**Investment profile and research notes**")
                us_a1, us_a2 = st.columns(2)
                with us_a1:
                    us_new_business_model = st.text_input(
                        "Business Model Preference",
                        key="us_new_business_model",
                    )
                    us_new_preferred = st.text_area(
                        "Preferred Characteristics",
                        height=100,
                        key="us_new_preferred",
                    )
                    us_new_avoid = st.text_area(
                        "Avoid / Negative Criteria",
                        height=90,
                        key="us_new_avoid",
                    )
                with us_a2:
                    us_new_notes = st.text_area("Notes", height=100, key="us_new_notes")
                    us_new_source_status = st.text_input(
                        "Source Status",
                        value="Added through app / needs review",
                        key="us_new_source_status",
                    )
                    us_new_source_file = st.text_input(
                        "Source URL or File",
                        key="us_new_source_file",
                    )
                    us_new_last_update = st.text_input(
                        "Last Update",
                        placeholder="YYYY-MM-DD",
                        key="us_new_last_update",
                    )

                submitted_us_pe = st.form_submit_button("Add U.S. PE fund to database")

            if submitted_us_pe:
                us_errors = []

                if not us_new_fund_name.strip():
                    us_errors.append("U.S. Fund Name is required.")
                if not us_new_primary_sectors.strip():
                    us_errors.append("Primary Sectors are required.")

                us_numeric_fields = {
                    "EBITDA Min": us_new_ebitda_min,
                    "EBITDA Max": us_new_ebitda_max,
                    "Revenue Min": us_new_revenue_min,
                    "Revenue Max": us_new_revenue_max,
                    "Ticket / EV Min": us_new_ticket_min,
                    "Ticket / EV Max": us_new_ticket_max,
                }
                for label, value in us_numeric_fields.items():
                    if value.strip() and parse_number(value) is None:
                        us_errors.append(f"{label} must be a number, for example 5 or 5.5.")

                us_range_pairs = [
                    ("EBITDA", us_new_ebitda_min, us_new_ebitda_max),
                    ("Revenue", us_new_revenue_min, us_new_revenue_max),
                    ("Ticket / EV", us_new_ticket_min, us_new_ticket_max),
                ]
                for label, min_text, max_text in us_range_pairs:
                    min_value = parse_number(min_text)
                    max_value = parse_number(max_text)
                    if min_value is not None and max_value is not None and min_value > max_value:
                        us_errors.append(f"{label} minimum cannot be greater than its maximum.")

                us_name_col = us_columns.get("fund_name")
                if us_name_col and not us_pe_funds.empty:
                    existing_names = {
                        normalize_text(name)
                        for name in us_pe_funds[us_name_col].astype(str).tolist()
                        if str(name).strip()
                    }
                    if normalize_text(us_new_fund_name) in existing_names:
                        us_errors.append("A U.S. PE fund with this name already exists.")

                if us_errors:
                    for error in us_errors:
                        st.error(error)
                else:
                    us_new_row = {
                        "fund_name": us_new_fund_name.strip(),
                        "website": us_new_website.strip(),
                        "ebitda_min": us_new_ebitda_min.strip(),
                        "ebitda_max": us_new_ebitda_max.strip(),
                        "ticket_min": us_new_ticket_min.strip(),
                        "ticket_max": us_new_ticket_max.strip(),
                        "revenue_min": us_new_revenue_min.strip(),
                        "revenue_max": us_new_revenue_max.strip(),
                        "primary_sectors": us_new_primary_sectors.strip(),
                        "secondary_sectors": us_new_secondary_sectors.strip(),
                        "business_model_preference": us_new_business_model.strip(),
                        "preferred_characteristics": us_new_preferred.strip(),
                        "avoid": us_new_avoid.strip(),
                        "geography": us_new_geography.strip(),
                        "transaction_type": us_new_transaction_type.strip(),
                        "notes": us_new_notes.strip(),
                        "last_update": us_new_last_update.strip(),
                        "source_status": us_new_source_status.strip(),
                        "source_file": us_new_source_file.strip(),
                        "sector_focus_original": us_new_primary_sectors.strip(),
                    }

                    try:
                        append_us_pe_fund_to_google_sheet(us_new_row)
                        st.success(
                            f"{us_new_fund_name.strip()} was added to the live U.S. PE database."
                        )
                        st.info(
                            "Refresh the app to see the new fund in U.S. browsing, matching, and News Search."
                        )
                    except Exception as exc:
                        st.error("The U.S. PE fund could not be added to Google Sheets.")
                        st.write(str(exc))

            with st.expander("Current U.S. PE fund columns"):
                st.write(list(us_pe_funds.columns))


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
        st.write("Revenue reference:", format_range(get_number(selected_fund, columns["fund_revenue_min"]), get_number(selected_fund, columns["fund_revenue_max"])))
        st.write("Ticket reference:", format_range(get_number(selected_fund, columns["fund_ticket_min"]), get_number(selected_fund, columns["fund_ticket_max"])))

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
                "Revenue Reference": match["revenue_reference"],
                "Ticket Reference": match["ticket_reference"],
                "Sector Fit": match["sector_fit"],
                "Geography Fit": match["geography_fit"],
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


# -----------------------------
# Tab 4: Add opportunity to Google Sheets
# -----------------------------

with tab4:
    st.header("Add a New Opportunity")
    st.write(
        "Use this form to add a new opportunity directly to the live Google Sheets database. "
        "Revenue and ticket/enterprise value are saved as reference information only."
    )

    if opportunities_source != "Google Sheets":
        st.warning(
            "The app is not currently reading opportunities from Google Sheets. "
            "Check Streamlit Secrets and the Google Sheet sharing settings before using this form."
        )

    with st.form("add_opportunity_form", clear_on_submit=True):
        st.subheader("Required fields")

        f1, f2, f3 = st.columns(3)

        with f1:
            new_company = st.text_input("Company *")
            new_sector = st.text_input("Sector *")
            new_subsector = st.text_input("Subsector")

        with f2:
            new_ebitda = st.text_input("EBITDA (€m) *", placeholder="Example: 5.5")
            new_revenue = st.text_input("Revenue (€m)", placeholder="Example: 25")
            new_enterprise_value = st.text_input("Enterprise Value / Ticket (€m)", placeholder="Optional")

        with f3:
            new_geography = st.text_input("Geography", value="Spain")
            new_deal_type = st.text_input("Deal Type")
            new_stage = st.text_input("Stage")

        st.subheader("Additional information")

        a1, a2 = st.columns(2)

        with a1:
            new_owner = st.text_input("Owner")
            new_advisor = st.text_input("Advisor")
            new_timing = st.text_input("Timing")
            new_source = st.text_input("Source")

        with a2:
            new_business_model = st.text_input("Business Model")
            new_characteristics = st.text_input("Characteristics / Keywords")
            new_margin = st.text_input("Margin (%)")
            new_last_update = st.text_input("Last Update")

        new_description = st.text_area("Description", height=120)
        new_comment = st.text_area("Comment", height=80)

        submitted = st.form_submit_button("Add opportunity to database")

    if submitted:
        errors = []

        if not new_company.strip():
            errors.append("Company is required.")
        if not new_sector.strip():
            errors.append("Sector is required.")
        if not new_ebitda.strip():
            errors.append("EBITDA is required.")
        elif parse_number(new_ebitda) is None:
            errors.append("EBITDA must be a number, for example 5 or 5.5.")

        if errors:
            for error in errors:
                st.error(error)
        else:
            new_row = {
                "company": new_company.strip(),
                "sector": new_sector.strip(),
                "subsector": new_subsector.strip(),
                "revenue": new_revenue.strip(),
                "ebitda": new_ebitda.strip(),
                "margin": new_margin.strip(),
                "enterprise_value": new_enterprise_value.strip(),
                "description": new_description.strip(),
                "business_model": new_business_model.strip(),
                "characteristics": new_characteristics.strip(),
                "owner": new_owner.strip(),
                "advisor": new_advisor.strip(),
                "stage": new_stage.strip(),
                "timing": new_timing.strip(),
                "comment": new_comment.strip(),
                "last_update": new_last_update.strip(),
                "source": new_source.strip(),
                "deal_type": new_deal_type.strip(),
                "geography": new_geography.strip(),
            }

            try:
                append_opportunity_to_google_sheet(new_row)
                st.success(
                    f"{new_company.strip()} was added to the Google Sheets opportunities database."
                )
                st.info(
                    "Refresh the app or switch tabs and rerun to see the new opportunity in the match selectors."
                )
            except Exception as exc:
                st.error("The opportunity could not be added to Google Sheets.")
                st.write(str(exc))

    with st.expander("Current opportunity columns"):
        st.write(list(opportunities.columns))




# -----------------------------
# Tab 5: Add PE fund to Google Sheets
# -----------------------------

with tab5:
    st.header("Add a New PE Fund")
    st.write(
        "Use this form to add a new PE fund directly to the live Google Sheets database. "
        "Revenue and ticket ranges are saved as reference information only."
    )

    if pe_funds_source != "Google Sheets":
        st.warning(
            "The app is not currently reading PE funds from Google Sheets. "
            "Check Streamlit Secrets and the pe_funds worksheet before using this form."
        )

    with st.form("add_pe_fund_form", clear_on_submit=True):
        st.subheader("Required fields")

        p1, p2, p3 = st.columns(3)

        with p1:
            new_fund_name = st.text_input("Fund Name *")
            new_website = st.text_input("Website")
            new_geography = st.text_input("Geography", value="Spain")

        with p2:
            new_primary_sectors = st.text_area("Primary Sectors *", height=90)
            new_secondary_sectors = st.text_area("Secondary Sectors", height=90)

        with p3:
            new_ebitda_min = st.text_input("EBITDA Min (€m)", placeholder="Example: 3")
            new_ebitda_max = st.text_input("EBITDA Max (€m)", placeholder="Example: 15")
            new_transaction_type = st.text_input("Transaction Type")

        st.subheader("Reference ranges")

        r1, r2 = st.columns(2)

        with r1:
            new_revenue_min = st.text_input("Revenue Min (€m)")
            new_revenue_max = st.text_input("Revenue Max (€m)")

        with r2:
            new_ticket_min = st.text_input("Ticket Min (€m)")
            new_ticket_max = st.text_input("Ticket Max (€m)")

        st.subheader("Additional information")

        b1, b2 = st.columns(2)

        with b1:
            new_business_model_preference = st.text_input("Business Model Preference")
            new_preferred_characteristics = st.text_area("Preferred Characteristics", height=100)

        with b2:
            new_avoid = st.text_area("Avoid / Negative Criteria", height=100)
            new_notes = st.text_area("Notes", height=100)

        submitted_pe = st.form_submit_button("Add PE fund to database")

    if submitted_pe:
        errors = []

        if not new_fund_name.strip():
            errors.append("Fund Name is required.")
        if not new_primary_sectors.strip():
            errors.append("Primary Sectors is required.")

        numeric_fields = {
            "EBITDA Min": new_ebitda_min,
            "EBITDA Max": new_ebitda_max,
            "Revenue Min": new_revenue_min,
            "Revenue Max": new_revenue_max,
            "Ticket Min": new_ticket_min,
            "Ticket Max": new_ticket_max,
        }

        for label, value in numeric_fields.items():
            if value.strip() and parse_number(value) is None:
                errors.append(f"{label} must be a number, for example 5 or 5.5.")

        if errors:
            for error in errors:
                st.error(error)
        else:
            new_pe_row = {
                "fund_name": new_fund_name.strip(),
                "website": new_website.strip(),
                "ebitda_min": new_ebitda_min.strip(),
                "ebitda_max": new_ebitda_max.strip(),
                "ticket_min": new_ticket_min.strip(),
                "ticket_max": new_ticket_max.strip(),
                "revenue_min": new_revenue_min.strip(),
                "revenue_max": new_revenue_max.strip(),
                "primary_sectors": new_primary_sectors.strip(),
                "secondary_sectors": new_secondary_sectors.strip(),
                "business_model_preference": new_business_model_preference.strip(),
                "preferred_characteristics": new_preferred_characteristics.strip(),
                "avoid": new_avoid.strip(),
                "geography": new_geography.strip(),
                "transaction_type": new_transaction_type.strip(),
                "notes": new_notes.strip(),
            }

            try:
                append_pe_fund_to_google_sheet(new_pe_row)
                st.success(f"{new_fund_name.strip()} was added to the Google Sheets PE funds database.")
                st.info("Refresh the app or switch tabs and rerun to see the new PE fund in the match selectors.")
            except Exception as exc:
                st.error("The PE fund could not be added to Google Sheets.")
                st.write(str(exc))

    with st.expander("Current PE fund columns"):
        st.write(list(pe_funds.columns))


# -----------------------------
# Tab 3: News search and deal signals
# -----------------------------

with tab3:
    st.header("News Search & Deal Signals")
    st.write(
        "Search recent news across all major PE sectors, including healthcare, technology, industrials, business services, "
        "energy, logistics, education, real estate, financial services, consumer, food, and hospitality. You can also select "
        "a company or PE fund from the database to create highly relevant conversation material. Searches run in the local "
        "market language for precision, while review fields and CSV exports remain in English."
    )

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        selected_market = st.selectbox(
            "Market",
            list(COMPOSITE_MARKETS.keys()),
            index=0,
        )

    with col2:
        selected_group = st.selectbox(
            "Research group",
            NEWS_QUERY_GROUPS,
            index=0,
            help="Choose a deal signal, a complete PE sector, or company-specific conversation research.",
        )

    with col3:
        days_back = st.selectbox(
            "Time window",
            [1, 7, 14, 30, 90],
            index=3,
            format_func=lambda x: f"Last {x} day" if x == 1 else f"Last {x} days",
        )

    with col4:
        max_results_per_query = st.selectbox(
            "Results per query",
            [5, 10, 20, 30],
            index=1,
        )

    research_context = {}

    if selected_group == "Company / Sector Conversation Material":
        st.subheader("Conversation research target")
        context_source = st.radio(
            "Select the target from",
            [
                "Opportunity database",
                "PE fund database",
                "U.S. PE fund database",
                "Manual company",
            ],
            horizontal=True,
        )

        if context_source == "Opportunity database":
            context_names = opportunities[columns["opp_company"]].astype(str).tolist()
            selected_context_name = st.selectbox(
                "Company / opportunity",
                context_names,
                key="news_context_opportunity",
            )
            context_row = opportunities[
                opportunities[columns["opp_company"]].astype(str) == selected_context_name
            ].iloc[0]
            research_context = {
                "name": safe_get(context_row, columns["opp_company"]),
                "sector": safe_get(context_row, columns["opp_sector"]),
                "subsector": safe_get(context_row, columns["opp_subsector"]),
                "description": safe_get(context_row, columns["opp_description"]),
                "geography": safe_get(context_row, columns["opp_country"]),
            }

        elif context_source == "PE fund database":
            context_names = pe_funds[columns["fund_name"]].astype(str).tolist()
            selected_context_name = st.selectbox(
                "PE fund",
                context_names,
                key="news_context_fund",
            )
            context_row = pe_funds[
                pe_funds[columns["fund_name"]].astype(str) == selected_context_name
            ].iloc[0]
            research_context = {
                "name": safe_get(context_row, columns["fund_name"]),
                "sector": safe_get(context_row, columns["fund_sector"]),
                "subsector": safe_get(context_row, columns["fund_secondary_sector"]),
                "description": " ".join([
                    safe_get(context_row, columns["fund_preferred_characteristics"]),
                    safe_get(context_row, columns["fund_notes"]),
                ]),
                "geography": safe_get(context_row, columns["fund_geography"]),
            }

        elif context_source == "U.S. PE fund database":
            if us_pe_funds.empty or us_columns.get("fund_name") is None:
                st.warning("The U.S. PE fund database is empty or unavailable.")
            else:
                us_context_names = sorted(
                    us_pe_funds[us_columns["fund_name"]].astype(str).tolist()
                )
                selected_us_context_name = st.selectbox(
                    "U.S. PE fund",
                    us_context_names,
                    key="news_context_us_fund",
                )
                us_context_row = us_pe_funds[
                    us_pe_funds[us_columns["fund_name"]].astype(str)
                    == selected_us_context_name
                ].iloc[0]
                research_context = {
                    "name": safe_get(us_context_row, us_columns["fund_name"]),
                    "sector": safe_get(us_context_row, us_columns["fund_sector"]),
                    "subsector": safe_get(us_context_row, us_columns["fund_secondary_sector"]),
                    "description": " ".join([
                        safe_get(us_context_row, us_columns["fund_business_model"]),
                        safe_get(us_context_row, us_columns["fund_preferred_characteristics"]),
                        safe_get(us_context_row, us_columns["fund_notes"]),
                    ]),
                    "geography": safe_get(us_context_row, us_columns["fund_geography"])
                    or "United States",
                }

        else:
            manual1, manual2, manual3 = st.columns(3)
            with manual1:
                manual_company = st.text_input("Company name")
            with manual2:
                manual_sector = st.text_input("Sector")
            with manual3:
                manual_subsector = st.text_input("Subsector")
            manual_description = st.text_area(
                "Company description or keywords",
                placeholder="Products, customers, business model, competitors, geography, and any topic your boss wants to discuss.",
            )
            research_context = {
                "name": manual_company,
                "sector": manual_sector,
                "subsector": manual_subsector,
                "description": manual_description,
                "geography": selected_market,
            }

        if any(str(value).strip() for value in research_context.values()):
            st.info(
                "Research context: "
                + " | ".join(
                    str(value).strip()
                    for value in [
                        research_context.get("name", ""),
                        research_context.get("sector", ""),
                        research_context.get("subsector", ""),
                        research_context.get("geography", ""),
                    ]
                    if str(value).strip()
                )
            )

    source_focus = st.radio(
        "Source focus",
        ["Priority sources first", "Priority sources only", "All indexed sources"],
        index=0,
        horizontal=True,
        help="Priority sources include El Economista / Capital Riesgo, Expansión, El Confidencial, CFNEWS, Les Echos, Fusacq, Reuters, Bloomberg, FT, PE Hub, PitchBook, BeBeez, Il Sole 24 Ore, and similar sources.",
    )

    custom_query = st.text_input(
        "Optional custom search",
        placeholder='Examples: energy services acquisition, dental clinics investor, industrial automation sale process, or an exact company/topic.',
    )

    jobs = build_news_search_jobs(
        selected_market=selected_market,
        selected_group=selected_group,
        days_back=days_back,
        custom_query=custom_query,
        source_focus=source_focus,
        research_context=research_context,
    )

    if selected_group == "Company / Sector Conversation Material" and not jobs:
        st.warning("Enter or select a company, sector, or description to create conversation-material searches.")

    with st.expander("Queries that will be searched"):
        preview_df = pd.DataFrame(jobs)
        st.dataframe(
            preview_df[["market", "query"]].head(60),
            use_container_width=True,
            hide_index=True,
        )
        if len(preview_df) > 60:
            st.caption(f"Showing first 60 of {len(preview_df)} queries.")

    if st.button("Search News", key="search_news"):
        with st.spinner("Searching recent news..."):
            raw_news_df = search_news_jobs(
                jobs,
                max_results_per_query=max_results_per_query,
            )

        if raw_news_df.empty:
            st.warning("No news results found. Try a broader query, longer time window, or all indexed sources.")
        else:
            news_df = add_english_review_columns(
                raw_news_df,
                opportunities=opportunities,
                pe_funds=pe_funds,
                columns=columns,
                us_pe_funds=us_pe_funds,
                us_columns=us_columns,
            )

            market_options = sorted(news_df["Market"].dropna().unique().tolist())
            signal_options = sorted(news_df["Signal Type"].dropna().unique().tolist())
            tier_options = sorted(news_df["Source Tier"].dropna().unique().tolist())
            priority_options = ["High", "Medium", "Review"]

            f1, f2, f3 = st.columns(3)

            with f1:
                selected_priorities = st.multiselect(
                    "Filter by priority",
                    priority_options,
                    default=priority_options,
                )

            with f2:
                selected_signals = st.multiselect(
                    "Filter by signal type",
                    signal_options,
                    default=signal_options,
                )

            with f3:
                selected_tiers = st.multiselect(
                    "Filter by source tier",
                    tier_options,
                    default=tier_options,
                )

            selected_markets = st.multiselect(
                "Filter by market",
                market_options,
                default=market_options,
            )

            filtered_news = news_df[
                news_df["Priority"].isin(selected_priorities)
                & news_df["Signal Type"].isin(selected_signals)
                & news_df["Source Tier"].isin(selected_tiers)
                & news_df["Market"].isin(selected_markets)
            ].copy()

            st.subheader(f"News Results ({len(filtered_news)})")

            summary_counts = (
                filtered_news.groupby(["Priority", "Signal Type"])
                .size()
                .reset_index(name="Count")
                .sort_values(["Priority", "Count"], ascending=[True, False])
            )

            with st.expander("Signal summary"):
                st.dataframe(summary_counts, use_container_width=True, hide_index=True)

            display_columns = [
                "Priority",
                "Market",
                "Research Group",
                "Research Target",
                "Signal Type",
                "Source Tier",
                "Title",
                "Source",
                "Published",
                "English Summary",
                "Database Mentions",
                "Link",
            ]

            st.dataframe(
                filtered_news[display_columns],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Link": st.column_config.LinkColumn("Link"),
                },
            )

            export_columns = [
                "Priority",
                "Priority Score",
                "Market",
                "Research Group",
                "Research Target",
                "Signal Type",
                "Source Tier",
                "Source",
                "Published",
                "Title",
                "Original Snippet",
                "English Summary",
                "Why It Matters",
                "Review Action",
                "Database Mentions",
                "Search Query",
                "Link",
            ]

            st.download_button(
                "Download English review CSV",
                data=filtered_news[export_columns].to_csv(index=False).encode("utf-8-sig"),
                file_name="news_deal_signals_english.csv",
                mime="text/csv",
            )

            st.subheader("Review links")
            for _, row in filtered_news.head(30).iterrows():
                st.markdown(f"**{row['Priority']} | {row['Signal Type']}** — [{row['Title']}]({row['Link']})")
                st.caption(f"{row['Market']} | {row['Source Tier']} | {row['Source']} | {row['Published']} | Query: {row['Search Query']}")
                st.write(row["English Summary"])
                if row.get("Database Mentions"):
                    st.write("Database mentions:", row["Database Mentions"])

