#!/usr/bin/env python3
"""
Substack Mention Tracker
========================
Tracks the number of times specific search terms (e.g., "Claude Code", "AI coding")
are mentioned in Substack articles. Provides three views:

  1. Monthly mention counts
  2. Daily mention counts
  3. Daily engagement analysis (avg reactions per post, total reactions)

Uses Substack's undocumented search API:
    GET https://substack.com/api/v1/post/search

Usage:
    python3 substack_mention_tracker.py
    python3 substack_mention_tracker.py --queries "Claude Code" "AI coding" "vibe coding"
    python3 substack_mention_tracker.py --granularity daily
    python3 substack_mention_tracker.py --granularity daily --engagement
    python3 substack_mention_tracker.py --granularity all --engagement
"""

import argparse
import csv
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://substack.com/api/v1/post/search"
RESULTS_PER_PAGE = 20
MAX_PAGES = 100  # Substack caps at ~100 pages (2,000 results per query)
REQUEST_DELAY = 2.0  # seconds between API calls to be respectful
MAX_RETRIES = 5  # max retries on rate-limit or server errors
INITIAL_BACKOFF = 10.0  # initial backoff in seconds after an error

DEFAULT_QUERIES = ["Claude Code", "AI coding"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


# ---------------------------------------------------------------------------
# Core Fetch Functions
# ---------------------------------------------------------------------------


def fetch_search_page(query: str, page: int = 0, max_retries: int = MAX_RETRIES) -> dict:
    """
    Fetch a single page of search results from Substack's API.
    Includes exponential backoff retry logic for HTTP 429 (rate limit)
    and 502/503 (server error) responses.
    """
    params = {
        "query": query,
        "page": page,
        "includePlatformResults": "true",
        "filter": "all",
    }

    backoff = INITIAL_BACKOFF

    for attempt in range(max_retries + 1):
        resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=30)

        if resp.status_code in (429, 502, 503):
            if attempt < max_retries:
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        wait_time = float(retry_after)
                    except ValueError:
                        wait_time = backoff
                else:
                    wait_time = backoff

                print(
                    f"    Server error ({resp.status_code}) on page {page}. "
                    f"Waiting {wait_time:.0f}s before retry "
                    f"({attempt + 1}/{max_retries})..."
                )
                time.sleep(wait_time)
                backoff *= 2  # exponential backoff
                continue
            else:
                print(
                    f"    Error ({resp.status_code}) on page {page}. "
                    f"Max retries ({max_retries}) exhausted. Stopping pagination."
                )
                resp.raise_for_status()

        resp.raise_for_status()
        return resp.json()


def fetch_all_results(query: str, max_pages: int = MAX_PAGES, delay: float = REQUEST_DELAY) -> list[dict]:
    """
    Paginate through all available search results for a given query.
    Automatically handles rate limiting and server errors with exponential backoff.
    """
    all_results = []
    seen_ids = set()

    for page in range(max_pages):
        try:
            data = fetch_search_page(query, page)
        except requests.exceptions.HTTPError as exc:
            if exc.response is not None and exc.response.status_code in (400, 422, 502, 503):
                print(f"    Reached page limit at page {page}.")
                break
            if exc.response is not None and exc.response.status_code == 429:
                print(f"    Stopping after rate-limit on page {page}. Collected {len(all_results)} results so far.")
                break
            raise

        results = data.get("results", [])
        if not results:
            break

        for post in results:
            pid = post.get("id")
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                all_results.append(post)

        has_more = data.get("more", False)
        print(
            f"  Page {page:>3d}: fetched {len(results):>2d} results "
            f"(total unique: {len(all_results)})"
        )

        if not has_more:
            break

        time.sleep(delay)

    return all_results


# ---------------------------------------------------------------------------
# Monthly Grouping
# ---------------------------------------------------------------------------


def group_by_month(posts: list[dict]) -> dict[str, int]:
    """Group posts by year-month and return counts."""
    counts: dict[str, int] = defaultdict(int)
    for post in posts:
        date_str = post.get("post_date", "")
        if not date_str:
            continue
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            key = dt.strftime("%Y-%m")
            counts[key] += 1
        except (ValueError, TypeError):
            continue
    return dict(sorted(counts.items()))


