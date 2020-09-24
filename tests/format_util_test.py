"""Unit tests for functions in format_util."""

import discord
import discord.abc

from escape_roomba.format_util import fid, fobj


def test_fid():
    assert fid(0x9305ac7cb9a2038) == '<2020-01-02/03:04:05.678/13/2/56>'
    assert fid(0x9305ac7cb800000) == '<2020-01-02/03:04:05.678///>'


def test_fobj(mocker, make_context, make_discord_message):
    # Create a discord.Client-like Mock with the functions fobj() calls.
    context = make_context(guild_count=1, channel_count=1, member_count=1)
    guild_id = context.client.guilds[0].id
    channel_id = context.client.guilds[0].channels[0].id
    user_id = context.client.guilds[0].members[0].id

    # Using fobj() with integers will call client lookup methods.
    assert (fobj(context.client, g=guild_id, c=channel_id, u=user_id) ==
            '"Mock Guild 0" #mock-channel-0 (Mock Member 0#1000)')
    context.client.get_guild.assert_called_with(guild_id)
    context.client.get_channel.assert_called_with(channel_id)
    context.client.get_user.assert_called_with(user_id)

    # Verify fobj() with a Message-like object will use its members.
    m = make_discord_message(
        context.client.guilds[0],
        context.client.guilds[0].channels[0],
        context.client.guilds[0].members[0])
    assert (fobj(client=None, m=m) ==
            '"Mock Guild 0" #mock-channel-0 (Mock Member 0#1000): '
            '"Mock message content"')

    # Verify fobj() will truncate content and normalize whitespace.
    m.content = '   somewhat longer\nmessage content text string here'
    assert (fobj(client=None, m=m) ==
            '"Mock Guild 0" #mock-channel-0 (Mock Member 0#1000): '
            '"somewhat longer mess ..."')
