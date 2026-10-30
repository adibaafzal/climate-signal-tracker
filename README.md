# Climate Signal — Climate-Tech Startup & Funding Radar

A small Python research pipeline that scans public RSS feeds, screens climate-tech stories for startup, funding and commercialisation signals, summarises relevant items, and exports a structured tracker to CSV or Google Sheets.

> **Purpose:** a lightweight venture-research assistant / portfolio project. It is not an investment recommendation engine and does not verify claims made by publishers.

## What it does

1. Reads three public RSS/Atom feeds: Climate Tech VC, Canary Media and TechCrunch Startups.
2. Cleans article headlines and RSS descriptions.
3. Uses transparent keyword rules to identify climate-tech sectors and classify items as funding or startup/commercial signals.
4. Extracts funding-stage and funding-amount wording when it appears in the headline or RSS description. These fields are clues, not verified facts.
5. Uses Claude optionally to create a short, source-bounded summary, a potential investor-relevance note and a list of details to verify. If no API key is provided, it uses a simple extractive summary instead.
6. Stores seen links in SQLite to avoid repeatedly processing the same story.
7. Exports a rolling CSV and can append newly discovered items to Google Sheets.

## Sample output

See [`docs/sample_output.csv`](docs/sample_output.csv) for an example of the exported tracker from a real run.

## Example output fields

| Field | Description |
|---|---|
| `published_at` | Publication timestamp supplied by the feed |
| `source` | Feed publisher |
| `signal_type` | Funding signal or startup / commercial signal |
| `sector_tags` | Climate-tech sectors matched by the keyword rules |
| `funding_stage` | Stage wording detected in the headline/description, if any |
| `funding_amount_mentioned` | Currency/amount wording detected in the headline/description, if any |
| `summary` | Short factual summary; Claude-assisted if configured |
| `investment_relevance` | A potential research angle, not an investment conclusion |
| `verification_notes` | Missing details / what to confirm in the original article |
| `url` | Link to the original publisher article |
| `relevance_score` | Transparent heuristic score (not a model confidence or investment score) |

## Quick start (local CSV mode)

Requires Python 3.10+.

```bash
git clone https://github.com/adibaafzal/climate-signal-tracker.git
cd climate-signal-tracker
python -m venv .venv
```

Activate the environment:

**macOS / Linux**
```bash
source .venv/bin/activate
```

**Windows PowerShell**
```powershell
.venv\Scripts\Activate.ps1
```

Install and run:

```bash
pip install -r requirements.txt
python climate_signal.py --days 30 --limit 40
```

The first run creates `data/climate_signals.db` and `data/latest_signals.csv`. The CSV contains the rolling set of relevant stories seen within the selected lookback window. The SQLite database remembers previously seen URLs so repeat runs do not duplicate them.

For a no-cost, no-LLM run:

```bash
python climate_signal.py --days 14 --limit 25 --no-ai
```

## Optional: Claude summaries

1. Create an Anthropic API key in your Anthropic Console.
2. Copy `.env.example` to `.env`.
3. Add your key to `ANTHROPIC_API_KEY`.
4. Set `ANTHROPIC_MODEL` to a model identifier currently available to your Anthropic account. The project does not hard-code a model identifier, since available model names can change. If the model is not configured, the script uses its built-in extractive summary.

The script summarises only the headline and RSS description, not the full article. It caps Claude summaries at 10 per run by default to limit API usage; any further items use the built-in extractive summary. Change the cap with `--max-ai-summaries`:

```bash
python climate_signal.py --days 30 --limit 40 --max-ai-summaries 10
```

Claude is instructed not to invent amounts, investors, traction or company information. Check the original source before relying on any summary.

## Optional: Google Sheets export

1. Create a Google Cloud project and enable the Google Sheets API and Google Drive API.
2. Install the optional Google Sheets dependencies: `pip install -r requirements-google.txt`.
3. Create a service account and download its JSON key.
4. Put the JSON file at `credentials/service-account.json` (this folder is ignored by Git).
5. Create a Google Sheet and share it with the service account's email address as an Editor.
6. Add the spreadsheet ID to `.env` as `GOOGLE_SHEET_ID`.
7. Run:

```bash
python climate_signal.py --days 30 --limit 40 --google-sheets
```

New URLs are appended to the `Signals` worksheet. Google credentials must never be committed to GitHub. A manual GitHub Actions workflow is included under **Actions → Run Climate Signal**; add `GOOGLE_SHEET_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON` and (optionally) both `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` as repository secrets first.

## Feed sources

- [Climate Tech VC](https://www.ctvc.co/) — climate-tech venture reporting. RSS: `https://www.ctvc.co/rss/`
- [Canary Media](https://www.canarymedia.com/) — clean energy, electrification and climate solutions. RSS: `https://www.canarymedia.com/rss.rss`
- [TechCrunch Startups](https://techcrunch.com/category/startups/) — startup reporting, screened by the project for climate-related terms. RSS: `https://techcrunch.com/category/startups/feed/`

The script uses feed-provided headlines and descriptions and links back to publishers. Publisher feeds, availability and terms can change; check feed availability if a source stops responding.

## How the screening works

The first pass is intentionally explainable: dictionaries of climate-sector terms, funding language and commercialisation terms produce the tags and a simple relevance score. It is a triage filter, not a complete climate taxonomy. A story may be missed if the RSS headline and description do not contain relevant terms. A funding amount may be misread if a headline contains another monetary figure. The original article is the source of truth.

## Run tests

```bash
python -m unittest discover -s tests -v
```

The tests run offline and cover text cleaning, relevant/off-topic screening, signal classification and fallback summaries.

## GitHub Actions (optional)

A manual workflow is included. After adding the relevant repository secrets, open the **Actions** tab, select **Run Climate Signal**, and choose **Run workflow**. The generated CSV is attached to that workflow run as an artifact. It is manual by design so you can validate the feed filters and any API costs before scheduling repeated runs.

## Ideas for a next iteration

- Add European geography filters and country tags.
- Extract company names, investors and round amounts into separate fields, then validate them against the article.
- Add sector-specific watchlists (energy storage, industrial decarbonisation, climate adaptation, etc.).
- Add a weekly digest with the strongest signals and unresolved verification questions.

## Responsible use

This tool is for research triage. It does not assess valuation, financial health, technical performance, regulatory risk or investment suitability. Confirm all facts in the linked original reporting before using them in a decision.

## Licence

MIT. See `LICENSE`.