def build_monthly_timeline(monthly_data: dict[str, dict[str, int]]) -> list[str]:
    """Build a sorted list of all year-month keys, filling gaps."""
    all_months = set()
    for counts in monthly_data.values():
        all_months.update(counts.keys())
    if not all_months:
        return []
    sorted_months = sorted(all_months)
    start = datetime.strptime(sorted_months[0], "%Y-%m")
    end = datetime.strptime(sorted_months[-1], "%Y-%m")
    timeline = []
    current = start
    while current <= end:
        timeline.append(current.strftime("%Y-%m"))
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    return timeline


# ---------------------------------------------------------------------------
# Daily Grouping
# ---------------------------------------------------------------------------


def group_by_day(posts: list[dict]) -> dict[str, int]:
    """Group posts by date and return counts."""
    counts: dict[str, int] = defaultdict(int)
    for post in posts:
        date_str = post.get("post_date", "")
        if not date_str:
            continue
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            key = dt.strftime("%Y-%m-%d")
            counts[key] += 1
        except (ValueError, TypeError):
            continue
    return dict(sorted(counts.items()))


def build_daily_timeline(daily_data: dict[str, dict]) -> list[str]:
    """Build a sorted list of all dates, filling gaps."""
    all_days = set()
    for data in daily_data.values():
        if isinstance(data, dict):
            all_days.update(data.keys())
    if not all_days:
        return []
    sorted_days = sorted(all_days)
    start = datetime.strptime(sorted_days[0], "%Y-%m-%d")
    end = datetime.strptime(sorted_days[-1], "%Y-%m-%d")
    timeline = []
    current = start
    while current <= end:
        timeline.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return timeline


# ---------------------------------------------------------------------------
# Engagement Analysis
# ---------------------------------------------------------------------------


def compute_daily_engagement(posts: list[dict]) -> dict[str, dict]:
    """
    For each day, compute total reactions, post count, and average reactions per post.
    Returns dict: { "YYYY-MM-DD": {"total_reactions": int, "post_count": int, "avg_reactions": float} }
    """
    daily = defaultdict(lambda: {"total_reactions": 0, "post_count": 0})
    for post in posts:
        date_str = post.get("post_date", "")
        if not date_str:
            continue
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            key = dt.strftime("%Y-%m-%d")
            reactions = post.get("reaction_count", 0) or 0
            daily[key]["total_reactions"] += reactions
            daily[key]["post_count"] += 1
        except (ValueError, TypeError):
            continue

    result = {}
    for day in sorted(daily.keys()):
        d = daily[day]
        avg = d["total_reactions"] / d["post_count"] if d["post_count"] > 0 else 0
        result[day] = {
            "total_reactions": d["total_reactions"],
            "post_count": d["post_count"],
            "avg_reactions": round(avg, 1),
        }
    return result


def rolling_average(values: list[float], window: int = 7) -> list[float]:
    """Compute a centered rolling average."""
    result = []
    half = window // 2
    for i in range(len(values)):
        start = max(0, i - half)
        end = min(len(values), i + half + 1)
        chunk = values[start:end]
        result.append(sum(chunk) / len(chunk) if chunk else 0)
    return result


# ---------------------------------------------------------------------------
# Output: Tables
# ---------------------------------------------------------------------------


def print_monthly_table(monthly_data: dict[str, dict[str, int]], timeline: list[str]) -> None:
    """Print a formatted ASCII table of monthly mention counts."""
    queries = list(monthly_data.keys())
    col_widths = [10] + [max(len(q), 6) for q in queries]
    header = f"{'Month':<{col_widths[0]}}"
    for i, q in enumerate(queries):
        header += f"  {q:>{col_widths[i+1]}}"
    print("\n" + header)
    print("-" * len(header))
    for month in timeline:
        row = f"{month:<{col_widths[0]}}"
        for i, q in enumerate(queries):
            count = monthly_data[q].get(month, 0)
            row += f"  {count:>{col_widths[i+1]}}"
        print(row)
    print("-" * len(header))
    totals_row = f"{'TOTAL':<{col_widths[0]}}"
    for i, q in enumerate(queries):
        total = sum(monthly_data[q].values())
        totals_row += f"  {total:>{col_widths[i+1]}}"
    print(totals_row)
    print()


