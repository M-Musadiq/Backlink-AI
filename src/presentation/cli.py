import argparse
import sys
import logging

from src.domain.entities import Topic
from src.domain.interfaces import ArticleRepository, ContentGenerator, LLMService
from src.infrastructure.devto_repository import DevtoArticleRepository
from src.infrastructure.wordpress_repository import WordPressArticleRepository
from src.infrastructure.gemini_service import GeminiLLMService
from src.infrastructure.openrouter_service import OpenRouterLLMService
from src.infrastructure.content_generators import LLMContentGenerator
from src.application.use_cases import GenerateAndPublishUseCase
from src.application.content_strategy import ContentStrategyFactory
from src.infrastructure.platform_config_store import JsonPlatformConfigStore
from src.infrastructure.scrapers.scrape_orchestrator import ScrapeOrchestrator

logger = logging.getLogger(__name__)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="AI Content Automation — research, generate, and publish articles"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    generate_parser = subparsers.add_parser("generate", help="Generate and publish an article")
    generate_parser.add_argument("topic", type=str, help="Article topic")
    generate_parser.add_argument("--platform", type=str, default="devto", choices=["devto", "wordpress"], help="Target platform")
    generate_parser.add_argument("--description", type=str, default="", help="Topic description")
    generate_parser.add_argument("--keywords", type=str, nargs="+", default=[], help="Keywords/tags")
    generate_parser.add_argument(
        "--strategy", type=str, default="tutorial",
        choices=ContentStrategyFactory.available_strategies(),
        help="Content generation strategy"
    )
    generate_parser.add_argument("--publish", action="store_true", help="Publish immediately")
    generate_parser.add_argument("--dry-run", action="store_true", help="Generate but don't publish")
    generate_parser.add_argument("--review", action="store_true", help="Review and refine before publishing")

    list_parser = subparsers.add_parser("list", help="List your existing articles")
    list_parser.add_argument("--platform", type=str, default="devto", choices=["devto", "wordpress"], help="Target platform")
    list_parser.add_argument("--show-body", action="store_true", help="Include article body in output")

    scrape_parser = subparsers.add_parser("scrape", help="Scrape a URL with auto-detection/escalation")
    scrape_parser.add_argument("url", type=str, help="URL to scrape")
    scrape_parser.add_argument("--type", type=str, choices=["api", "static", "playwright", "llm"], help="Force specific scraper type")
    scrape_parser.add_argument("--verbose", action="store_true", help="Show full content and metadata details")

    subparsers.add_parser("help", help="Show all commands with examples")

    return parser


def run_cli(args: argparse.Namespace) -> None:
    from src import config

    if args.command == "help":
        _handle_help()
        return

    if config.GEMINI_API_KEY:
        llm: LLMService = GeminiLLMService(api_key=config.GEMINI_API_KEY)
        logger.info("Using Gemini API (gemini-flash-latest)")
    elif config.OPENROUTER_API_KEY:
        llm: LLMService = OpenRouterLLMService(
            api_key=config.OPENROUTER_API_KEY,
            model=config.OPENROUTER_MODEL,
        )
        logger.info(f"Using OpenRouter ({config.OPENROUTER_MODEL})")
    else:
        logger.error("No LLM configured. Set GEMINI_API_KEY or OPENROUTER_API_KEY in .env")
        sys.exit(1)

    platform = getattr(args, "platform", "devto")

    if platform == "wordpress":
        if not config.WP_ACCESS_TOKEN or not config.WP_SITE_ID:
            logger.error("WP_ACCESS_TOKEN and WP_SITE_ID must be set in .env")
            sys.exit(1)
        repo: ArticleRepository = WordPressArticleRepository(
            access_token=config.WP_ACCESS_TOKEN,
            site_id=config.WP_SITE_ID,
        )
        logger.info(f"Using WordPress ({config.WP_SITE_URL})")
    else:
        if not config.DEVTO_API_KEY:
            logger.error("DEVTO_API_KEY is not set in .env")
            sys.exit(1)
        repo = DevtoArticleRepository(api_key=config.DEVTO_API_KEY)
        logger.info("Using Dev.to")

    if args.command == "list":
        _handle_list(repo, args)
    elif args.command == "generate":
        _handle_generate(llm, repo, args, platform)
    elif args.command == "scrape":
        _handle_scrape(llm, args)
    else:
        logger.error("Unknown command. Use 'generate', 'list', 'scrape', or 'help'.")
        sys.exit(1)


def _handle_list(repo: ArticleRepository, args: argparse.Namespace) -> None:
    articles = repo.get_my_articles()
    if not articles:
        print("No articles found.")
        return

    print(f"\nFound {len(articles)} article(s):\n")
    for article in articles:
        status = "PUBLISHED" if article.published else "DRAFT"
        print(f"  [{status}] #{article.id} — {article.title}")
        if article.url:
            print(f"         {article.url}")
        if args.show_body and article.body_markdown:
            preview = article.body_markdown[:200].replace("\n", " ")
            print(f"         Body: {preview}...")
        print()


