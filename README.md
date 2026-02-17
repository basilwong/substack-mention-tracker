# Substack Mention Tracker

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/basilwong/substack-mention-tracker/blob/main/Substack_Mention_Tracker-2.ipynb)

Track how often specific terms are mentioned in Substack articles over time, with monthly counts, daily counts, and engagement analysis.

Uses Substack's undocumented search API to fetch article metadata, then groups results by time period and computes engagement metrics.

## Quick Start

### Google Colab (zero setup)

Click the **Open in Colab** badge above. Edit the search terms in Step 2 and run all cells.

### Local

```bash
git clone https://github.com/basilwong/substack-mention-tracker.git
cd substack-mention-tracker
pip install -r requirements.txt

# Default: monthly + daily counts for "Claude Code" and "AI coding"
python3 substack_mention_tracker.py

# With engagement analysis
python3 substack_mention_tracker.py --engagement

# Custom queries
python3 substack_mention_tracker.py --queries "vibe coding" "AI agents" --engagement

# Daily only
python3 substack_mention_tracker.py --granularity daily

# Monthly only, no chart
python3 substack_mention_tracker.py --granularity monthly --no-chart
```

## Features

The script provides three views of the data:

**Monthly mention counts.** How many Substack articles mention each search term per month, displayed as an ASCII table, CSV file, and line chart.

**Daily mention counts.** The same data at daily granularity, useful for spotting inflection points and short-term trends.

**Engagement analysis** (opt-in with `--engagement`). For each day, computes the average reactions per post and total reactions across all matching posts. Charts include a 7-day rolling average for smoothing.

## Command Line Options

| Flag | Default | Description |
|---|---|---|
| `--queries` | `"Claude Code" "AI coding"` | Search terms to track |
| `--granularity` | `all` | `monthly`, `daily`, or `all` |
| `--engagement` | off | Include engagement analysis |
| `--max-pages` | `100` | Max pages per query (20 results/page) |
| `--delay` | `2.0` | Seconds between API requests |
| `--output-dir` | `.` | Directory for output files |
| `--no-chart` | off | Skip chart generation |
| `--no-json` | off | Skip detailed JSON export |

## Output Files

All files are saved to the output directory (current directory by default):

| File | Description |
|---|---|
| `substack_monthly_mentions.csv` | Monthly counts per query |
| `substack_monthly_chart.png` | Monthly trend line chart |
| `substack_daily_mentions.csv` | Daily counts per query |
| `substack_daily_chart.png` | Daily trend line chart |
| `substack_engagement.csv` | Daily avg/total reactions per query |
| `substack_engagement_chart.png` | Engagement charts with 7-day rolling avg |
| `substack_mentions_detailed.json` | Full post metadata (title, URL, reactions, etc.) |

## How It Works

The script uses Substack's undocumented search API:

```
GET https://substack.com/api/v1/post/search?query=<term>&page=<n>&includePlatformResults=true&filter=all
```

Each page returns 20 results. The script paginates through up to 100 pages (2,000 results) per query, deduplicates by post ID, and groups by date.

**Rate limiting.** The API enforces rate limits. The script includes exponential backoff retry logic for HTTP 429 (rate limit) and 502/503 (server error) responses. If you encounter persistent rate limiting, increase the delay with `--delay 3` or `--delay 4`.

## Limitations

**Result cap.** Substack's API returns at most ~2,000 results per query. For very popular terms, this means older articles may be missing from the data.

**Relevance ranking.** Results are ranked by relevance, not chronologically. This can cause recent articles to be overrepresented.

**No exact match.** The search is keyword-based, not exact-match. A search for "AI coding" may return articles that mention "AI" and "coding" separately.

**Undocumented API.** This uses an undocumented API that could change at any time without notice.

## Requirements

- Python 3.9+
- `requests`
- `matplotlib`
- `pandas` (Colab notebook only)

## License

MIT
