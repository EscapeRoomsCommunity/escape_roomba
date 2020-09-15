"""Main Discord bot program.

Called by the poetry-generated 'run_bot' script which invokes main() below
(see pyproject.yaml).
"""

import argparse
import logging
import os
import signal

import discord

import escape_roomba.context
import escape_roomba.event_logger


def main():
    """Main entry point from 'run_bot' wrapper script (see pyproject.yaml)."""

    signal.signal(signal.SIGINT, signal.SIG_DFL)  # Sane ^C behavior.
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('--debug', action='store_true')
    arg_parser.add_argument('--debug_discord', action='store_true')
    args = arg_parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format='%(asctime)s %(name)s [%(levelname)s] %(message)s',
        datefmt='%m-%d %H:%M:%S')
    logging.getLogger('discord').setLevel(
        logging.DEBUG if args.debug_discord else logging.WARNING)
    logging.captureWarnings(True)
    bot_logger = logging.getLogger('bot')

    try:
        bot_token = os.environ['ESCAPE_ROOMBA_BOT_TOKEN']
    except KeyError as e:
        bot_logger.critical(f'*** No ${e.args[0]}! See README.md.')
        return 1

    context = escape_roomba.context.Context()
    context.logger = bot_logger
    context.client = discord.Client()
    escape_roomba.event_logger.EventLogger(context)
    context.client.run(bot_token)
