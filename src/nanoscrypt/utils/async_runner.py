import asyncio
import sys
import warnings
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

T = TypeVar("T")


def run_sync(coro: Coroutine[None, None, T]) -> T:
    """Runs an asynchronous coroutine synchronously, handling already running event loops cleanly."""
    # Ignore ProactorBasePipeTransport and unawaited LiteLLM coroutine warnings on exit
    warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*was never awaited.*")
    if sys.platform == "win32":
        def silence_unraisable(unraisable):
            if unraisable.exc_type is RuntimeError and "Event loop is closed" in str(unraisable.exc_value):
                return
            sys.__unraisablehook__(unraisable)
        sys.unraisablehook = silence_unraisable

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
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            try:
                # Cancel pending tasks
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.run_until_complete(loop.shutdown_asyncgens())
                if hasattr(loop, "shutdown_default_executor"):
                    loop.run_until_complete(loop.shutdown_default_executor())
            except Exception:
                pass
            finally:
                loop.close()
