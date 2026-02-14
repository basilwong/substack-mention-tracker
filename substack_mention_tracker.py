#!/usr/bin/env python3
"""
Substack Mention Tracker
========================
Tracks the number of times specific search terms (e.g., "Claude Code", "AI coding")
are mentioned in Substack articles, grouped by month.

Uses Substack's undocumented search API:
    GET https://substack.com/api/v1/post/search

Usage:
    python3 substack_mention_tracker.py
    python3 substack_mention_tracker.py --queries "Claude Code" "AI coding" "vibe coding"
    python3 substack_mention_tracker.py --output results.csv --chart chart.png
"""

import argparse
import csv
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://substack.com/api/v1/post/search"
RESULTS_PER_PAGE = 20
MAX_PAGES = 100  # Substack caps at ~100 pages (2,000 results per query)
REQUEST_DELAY = 2.0  # seconds between API calls to be respectful
MAX_RETRIES = 5  # max retries on rate-limit (429) errors
INITIAL_BACKOFF = 10.0  # initial backoff in seconds after a 429

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
# Core Functions
# ---------------------------------------------------------------------------


def fetch_search_page(query: str, page: int = 0, max_retries: int = MAX_RETRIES) -> dict:
    """
    Fetch a single page of search results from Substack's API.
    Includes exponential backoff retry logic for HTTP 429 (rate limit) errors.

    Parameters
    ----------
    query : str
        The search term (e.g., "Claude Code").
    page : int
        Zero-indexed page number.
    max_retries : int
        Maximum number of retries on 429 errors.

    Returns
    -------
    dict
        Parsed JSON response with keys: results, more, etc.
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

        if resp.status_code == 429:
            if attempt < max_retries:
                # Check for Retry-After header
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        wait_time = float(retry_after)
                    except ValueError:
                        wait_time = backoff
                else:
                    wait_time = backoff

                print(
                    f"    Rate limited (429) on page {page}. "
                    f"Waiting {wait_time:.0f}s before retry "
                    f"({attempt + 1}/{max_retries})..."
                )
                time.sleep(wait_time)
                backoff *= 2  # exponential backoff
                continue
            else:
                print(
                    f"    Rate limited (429) on page {page}. "
                    f"Max retries ({max_retries}) exhausted. Stopping pagination."
                )
                resp.raise_for_status()

        resp.raise_for_status()
        return resp.json()


def fetch_all_results(query: str, max_pages: int = MAX_PAGES, delay: float = REQUEST_DELAY) -> list[dict]:
    """
    Paginate through all available search results for a given query.
    Automatically handles rate limiting with exponential backoff.

    Each result dict contains at minimum:
        - id (int): Post ID
        - title (str): Post title
        - post_date (str): ISO-8601 publication date
        - publication_id (int): Newsletter ID
        - canonical_url (str): Full URL to the post

    Parameters
    ----------
    query : str
        The search term.
    max_pages : int
        Safety cap on the number of pages to fetch.
    delay : float
        Base delay in seconds between requests.

    Returns
    -------
    list[dict]
        Deduplicated list of post result dicts.
    """
    all_results = []
    seen_ids = set()

    for page in range(max_pages):
        try:
            data = fetch_search_page(query, page)
        except requests.exceptions.HTTPError as exc:
            # Substack returns 400/422 for pages beyond the limit
            if exc.response is not None and exc.response.status_code in (400, 422):
                print(f"    Reached page limit at page {page}.")
                break
            # If we exhausted retries on a 429, stop gracefully
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
            f"(total unique so far: {len(all_results)})"
        )

        if not has_more:
            break

        time.sleep(delay)

    return all_results


def group_by_month(posts: list[dict]) -> dict[str, int]:
    """
    Group posts by year-month and return counts.

    Parameters
    ----------
    posts : list[dict]
        List of post dicts, each with a ``post_date`` field.

    Returns
    -------
    dict[str, int]
        Mapping from "YYYY-MM" to the number of posts in that month,
        sorted chronologically.
    """
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


def build_full_timeline(monthly_data: dict[str, dict[str, int]]) -> list[str]:
    """
    Build a sorted list of all year-month keys across all queries,
    filling in zeros for months with no mentions.

    Parameters
    ----------
    monthly_data : dict[str, dict[str, int]]
        Mapping from query -> {month -> count}.

    Returns
    -------
    list[str]
        Sorted list of "YYYY-MM" strings covering the full range.
    """
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
        # Advance by one month
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    return timeline


def print_table(monthly_data: dict[str, dict[str, int]], timeline: list[str]) -> None:
    """
    Print a formatted ASCII table of monthly mention counts.
    """
    queries = list(monthly_data.keys())
    col_widths = [10] + [max(len(q), 6) for q in queries]

    # Header
    header = f"{'Month':<{col_widths[0]}}"
    for i, q in enumerate(queries):
        header += f"  {q:>{col_widths[i+1]}}"
    print("\n" + header)
    print("-" * len(header))

    # Rows
    for month in timeline:
        row = f"{month:<{col_widths[0]}}"
        for i, q in enumerate(queries):
            count = monthly_data[q].get(month, 0)
            row += f"  {count:>{col_widths[i+1]}}"
        print(row)

    # Totals
    print("-" * len(header))
    totals_row = f"{'TOTAL':<{col_widths[0]}}"
    for i, q in enumerate(queries):
        total = sum(monthly_data[q].values())
        totals_row += f"  {total:>{col_widths[i+1]}}"
    print(totals_row)
    print()


def save_csv(
    monthly_data: dict[str, dict[str, int]],
    timeline: list[str],
    output_path: str,
) -> None:
    """
    Save monthly mention counts to a CSV file.
    """
    queries = list(monthly_data.keys())
    path = Path(output_path)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Month"] + queries)
        for month in timeline:
            row = [month] + [monthly_data[q].get(month, 0) for q in queries]
            writer.writerow(row)
        # Totals row
        writer.writerow(
            ["TOTAL"] + [sum(monthly_data[q].values()) for q in queries]
        )

    print(f"CSV saved to: {path.resolve()}")


def save_chart(
    monthly_data: dict[str, dict[str, int]],
    timeline: list[str],
    output_path: str,
) -> None:
    """
    Generate and save a line chart of monthly mention counts.
    Requires matplotlib.
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.ticker as ticker
    except ImportError:
        print("matplotlib not installed — skipping chart generation.")
        print("Install with: pip install matplotlib")
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

    # Rotate x-axis labels for readability
    step = max(1, len(timeline) // 20)
    ax.set_xticks(range(0, len(timeline), step))
    ax.set_xticklabels([timeline[i] for i in range(0, len(timeline), step)], rotation=45, ha="right")

    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()
    print(f"Chart saved to: {Path(output_path).resolve()}")


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


def save_detailed_json(
    all_posts: dict[str, list[dict]],
    monthly_data: dict[str, dict[str, int]],
    output_path: str,
) -> None:
    """
    Save detailed results including individual post metadata to JSON.
    """
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
        description="Track monthly mentions of search terms in Substack articles."
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
        "--output",
        default="substack_mentions.csv",
        help="Output CSV file path (default: substack_mentions.csv)",
    )
    parser.add_argument(
        "--chart",
        default="substack_mentions_chart.png",
        help="Output chart image path (default: substack_mentions_chart.png)",
    )
    parser.add_argument(
        "--json",
        default="substack_mentions_detailed.json",
        help="Output detailed JSON path (default: substack_mentions_detailed.json)",
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

    print("=" * 60)
    print("  Substack Mention Tracker")
    print("=" * 60)
    print(f"  Queries:    {args.queries}")
    print(f"  Max pages:  {args.max_pages} per query")
    print(f"  Delay:      {args.delay}s between requests")
    print("=" * 60)

    all_posts: dict[str, list[dict]] = {}
    monthly_data: dict[str, dict[str, int]] = {}

    for query in args.queries:
        print(f"\nFetching results for: \"{query}\"")
        posts = fetch_all_results(query, max_pages=args.max_pages, delay=args.delay)
        all_posts[query] = posts
        monthly_data[query] = group_by_month(posts)
        print(f"  => {len(posts)} total posts found")

    # Build a unified timeline
    timeline = build_full_timeline(monthly_data)

    if not timeline:
        print("\nNo results found for any query.")
        sys.exit(0)

    # Display table
    print_table(monthly_data, timeline)

    # Save CSV
    save_csv(monthly_data, timeline, args.output)

    # Save chart
    if not args.no_chart:
        save_chart(monthly_data, timeline, args.chart)

    # Save detailed JSON
    if not args.no_json:
        save_detailed_json(all_posts, monthly_data, args.json)

    print("\nDone!")


if __name__ == "__main__":
    main()
