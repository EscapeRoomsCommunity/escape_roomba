"""Main Discord bot program.

Called by the poetry-generated 'run_bot' script which invokes main() below
(see pyproject.yaml).
"""

import logging
import os
import signal

import discord

import escape_roomba.context


def main():
    """Main entry point from 'run_bot' wrapper script (see pyproject.yaml)."""

    signal.signal(signal.SIGINT, signal.SIG_DFL)  # Sane ^C behavior.
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(name)s [%(levelname)s] %(message)s',
        datefmt='%m-%d %H:%M:%S')
    for name in logging.root.manager.loggerDict:  # Suppress library chatter.
        logging.getLogger(name).setLevel(logging.WARNING)

    try:
        bot_token = os.environ['ESCAPE_ROOMBA_BOT_TOKEN']
    except KeyError as e:
        logging.critical(f'*** No ${e.args[0]}! See README.md.')
        return 1

    context = escape_roomba.context.Context(discord.Client())
    status_logger = StatusLogger(context)
    context.client.run(bot_token)


class StatusLogger:
    """Logs notable server/connection events."""

    def __init__(self, context):
        self.context = context
        context.add_listener_methods(self)

    async def on_connect(self):
        logging.info('Connected to Discord:\n'
                     f'    {self.context.client.ws.gateway}')

    async def on_disconnect(self):
        logging.info(f'Disconnected from Discord')

    async def on_resumed(self):
        logging.info(f'Resumed Discord session')

    async def on_ready(self):
        c = self.context.client
        logging.info(f'Ready in {len(c.guilds)} servers (as {c.user}):' +
                     ''.join(f'\n    {g.name}' for g in c.guilds))
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
        logging.info(f'Invite link to add servers:\n' + f'    {invite_url}')

    async def on_guild_join(self, guild):
        logging.info(f'Joined Discord guild (server) "{guild.name}"')

    async def on_guild_remove(self, guild):
        logging.info(f'Removed from Discord guild (server) "{guild.name}"')

    async def on_error(self, event, *args, **kwargs):
        logging.exception(f'Exception in "{event}" handler:')
