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
            '<@Mock Member 0#1000> #mock-channel-0 on "Mock Guild 0"')
    context.discord().get_guild.assert_called_with(guild_id)
    context.discord().get_channel.assert_called_with(channel_id)
    context.discord().get_user.assert_called_with(user_id)

    # Verify fobj() with a Message-like object will use its members.
    m = discord_mock.make_message(
        channel=context.discord().guilds[0].channels[0],
        author=context.discord().guilds[0].members[0])
    assert (fobj(client=None, m=m) ==
            '"Mock content" by '
            '<@Mock Member 0#1000> in #mock-channel-0 on "Mock Guild 0"')

    # Verify fobj() will truncate content and normalize whitespace.
    m.content = '   somewhat longer\nmessage content text string here'
    assert (fobj(client=None, m=m) ==
            '"somewhat longer ..." by '
            '<@Mock Member 0#1000> in #mock-channel-0 on "Mock Guild 0"')

    # Verify fobj() with permissions-type objects.
    permissions = discord.Permissions(stream=True, read_messages=True)
    overwrite = discord.PermissionOverwrite(stream=False, read_messages=True)
    assert fobj(p=1536) == '600 read_msgs, stream'
    assert fobj(p=permissions) == '600 read_msgs, stream'
    assert fobj(p=overwrite) == '400-200 read_msgs=Y, stream=N'

    discord_mock.reset_data(members_per_guild=2)
    members = context.discord().guilds[0].members
    Overwrite = discord.PermissionOverwrite
    overwrites = {
        members[0]: Overwrite(stream=True, read_messages=False),
        members[1]: Overwrite(stream=False, read_messages=True),
    }
    assert (
        fobj(p=overwrites) ==
        '200-400 read_msgs=N, stream=Y for <@Mock Member 0#1000>\n'
        '400-200 read_msgs=Y, stream=N for <@Mock Member 1#1001>')

    # Verify fobj() produces reasonable output with all parameters None.
    assert fobj() == '(None)'
