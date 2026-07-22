import sys
import logging
from src import config
from src.presentation.cli import create_parser, run_cli

logger = logging.getLogger(__name__)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        
    parser = create_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if not config.check_configuration():
        logger.error("Configuration checks failed. Verify your .env file.")
        sys.exit(1)

    run_cli(args)


if __name__ == "__main__":
    main()
