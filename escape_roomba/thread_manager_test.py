"""Unit tests for thread_manager.ThreadManager."""

import logging

import discord
import discord.abc
import pytest

from escape_roomba.context import Context
from escape_roomba.thread_manager import ThreadManager


@pytest.mark.asyncio
async def test_thread_creation(mocker, make_context):
    # Create a Context with a discord.Client-like Mock.
    context = make_context(guild_count=2, channel_count=2, member_count=2)

    # Create the ThreadManager and register its listeners.
    ThreadManager(context)

    # TODO: Finish this!
    # await context.client.on_ready()
