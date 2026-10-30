#!/usr/bin/env python3
"""Collect and screen public climate-tech startup and funding RSS signals."""
from __future__ import annotations
import argparse, csv, datetime as dt, email.utils, html, json, logging, os, re, sqlite3
from pathlib import Path
from typing import Any
import requests

ROOT = Path(__file__).resolve().parent
DATA, DB, CSV = ROOT / "data", ROOT / "data/climate_signals.db", ROOT / "data/latest_signals.csv"
LOG = logging.getLogger("climate_signal")
FEEDS = {
    "Climate Tech VC": "https://www.ctvc.co/rss/",
    "Canary Media": "https://www.canarymedia.com/rss.rss",
    "TechCrunch Startups": "https://techcrunch.com/category/startups/feed/",
}
FIELDS = ["discovered_at_utc", "published_at", "source", "signal_type", "sector_tags", "funding_stage",
          "funding_amount_mentioned", "title", "summary", "investment_relevance", "verification_notes", "url", "relevance_score"]
SECTORS = {
    "Renewables & clean power": ("renewable energy", "clean energy", "solar", "wind power", "geothermal"),
    "Batteries & energy storage": ("battery", "batteries", "energy storage", "long-duration storage"),
    "Electrification & mobility": ("electrification", "electric vehicle", "ev charging", "heat pump", "electric truck"),
    "Carbon & industrial decarbonisation": ("carbon capture", "carbon removal", "green steel", "decarbonisation", "decarbonization"),
    "Hydrogen & alternative fuels": ("green hydrogen", "hydrogen", "e-fuels", "sustainable fuels", "biogas"),
    "Food, agriculture & circularity": ("agtech", "food waste", "circular economy", "recycling", "alternative protein"),
    "Climate adaptation & nature": ("climate adaptation", "climate resilience", "wildfire", "water scarcity", "methane monitoring"),
    "Grid & climate software": ("smart grid", "grid software", "virtual power plant", "demand response", "climate software"),
    "Climate-tech (cross-sector)": ("climate tech", "climate-tech", "climate startup", "climate start-up", "climate venture"),
}
FUNDING = ("funding", "raised", "raises", "series a", "series b", "series c", "seed round", "pre-seed", "venture capital", "financing", "grant award", "investment round")
BUSINESS = ("startup", "start-up", "company", "founder", "launches", "pilot", "partnership", "contract", "manufacturing", "factory", "expansion", "customer", "deployment", "offtake")
STAGES = [("Pre-seed", r"\bpre[- ]seed\b"), ("Seed", r"\bseed(?: round| funding| stage)?\b"), ("Series A", r"\bseries\s+a\b"), ("Series B", r"\bseries\s+b\b"), ("Series C", r"\bseries\s+c\b"), ("Series D+", r"\bseries\s+[d-z]\b"), ("Growth", r"\bgrowth (?:round|funding|capital)\b"), ("Grant", r"\bgrant\b")]
AMOUNT = re.compile(r"(?:[$€£]\s?\d+(?:[.,]\d+)?\s?(?:bn|billion|m|million|k|thousand)?|\b(?:USD|EUR|GBP)\s?\d+(?:[.,]\d+)?\s?(?:bn|billion|m|million|k|thousand)?\b)", re.I)


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def analyse_signal(title: str, description: str) -> dict[str, Any] | None:
    text = f"{title} {description}".lower()
    sectors = [name for name, terms in SECTORS.items() if any(term in text for term in terms)]
    if not sectors:
        return None
    funding, commercial = any(x in text for x in FUNDING), any(x in text for x in BUSINESS)
    if not (funding or commercial):
        return None
    stage = next((label for label, pattern in STAGES if re.search(pattern, text, re.I)), "")
    amount = AMOUNT.search(f"{title} {description}") if funding else None
    return {"signal_type": "Funding signal" if funding else "Startup / commercial signal",
            "sector_tags": "; ".join(sectors), "funding_stage": stage,
            "funding_amount_mentioned": amount.group(0).strip() if amount else "",
            "relevance_score": min(10, 2 * len(sectors) + (4 if funding else 2))}


