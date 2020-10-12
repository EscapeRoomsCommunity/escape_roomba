"""Shared configuration for unit tests:
docs.pytest.org/en/stable/fixture.html#conftest-py-sharing-fixture-functions.
"""

import argparse
import copy
import logging

import discord
import pytest
import regex

from escape_roomba.format_util import fobj
import escape_roomba.context

logger_ = logging.getLogger('bot.mock')


class DiscordMockFixture:
    """Class to generate Discord client library Mocks simulating a server.
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
        logger_.debug('make_client')
        return client

    def make_guild(self, client, name='Mock Guild'):
        """Returns a new Guild-like Mock."""

        guild = self.pytest_mocker.Mock(spec=discord.Guild, name='guild')
        guild.id = self.unique_id()
        guild.name = name
        guild.channels = []
        guild.members = []
        guild.default_role = self.make_role(guild, '@everyone')
        guild.me = self.make_user(
            guild=guild, name=client.user.name, id=client.user.id,
            discriminator=client.user.discriminator)

        async def create_text_channel(*args, **kwargs):
            return self.sim_add_channel(*args, guild=guild, **kwargs)

        guild.create_text_channel.side_effect = create_text_channel
        guild.get_channel = client.get_channel
        logger_.debug(f'make_guild:\n    {fobj(g=guild)}')
        return guild

    def make_role(self, guild, name=None):
        """Returns a new Role-like Mock."""

        role = self.pytest_mocker.Mock(spec=discord.Role, name='role')
        role.id = self.unique_id()
        role.name = name
        role.guild = guild
        # TODO: Add other fields and methods.
        logger_.debug(f'make_role: {fobj(r=role)}')
        return role

    def make_user(self, guild=None, name=None, id=None, discriminator='9999'):
        """Returns a new User-like (or Member-like if guild is set) Mock."""

        user = self.pytest_mocker.Mock(
            spec=discord.Member if guild else discord.User, name='user')
        user.id = id or self.unique_id()
        user.discriminator = discriminator

        if guild is None:
            user.name = name or 'Mock User'
        else:
            user.name = name or 'Mock Member'
            user.guild = guild

        logger_.debug(f'make_user: {fobj(u=user)}')
        return user

    def make_text_channel(self, guild, name='mock-channel', category=None,
                          position=None, topic=None, reason=None,
                          overwrites=None):
        # TODO: Handle all the other arguments, mangle the name...
        """Returns a new TextChannel-like Mock."""

        channel = self.pytest_mocker.Mock(
            spec=discord.TextChannel, name='channel')
        channel.id = self.unique_id()
        channel.guild = guild
        channel.type = discord.ChannelType.text
        channel.name = name
        channel.topic = topic or f'topic for {name}'
        channel.history_for_mock = []  # Messages that history() will return.
        channel.position = position
        channel.overwrites = overwrites or {}
        # TODO: Handle category and reason.

        async def history(limit=100, oldest_first=None):
            limit = len(channel.history_for_mock) if limit is None else limit
            history = channel.history_for_mock
            slice = history[:limit] if oldest_first else history[:-limit:-1]
            for m in slice:
                yield m

        async def fetch_message(id):
            m = next((m for m in channel.history_for_mock if m.id == id), None)
            if not m:
                raise discord.NotFound(None, f'message {id} not found')
            return m

        async def send(content=None, embed=None):
            return self.sim_add_message(
                channel=channel, author=guild.me, content=content, embed=embed)

        async def edit(name=None, overwrites=None):
            # TODO: Handle all the other arguments (and mangle the name)...
            if overwrites is not None:
                channel.overwrites = overwrites

        channel.history.side_effect = history
        channel.fetch_message.side_effect = fetch_message
        channel.send.side_effect = send
        channel.edit.side_effect = edit
        logger_.debug(f'make_channel:\n    {fobj(c=channel)}')
        return channel

    def make_message(self, channel, author, content='Mock content',
                     embed=None):
        """Returns a new Message-like Mock."""

        message = self.pytest_mocker.Mock(spec=discord.Message, name='message')
        message.id = self.unique_id()
        message.guild = channel.guild
        message.channel = channel
        message.author = author
        message.content = content
        message.attachments = []
        message.embeds = [embed] if embed is not None else []
        message.reactions = []

        async def edit(*args, **kwargs):
            self.sim_edit_message(message, *args, **kwargs)

        async def add_reaction(emoji):
            self.sim_reaction(message, str(emoji), message.guild.me, +1)

        async def remove_reaction(emoji, member):
            self.sim_reaction(message, str(emoji), message.guild.me, -1)

        message.edit.side_effect = edit
        message.add_reaction.side_effect = add_reaction
        message.remove_reaction.side_effect = remove_reaction
        logger_.debug(f'make_message:\n    {fobj(m=message)}')
        return message

    def make_reaction(self, message, unicode):
        logger_.debug(f'make_reaction: {unicode}\n    on: {fobj(m=message)}')
        assert isinstance(unicode, str)
        assert regex.fullmatch(r'\p{Emoji}', unicode)

        reaction = self.pytest_mocker.MagicMock(
            spec=discord.Reaction, name='reaction')
        reaction.emoji = self.pytest_mocker.MagicMock(
            spec=discord.PartialEmoji, name='reaction.emoji')
        reaction.emoji.name = unicode
        reaction.emoji.__str__.return_value = unicode
        reaction.__str__.return_value = unicode
        reaction.count = 0
        reaction.me = False
        reaction.message = message
        reaction.users_for_mock = {}

        async def users(limit=None, oldest_first=None):
            for i, m in enumerate(reaction.users_for_mock.values()):
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
        """Clears the simulated server and populates it with test data.

        Args:
            guild_count - number of (simulated) guilds (servers) to set up
            members_per_guild - number of members in each simulated guild
            channels_per_guild - number of text channels in each guild
            messages_per_channel - number of messages in each channel's history
        """

        logger_.debug(f'reset_data: #g={guild_count} #u/g={members_per_guild} '
                      f'#c/g={channels_per_guild} #m/c={messages_per_channel}')

        self.context.discord().guilds[:] = []  # Erase preexisting data.
        for gi in range(guild_count):
            guild = self.make_guild(
                self.context.discord(), name=f'Mock Guild {gi}')
            self.context.discord().guilds.append(guild)

            for mi in range(members_per_guild):
                guild.members.append(self.make_user(
                    guild, name=f'Mock Member {mi}', discriminator=1000 + mi))

            for ci in range(channels_per_guild):
                chan = self.sim_add_channel(guild, name=f'mock-channel-{ci}')
                for mi in range(messages_per_channel):
                    # Need member for message author.
                    assert len(guild.members) > 0
                    author = guild.members[mi % len(guild.members)]
                    self.sim_add_message(
                        channel=chan, author=author,
                        content=f'Mock message {mi} in #mock-channel-{ci}')

        self.event_queue = []  # No events for initial content.
        logger_.debug('reset_data done')

    def queue_event(self, event_name, *args, **kwargs):
        """Queues an event to be sent to registered listeners."""

        logger_.debug(f'queue_event: {event_name}')
        assert event_name.startswith('on_')
        self.event_queue.append((event_name, args, kwargs))

    async def async_dispatch_events(self):
        """Sends all queued events to registered handlers."""

        logger_.debug(f'async_dispatch_event: {len(self.event_queue)} events')
        while self.event_queue:
            batch, self.event_queue = self.event_queue, []
            for event_name, args, kwargs in batch:
                handler = getattr(self.context.discord(), event_name, None)
                logger_.debug(f'async_dispatch_event: {event_name}'
                              f'{"" if handler else " [unhandled]"}]')
                if handler is not None:
                    await handler(*args, **kwargs)
            logger_.debug('async_dispatch_event: batch done, '
                          f'{len(self.event_queue)} added')

    def sim_add_message(self, channel, **kwargs):
        """Simulates a message post and queues notification events.

        Args:
            channel - the channel to post to
            message - the message to post
        """

        message = self.make_message(channel=channel, **kwargs)
        logger_.debug(f'sim_add_message:\n    {fobj(m=message)}')
        channel.history_for_mock.append(message)
        self.queue_event(f'on_message', message)
        return message

    def sim_edit_message(self, message, content=None, embed=None):
        edited = copy.copy(message)
        edited.content = content
        edited.embeds = [embed] if embed is not None else []
        logger_.debug('sim_edit_message:\n'
                      f'    before: {fobj(m=message)}\n'
                      f'    after: {fobj(m=edited)}')

        history = message.channel.history_for_mock
        history[:] = [edited if m.id == message.id else m for m in history]

        event = self.pytest_mocker.Mock(
            spec=discord.RawMessageUpdateEvent, name='raw_edit_event')
        event.message_id = message.id
        event.channel_id = message.channel.id
        event.data = None  # TODO: Fill in if needed.
        event.cached_message = message
        self.queue_event('on_raw_message_edit', event)
        self.queue_event('on_message_edit', message, edited)

    def sim_reaction(self, message, unicode, user, delta):
        """Simulates an emoji reaction change and queues notification events.

        Args:
            message - the message object to modify
            unicode - unicode of emoji to add/remove
            user - the user adding/removing the emoji
            delta - +1 to add, -1 to remove
        """

        logger_.debug(f'sim_reaction: {delta:+d} {unicode}\n'
                      f'    by: {fobj(u=user)}\n'
                      f'    on: {fobj(m=message)}')
        assert isinstance(unicode, str)
        assert regex.fullmatch(r'\p{Emoji}', unicode)
        assert delta in (-1, +1)

        reaction = next(
            (r for r in message.reactions if str(r.emoji) == unicode), None)
        if reaction is None:
            reaction = self.make_reaction(message, unicode)
            message.reactions.append(reaction)

        old_count = len(reaction.users_for_mock)
        if delta > 0:
            reaction.users_for_mock[user.id] = user
        elif delta < 0:
            reaction.users_for_mock.pop(user.id, None)

        reaction.me = (message.guild.me.id in reaction.users_for_mock)
        reaction.count = len(reaction.users_for_mock)
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

        logger_.debug('sim_reaction done:\n    ' + ' '.join(
            f'{str(r.emoji)}x{r.count}{"*" if r.me else ""}'
            for r in message.reactions))
        return reaction

    def sim_add_channel(self, guild, name, *args, **kwargs):
        """Simulates guild.create_text_channel() and queues events."""

        logger_.debug(f'sim_add_channel: #{name}')
        channel = self.make_text_channel(guild, name, *args, **kwargs)
        if channel.position is None:
            channel.position = len(guild.channels)
        guild.channels.insert(channel.position, channel)
        for i in range(channel.position + 1, len(guild.channels)):
            guild.channels[i].position = i
        self.queue_event('on_guild_channel_create', channel)
        return channel


@pytest.fixture
def discord_mock(mocker, event_loop):
    """Fixture class to generate Mocks for Discord client library objects."""

    yield DiscordMockFixture(mocker)  # Keep event loop until teardown.
