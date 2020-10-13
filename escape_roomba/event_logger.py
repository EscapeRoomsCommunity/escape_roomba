import datetime
import logging

import discord
import discord.abc

from escape_roomba.format_util import fid, fobj

_logger = logging.getLogger('bot.events')


class EventLogger:
    """Discord event listener that logs server/connection events."""

    def __init__(self, context):
        """Initializes with a Context and starts listening for events."""
        self._discord = context.discord()
        context.add_listener_methods(self)
        if _logger.isEnabledFor(logging.DEBUG):
            context.add_listener_methods(self, prefix='_debug_on_')

    def _fobj(self, **kw):
        return fobj(client=self._discord, **kw)

    #
    # Logging listeners for 'notable' message types.
    #

    async def _on_connect(self):
        _logger.info('\n    Connected to Discord:'
                     f'\n      {self._discord.ws.gateway}')

    async def _on_disconnect(self):
        _logger.info(f'Disconnected from Discord')

    async def _on_resumed(self):
        _logger.info(f'Resumed Discord session')

    async def _on_ready(self):
        c = self._discord
        _logger.info(f'\n    Ready in {len(c.guilds)} servers as {c.user}:' +
                     ''.join(f'\n      "{g}"' for g in c.guilds))
        invite_url = discord.utils.oauth_url(
            (await c.application_info()).id,
            discord.Permissions(
                manage_channels=True, add_reactions=True, read_messages=True,
                send_messages=True, manage_messages=True,
                read_message_history=True, manage_roles=True))
        _logger.info('\n    Open this link to add this bot to more servers:'
                     f'\n      {invite_url}')

    async def _on_guild_join(self, guild):
        _logger.info(f'\n    Joined Discord guild (server) "{guild}"')

    async def _on_guild_remove(self, guild):
        _logger.info(f'\n    Removed from Discord guild (server) "{guild}"')

    async def _on_error(self, event, *args, **kwargs):
        _logger.exception(f'\nException in "{event}" handler:')

    #
    # Debug-only logging listeners for all message types.
    #

    async def _debug_on_message(self, m):
        _logger.debug(f'Received message\n    {self._fobj(m=m)}')

    async def _debug_on_message_delete(self, m):
        _logger.debug(f'\n    Delete: {self._fobj(m=m)}')

    async def _debug_on_bulk_message_delete(self, ms):
        _logger.debug(f'\n    Bulk delete of {len(ms)} messages:\n' +
                      '\n'.join(f'      {self._fobj(m=m)}' for m in ms))

    async def _debug_on_raw_message_delete(self, p):
        _logger.debug(f'\n    Raw delete: ' +
                      self._fobj(g=p.guild_id, c=p.channel_id, m=p.message_id))

    async def _debug_on_raw_bulk_message_delete(self, p):
        _logger.debug(
            f'\n    Raw bulk delete of {len(p.message_ids)} messages in '
            f'{self._fobj(g=p.guild_id, c=p.channel_id)}:'
            ''.join(f'\n      {self._fobj(m=m)}' for m in p.message_ids))

    async def _debug_on_message_edit(self, b, a):
        _logger.debug('Message edit:'
                      f'\n    Old {self._fobj(m=b)}\n'
                      f'\n    New {self._fobj(m=a)}')

    async def _debug_on_raw_message_edit(self, p):
        _logger.debug(
            '\n    Raw edit: ' +
            self._fobj(c=p.channel_id, m=p.message_id,
                       u=int(p.data.get('author', {}).get('id', 0))))

    async def _debug_on_reaction_add(self, r, u):
        _logger.debug(f'\n    Add [{r.emoji}] {self._fobj(u=u)} to\n    ' +
                      self._fobj(m=r.message))

    async def _debug_on_raw_reaction_add(self, p):
        _logger.debug(
            f'\n    Raw add [{p.emoji}] '
            f'{self._fobj(u=p.user_id)} to\n      ' +
            self._fobj(g=p.guild_id, c=p.channel_id, m=p.message_id))

    async def _debug_on_reaction_remove(self, r, u):
        _logger.debug(
            f'\n    Remove [{r.emoji}] {self._fobj(u=u)} from\n    ' +
            self._fobj(m=r.message))

    async def _debug_on_raw_reaction_remove(self, p):
        _logger.debug(
            f'\n    Raw remove [{p.emoji}] '
            f'{self._fobj(u=p.user_id)} from\n      ' +
            self._fobj(g=p.guild_id, c=p.channel_id, m=p.message_id))

    async def _debug_on_reaction_clear(self, m, rs):
        _logger.debug(f'\n    Clear all reactions from {self._fobj(m=m)}:' +
                      ''.join(f'\n      {r.count}x [{r.emoji}]' for r in rs))

    async def _debug_on_raw_reaction_clear(self, p):
        _logger.debug('\n    Raw clear all reactions on\n      ' +
                      self._fobj(g=p.guild_id, c=p.channel_id, m=p.message_id))

    async def _debug_on_reaction_clear_emoji(self, r):
        _logger.debug(f'\n    Clear {r.count}x [{r.emoji}] on'
                      f'\n      {self._fobj(m=r.message)}')

    async def _debug_on_raw_reaction_clear_emoji(self, p):
        _logger.debug(f'\n    Raw clear [{p.emoji}] on\n      ' +
                      self._fobj(g=p.guild_id, c=p.channel_id, m=p.message_id))

    async def _debug_on_guild_channel_delete(self, c):
        _logger.debug(f'\n    Delete {self._fobj(c=c)}')

    async def _debug_on_guild_channel_create(self, c):
        _logger.debug(f'\n    Create {self._fobj(c=c)}')

    async def _debug_on_guild_channel_update(self, b, a):
        _logger.debug(f'\n    Update {self._fobj(c=a)}')

    async def _debug_on_guild_available(self, g):
        _logger.debug(f'Guild avail {self._fobj(g=g)}')

    async def _debug_on_guild_unavailable(self, g):
        _logger.debug(f'Guild unavail {self._fobj(g=g)}')


def event_logger_main():
    """Main entry point from 'event_logger' wrapper script (pyproject.yaml)."""

    import argparse
    import signal

    import escape_roomba.context
    import escape_roomba.event_logger

    signal.signal(signal.SIGINT, signal.SIG_DFL)
    arg_parser = argparse.ArgumentParser(parents=[escape_roomba.context.args])
    context = escape_roomba.context.Context(
        parsed_args=arg_parser.parse_args(), max_messages=None,
        intents=discord.Intents(
            guilds=True, members=True,
            guild_messages=True, guild_reactions=True))

    escape_roomba.event_logger.EventLogger(context)
    context.run_forever()
