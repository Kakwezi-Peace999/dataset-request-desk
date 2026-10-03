"""Command line tools.

    python -m app.cli seed                       create demo users (and sample episodes if SEED_EPISODES=1)
    python -m app.cli import-episodes FILE.csv   import a CSV and print the report as JSON
"""
import json
import sys

from .db import SessionLocal
from .logging_conf import configure_logging
from .services.importer import import_csv


def main(argv: list[str]) -> int:
    configure_logging()
    if len(argv) >= 1 and argv[0] == "seed":
        from .seed import run_seed

        run_seed()
        return 0
    if len(argv) == 2 and argv[0] == "import-episodes":
        with open(argv[1], encoding="utf-8-sig", newline="") as fh:
            text = fh.read()
        with SessionLocal() as db:
            print(json.dumps(import_csv(db, text), indent=2))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
