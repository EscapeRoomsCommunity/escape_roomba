"""Unit tests for context.Context."""

import pytest

from escape_roomba.context import Context


@pytest.mark.asyncio
async def test_add_listener(discord_mock):
    # Register two listeners on one event (should broadcast).
    foo_listeners = [discord_mock.pytest_mocker.AsyncMock() for i in range(2)]
    discord_mock.context.add_listener('on_foo', foo_listeners[0])
    discord_mock.context.add_listener('on_foo', foo_listeners[1])

    # Register a listener for a different event.
    bar_listener = discord_mock.pytest_mocker.AsyncMock()
    discord_mock.context.add_listener('on_bar', bar_listener)

    # No events dispatched yet, nothing should be called.
    foo_listeners[0].assert_not_called()
    foo_listeners[1].assert_not_called()
    bar_listener.assert_not_called()

    # Dispatch events and verify that they are broadcast.
    await discord_mock.context.client.on_foo(123)
    foo_listeners[0].assert_awaited_with(123)
    foo_listeners[1].assert_awaited_with(123)
    bar_listener.assert_not_called()

    await discord_mock.context.client.on_bar('abc', 321)
    bar_listener.assert_awaited_with('abc', 321)


@pytest.mark.asyncio
async def test_add_listener_methods(discord_mock):
    # Create and register an object with two "listener" methods.
    listeners = discord_mock.pytest_mocker.Mock()
    listeners._listen_foo = discord_mock.pytest_mocker.AsyncMock()
    listeners._listen_bar = discord_mock.pytest_mocker.AsyncMock()
    discord_mock.context.add_listener_methods(listeners, prefix='_listen_')

    # No events dispatched yet, nothing should be called.
    listeners._listen_foo.assert_not_called()
    listeners._listen_bar.assert_not_called()

    # Dispatch events and verify that they are broadcast.
    await discord_mock.context.client.on_foo(123)
    listeners._listen_foo.assert_awaited_with(123)
    listeners._listen_bar.assert_not_called()

    await discord_mock.context.client.on_bar('abc', 321)
    listeners._listen_bar.assert_awaited_with('abc', 321)
