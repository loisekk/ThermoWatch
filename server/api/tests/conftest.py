"""Pytest bootstrap — MUST run before any ``app.*`` import.

The suite exercises the API under several event loops: pytest-asyncio gives
each async test its own loop, and starlette's TestClient runs the lifespan in
an anyio portal loop. asyncpg connections are bound to the loop that created
them, so a *pooled* connection from a finished loop fails with
``RuntimeError: Event loop is closed`` on the next checkout. NullPool
sidesteps this entirely: each checkout creates a fresh connection in the
current loop and closes it on release.
"""
import os

os.environ["TW_DB_NULL_POOL"] = "1"