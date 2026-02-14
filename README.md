# Substack Mention Tracker

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/basilwong/substack-mention-tracker/blob/main/substack_mention_tracker.ipynb)

A Python script that tracks how often specific terms (e.g., "Claude Code", "AI coding") appear in Substack articles over time, grouped by month.

## How It Works

The script uses **Substack's undocumented search API** to fetch article metadata, extract publication dates, and aggregate mention counts by month. It produces a formatted console table, a CSV file, a line chart, and an optional detailed JSON export.

### API Details (Discovered Through Reverse Engineering)

| Property | Value |
|---|---|
| **Endpoint** | `GET https://substack.com/api/v1/post/search` |
| **Results per page** | 20 |
| **Max pages** | ~100 (hard limit; returns HTTP 400 beyond) |
| **Max results per query** | ~2,000 |
| **Authentication** | None required |
| **Rate limiting** | Handled automatically with exponential backoff retry |

**Query parameters:**

| Parameter | Type | Description |
|---|---|---|
| `query` | string | Search term (e.g., `"Claude Code"`) |
| `page` | int | Zero-indexed page number (0–99) |
| `filter` | string | Content type: `all`, `free`, `paid` |
| `dateRange` | string | Time filter: `day`, `week`, `month`, `year` (optional) |
| `includePlatformResults` | bool | Include platform-wide results |

**Each result object includes:** `id`, `title`, `post_date` (ISO-8601), `canonical_url`, `reaction_count`, `comment_count`, `wordcount`, `publishedBylines`, and more.

## Installation

```bash
pip install -r requirements.txt
# or manually:
pip install requests matplotlib pandas
```

## Usage

### Basic (default queries: "Claude Code" and "AI coding")

```bash
python3 substack_mention_tracker.py
```

### Custom queries

```bash
python3 substack_mention_tracker.py --queries "Claude Code" "AI coding" "vibe coding" "Cursor AI"
```

### Control pagination depth and request delay

```bash
# Fetch up to 50 pages per query (1,000 results) with 2-second delay
python3 substack_mention_tracker.py --max-pages 50 --delay 2.0
```

### Specify output file paths

```bash
python3 substack_mention_tracker.py \
  --output results.csv \
  --chart trend_chart.png \
  --json detailed_results.json
```

### Skip optional outputs

```bash
python3 substack_mention_tracker.py --no-chart --no-json
```

## Output Files

| File | Description |
|---|---|
| `substack_mentions.csv` | Monthly counts per query in CSV format |
| `substack_mentions_chart.png` | Line chart visualization of trends |
| `substack_mentions_detailed.json` | Full post metadata for every matched article |

## Limitations and Caveats

1. **Undocumented API.** This endpoint is not part of Substack's official API and could change or be rate-limited at any time. The script is best suited for periodic research, not production monitoring.

2. **~2,000 result cap per query.** Substack's search API returns at most ~100 pages (20 results each). For very popular terms, older results may be truncated. For terms with more than 2,000 total results, consider running the script monthly and accumulating data over time.

3. **Search relevance, not exact match.** The API performs relevance-based search, not strict substring matching. A search for "AI coding" may return articles that mention "AI" and "coding" separately. For higher precision, you could post-filter results by checking whether the exact phrase appears in the title or body text.

4. **No official date-range filtering by arbitrary dates.** The `dateRange` parameter only supports relative windows (`day`, `week`, `month`, `year`), not custom date ranges. The script works around this by fetching all available results and grouping by the `post_date` field.

5. **Rate limiting.** The script automatically retries with exponential backoff (10s → 20s → 40s → 80s → 160s) on HTTP 429 errors, up to 5 times per page. The default delay between requests is 2 seconds. Increase `--delay` if you still encounter issues.

## Alternative Approaches Considered

| Approach | Pros | Cons |
|---|---|---|
| **Substack Search API** (used here) | No auth needed, structured JSON, includes dates and metadata | Undocumented, 2K result cap, relevance-based |
| **Substack Official API** | Official, stable | Requires publisher account; only accesses your own publication's data |
| **RSS feeds per publication** | Stable, standard format | Must know which publications to monitor; no cross-platform search |
| **`substack_api` Python package** | Convenient wrapper | Focuses on individual publication data, not global search |
| **Web scraping** | Full control | Fragile, slower, may violate ToS |
| **Google Custom Search API** | Powerful, `site:substack.com` filter | Costs money after free tier (100 queries/day), less precise date info |

## Extending the Script

- **Add more queries:** Simply pass additional terms via `--queries`.
- **Schedule monthly runs:** Use `cron` to run the script on the 1st of each month and append to a cumulative CSV.
- **Post-filter for exact matches:** After fetching results, filter posts where the exact query string appears in the title or body text (requires fetching full article content via the publication's RSS or API).
- **Track engagement metrics:** The detailed JSON includes `reaction_count`, `comment_count`, and `wordcount` — useful for analyzing not just volume but engagement depth.
