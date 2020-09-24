"""Unit tests for thread_manager.ThreadManager."""

import logging

import discord
import discord.abc
import pytest

from escape_roomba.context import Context
from escape_roomba.thread_manager import ThreadManager


@pytest.mark.asyncio
async def test_thread_creation(discord_mock):
    # Create the ThreadManager and register its listeners.
    ThreadManager(discord_mock.context)

    discord_mock.queue_event('on_ready')
    await discord_mock.async_dispatch_events()

    message = discord_mock.context.client.guilds[0].channels[0].test_history[0]
    discord_mock.sim_reaction(
        message=message, unicode='🧵',
        user=discord_mock.context.client.guilds[0].members[0], delta=+1)
    await discord_mock.async_dispatch_events()

    # Make sure the thread channel was added.
    assert '🧵' == discord_mock.context.client.guilds[0].channels[-1].name[0]


# TODO: Add more tests of more functionality.
