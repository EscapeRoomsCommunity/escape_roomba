import asyncio


class Context:
    """Global data shared by bot subfunctions.

    Attributes:
        logger: logging.Logger - for general reporting
        client: discord.Client - access to the Discord API
    """

    def __init__(self):
        """Creates an empty Context. The caller must populate attributes."""
        self.logger = None
        self.client = None

        self._event_listeners = {}  # Used by add_listener() (below).

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