def _preview_article(article) -> None:
    print("\n" + "=" * 60)
    print("ARTICLE PREVIEW")
    print("=" * 60)
    print(f"Title:       {article.title}")
    print(f"Tags:        {', '.join(article.tags)}")
    print(f"Description: {article.description}")
    print("-" * 60)
    print(article.body_markdown)
    print("=" * 60)


def _handle_help() -> None:
    print("""
AI Content Automation — Commands
================================

LIST ARTICLES
  python -m src.main list
  python -m src.main list --platform wordpress
  python -m src.main list --show-body

GENERATE ARTICLE (saved as draft)
  python -m src.main generate "Your Topic"
  python -m src.main generate "Your Topic" --platform wordpress
  python -m src.main generate "Your Topic" --keywords tag1 tag2 tag3

GENERATE WITH REVIEW (grammar fix on opening)
  python -m src.main generate "Your Topic" --review

GENERATE WITH STRATEGY
  python -m src.main generate "Your Topic" --strategy tutorial
  python -m src.main generate "Your Topic" --strategy opinion
  python -m src.main generate "Your Topic" --strategy howto

PUBLISH (asks for confirmation y/N)
  python -m src.main generate "Your Topic" --publish

PUBLISH WITH REVIEW
  python -m src.main generate "Your Topic" --review --publish

DRY RUN (preview only, nothing saved)
  python -m src.main generate "Your Topic" --dry-run

FLAGS
  --platform PLATFORM   devto | wordpress (default: devto)
  --keywords tag1 tag2  Tags for the article
  --strategy TYPE       tutorial | opinion | howto
  --review              Fix grammar on first paragraph
  --publish             Ask to publish live
  --dry-run             Preview only, nothing saved

SCRAPE URL (auto-detects and extracts content)
  python -m src.main scrape "https://dev.to/some-article"
  python -m src.main scrape "https://reddit.com/r/.../comments/..."
  python -m src.main scrape "https://example.com/blog" --type static
  python -m src.main scrape "https://example.com/dynamic-spa" --type playwright --verbose

HELP
  python -m src.main help
""")


def _confirm_publish(platform: str) -> bool:
    site = "dev.to" if platform == "devto" else "WordPress"
    answer = input(f"\nPublish this article to {site}? (y/N): ").strip().lower()
    return answer == "y"


def _handle_generate(llm: LLMService, repo: ArticleRepository, args: argparse.Namespace, platform: str) -> None:
    generator: ContentGenerator = LLMContentGenerator(
        llm_service=llm,
        strategy_type=args.strategy,
        backlink_enabled=True,
    )

    use_case = GenerateAndPublishUseCase(
        content_generator=generator,
        article_repository=repo,
    )

    topic = Topic(
        name=args.topic,
        description=args.description,
        keywords=args.keywords if args.keywords else [args.topic.lower().replace(" ", "-")],
    )

    if args.review:
        logger.info("Using generate + review pipeline...")
        article = use_case.generate_and_review(
            topic=topic,
            publish=False,
        )
    else:
        article = use_case.execute(
            topic=topic,
            publish=False,
            dry_run=True,
        )

    _preview_article(article)

    if args.dry_run:
        print("\nDry run — article was not saved.")
        return

    if args.publish:
        if _confirm_publish(platform):
            article.published = True
            created = repo.create(article)
            print(f"\nPublished: {created.url}")
        else:
            article.published = False
            created = repo.create(article)
            print(f"\nSaved as draft: {created.url}")
    else:
        article.published = False
        created = repo.create(article)
        print(f"\nSaved as draft: {created.url}")


def _handle_scrape(llm: LLMService, args: argparse.Namespace) -> None:
    config_store = JsonPlatformConfigStore()
    orchestrator = ScrapeOrchestrator(
        config_store=config_store,
        llm_service=llm,
    )

    try:
        scraped = orchestrator.scrape(args.url, force_type=args.type)
        print("\n" + "=" * 60)
        print("SCRAPED CONTENT DETAILS")
        print("=" * 60)
        print(f"URL:          {scraped.url}")
        print(f"Domain:       {scraped.domain}")
        print(f"Scraper Used: {scraped.scraper_type.upper()}")
        print(f"Title:        {scraped.title or '[No Title]'}")
        print(f"Author:       {scraped.author or '[Unknown]'}")
        print(f"Published At: {scraped.published_at or '[Unknown]'}")
        print("-" * 60)
        
        if args.verbose:
            print("METADATA:")
            for k, v in scraped.metadata.items():
                print(f"  {k}: {v}")
            print("-" * 60)
            print("BODY:")
            print(scraped.body)
        else:
            print("BODY PREVIEW:")
            print(scraped.preview)
            print(f"\n[Run with --verbose to view all {len(scraped.body)} characters of content]")
        
        print("=" * 60)

    except Exception as e:
        logger.error(f"Scrape failed: {e}")
        sys.exit(1)
    finally:
        orchestrator.close()
