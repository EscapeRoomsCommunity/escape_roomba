"""Shared configuration for unit tests:
docs.pytest.org/en/stable/fixture.html#conftest-py-sharing-fixture-functions.
"""

import logging

import discord
import discord.abc
import pytest

from escape_roomba.context import Context

#
# Mock generators as pytest *factory fixtures*
# (see docs.pytest.org/en/stable/fixture.html#factories-as-fixtures).
# These are used by referencing the name in a test function parameters:
#
# def test_some_stuff(make_context):
#     my_context = make_context()
#


@pytest.fixture(scope='session')
def make_discord_id():
    """Factory fixture to generate unique Discord/snowflake-style ID ints."""

    last_id = 0x92ee70e00000000  # 2020-01-01 at midnight.

    def factory():
        nonlocal last_id
        last_id += (1000 << 22)  # Advance one second.
        return last_id

    return factory


@pytest.fixture
def make_context(mocker, event_loop,
                 make_discord_guild, make_discord_member,
                 make_discord_text_channel, make_discord_message):
    """Factory fixture to generate escape_roomba.Context-like Mock objects,
    including a discord.Client-like Mock."""

    def factory(guild_count=0, member_count=0, channel_count=0,
                message_count=0):
        context = Context()
        context.logger = logging.getLogger('test')  # TODO: Mock if needed.
        context.client = mocker.Mock(spec=discord.Client)
        context.client.guilds = []
        for gi in range(guild_count):
            g = make_discord_guild(name=f'Mock Guild {gi}')
            context.client.guilds.append(g)

            for mi in range(member_count):
                g.members.append(make_discord_member(
                    g, name=f'Mock Member {mi}', discriminator=1000 + mi))
            for ci in range(channel_count):
                c = make_discord_text_channel(g, name=f'mock-channel-{ci}')
                g.channels.append(c)
                for mi in range(message_count):
                    assert member_count > 0  # need members
                    c.test_history.append(make_discord_message(
                        g, c, g.members[mi % member_count],
                        f'Mock message {mi} in #mock-channel-{ci}'))

        gs = context.client.guilds
        context.client.get_guild.side_effect = lambda id: next(
            (g for g in gs if g.id == id), None)
        context.client.get_channel.side_effect = lambda id: next(
            (c for g in gs for c in g.channels if c.id == id), None)
        context.client.get_user.side_effect = lambda id: next(
            (m for g in gs for m in g.members if m.id == id), None)
        return context

    return factory


@pytest.fixture
def make_discord_guild(mocker, make_discord_id):
    """Factory fixture to generate discord.Guild-like Mock objects."""

    def factory(name='Mock Guild'):
        guild = mocker.Mock(spec=discord.Guild)
        guild.id = make_discord_id()
        guild.name = name
        guild.channels = []
        guild.members = []
        return guild

    return factory


@pytest.fixture
def make_discord_member(mocker, make_discord_id):
    """Factory fixture to generate discord.Member-like Mock objects."""

    def factory(guild, name='Mock Member', discriminator='1234'):
        member = mocker.Mock(spec=discord.Member)
        member.id = make_discord_id()
        member.guild = guild
        member.name = name
        member.discriminator = discriminator
        return member

    return factory


@pytest.fixture
def make_discord_text_channel(mocker, make_discord_id):
    """Factory fixture to generate discord.TextChannel-like Mock objects."""

    def factory(guild, name='mock-channel'):
        channel = mocker.Mock(spec=discord.TextChannel)
        channel.id = make_discord_id()
        channel.guild = guild
        channel.type = discord.ChannelType.text
        channel.name = name
        channel.topic = f'topic for {name}'
        channel.test_history = []

        async def get_history(limit=100, oldest_first=None):
            limit = len(channel.test_history) if limit is None else limit
            history = channel.test_history
            slice = history[:limit] if oldest_first else history[:-limit:-1]
            for m in slice:
                yield m

        channel.history.side_effect = get_history
        return channel

    return factory


@pytest.fixture
def make_discord_message(mocker, make_discord_id):
    """Factory fixture to generate discord.Message-like Mock objects."""

    def factory(guild, channel, author, content='Mock message content'):
        message = mocker.Mock(spec=discord.Message)
        message.id = make_discord_id()
        message.guild = guild
        message.channel = channel
        message.author = author
        message.content = content
        message.reactions = []
        return message

    return factory
