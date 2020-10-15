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


def fobj(client=None, g=None, c=None, u=None, r=None, m=None, p=None):
    """Pretty-formats Discord objects associated with some action.

    Args: (may be None to infer if possible, '' to suppress)
        client: discord.Client or discord.Guild for lookup
        g: discord.Guild, int guild ID, or None
        c: discord.GuildChannel, PrivateChannel, int channel ID, or None
        u: discord.User, Member, int user ID, or None
        r: discord.Role, int role ID, or None
        m: discord.Message, int message ID, or None
        p: discord.Permissions, PermissionOverwrites, user dict, int, or None

    Returns:
        A string describing all the given parameters, e.g.
        '"guild" #channel (user#1234) "message text"'
    """

    # Look up int IDs using the client, if possible.
    def lookup(a, m, b):
        return getattr(a, m, lambda x: x)(b) if isinstance(b, int) else b

    g = lookup(client, 'get_guild', g)
    c = lookup(client, 'get_channel', c)
    u = lookup(client, 'get_user', u)
    u = lookup(client, 'get_member', u)  # (if using Guild for lookup)

    # Get the guild from object properties, if present.
    if g is None or isinstance(g, int):
        g = (m.guild if hasattr(m, 'guild') else     # Message-like
             u.guild if hasattr(u, 'guild') else     # Member-like
             c.guild if hasattr(c, 'guild') else g)  # GuildChannel-like

    # Look up int IDs using the guild, if available.
    c = lookup(g, 'get_channel', c)
    u = lookup(g, 'get_member', u)
    r = lookup(g, 'get_role', r)

    # Look up values from the message, if available.
    c = m.channel if c is None and hasattr(m, 'channel') else c
    u = m.author if u is None and hasattr(m, 'author') else u

    # Accumulate output that will be assembled with spaces.
    # Final output will be a subset of this:
    #   "message text" <@user> #channel (Guild)
    out = []

    def abbreviate(text):
        text = ' '.join((text or '').split())  # Normalize spaces.
        return text[:15].strip() + ' ...' if len(text) > 15 else text

    if hasattr(m, 'content'):  # Message-like
        text = abbreviate(m.content)
        out.append(f'"{text or ""}"')
        for e in m.embeds if hasattr(m, 'embeds') else []:
            text = abbreviate(e.title or e.description)
            out.append(f'E[{text}]' if text else '[empty embed]')
    elif m:
        out.append(fid(m).replace('<', '<m:'))

    if m and u:
        out.append('by')

    if hasattr(u, 'name') and hasattr(u, 'discriminator'):  # User/Member-like
        out.append(f'<@{u.name}#{u.discriminator}>')
    elif hasattr(u, 'name'):
        out.append(f'<@{u.name.strip("@")}>')  # Also allow Role-like
    elif u:
        out.append(fid(u).replace('<', '<@'))

    if hasattr(r, 'name'):
        out.append(f'<@{r.name.strip("@")}>')  # Role-like
    elif r:
        out.append(fid(r).replace('<', '<@&'))

    if m and c:
        out.append('in')

    # Channel attributes. (Don't show position when printing a message.)
    if hasattr(c, 'position') and not (m or u or r):  # GuildChannel-like
        out.append(f'(p{c.position})')
    if hasattr(c, 'type') and c.type != discord.ChannelType.text:
        out.append(f'[{str(c.type)[:3]}]')

    if hasattr(c, 'me') and hasattr(c, 'recipient'):  # DMChannel-like
        out.append(f'[{c.me} => {c.recipient}]')
    elif hasattr(c, 'me') and hasattr(c, 'recipients'):  # GroupChannel-like
        out.append(f'[{c.me} => {", ".join(r for r in c.recipients)}]')
    elif hasattr(c, 'name'):  # GuildChannel-like
        is_cat = (getattr(c, 'type', None) == discord.ChannelType.category)
        out.append(f'"{c.name}"' if is_cat else f'#{c.name}')
    elif c:
        out.append(fid(c).replace('<', '<#'))

    if (m or r or u or c) and g:
        out.append('on')

    if hasattr(g, 'name'):  # Guild-like
        out.append(f'"{g.name}"')
    elif g:
        out.append(fid(g).replace('<', '<g:'))

    # Shorten permission names so they fit better.
    def abbrev(a):
        return a.replace('message', 'msg').replace('history', 'hist')

    if hasattr(p, 'items'):   # user/permission dict
        out.append('\n'.join(
            f'{fobj(p=v)} for {fobj(u=k, g="")}' for k, v in p.items()) or
            '(no user overwrites)')
    elif hasattr(p, 'pair'):  # PermissionOverwrite-like
        ab, db = (v.value for v in p.pair())
        kv = [f'{abbrev(k)}={"NY"[v]}' for k, v in sorted(p) if v is not None]
        out.append(f'{ab:x}-{db:x} ' + ', '.join(kv) or '(no overwrites)')
    elif hasattr(p, 'value'):  # Permissions-like
        kv = [abbrev(k) for k, v in sorted(p) if v]
        out.append(f'{p.value:x} ' + ', '.join(kv) or '(no permissions)')
    elif p:
        out.append(fobj(p=discord.Permissions(p)))

    return ' '.join(out) if out else '(None)'
