import os

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

# autocommit=True: every statement here is either a single read or a single
# write, so there is no multi-statement transaction that needs rollback.
pool = ConnectionPool(
    conninfo=os.environ["DATABASE_URL"],
    min_size=1,
    max_size=5,
    kwargs={"row_factory": dict_row, "autocommit": True},
)
