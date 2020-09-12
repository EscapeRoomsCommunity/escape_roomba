import datetime
import logging

import discord
import discord.abc

class EventLogger:
    """Discord event listener that logs server/connection events."""

    def __init__(self, context):
        """Initialize with an escape_roomba.context.Context object."""
        self.context = context
        self.debug = self.context.logger.debug  # Shortcut methods
        self.info = self.context.logger.info

        context.add_listener_methods(self)
        if self.context.logger.isEnabledFor(logging.DEBUG):
            context.add_listener_methods(self, prefix='debug_on_')

    #
    # Logging handlers for 'notable' message types.
    #

    async def on_connect(self):
        self.info('Connected to Discord:\n'
                  f'    {self.context.client.ws.gateway}')

    async def on_disconnect(self):
        self.info(f'Disconnected from Discord')

    async def on_resumed(self):
        self.info(f'Resumed Discord session')

    async def on_ready(self):
        c = self.context.client
        self.info(f'Ready in {len(c.guilds)} servers (as {c.user}):' +
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
        self.info('Invite link, open in browser to add servers:\n'
                  f'    {invite_url}')

    async def on_guild_join(self, guild):
        self.info(f'Joined Discord guild (server) "{guild}"')

    async def on_guild_remove(self, guild):
        self.info(f'Removed from Discord guild (server) "{guild}"')

    async def on_error(self, event, *args, **kwargs):
        self.context.logger.exception(f'Exception in "{event}" handler:')

    #
    # Debug-only logging for all message types.
    #

    async def debug_on_message(self, m):
        self.debug(f'Post "{m.author.guild}" #{m.channel} ({m.author}):\n'
                   f'    "{m.content.strip()}"')

    async def debug_on_message_delete(self, m):
        self.debug(f'Delete "{m.author.guild}" #{m.channel} ({m.author}):\n'
                   f'    "{m.content.strip()}"')

    async def debug_on_bulk_message_delete(self, messages):
        self.debug(f'Bulk delete {len(messages)}x:')
        for m in messages:
            self.debug(f'    "{m.author.guild}" #{m.channel} ({m.author}):\n'
                       f'        "{m.content.strip()}"')

    async def debug_on_raw_message_delete(self, p):
        self.debug(f'Raw delete {self._guild(p.guild_id)} '
                   f'{self._channel(p.channel_id)}:\n    {_id(p.message_id)}')

    async def debug_on_raw_bulk_message_delete(self, p):
        self.debug(
            f'Raw bulk delete {len(p.message_ids)}x '
            f'{self._guild(p.guild_id)} {self._channel(p.channel_id)}:\n' +
            '\n'.join(f'    {_id(id)}' for id in p.message_ids))

    async def debug_on_message_edit(self, b, a):
        self.debug(f'Edit "{b.author.guild}" #{b.channel} ({b.author}):\n'
                   f'    before: "{b.content.strip()}"\n'
                   f'    after:  "{a.content.strip()}"')

    async def debug_on_raw_message_edit(self, p):
        self.debug(f'Raw edit {self._channel(p.channel_id)}:\n'
                   f'    {_id(p.message_id)}')

    async def debug_on_reaction_add(self, reaction, user):
        self.debug(f'Reaction add: {reaction} by {user}')

    async def debug_on_raw_reaction_add(self, payload):
        self.debug(f'Raw reaction add: {payload}')

    async def debug_on_reaction_remove(self, reaction, user):
        self.debug(f'Reaction remove: {reaction} by {user}')

    async def debug_on_raw_reaction_remove(self, payload):
        self.debug(f'Raw reaction remove: {payload}')

    async def debug_on_reaction_clear(self, message, reactions):
        self.debug(f'Reaction clear: {message} {reactions}')

    async def debug_on_raw_reaction_clear(self, payload):
        self.debug(f'Raw reaction clear: {payload}')

    async def debug_on_reaction_clear_emoji(self, message, reactions):
        self.debug(f'Reaction emoji clear: {message} {reactions}')

    async def debug_on_raw_reaction_clear_emoji(self, payload):
        self.debug(f'Raw reaction emoji clear: {payload}')

    async def debug_on_guild_channel_delete(self, channel):
        self.debug(f'Guild (server) text channel delete: {channel}')

    async def debug_on_guild_channel_create(self, channel):
        self.debug(f'Guild (server) text channel create: {channel}')

    async def debug_on_guild_channel_update(self, before, after):
        self.debug(f'Guild (server) text channel update: {before} => {after}')

    async def debug_on_guild_available(self, guild):
        self.debug(f'Guild (server) available: {guild}')

    async def debug_on_guild_unavailable(self, guild):
        self.debug(f'Guild (server) UNavailable: {guild}')

    def _guild(self, g):
        """Pretty-print a Guild or guild ID."""
        if isinstance(g, discord.Guild): return f'"{g}"'
        if isinstance(g, discord.abc.Snowflake): g = g.id
        if isinstance(g, int):
            lookup = self.context.client.get_guild(g)
            if lookup: return f'"{lookup}"'
            return _id(c)
        return f'"{g}"'

    def _channel(self, c):
        """Pretty-print a (Guild/Private)Channel or channel ID."""
        if isinstance(c, discord.abc.GuildChannel): return f'#{c}'
        if isinstance(c, discord.abc.PrivateChannel): return f'#{c}'
        if isinstance(c, discord.abc.Snowflake): c = c.id
        if isinstance(c, int):
            lookup = self.context.client.get_channel(c)
            if lookup: return f'#{lookup}'
            return _id(c)
        return f'#{c}'


def _id(id):
    """Pretty-print a "snowflake" ID value (see
    https://discordpy.readthedocs.io/en/latest/api.html#discord.abc.Snowflake,
    https://discord.com/developers/docs/reference#snowflakes,
    https://github.com/twitter-archive/snowflake/tree/snowflake-2010)."""

    if isinstance(id, discord.abc.Snowflake): id = id.id
    if isinstance(id, str): id = int(id)

    dt = (datetime.datetime(2015, 1, 1) +
          datetime.timedelta(seconds=(id >> 22) * 1e-3))
    return (f'<{dt.strftime("%Y-%m-%d/%H:%M:%S.%f")[:-3]}/'
            f'{((id & 0x3E0000) >> 17) or ""}/{((id & 0x1F000) >> 12) or ""}/'
            f'{(id & 0xFFF) or ""}>')
