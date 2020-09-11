import asyncio
import inspect


class Context:
    """Global data shared by bot subfunctions."""

    def __init__(self, client):
        self.client = client
        self._event_listeners = {}

    # discord.Client only dispatches one callback per event type
    # (discordpy.readthedocs.io/en/latest/api.html#discord.Client.event);
    # discord.ext.commands.Bot/.Cog allow multiple subscribers, but also
    # assume a specific UX, so we implement our own simple broadcasting.
    def add_listener(self, event_name, handler):
        """Registers an async function for a Discord event (like 'on_message').
        Multiple functions can be registered for the same event name."""

        # Fail up front if the callback has the wrong type.
        # (Sadly, discord.Client has no way to verify valid event names!)
        if not event_name.startswith('on_'):
            raise ValueError(f'event "{event_name}" doesn\'t start with "on_"')
        if not inspect.iscoroutinefunction(handler):
            raise ValueError(f'{handler} for "{event_name}" isn\'t async')

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
        listeners.append(handler)

    def add_listener_methods(self, obj):
        """Adds all methods named 'on_*' for an object as event listeners."""

        for attr_name in dir(obj):
            if attr_name.startswith('on_'):
                self.add_listener(attr_name, getattr(obj, attr_name))
