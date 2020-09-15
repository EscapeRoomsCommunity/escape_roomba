import discord.abc


class HistoryBuffer:
    """Discord history tracker with guaranteed minimum per-channel history."""

    def __init__(self, context, min_age, min_per_channel):
        """Initializes the history buffer with a Context.

        Args:
            min_age: datetime.timedelta - retain messages newer than this
            min_per_channel: int - retain at least this many per channel

        Events sent (via context):
            on_history_loaded(guild) - sent after startup or new guild join
                guild: discord.Guild - this guild's channel history is loaded

            on_history_update(cause, before, after) - sent after message change
                (not sent for initial history load, or retention expiration)
                cause: discord.Message or discord.Raw*Event - original event
                before: discord.Message - old state (None if new message)
                after: discord.Message - new state (None if deleted)

        Listens for 'on_ready' and 'on_guild_available', then starts loading
        history; tracks channel/message creation/edit events thereafter.
        """

        self._context = context
        self._history_by_channel = {}
        self._pending_by_channel = {}  # Updates arriving while history loads

        context.add_listener_methods(self)

        # Route many raw message update events to _raw_message_update.
        for event_name in (
                'message', 'raw_message_delete', 'raw_bulk_message_delete',
                'raw_message_edit', 'raw_reaction_add', 'raw_reaction_remove',
                'raw_reaction_clear', 'raw_clear_emoji'):
            context.add_listener(event_name, self._async_message_update)

    def get_channel_history(channel):
        """Returns history for a text channel of any joined guild.

        Args:
            channel: discord.channel.Text or int channel ID to look up.

        Returns:
            dict from message id to Message object, in channel order.
        """

        id = getattr(channel, 'id', None) or channel
        if not isinstance(id, int):
            raise TypeError(f'channel {id} is not int (and has no .id)')
        return self._channel_history.setdefault(id, {})

    #
    # Discord event listeners
    #

    async def _on_ready(self):
        # Load existing channels at startup.
        await asyncio.gather(
            *[self._on_guild_join(g) for g in self._context.client.guilds])

    async def _on_guild_join(self, guild):
        await asyncio.gather(
            *[self._async_load_channel(c) for c in guild.channels])

    async def _on_guild_remove(self, guild):
        await asyncio.gather(
            *[self._async_remove_channel(c) for c in guild.channels])

    async def _on_guild_channel_delete(self, channel):
        pass

    async def _on_guild_channel_create(self, channel):
        pass

    # This listener is registered for many update events (see __init__).
    async def _async_message_update(self, arg):
        channel_id = (arg.channel.id if isinstance(arg, discord.Message) else
                      arg.channel_id)

        pending_updates = self._pending_by_channel.get(channel_id)
        if pending_updates is not None:
            pending_updates.append(arg)  # Updates suspended during fetch.
            return

        self._apply_update(arg)  # No fetch in progress, apply the update.

    #
    # Internal methods
    #

    async def _async_load_channel(channel):
        if channel.id in self._pending_by_channel:
            return  # Load already in progress

        # Collect updates that arrive while history downloads, to apply after,
        # to avoid race conditions between history download/update reception.
        pending_updates = []
        self._pending_by_channel[channel.id] = pending_updates
        self._history_by_channel[channel.id] = {}

        # TODO -- actually fetch history!

        # If the pending list was removed/replaced, the channel was
        # unloaded/reloaded during download, invalidating the download.
        if self._pending_by_channel.get(channel.id) is not pending:
            return

        # Apply all the buffered updates (this is synchronous).
        for update in pending:
            self._apply_update(update)
        del self._pending_by_channel[channel.id]

    def _apply_update(update):
        # TODO - apply the update!
