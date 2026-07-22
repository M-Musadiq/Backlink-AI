"""Discovery CLI - run URL discovery from command line."""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, ".")

import argparse
import logging
from src.infrastructure.database import SessionLocal
from src.infrastructure.discovery.discovery_node import DiscoveryNode
from src.infrastructure.platform_config import PlatformConfigService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def main():
    parser = argparse.ArgumentParser(description="Discovery Node - find new URLs to track")
    parser.add_argument(
        "--keywords", "-k",
        nargs="+",
        required=True,
        help="Search keywords (e.g., 'backlink seo forum')",
    )
    parser.add_argument(
        "--platforms", "-p",
        nargs="*",
        default=None,
        help="Platform site filters for SERP (default: from platform_configs.json)",
    )
    parser.add_argument(
        "--num-per-platform", "-n",
        type=int,
        default=10,
        help="Results per platform",
    )
    parser.add_argument(
        "--rss-feeds", "-r",
        nargs="*",
        default=[],
        help="Direct RSS feed URLs to parse",
    )

    args = parser.parse_args()

    if args.platforms is None:
        args.platforms = PlatformConfigService().get_search_platforms()

    print("=" * 60)
    print("DISCOVERY NODE")
    print("=" * 60)
    print(f"Keywords: {args.keywords}")
    print(f"Platforms: {args.platforms}")
    print(f"RSS feeds: {args.rss_feeds or 'none'}")
    print()

    session = SessionLocal()
    try:
        node = DiscoveryNode(session)

        stats = node.discover(
            keywords=args.keywords,
            platforms=args.platforms,
            num_per_platform=args.num_per_platform,
            rss_feeds=args.rss_feeds,
        )

        print()
        print("=" * 60)
        print("DISCOVERY RESULTS")
        print("=" * 60)
        print(f"Total found:      {stats['total_found']}")
        print(f"After dedup:      {stats['after_internal_dedup']}")
        print(f"New URLs added:   {stats['new_count']}")
        print(f"Skipped (dupes):  {stats['skipped_count']}")
        print(f"Errors:           {stats['errors']}")
        print("=" * 60)

        if stats['new_count'] > 0:
            print(f"\n{stats['new_count']} new URLs added to tracked_urls table.")
        else:
            print("\nNo new URLs found (all were duplicates or errors).")

    finally:
        session.close()


if __name__ == "__main__":
    main()