# ---------------------------------------------------------------------------
# Output: CSV
# ---------------------------------------------------------------------------


def save_monthly_csv(monthly_data, timeline, output_path):
    """Save monthly mention counts to CSV."""
    queries = list(monthly_data.keys())
    path = Path(output_path)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Month"] + queries)
        for month in timeline:
            row = [month] + [monthly_data[q].get(month, 0) for q in queries]
            writer.writerow(row)
        writer.writerow(["TOTAL"] + [sum(monthly_data[q].values()) for q in queries])
    print(f"Monthly CSV saved to: {path.resolve()}")


def save_daily_csv(daily_data, timeline, output_path):
    """Save daily mention counts to CSV."""
    queries = list(daily_data.keys())
    path = Path(output_path)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Date"] + queries)
        for day in timeline:
            row = [day] + [daily_data[q].get(day, 0) for q in queries]
            writer.writerow(row)
    print(f"Daily CSV saved to: {path.resolve()}")


def save_engagement_csv(engagement_data, timeline, queries, output_path):
    """Save daily engagement data to CSV."""
    path = Path(output_path)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        header = ["Date"]
        for q in queries:
            header.extend([f"{q} - Avg Reactions", f"{q} - Total Reactions", f"{q} - Post Count"])
        writer.writerow(header)
        for day in timeline:
            row = [day]
            for q in queries:
                eng = engagement_data[q].get(day, {})
                row.extend([
                    eng.get("avg_reactions", 0),
                    eng.get("total_reactions", 0),
                    eng.get("post_count", 0),
                ])
            writer.writerow(row)
    print(f"Engagement CSV saved to: {path.resolve()}")


# ---------------------------------------------------------------------------
# Output: Charts
# ---------------------------------------------------------------------------


def save_monthly_chart(monthly_data, timeline, output_path):
    """Generate and save a line chart of monthly mention counts."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.ticker as ticker
    except ImportError:
        print("matplotlib not installed. Skipping chart. Install with: pip install matplotlib")
        return

    fig, ax = plt.subplots(figsize=(14, 6))
    for query, counts in monthly_data.items():
        values = [counts.get(m, 0) for m in timeline]
        ax.plot(timeline, values, marker="o", markersize=4, linewidth=2, label=query)
    ax.set_xlabel("Month", fontsize=12)
    ax.set_ylabel("Number of Substack Articles", fontsize=12)
    ax.set_title("Monthly Mentions in Substack Articles", fontsize=14, fontweight="bold")
    ax.legend(fontsize=11)
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.grid(True, alpha=0.3)
    step = max(1, len(timeline) // 20)
    ax.set_xticks(range(0, len(timeline), step))
    ax.set_xticklabels([timeline[i] for i in range(0, len(timeline), step)], rotation=45, ha="right")
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()
    print(f"Monthly chart saved to: {Path(output_path).resolve()}")


def save_daily_chart(daily_data, timeline, output_path):
    """Generate and save a line chart of daily mention counts."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        import matplotlib.ticker as ticker
    except ImportError:
        print("matplotlib not installed. Skipping chart. Install with: pip install matplotlib")
        return

    fig, ax = plt.subplots(figsize=(16, 6))
    dates = [datetime.strptime(d, "%Y-%m-%d") for d in timeline]
    for query, counts in daily_data.items():
        values = [counts.get(d, 0) for d in timeline]
        ax.plot(dates, values, linewidth=1.5, alpha=0.85, label=query)
    ax.set_xlabel("Date", fontsize=12)
    ax.set_ylabel("Number of Substack Articles", fontsize=12)
    ax.set_title("Daily Mentions in Substack Articles", fontsize=14, fontweight="bold")
    ax.legend(fontsize=11)
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()
    print(f"Daily chart saved to: {Path(output_path).resolve()}")


