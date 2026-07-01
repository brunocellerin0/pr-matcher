import re
from pathlib import Path
from datetime import datetime

import pandas as pd
import requests
from bs4 import BeautifulSoup


DATA_DIR = Path(__file__).parent / "data"
OUTPUT_FILE = DATA_DIR / "website_enrichment.csv"


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


def find_column(df, possible_names):
    for name in possible_names:
        clean_name = clean_column_name(name)
        if clean_name in df.columns:
            return clean_name
    return None


def normalize_url(url):
    url = str(url).strip()

    if not url or url.lower() in ["nan", "none", "n/a"]:
        return ""

    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    return url


def extract_website_text(url):
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=12
        )

        if response.status_code != 200:
            return ""

        soup = BeautifulSoup(response.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        text = soup.get_text(" ")
        text = re.sub(r"\s+", " ", text).strip()

        return text[:5000]

    except Exception:
        return ""


def extract_keywords(text, max_keywords=25):
    text = str(text).lower()
    words = re.findall(r"[a-zA-Z]{4,}", text)

    stopwords = {
        "about", "also", "from", "that", "this", "with", "have", "their",
        "more", "into", "your", "they", "will", "shall", "been", "were",
        "company", "companies", "business", "service", "services", "group",
        "contact", "privacy", "policy", "cookie", "cookies", "website",
        "home", "read", "learn", "solutions", "page", "data"
    }

    counts = {}

    for word in words:
        if word not in stopwords:
            counts[word] = counts.get(word, 0) + 1

    sorted_words = sorted(counts.items(), key=lambda x: x[1], reverse=True)

    return ", ".join([word for word, count in sorted_words[:max_keywords]])


def collect_links_from_file(file_name, source_type, name_columns, url_columns):
    df = load_csv(file_name)

    name_col = find_column(df, name_columns)
    url_col = find_column(df, url_columns)

    if not name_col or not url_col:
        print(f"Skipping {file_name}: no name/url columns found.")
        return []

    rows = []

    for _, row in df.iterrows():
        name = row.get(name_col, "")
        url = normalize_url(row.get(url_col, ""))

        if not name or not url:
            continue

        rows.append({
            "source_type": source_type,
            "name": name,
            "url": url
        })

    return rows


def main():
    all_links = []

    all_links += collect_links_from_file(
        "pe_funds.csv",
        "PE Fund",
        ["fund_name", "fund", "name", "pe_fund"],
        ["website", "url", "link"]
    )

    all_links += collect_links_from_file(
        "portfolio_companies.csv",
        "Portfolio Company",
        ["company", "portfolio_company", "name"],
        ["website", "url", "link"]
    )

    all_links += collect_links_from_file(
        "opportunities.csv",
        "Opportunity",
        ["company", "opportunity", "name"],
        ["website", "url", "link", "source"]
    )

    seen = set()
    unique_links = []

    for item in all_links:
        key = (item["source_type"], str(item["name"]).lower(), item["url"].lower())

        if key not in seen:
            seen.add(key)
            unique_links.append(item)

    print(f"Found {len(unique_links)} links to enrich.")

    results = []

    for i, item in enumerate(unique_links, start=1):
        print(f"[{i}/{len(unique_links)}] Reading {item['name']} - {item['url']}")

        website_text = extract_website_text(item["url"])
        keywords = extract_keywords(website_text)

        results.append({
            "source_type": item["source_type"],
            "name": item["name"],
            "url": item["url"],
            "keywords": keywords,
            "text_preview": website_text[:1000],
            "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

    output_df = pd.DataFrame(results)
    output_df.to_csv(OUTPUT_FILE, index=False)

    print(f"Done. Saved enrichment file to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()