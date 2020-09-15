import datetime
import logging

import discord
import discord.abc


class EventLogger:
    """Discord event listener that logs server/connection events."""

    def __init__(self, context):
        """Initializes with a Context and starts listening for events."""
        self._context = context

        # Shortcut logging methods.
        self._debug = context.logger.debug
        self._info = context.logger.info

        context.add_listener_methods(self)
        if self._context.logger.isEnabledFor(logging.DEBUG):
            context.add_listener_methods(self, prefix='_debug_on_')

    #
    # Logging listeners for 'notable' message types.
    #

    async def _on_connect(self):
        self._info('Connected to Discord:\n'
                   f'    {self._context.client.ws.gateway}')

    async def _on_disconnect(self):
        self._info(f'Disconnected from Discord')

    async def _on_resumed(self):
        self._info(f'Resumed Discord session')

    async def _on_ready(self):
        c = self._context.client
        self._info(f'Ready in {len(c.guilds)} servers (as {c.user}):' +
                   ''.join(f'\n    "{g}"' for g in c.guilds))
        invite_url = discord.utils.oauth_url(
            (await c.application_info()).id,
            discord.Permissions(
                manage_channels=True,
                add_reactions=True,
                read_messages=True,
                send_messages=True,
                manage_messages=True,
                read_message_history=True,
                manage_roles=True))
        self._info('Invite link, open in browser to add servers:\n'
                   f'    {invite_url}')

    async def _on_guild_join(self, guild):
        self._info(f'Joined Discord guild (server) "{guild}"')

    async def _on_guild_remove(self, guild):
        self._info(f'Removed from Discord guild (server) "{guild}"')

    async def _on_error(self, event, *args, **kwargs):
        self._context.logger.exception(f'Exception in "{event}" handler:')

    #
    # Debug-only logging listeners for all message types.
    #

    async def _debug_on_message(self, m):
        self._debug(f'Post message\n    {self._format(m=m)}')

    async def _debug_on_message_delete(self, m):
        self._debug(f'Delete message\n    {self._format(m=m)}')

    async def _debug_on_bulk_message_delete(self, ms):
        self._debug(f'Delete {len(ms)} messages:\n' +
                    '\n'.join(f'    {self._format(m=m)}' for m in ms))

    async def _debug_on_raw_message_delete(self, p):
        self._debug(f'Raw delete message\n    ' +
                    self._format(g=p.guild_id, c=p.channel_id, m=p.message_id))

    async def _debug_on_raw_bulk_message_delete(self, p):
        self._debug(
            f'Raw delete {len(p.message_ids)} messages in '
            f'{self._format(g=p.guild_id, c=p.channel_id)}:\n'
            '\n'.join(f'    {self._format(m=m)}' for m in p.message_ids))

    async def _debug_on_message_edit(self, b, a):
        self._debug('Edit message\n'
                    f'    was: {self._format(m=b)}\n'
                    f'    now: {self._format(m=a)}')

    async def _debug_on_raw_message_edit(self, p):
        self._debug('Raw edit message\n    ' +
                    self._format(c=p.channel_id, m=p.message_id))

    async def _debug_on_reaction_add(self, r, u):
        self._debug(f'Add [{r.emoji}] {self._format(u=u)} on\n    ' +
                    self._format(m=r.message))

    async def _debug_on_raw_reaction_add(self, p):
        self._debug(f'Raw add [{p.emoji}] {self._format(u=p.user_id)} on\n'
                    f'    ' +
                    self._format(g=p.guild_id, c=p.channel_id, m=p.message_id))

    async def _debug_on_reaction_remove(self, r, u):
        self._debug(f'Remove [{r.emoji}] {self._format(u=u)} on\n    ' +
                    self._format(m=r.message))

    async def _debug_on_raw_reaction_remove(self, p):
        self._debug(f'Raw remove [{p.emoji}] {self._format(u=p.user_id)} on\n'
                    f'    ' +
                    self._format(g=p.guild_id, c=p.channel_id, m=p.message_id))

    async def _debug_on_reaction_clear(self, m, rs):
        self._debug(f'Clear all {len(rs)} reactions from\n'
                    f'    {self._format(m=m)}:' +
                    '\n'.join(f'    {r.count}x {r.emoji}' for r in rs))

    async def _debug_on_raw_reaction_clear(self, p):
        self._debug(f'Raw clear all reactions from\n    ' +
                    self._format(g=p.guild_id, c=p.channel_id, m=p.message_id))

    async def _debug_on_reaction_clear_emoji(self, r):
        self._debug(f'Clear [{r.emoji}] from\n    {self._format(m=r.message)}')

    async def _debug_on_raw_reaction_clear_emoji(self, p):
        self._debug(f'Raw clear [{p.emoji}] from\n    ' +
                    self._format(g=p.guild_id, c=p.channel_id, m=p.message_id))

    async def _debug_on_guild_channel_delete(self, c):
        self._debug(f'Channel delete {self._format(c=c)}')

    async def _debug_on_guild_channel_create(self, c):
        self._debug(f'Channel create {self._format(c=c)}')

    async def _debug_on_guild_channel_update(self, b, a):
        self._debug(f'Channel update {self._format(c=b)}')

    async def _debug_on_guild_available(self, g):
        self._debug(f'Server available {self._format(g=g)}')

    async def _debug_on_guild_unavailable(self, g):
        self._debug(f'Server UNavailable {self._format(g=g)}')

    def _format(self, g=None, c=None, u=None, m=None):
        """Pretty-formats Discord structures associated with some action.

        Args:
            g: Guild, int guild ID, or None
            c: GuildChannel, PrivateChannel, int channel ID, or None
            u: User, Member, int user ID, or None
            m: Message, int message ID, or None

        Returns:
            A string describing all the given parameters, e.g.
            '"guild" #channel (user#1234) "message text"'
        """

        # Look up raw IDs, if possible.
        if isinstance(g, int):
            g = self._context.client.get_guild(g) or g
        if isinstance(c, int):
            c = self._context.client.get_channel(c) or c
        if isinstance(u, int):
            u = self._context.client.get_user(u) or u

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
            out.append(f'g={self._format_id(g)}')

        if isinstance(c, discord.abc.GuildChannel):
            out.append(f'#{c}')
        elif isinstance(c, discord.abc.PrivateChannel):
            out.append(f'PRIVATE #{c}')
        elif c:
            out.append(f'c={self._format_id(c)}')

        if isinstance(u, discord.Member) or isinstance(u, discord.User):
            out.append(f'({u})')
        elif u:
            out.append(f'u={self._format_id(u)}')

        if isinstance(m, discord.Message):
            text = ' '.join(m.content.split())
            if len(text) > 20:
                text = text[:20].strip() + ' ...'
            if out:
                out[-1] = out[-1] + ':'
            out.append(f'"{text}"')
        elif m:
            out.append(f'm={self._format_id(m)}')

        return ' '.join(out) if out else '(None)'

    @staticmethod
    def _format_id(id):
        """Pretty-prints a "snowflake" ID value (see
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
