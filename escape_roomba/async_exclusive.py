import asyncio
import contextlib


class AsyncExclusive:
    """Allows callers to serialize *async* operations (*not* multithreaded
    operations -- this is not thread safe!) based on ID keys, without needing
    a separate lock object for every ID encountered."""

    def __init__(self):
        self._event_loop = asyncio.get_event_loop()
        self._active_futures = {}  # {id: asyncio.Future}

    @contextlib.asynccontextmanager
    async def locker(self, id):
        """Returns an async context manager (for 'async with') that serializes
        code in all with-blocks using the same (hashable) 'id' value."""

        # Operations are serialized via the _active_futures ID-to-Future map.
        # Each operation captures any existing Future, installs a new Future,
        # waits for the previous Future, runs, and sets the new Future.
        last_future = self._active_futures.get(id)
        this_future = self._event_loop.create_future()
        self._active_futures[id] = this_future
        try:
            if last_future is not None:
                await last_future
            yield  # run the code in the with-block
        finally:
            if self._active_futures.get(id) is this_future:
                del self._active_futures[id]  # Nobody used it; OK to del.
            this_future.set_result(True)

    def is_locked(self, id):
        """Returns True if a locker() with-block is active for the given id."""

        return id in self._active_futures
