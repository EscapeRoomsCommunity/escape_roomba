import datetime
import logging

import discord
import discord.abc

from escape_roomba.format_util import fid, fobj


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

    def _fobj(self, **kw):
        return fobj(client=self._context.client, **kw)

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
        self._info('Open this link to add this bot to more servers:\n'
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
        self._debug(f'Post message\n    {self._fobj(m=m)}')

    async def _debug_on_message_delete(self, m):
        self._debug(f'Delete message\n    {self._fobj(m=m)}')

    async def _debug_on_bulk_message_delete(self, ms):
        self._debug(f'Delete {len(ms)} messages:\n' +
                    '\n'.join(f'    {self._fobj(m=m)}' for m in ms))

    async def _debug_on_raw_message_delete(self, p):
        self._debug(f'Raw delete message\n    ' +
                    self._fobj(g=p.guild_id, c=p.channel_id, m=p.message_id))

    async def _debug_on_raw_bulk_message_delete(self, p):
        self._debug(
            f'Raw delete {len(p.message_ids)} messages in '
            f'{self._fobj(g=p.guild_id, c=p.channel_id)}:\n'
            '\n'.join(f'    {self._fobj(m=m)}' for m in p.message_ids))

    async def _debug_on_message_edit(self, b, a):
        self._debug('Edit message\n'
                    f'    was: {self._fobj(m=b)}\n'
                    f'    now: {self._fobj(m=a)}')

    async def _debug_on_raw_message_edit(self, p):
        self._debug('Raw edit message\n    ' +
                    self._fobj(c=p.channel_id, m=p.message_id,
                               u=int(p.data.get('author', {}).get('id', 0))))

    async def _debug_on_reaction_add(self, r, u):
        self._debug(f'Add [{r.emoji}] {self._fobj(u=u)} on\n    ' +
                    self._fobj(m=r.message))

    async def _debug_on_raw_reaction_add(self, p):
        self._debug(f'Raw add [{p.emoji}] {self._fobj(u=p.user_id)} on\n'
                    f'    ' +
                    self._fobj(g=p.guild_id, c=p.channel_id, m=p.message_id))

    async def _debug_on_reaction_remove(self, r, u):
        self._debug(f'Remove [{r.emoji}] {self._fobj(u=u)} on\n    ' +
                    self._fobj(m=r.message))

    async def _debug_on_raw_reaction_remove(self, p):
        self._debug(f'Raw remove [{p.emoji}] {self._fobj(u=p.user_id)} on\n'
                    f'    ' +
                    self._fobj(g=p.guild_id, c=p.channel_id, m=p.message_id))

    async def _debug_on_reaction_clear(self, m, rs):
        self._debug(f'Clear all {len(rs)} reactions from\n'
                    f'    {self._fobj(m=m)}:' +
                    '\n'.join(f'    {r.count}x {r.emoji}' for r in rs))

    async def _debug_on_raw_reaction_clear(self, p):
        self._debug(f'Raw clear all reactions from\n    ' +
                    self._fobj(g=p.guild_id, c=p.channel_id, m=p.message_id))

    async def _debug_on_reaction_clear_emoji(self, r):
        self._debug(f'Clear [{r.emoji}] from\n    {self._fobj(m=r.message)}')

    async def _debug_on_raw_reaction_clear_emoji(self, p):
        self._debug(f'Raw clear [{p.emoji}] from\n    ' +
                    self._fobj(g=p.guild_id, c=p.channel_id, m=p.message_id))

    async def _debug_on_guild_channel_delete(self, c):
        self._debug(f'Channel delete {self._fobj(c=c)}')

    async def _debug_on_guild_channel_create(self, c):
        self._debug(f'Channel create {self._fobj(c=c)}')

    async def _debug_on_guild_channel_update(self, b, a):
        self._debug(f'Channel update {self._fobj(c=b)}')

    async def _debug_on_guild_available(self, g):
        self._debug(f'Server available {self._fobj(g=g)}')

    async def _debug_on_guild_unavailable(self, g):
        self._debug(f'Server UNavailable {self._fobj(g=g)}')
