import asyncio
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

T = TypeVar("T")


def run_sync(coro: Coroutine[None, None, T]) -> T:
    """Runs an asynchronous coroutine synchronously, handling already running event loops cleanly."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Running inside an active loop (e.g. pytest-asyncio). Run in a separate thread.
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()
    else:
        # Standard execution thread. Safe to call asyncio.run
        return asyncio.run(coro)
