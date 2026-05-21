from __future__ import annotations

import logging


def configure_logging(log_level: str) -> None:
    level_name = log_level.upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
