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

    if hasattr(id, 'id'):
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
    if hasattr(m, 'guild'):    # Message-like
        g = m.guild or g
    if hasattr(m, 'channel'):  # Message-like
        c = m.channel or c
    if hasattr(m, 'author'):   # Message-like
        u = m.author or u
    if hasattr(u, 'guild'):    # Member-like
        g = u.guild or g
    if hasattr(c, 'guild'):    # GuildChannel-like
        g = c.guild or g

    # Accumulate output that will be assembled with spaces.
    # The final format will be part or all of this:
    out = []
    if hasattr(g, 'name'):     # Guild-like
        out.append(f'"{g.name}"')
    elif g:
        out.append(f'g={fid(g)}')

    if hasattr(c, 'me') and hasattr(c, 'recipient'):  # DMChannel-like
        out.append(f'[{c.me} => {c.recipient}]')
    elif hasattr(c, 'me') and hasattr(c, 'recipients'):  # GroupChannel-like
        out.append(f'[{c.me} => {", ".join(r for r in c.recipients)}]')
    elif hasattr(c, 'name'):  # GuildChannel-like
        out.append(f'#{c.name}')
    elif c:
        out.append(f'c={fid(c)}')

    if hasattr(u, 'name') and hasattr(u, 'discriminator'):  # User/Member-like
        out.append(f'({u.name}#{u.discriminator})')
    elif u:
        out.append(f'u={fid(u)}')

    if hasattr(m, 'content'):  # Message-like
        text = ' '.join(m.content.split())
        if len(text) > 20:
            text = text[:20].strip() + ' ...'
        if out:
            out[-1] = out[-1] + ':'
        out.append(f'"{text}"')
    elif m:
        out.append(f'm={fid(m)}')

    return ' '.join(out) if out else '(None)'
