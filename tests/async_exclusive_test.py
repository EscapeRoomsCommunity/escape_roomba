"""Unit tests for async_exclusive.AsyncExclusive."""

import asyncio
import pytest

from escape_roomba.async_exclusive import AsyncExclusive


@pytest.mark.asyncio
async def test_exclusive_running(event_loop):
    exclusive = AsyncExclusive()
    exclusive_check = {}

    async def use_exclusive(id, exception=None):
        async with exclusive.locker(id):
            assert id not in exclusive_check
            exclusive_check[id] = True
            await asyncio.sleep(0.1)  # Allow time for conflict to happen.
            del exclusive_check[id]
            if exception is not None:
                raise exception
            else:
                return id

    exception = ValueError()
    results = await asyncio.gather(
        use_exclusive(0), use_exclusive(1, exception=exception),
        use_exclusive(0, exception=exception), use_exclusive(1),
        return_exceptions=True)
    assert results == [0, exception, exception, 1]
    assert len(exclusive._active_futures) == 0  # All map items removed.
