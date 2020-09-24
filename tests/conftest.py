"""Shared configuration for unit tests:
docs.pytest.org/en/stable/fixture.html#conftest-py-sharing-fixture-functions.
"""

import logging

import discord
import discord.abc
import pytest

from escape_roomba.context import Context

#
# Mock generators as pytest *factory fixtures*:
# https://docs.pytest.org/en/stable/fixture.html#factories-as-fixtures
# These are used by referencing the name in a test function parameters:
#
# def test_some_stuff(make_context):
#     my_context = make_context()
#


@pytest.fixture(scope='session')
def make_discord_id():
    """Factory fixture to generate unique Discord/snowflake-style ID ints."""

    last_id = 0x9305ac7cb9a2038  # 2020-01-01 at midnight.

    def _factory():
        nonlocal last_id
        last_id += (1000 << 22)  # Advance one second.
        return last_id

    return _factory


@pytest.fixture
def make_context(
        mocker, event_loop,
        make_discord_guild, make_discord_member, make_discord_text_channel):
    """Factory fixture to generate escape_roomba.Context-like Mock objects,
    including a discord.Client-like Mock."""

    def _factory(guild_count=0, member_count=0, channel_count=0):
        context = Context()
        context.logger = logging.getLogger('test')  # TODO: Mock if needed.
        context.client = mocker.Mock(spec=discord.Client)
        context.client.guilds = []
        for gi in range(guild_count):
            guild = make_discord_guild(name=f'Mock Guild {gi}')
            guild.members = [
                make_discord_member(guild, name=f'Mock Member {mi}',
                                    discriminator=1000 + mi)
                for mi in range(member_count)]
            guild.channels = [
                make_discord_text_channel(guild, name=f'mock-channel-{ci}')
                for ci in range(channel_count)]
            context.client.guilds.append(guild)

        gs = context.client.guilds
        context.client.get_guild.side_effect = lambda id: next(
            (g for g in gs if g.id == id), None)
        context.client.get_channel.side_effect = lambda id: next(
            (c for g in gs for c in g.channels if c.id == id), None)
        context.client.get_user.side_effect = lambda id: next(
            (m for g in gs for m in g.members if m.id == id), None)
        return context

    return _factory


@pytest.fixture
def make_discord_guild(mocker, make_discord_id):
    """Factory fixture to generate discord.Guild-like Mock objects."""

    def _factory(name='Mock Guild'):
        guild = mocker.MagicMock(spec=discord.Guild)
        guild.id = make_discord_id()
        guild.name = name
        guild.channels = []
        guild.members = []
        return guild

    return _factory


@pytest.fixture
def make_discord_member(mocker, make_discord_id):
    """Factory fixture to generate discord.Member-like Mock objects."""

    def _factory(guild, name='Mock Member', discriminator='1234'):
        member = mocker.Mock(spec=discord.Member)
        member.id = make_discord_id()
        member.guild = guild
        member.name = name
        member.discriminator = discriminator
        return member

    return _factory


@pytest.fixture
def make_discord_text_channel(mocker, make_discord_id):
    """Factory fixture to generate discord.TextChannel-like Mock objects."""

    def _factory(guild, name='mock-channel'):
        channel = mocker.Mock(spec=discord.TextChannel)
        channel.id = make_discord_id()
        channel.guild = guild
        channel.type = discord.ChannelType.text
        channel.name = name
        channel.topic = f'topic for {name}'
        return channel

    return _factory


@pytest.fixture
def make_discord_message(mocker, make_discord_id):
    """Factory fixture to generate discord.Message-like Mock objects."""

    def _factory(guild, channel, author, content='Mock message content'):
        message = mocker.Mock(spec=discord.Message)
        message.id = make_discord_id()
        message.guild = guild
        message.channel = channel
        message.author = author
        message.content = content
        return message

    return _factory
