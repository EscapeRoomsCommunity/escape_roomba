"""Unit tests for thread_channel.ThreadChannel."""

import discord
import pytest

from escape_roomba.thread_channel import ThreadChannel


@pytest.fixture
async def thread_channel(discord_mock):
    """Fixture that creates and returns a ThreadChannel for a new thread."""
    client = discord_mock.context.discord()
    message = client.guilds[0].channels[0].history_for_mock[0]
    discord_mock.sim_reaction(message, '🧵', client.guilds[0].members[0], +1)
    return await ThreadChannel.async_maybe_create_from_origin(
        client, message.channel.id, message.id)


def test_relevant_origin_update(discord_mock):
    # Reaction update should be relevant if emoji is 🧵.
    assert not ThreadChannel.relevant_origin_update(emoji='🧶')
    assert ThreadChannel.relevant_origin_update(emoji='🧵')

    # Message update should be relevant if it contains 🧵 reaction.
    guild = discord_mock.context.discord().guilds[0]
    message = guild.channels[0].history_for_mock[0]
    discord_mock.sim_reaction(message, '🧶', guild.members[0], +1)
    assert not ThreadChannel.relevant_origin_update(message=message)

    discord_mock.sim_reaction(message, '🧵', guild.members[0], +1)
    assert ThreadChannel.relevant_origin_update(message=message)

    discord_mock.sim_reaction(message, '🧵', guild.me, +1)
    assert not ThreadChannel.relevant_origin_update(message=message)


@pytest.mark.asyncio
async def test_relevant_intro_update(discord_mock, thread_channel):
    # Before the intro cache is filled, any message is relevant.
    channel = thread_channel.thread_channel
    user = channel.guild.members[0]  # arbitrary user

    assert len(thread_channel.thread_channel.history_for_mock) == 1
    message = discord_mock.sim_add_message(channel=channel, author=user)
    assert thread_channel.relevant_intro_update(message_id=message.id)
    await thread_channel.async_refresh_intro()  # Pick up new message.

    # Now that there are two messages, another one isn't relevant.
    message = discord_mock.sim_add_message(channel=channel, author=user)
    assert not thread_channel.relevant_intro_update(message_id=message.id)

    # However, one of the first two messages is always relevant.
    history = channel.history_for_mock
    assert thread_channel.relevant_intro_update(message_id=history[0].id)
    assert thread_channel.relevant_intro_update(message_id=history[1].id)
    assert not thread_channel.relevant_intro_update(message_id=history[2].id)


@pytest.mark.asyncio
async def test_maybe_create_from_origin(discord_mock):
    client = discord_mock.context.discord()
    message = client.guilds[0].channels[0].history_for_mock[0]
    thread_channel = await ThreadChannel.async_maybe_create_from_origin(
        client, message.channel.id, message.id)
    assert thread_channel is None

    discord_mock.sim_reaction(message, '🧵', message.guild.members[0], +1)
    thread_channel = await ThreadChannel.async_maybe_create_from_origin(
        client, message.channel.id, message.id)
    assert thread_channel is not None
    assert thread_channel.thread_channel.name == '🧵mock-message-0-in…'

    Overwrite = discord.PermissionOverwrite
    assert thread_channel.thread_channel.overwrites == {
        message.guild.default_role:
            Overwrite(read_messages=False),
        message.guild.me:
            Overwrite(embed_links=True, manage_channels=True,
                      manage_messages=True, manage_permissions=True,
                      read_message_history=True, read_messages=True,
                      send_messages=True),
        message.guild.members[0]:
            Overwrite(read_messages=True, send_messages=True,
                      read_message_history=True),
    }

    assert message.reactions[0].count == 2


def test_maybe_attach_to_thread_channel(discord_mock, thread_channel):
    # Should be able to attach to the thread created by another instance.
    new_tc = ThreadChannel.maybe_attach_to_thread_channel(
        thread_channel.thread_channel)
    assert new_tc.thread_channel is thread_channel.thread_channel
    assert new_tc.origin_message_id == thread_channel.origin_message_id
    assert new_tc.origin_channel_id == thread_channel.origin_channel_id

    # Should *not* attach to the non-thread mock channel.
    nonthread = discord_mock.context.discord().guilds[0].channels[0]
    assert ThreadChannel.maybe_attach_to_thread_channel(nonthread) is None


@pytest.mark.asyncio
async def test_refresh_origin(discord_mock, thread_channel):
    t_channel = thread_channel.thread_channel
    o_channel = t_channel.guild.get_channel(thread_channel.origin_channel_id)
    o_message = await o_channel.fetch_message(thread_channel.origin_message_id)

    # The thread channel's intro message should echo the origin message.
    embed_content = t_channel.history_for_mock[0].embeds[0].description
    assert o_message.content and o_message.content in embed_content

    # After an edit and an origin refresh, the thread's intro should update.
    await o_message.edit(content='Revised Content')
    await thread_channel.async_refresh_origin()
    embed_content = t_channel.history_for_mock[0].embeds[0].description
    assert 'Revised Content' in embed_content


# TODO: Add more tests of more functionality.
