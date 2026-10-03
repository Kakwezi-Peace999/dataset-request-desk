"""Container start-up: migrate the database, seed demo data, then serve. One command, nothing to run by hand."""
import uvicorn
from alembic import command
from alembic.config import Config

from .logging_conf import configure_logging
from .seed import run_seed


def main() -> None:
    configure_logging()
    command.upgrade(Config("alembic.ini"), "head")
    run_seed()
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, access_log=False, log_config=None)


if __name__ == "__main__":
    main()
