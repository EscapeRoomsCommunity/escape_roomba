"""Unit tests for functions in format_util."""

import discord
import discord.abc

from escape_roomba.format_util import fid, fobj


def test_fid():
    assert fid(0x9305ac7cb9a2038) == '<2020-01-02/03:04:05.678/13/2/56>'
    assert fid(0x9305ac7cb800000) == '<2020-01-02/03:04:05.678///>'


def test_fobj(discord_mock):
    context = discord_mock.context
    guild_id = context.discord().guilds[0].id
    channel_id = context.discord().guilds[0].channels[0].id
    user_id = context.discord().guilds[0].members[0].id

    # Using fobj() with integers will call client lookup methods.
    assert (fobj(context.discord(), g=guild_id, c=channel_id, u=user_id) ==
            '"Mock Guild 0" #mock-channel-0 (Mock Member 0#1000)')
    context.discord().get_guild.assert_called_with(guild_id)
    context.discord().get_channel.assert_called_with(channel_id)
    context.discord().get_user.assert_called_with(user_id)

    # Verify fobj() with a Message-like object will use its members.
    m = discord_mock.make_message(
        channel=context.discord().guilds[0].channels[0],
        author=context.discord().guilds[0].members[0])
    assert (fobj(client=None, m=m) ==
            '"Mock Guild 0" #mock-channel-0 (Mock Member 0#1000): '
            '"Mock content"')

    # Verify fobj() will truncate content and normalize whitespace.
    m.content = '   somewhat longer\nmessage content text string here'
    assert (fobj(client=None, m=m) ==
            '"Mock Guild 0" #mock-channel-0 (Mock Member 0#1000): '
            '"somewhat longer mess ..."')