def save_engagement_chart(engagement_data, timeline, output_path):
    """Generate and save engagement charts (avg reactions per post + total reactions per day)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        import matplotlib.ticker as ticker
    except ImportError:
        print("matplotlib not installed. Skipping chart. Install with: pip install matplotlib")
        return

    dates = [datetime.strptime(d, "%Y-%m-%d") for d in timeline]
    fig, axes = plt.subplots(2, 1, figsize=(16, 10), sharex=True)

    # Chart 1: Average reactions per post per day
    ax1 = axes[0]
    for query, eng in engagement_data.items():
        raw_values = [eng.get(d, {}).get("avg_reactions", 0) for d in timeline]
        smoothed = rolling_average(raw_values, window=7)
        ax1.plot(dates, raw_values, linewidth=0.8, alpha=0.3)
        ax1.plot(dates, smoothed, linewidth=2.0, alpha=0.9, label=f"{query} (7-day avg)")
    ax1.set_ylabel("Avg. Reactions per Post", fontsize=12)
    ax1.set_title("Average Engagement per Post (Daily)", fontsize=14, fontweight="bold")
    ax1.legend(fontsize=11)
    ax1.grid(True, alpha=0.3)

    # Chart 2: Total reactions per day
    ax2 = axes[1]
    for query, eng in engagement_data.items():
        raw_values = [eng.get(d, {}).get("total_reactions", 0) for d in timeline]
        smoothed = rolling_average(raw_values, window=7)
        ax2.plot(dates, raw_values, linewidth=0.8, alpha=0.3)
        ax2.plot(dates, smoothed, linewidth=2.0, alpha=0.9, label=f"{query} (7-day avg)")
    ax2.set_xlabel("Date", fontsize=12)
    ax2.set_ylabel("Total Reactions", fontsize=12)
    ax2.set_title("Total Engagement per Day", fontsize=14, fontweight="bold")
    ax2.legend(fontsize=11)
    ax2.grid(True, alpha=0.3)

    for ax in axes:
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")

    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()
    print(f"Engagement chart saved to: {Path(output_path).resolve()}")


# ---------------------------------------------------------------------------
# Output: JSON
# ---------------------------------------------------------------------------


def _extract_pub_name(post: dict) -> str:
    """Safely extract the publication name from a post dict."""
    try:
        bylines = post.get("publishedBylines", [])
        if bylines:
            pub_users = bylines[0].get("publicationUsers", [])
            if pub_users:
                return pub_users[0].get("publication", {}).get("name", "Unknown")
    except (IndexError, KeyError, TypeError):
        pass
    return "Unknown"


def save_detailed_json(all_posts, monthly_data, output_path):
    """Save detailed results including individual post metadata to JSON."""
    export = {}
    for query, posts in all_posts.items():
        export[query] = {
            "total_posts": len(posts),
            "monthly_counts": monthly_data[query],
            "posts": [
                {
                    "id": p.get("id"),
                    "title": p.get("title"),
                    "post_date": p.get("post_date"),
                    "canonical_url": p.get("canonical_url"),
                    "publication_name": _extract_pub_name(p),
                    "reaction_count": p.get("reaction_count", 0),
                    "comment_count": p.get("comment_count", 0),
                    "wordcount": p.get("wordcount", 0),
                }
                for p in sorted(posts, key=lambda x: x.get("post_date", ""), reverse=True)
            ],
        }
    path = Path(output_path)
    with path.open("w", encoding="utf-8") as f:
        json.dump(export, f, indent=2, ensure_ascii=False)
    print(f"Detailed JSON saved to: {path.resolve()}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Track mentions of search terms in Substack articles with monthly/daily counts and engagement analysis."
    )
    parser.add_argument(
        "--queries",
        nargs="+",
        default=DEFAULT_QUERIES,
        help='Search terms to track (default: "Claude Code" "AI coding")',
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=MAX_PAGES,
        help=f"Max pages to fetch per query (default: {MAX_PAGES})",
    )
    parser.add_argument(
        "--granularity",
        choices=["monthly", "daily", "all"],
        default="all",
        help="Time granularity for counts: monthly, daily, or all (default: all)",
    )
    parser.add_argument(
        "--engagement",
        action="store_true",
        help="Include engagement analysis (avg reactions per post per day)",
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Directory for output files (default: current directory)",
    )
    parser.add_argument(
        "--no-chart",
        action="store_true",
        help="Skip chart generation",
    )
    parser.add_argument(
        "--no-json",
        action="store_true",
        help="Skip detailed JSON export",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=REQUEST_DELAY,
        help=f"Delay in seconds between API requests (default: {REQUEST_DELAY})",
    )

    args = parser.parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  Substack Mention Tracker")
    print("=" * 60)
    print(f"  Queries:      {args.queries}")
    print(f"  Max pages:    {args.max_pages} per query")
    print(f"  Granularity:  {args.granularity}")
    print(f"  Engagement:   {'yes' if args.engagement else 'no'}")
    print(f"  Delay:        {args.delay}s between requests")
    print(f"  Output dir:   {out_dir.resolve()}")
    print("=" * 60)

    # ---- Fetch data ----
    all_posts: dict[str, list[dict]] = {}
    for query in args.queries:
        print(f'\nFetching results for: "{query}"')
        posts = fetch_all_results(query, max_pages=args.max_pages, delay=args.delay)
        all_posts[query] = posts
        print(f"  => {len(posts)} total posts found")

    # ---- Monthly analysis ----
    if args.granularity in ("monthly", "all"):
        print("\n--- Monthly Analysis ---")
        monthly_data = {q: group_by_month(posts) for q, posts in all_posts.items()}
        monthly_timeline = build_monthly_timeline(monthly_data)

        if monthly_timeline:
            print_monthly_table(monthly_data, monthly_timeline)
            save_monthly_csv(monthly_data, monthly_timeline, out_dir / "substack_monthly_mentions.csv")
            if not args.no_chart:
                save_monthly_chart(monthly_data, monthly_timeline, out_dir / "substack_monthly_chart.png")
        else:
            print("No monthly data found.")

    # ---- Daily analysis ----
    if args.granularity in ("daily", "all"):
        print("\n--- Daily Analysis ---")
        daily_data = {q: group_by_day(posts) for q, posts in all_posts.items()}
        daily_timeline = build_daily_timeline(daily_data)

        if daily_timeline:
            save_daily_csv(daily_data, daily_timeline, out_dir / "substack_daily_mentions.csv")
            if not args.no_chart:
                save_daily_chart(daily_data, daily_timeline, out_dir / "substack_daily_chart.png")
            for q in args.queries:
                total = sum(daily_data[q].values())
                print(f'  "{q}": {total} posts across {len(daily_data[q])} days')
        else:
            print("No daily data found.")

    # ---- Engagement analysis ----
    if args.engagement:
        print("\n--- Engagement Analysis ---")
        engagement_data = {q: compute_daily_engagement(posts) for q, posts in all_posts.items()}
        eng_timeline = build_daily_timeline(engagement_data)

        if eng_timeline:
            save_engagement_csv(engagement_data, eng_timeline, args.queries, out_dir / "substack_engagement.csv")
            if not args.no_chart:
                save_engagement_chart(engagement_data, eng_timeline, out_dir / "substack_engagement_chart.png")
            for q in args.queries:
                eng = engagement_data[q]
                total_reactions = sum(d["total_reactions"] for d in eng.values())
                total_posts = sum(d["post_count"] for d in eng.values())
                overall_avg = total_reactions / total_posts if total_posts > 0 else 0
                print(f'  "{q}": {total_reactions:,} total reactions, {overall_avg:.1f} avg reactions/post')
        else:
            print("No engagement data found.")

    # ---- Detailed JSON ----
    if not args.no_json:
        monthly_data = {q: group_by_month(posts) for q, posts in all_posts.items()}
        save_detailed_json(all_posts, monthly_data, out_dir / "substack_mentions_detailed.json")

    print("\nDone!")


if __name__ == "__main__":
    main()