def fallback_analysis(title: str, description: str, signal: dict[str, Any]) -> dict[str, str]:
    text = description.strip() or title.strip()
    summary = " ".join(re.split(r"(?<=[.!?])\s+", text)[:2])[:420].strip() or title
    funding = signal["signal_type"] == "Funding signal"
    relevance = ("Potential financing signal; verify the round size, investors, use of proceeds and traction."
                 if funding else "Potential company or commercial signal; verify customer traction, deployment and route to scale.")
    return {"summary": summary, "investment_relevance": relevance,
            "verification_notes": "Keyword classification from the RSS headline/description; confirm details in the original article."}


def initialise_db(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE IF NOT EXISTS signals (url TEXT PRIMARY KEY, published_at TEXT, discovered_at_utc TEXT NOT NULL, payload TEXT NOT NULL)")
    connection.commit()


def store_signal(connection: sqlite3.Connection, article: dict[str, Any]) -> bool:
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    key = article.get("url") or f"{article.get('title','')}|{article.get('published_at','')}"
    item = {**article, "discovered_at_utc": now}
    cur = connection.execute("INSERT OR IGNORE INTO signals VALUES (?, ?, ?, ?)",
        (key, article.get("published_at", ""), now, json.dumps(item, ensure_ascii=False)))
    connection.commit()
    if cur.rowcount:
        article["discovered_at_utc"] = now
        return True
    return False


def recent_signals(connection: sqlite3.Connection, days: int) -> list[dict[str, Any]]:
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat(timespec="seconds")
    rows = connection.execute("SELECT payload FROM signals WHERE (published_at >= ? OR (published_at = '' AND discovered_at_utc >= ?)) ORDER BY published_at DESC, discovered_at_utc DESC", (cutoff, cutoff)).fetchall()
    return [json.loads(row[0]) for row in rows]


def fetch_feed(name: str, url: str, days: int) -> list[dict[str, Any]]:
    response = requests.get(url, headers={"User-Agent": "ClimateSignalTracker/1.0"}, timeout=25)
    response.raise_for_status()
    import feedparser
    parsed = feedparser.parse(response.content)
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    found = []
    for entry in parsed.entries:
        title, link = clean_text(entry.get("title")), entry.get("link", "").strip()
        description = clean_text(entry.get("summary", ""))
        if not title or not link:
            continue
        published = ""
        raw_date = entry.get("published") or entry.get("updated")
        if raw_date:
            try:
                parsed_date = email.utils.parsedate_to_datetime(raw_date)
                if parsed_date.tzinfo is None:
                    parsed_date = parsed_date.replace(tzinfo=dt.timezone.utc)
                published = parsed_date.astimezone(dt.timezone.utc).isoformat(timespec="seconds")
                if parsed_date < cutoff:
                    continue
            except (TypeError, ValueError, OverflowError):
                pass
        signal = analyse_signal(title, description)
        if signal:
            found.append({"published_at": published, "source": name, "title": title,
                          "description": description, "url": link, **signal})
    return found


def claude_summary(title: str, description: str, signal: dict[str, Any]) -> dict[str, str]:
    api_key, model = os.getenv("ANTHROPIC_API_KEY", "").strip(), os.getenv("ANTHROPIC_MODEL", "").strip()
    if not api_key or not model:
        return fallback_analysis(title, description, signal)
    prompt = ("Use only this headline and RSS description. Do not invent facts. Return JSON with string keys "
              "summary, investment_relevance, verification_notes.\nHeadline: " + title +
              "\nRSS description: " + description[:2500])
    try:
        response = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": model, "max_tokens": 350, "messages": [{"role": "user", "content": prompt}]}, timeout=40)
        response.raise_for_status()
        blocks = [part.get("text", "") for part in response.json().get("content", []) if part.get("type") == "text"]
        raw = "\n".join(blocks).strip()
        fence = chr(96) * 3
        raw = raw.removeprefix(fence + "json").removeprefix(fence).removesuffix(fence).strip()
        result = json.loads(raw)
        return {key: str(result.get(key, "")).strip() for key in ("summary", "investment_relevance", "verification_notes")}
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        LOG.warning("Claude summary failed; using extractive summary: %s", exc)
        return fallback_analysis(title, description, signal)


def upload_to_google_sheets(items: list[dict[str, Any]]) -> int:
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
    credentials_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    credentials_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/service-account.json").strip()
    if not sheet_id or not (credentials_json or (ROOT / credentials_file).exists()):
        LOG.info("Google Sheets not configured; CSV export remains available.")
        return 0
    import gspread
    from google.oauth2.service_account import Credentials
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    credentials = (Credentials.from_service_account_info(json.loads(credentials_json), scopes=scopes)
                   if credentials_json else Credentials.from_service_account_file(str(ROOT / credentials_file), scopes=scopes))
    sheet = gspread.authorize(credentials).open_by_key(sheet_id)
    try:
        tab = sheet.worksheet("Signals")
    except gspread.WorksheetNotFound:
        tab = sheet.add_worksheet(title="Signals", rows=1000, cols=len(FIELDS))
    rows = tab.get_all_values()
    if not rows:
        tab.append_row(FIELDS, value_input_option="RAW")
        known = set()
    else:
        known = {r[11] for r in rows[1:] if len(r) > 11 and r[11]}
    new_rows = [[str(item.get(field, "")) for field in FIELDS] for item in items if item.get("url") not in known]
    if new_rows:
        tab.append_rows(new_rows, value_input_option="USER_ENTERED")
    LOG.info("Appended %s new rows to Google Sheets.", len(new_rows))
    return len(new_rows)


def write_csv(items: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(items)


def main() -> int:
    parser = argparse.ArgumentParser(description="Track climate-tech startup and funding signals from RSS feeds.")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--google-sheets", action="store_true")
    parser.add_argument("--no-ai", action="store_true")
    parser.add_argument("--max-ai-summaries", type=int, default=10,
                        help="Maximum number of Claude summaries per run (default: 10). Remaining items use the extractive summary.")
    args = parser.parse_args()
    if args.days < 1 or args.limit < 1:
        parser.error("--days and --limit must be positive")
    if args.max_ai_summaries < 0:
        parser.error("--max-ai-summaries cannot be negative")
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    DATA.mkdir(exist_ok=True)
    db = sqlite3.connect(DB)
    initialise_db(db)
    new, successful = [], 0
    for name, url in FEEDS.items():
        try:
            entries = fetch_feed(name, url, args.days)
            successful += 1
            LOG.info("%s: %s matching items", name, len(entries))
            new.extend(entries)
        except (requests.RequestException, ValueError) as exc:
            LOG.warning("Skipping %s: %s", name, exc)
    if not successful:
        LOG.error("All feeds failed; check connectivity and retry.")
        db.close()
        return 2
    unique = {entry["url"]: entry for entry in new}
    new_items, ai_used = [], 0
    for article in sorted(unique.values(), key=lambda x: x.get("published_at", ""), reverse=True)[:args.limit]:
        use_ai = not args.no_ai and ai_used < args.max_ai_summaries
        if use_ai:
            summary = claude_summary(article["title"], article["description"], article)
            ai_used += 1
        else:
            summary = fallback_analysis(article["title"], article["description"], article)
        article.update(summary)
        article.pop("description", None)
        if store_signal(db, article):
            new_items.append(article)
    current = recent_signals(db, args.days)
    write_csv(current, CSV)
    if args.google_sheets:
        upload_to_google_sheets(new_items)
    LOG.info("New signals: %s | CSV rows: %s | Saved: %s", len(new_items), len(current), CSV)
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
