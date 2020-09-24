"""Unit tests for context.Context."""

import logging

import pytest

from escape_roomba.context import Context


@pytest.mark.asyncio
async def test_add_listener(mocker, make_context):
    context = make_context()

    # Register two listeners on one event (should broadcast).
    foo_listeners = [mocker.AsyncMock(), mocker.AsyncMock()]
    context.add_listener('on_foo', foo_listeners[0])
    context.add_listener('on_foo', foo_listeners[1])

    # Register a listener for a different event.
    bar_listener = mocker.AsyncMock()
    context.add_listener('on_bar', bar_listener)

    # No events dispatched yet, nothing should be called.
    foo_listeners[0].assert_not_called()
    foo_listeners[1].assert_not_called()
    bar_listener.assert_not_called()

    # Dispatch events and verify that they are broadcast.
    await context.client.on_foo(123)
    foo_listeners[0].assert_awaited_with(123)
    foo_listeners[1].assert_awaited_with(123)
    bar_listener.assert_not_called()

    await context.client.on_bar('abc', 321)
    bar_listener.assert_awaited_with('abc', 321)


@pytest.mark.asyncio
async def test_add_listener_methods(mocker, make_context):
    context = make_context()

    # Create and register an object with two "listener" methods.
    listeners = mocker.Mock()
    listeners._listen_to_foo = mocker.AsyncMock()
    listeners._listen_to_bar = mocker.AsyncMock()
    context.add_listener_methods(listeners, prefix='_listen_to_')

    # No events dispatched yet, nothing should be called.
    listeners._listen_to_foo.assert_not_called()
    listeners._listen_to_bar.assert_not_called()

    # Dispatch events and verify that they are broadcast.
    await context.client.on_foo(123)
    listeners._listen_to_foo.assert_awaited_with(123)
    listeners._listen_to_bar.assert_not_called()

    await context.client.on_bar('abc', 321)
    listeners._listen_to_bar.assert_awaited_with('abc', 321)
