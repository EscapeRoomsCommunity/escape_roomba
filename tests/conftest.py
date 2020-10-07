"""Shared configuration for unit tests:
docs.pytest.org/en/stable/fixture.html#conftest-py-sharing-fixture-functions.
"""

import argparse
import collections
import logging

import discord
import discord.abc
import pytest

import escape_roomba.context


class DiscordMockFixture:
    """Class to generate Mocks for Discord client library objects.
    Tests can get an instance via the 'discord_mock' fixture (defined below).

    Attributes:
        pytest_mocker - The mocker fixture from pytest-mock
        context - A default Context-like object, with a Client-like object.
    """

    # Keep generated IDs globally unique (see unique_id() below).
    last_id = 0x92ee70e00000000  # 2020-01-01 at midnight.

    def __init__(self, pytest_mocker):
        self.pytest_mocker = pytest_mocker

        parser = argparse.ArgumentParser(parents=[escape_roomba.context.args])
        self.context = escape_roomba.context.Context(
            parsed_args=parser.parse_args([]),
            inject_client=self.make_client())
        self.event_queue = []
        self.reset_data()  # Default setup.

    @classmethod
    def unique_id(cls):
        """Returns a unique Discord/snowflake-style ID int."""

        cls.last_id += (1000 << 22)  # Advance one second.
        return cls.last_id

    #
    # Mock object creation
    #

    def make_client(self):
        """Returns a new Client-like Mock object."""

        client = self.pytest_mocker.Mock(spec=discord.Client, name='client')
        client.guilds = []
        client.user = self.make_user(name='Client User')
        client.get_guild.side_effect = lambda id: next(
            (g for g in client.guilds if g.id == id), None)
        client.get_channel.side_effect = lambda id: next(
            (c for g in client.guilds for c in g.channels if c.id == id), None)
        client.get_user.side_effect = lambda id: next(
            (m for g in client.guilds for m in g.members if m.id == id), None)
        return client

    def make_guild(self, client, name='Mock Guild'):
        """Returns a new Guild-like Mock."""

        guild = self.pytest_mocker.Mock(spec=discord.Guild, name='guild')
        guild.id = self.unique_id()
        guild.name = name
        guild.channels = []
        guild.members = []
        guild.test_client = client

        async def create_text_channel(*args, **kwargs):
            return self.sim_create_channel(*args, guild=guild, **kwargs)

        guild.create_text_channel.side_effect = create_text_channel
        guild.get_channel = client.get_channel
        return guild

    def make_user(self, guild=None, name=None, discriminator='9999'):
        """Returns a new User-like (or Member-like if guild is set) Mock."""

        user = self.pytest_mocker.Mock(
            spec=discord.Member if guild else discord.User, name='user')
        user.id = self.unique_id()
        user.discriminator = discriminator

        if guild is None:
            user.name = name or 'Mock User'
        else:
            user.name = name or 'Mock Member'
            user.guild = guild

        return user

    def make_text_channel(self, guild, name='mock-channel'):
        """Returns a new TextChannel-like Mock."""

        channel = self.pytest_mocker.Mock(
            spec=discord.TextChannel, name='channel')
        channel.id = self.unique_id()
        channel.guild = guild
        channel.type = discord.ChannelType.text
        channel.name = name
        channel.topic = f'topic for {name}'
        channel.test_history = []  # The messages that history() will return.

        async def history(limit=100, oldest_first=None):
            limit = len(channel.test_history) if limit is None else limit
            history = channel.test_history
            slice = history[:limit] if oldest_first else history[:-limit:-1]
            for m in slice:
                yield m

        async def fetch_message(id):
            found = next((m for m in channel.test_history if m.id == id), None)
            if found:
                return found
            else:
                raise discord.NotFound(None, f'message {id} not found')

        async def send(content=None, embed=None):
            message = self.make_message(
                guild=guild, channel=channel, author=guild.test_client.user,
                content=content, embed=embed)
            channel.test_history.append(message)
            return message

        channel.history.side_effect = history
        channel.fetch_message.side_effect = fetch_message
        channel.send.side_effect = send
        return channel

    def make_message(self, guild, channel, author,
                     content='Mock content', embed=None):
        """Returns a new Message-like Mock."""

        message = self.pytest_mocker.Mock(spec=discord.Message, name='message')
        message.id = self.unique_id()
        message.guild = guild
        message.channel = channel
        message.author = author
        message.content = content
        message.attachments = []
        message.embeds = [embed] if embed is not None else []
        message.reactions = []
        return message

    def make_reaction(self, message, unicode):
        reaction = self.pytest_mocker.Mock(
            spec=discord.Reaction, name='reaction')
        reaction.emoji = self.pytest_mocker.MagicMock(
            spec=discord.PartialEmoji, name='reaction.emoji')
        reaction.emoji.name = unicode
        reaction.emoji.__str__.return_value = unicode
        reaction.count = 0
        reaction.me = False
        reaction.message = message
        reaction.test_users = {}

        async def users(limit=None, oldest_first=None):
            for i, m in enumerate(reaction.test_users.values()):
                if limit is not None and i >= limit:
                    break
                yield m

        reaction.users.side_effect = users
        return reaction

    #
    # Helper methods to update data and generate notification events.
    #

    def reset_data(self, guild_count=1, members_per_guild=1,
                   channels_per_guild=1, messages_per_channel=1):
        """Populates a client (the default client if not given) with test data.
        Removes any previously configured data.

        Args:
            guild_count - number of (simulated) guilds (servers) to set up
            members_per_guild - number of members in each simulated guild
            channels_per_guild - number of text channels in each guild
            messages_per_channel - number of messages in each channel's history
        """

        self.context.discord().guilds[:] = []  # Erase preexisting data.
        for gi in range(guild_count):
            g = self.make_guild(
                self.context.discord(),
                name=f'Mock Guild {gi}')
            self.context.discord().guilds.append(g)

            for mi in range(members_per_guild):
                g.members.append(self.make_user(
                    g, name=f'Mock Member {mi}', discriminator=1000 + mi))
            for ci in range(channels_per_guild):
                name = f'mock-channel-{ci}'
                c = self.make_text_channel(g, name=name)
                g.channels.append(c)
                for mi in range(messages_per_channel):
                    # Need member for message author.
                    assert len(g.members) > 0
                    c.test_history.append(self.make_message(
                        g, c, g.members[mi % len(g.members)],
                        f'Mock message {mi} in #mock-channel-{ci}'))

    def queue_event(self, event_name, *args, **kwargs):
        """Queues an event to be sent to registered listeners."""

        if not event_name.startswith('on_'):
            raise ValueError(f"event '{event_name}' doesn't start with 'on_'")
        self.event_queue.append((event_name, args, kwargs))

    async def async_dispatch_events(self):
        """Sends all queued events to registered handlers."""

        while self.event_queue:
            batch, self.event_queue = self.event_queue, []
            for event_name, args, kwargs in batch:
                handler = getattr(self.context.discord(), event_name, None)
                if handler is not None:
                    await handler(*args, **kwargs)

    def sim_reaction(self, message, unicode, user, delta):
        """Simulates an emoji reaction change and queues notification events.

        Args:
            message - the message object to modify
            unicode - unicode of emoji to add/remove
            user - the user adding/removing the emoji
            delta - +1 to add, -1 to remove
        """

        if delta not in (-1, +1):
            raise ValueError(f'reaction {unicode} delta {delta} not -1 or +1')

        reaction = next(
            (r for m in message.reactions if str(r.emoji) == unicode), None)
        if reaction is None:
            reaction = self.make_reaction(message, unicode)
            message.reactions.append(reaction)

        old_count = len(reaction.test_users)
        if delta > 0:
            reaction.test_users[user.id] = user
        elif delta < 0:
            reaction.test_users.pop(user.id, None)

        reaction.me = (self.context.discord().user.id in reaction.test_users)
        reaction.count = len(reaction.test_users)
        if reaction.count != old_count:
            event = self.pytest_mocker.Mock(
                spec=discord.RawReactionActionEvent, name='raw_reaction_event')
            event.message_id = message.id
            event.user_id = user.id
            event.channel_id = message.channel.id
            event.guild_id = message.guild.id
            event.emoji = reaction.emoji
            event.member = user
            event.event_type = 'REACTION_' + ('ADD' if delta > 0 else 'REMOVE')
            self.queue_event(f'on_raw_{event.event_type.lower()}', event)
            return reaction

    def sim_create_channel(self, guild, name, category=None,
                           position=None, topic=None, reason=None):
        """Simulates guild.create_text_channel() and queues events."""

        channel = self.make_text_channel(guild, name)
        channel.topic = topic
        # TODO: Handle all the other arguments, mangle the name...
        guild.channels.append(channel)
        self.queue_event('on_guild_channel_create', channel)
        return channel


@pytest.fixture
def discord_mock(mocker, event_loop):
    """Fixture class to generate Mocks for Discord client library objects."""

    yield DiscordMockFixture(mocker)  # Keep event loop until teardown.
