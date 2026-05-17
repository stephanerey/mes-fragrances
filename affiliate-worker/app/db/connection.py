from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg import Connection


@contextmanager
def open_connection(database_url: str) -> Iterator[Connection]:
    """Open a PostgreSQL connection using psycopg.

    The caller owns transaction boundaries.
    """

    with psycopg.connect(database_url) as connection:
        yield connection
