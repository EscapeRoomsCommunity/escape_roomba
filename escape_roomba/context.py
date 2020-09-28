import argparse
import asyncio
import discord
import logging
import signal
import os


# Parser to use/extend for logging-related arguments.
args = argparse.ArgumentParser(add_help=False)
logging_args = args.add_argument_group('logging')
logging_args.add_argument('--debug', action='store_true')
logging_args.add_argument('--debug_discord', action='store_true')


class Context:
    """Global data shared by bot subfunctions.

    Attributes:
        logger: logging.Logger - for general reporting
        client: discord.Client - access to the Discord API
    """

    def __init__(self, parsed_args, inject_client=None, **kwargs):
        """Creates a Context.

        Args:
            parsed_args: argparse.Namespace - command line options
            inject_client: discord.Client-like - replacement Discord client
            **kwargs - other arguments for discord.Client

        Attributes:
            logger: logger.Logger - to use for bot-related logging
            client: discord.Client - to use for Discord access
        """

        signal.signal(signal.SIGINT, signal.SIG_DFL)  # Sane ^C behavior.
        logging.basicConfig(
            level=logging.DEBUG if parsed_args.debug else logging.INFO,
            format='%(asctime)s %(name)s [%(levelname)s] %(message)s',
            datefmt='%m-%d %H:%M:%S')
        logging.getLogger('discord').setLevel(
            logging.DEBUG if parsed_args.debug_discord else logging.WARNING)
        logging.captureWarnings(True)
        self.logger = logging.getLogger('bot')

        if inject_client is not None:
            self.client = inject_client
            self.bot_token = None  # Don't require for injected clients.
        else:
            self.client = discord.Client(**kwargs)

        self._event_listeners = {}  # Used by add_listener() (below).

    def run_forever(self):
        """Runs the Discord client's event loop with a bot token
        from the system environment."""

        try:
            bot_token = os.environ['ESCAPE_ROOMBA_BOT_TOKEN']
        except KeyError as e:
            bot_logger.critical(f'No ${e.args[0]}! See README.md.')
            raise SystemExit(1)

        self.client.run(bot_token)

    # discord.Client only dispatches one callback per event type
    # (discordpy.readthedocs.io/en/latest/api.html#discord.Client.event);
    # discord.ext.commands.Bot/.Cog allow multiple subscribers, but also
    # assume a specific UX, so we implement our own simple broadcasting.
    def add_listener(self, event_name, listener):
        """Registers an async function for a Discord event (like 'on_message').
        Multiple functions can be registered for the same event name.

        Args:
            event_name: str - name of event, like "on_message"
            listener: coroutine - called on event, with event args
        """

        # Argument validation. (Alas, discord.py can't check event names!)
        if not event_name.startswith('on_'):
            raise ValueError(f"event '{event_name}' doesn't start with 'on_'")
        if not asyncio.iscoroutinefunction(listener):
            raise TypeError(f"{listener} for '{event_name}' isn't async")

        # For the first listener, register a callback to run the listener list.
        listeners = self._event_listeners.setdefault(event_name, [])
        if not listeners:
            if event_name == 'on_error':
                # For on_error, serialize calls to preserve exc_info().
                async def run(*args, **kw):
                    [await l(*args, **kw) for l in listeners]
            else:
                # For non-error events, run all listeners asynchronously.
                async def run(*args, **kw):
                    await asyncio.gather(*[l(*args, **kw) for l in listeners])
            setattr(self.client, event_name, run)

        # Add to the listener list (captured by run() above).
        listeners.append(listener)

    def add_listener_methods(self, obj, prefix='_on_'):
        """Adds designated object methods (default '_on_*') as listeners.

        Args:
            obj - some class object with methods to invoke for events
            prefix - methods with this prefix will be added as listeners
        """

        for attr_name in dir(obj):
            if attr_name.startswith(prefix):
                event_name = f'on_{attr_name[len(prefix):]}'
                self.add_listener(event_name, getattr(obj, attr_name))
