"""Utility functions to format Discord objects as text for logging."""

import datetime
import logging

import discord
import discord.abc


def fid(id):
    """Pretty-formats a Discord "snowflake" ID (see
    https://discordpy.readthedocs.io/en/latest/api.html#discord.abc.Snowflake,
    https://discord.com/developers/docs/reference#snowflakes,
    https://github.com/twitter-archive/snowflake/tree/snowflake-2010)."""

    if isinstance(id, discord.abc.Snowflake):
        id = id.id
    if not isinstance(id, int):
        return f'?{repr(id)}?'  # Unknown type!

    dt = (datetime.datetime(2015, 1, 1) +
          datetime.timedelta(seconds=(id >> 22) * 1e-3))
    return (f'<{dt.strftime("%Y-%m-%d/%H:%M:%S.%f")[:-3]}/'
            f'{((id & 0x3E0000) >> 17) or ""}/'
            f'{((id & 0x1F000) >> 12) or ""}/'
            f'{(id & 0xFFF) or ""}>')


def fobj(client=None, g=None, c=None, u=None, m=None):
    """Pretty-formats Discord objects associated with some action.

    Args: (all may be None)
        client: discord.Client for lookup
        g: discord.Guild, int guild ID, or None
        c: discord.GuildChannel, .PrivateChannel, int channel ID, or None
        u: discord.User, .Member, int user ID, or None
        m: discord.Message, int message ID, or None

    Returns:
        A string describing all the given parameters, e.g.
        '"guild" #channel (user#1234) "message text"'
    """

    # Look up raw IDs, if possible.
    if client and isinstance(g, int):
        g = client.get_guild(g) or g
    if client and isinstance(c, int):
        c = client.get_channel(c) or c
    if client and isinstance(u, int):
        u = client.get_user(u) or u

    # Get embedded values from objects, if present.
    if isinstance(m, discord.Message):
        g = m.guild or g
        c = m.channel or c
        u = m.author or u
    if isinstance(u, discord.Member):
        g = u.guild or g
    if isinstance(c, discord.abc.GuildChannel):
        g = c.guild or g

    # Accumulate output that will be assembled with spaces.
    # The final format will be part or all of this:
    out = []

    if isinstance(g, discord.Guild):
        out.append(f'"{g}"')
    elif g:
        out.append(f'g={fid(g)}')

    if isinstance(c, discord.abc.GuildChannel):
        out.append(f'#{c}')
    elif isinstance(c, discord.abc.PrivateChannel):
        out.append(f'PRIVATE #{c}')
    elif c:
        out.append(f'c={fid(c)}')

    if isinstance(u, discord.Member) or isinstance(u, discord.User):
        out.append(f'({u})')
    elif u:
        out.append(f'u={fid(u)}')

    if isinstance(m, discord.Message):
        text = ' '.join(m.content.split())
        if len(text) > 20:
            text = text[:20].strip() + ' ...'
        if out:
            out[-1] = out[-1] + ':'
        out.append(f'"{text}"')
    elif m:
        out.append(f'm={fid(m)}')

    return ' '.join(out) if out else '(None)'
