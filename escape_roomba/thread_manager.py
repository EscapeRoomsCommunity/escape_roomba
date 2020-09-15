import asyncio
import collections
import discord

from dataclasses import dataclass
from types import Optional


class ThreadManager:
    THREAD_EMOJI = '🧵'

    @dataclass 
    class _Thread:
        guild: discord.Guild
        origin_channel_id: Optional[int]
        origin_message_id: Optional[int]
        thread_channel_id: Optional[int]

    def __init__(self, context):
        self._context = context

        # {(origin_channel_id, origin_message_id): _Thread}
        self._thread_by_origin = {}

        # {thread_channel_id: _Thread}
        self._thread_by_channel = {}

        # {(channel_id, message_id): asyncio.Lock} for serializing fetches
        self._lock_by_message = collections.defaultdict(asyncio.Lock)

        context.add_listener_methods(self)

    #
    # Discord event listeners
    #

    async def _on_ready(self):
        await asyncio.gather(
            *[self._on_guild_join(g) for g in self._context.client.guilds])

    async def _on_guild_join(self, guild):
        for channel in guild.channels:
            self._check_channel(channel)
        await asyncio.gather(
            *[self._async_check_history(c) for c in guild.channels])

    async def _on_guild_remove(self, guild):
        for c in guild.channels:
            self._remove_channel(c)

    async def _on_message(self, message):
        pass

    async def _on_raw_message_delete(self, payload):
        pass

    async def _on_raw_bulk_message_delete(self, payload):
        pass

    async def _on_raw_message_edit(self, payload):
        pass

    async def _on_raw_reaction_add(self, payload):
        pass

    async def _on_raw_reaction_remove(self, payload):
        pass

    async def _on_raw_reaction_clear(self, payload):
        pass

    async def _on_raw_reaction_clear_emoji(self, payload):
        pass

    async def _on_guild_channel_delete(self, channel):
        self._remove_channel(channel)

    async def _on_guild_channel_create(self, channel):
        self._check_channel(channel)
        await self._async_check_history(channel)

    async def _on_guild_channel_update(self, channel):
        self._check_channel(channel)

    #
    # Internal methods
    #

    def _check_channel(self, channel):
        pass

    def _remove_channel(self, channel):
        pass

    async def _async_fetch_and_check_history(self, channel):
        await self._async_check_channel(channel)
        async for message in channel.history(limit=100, oldest_first=False):
            if any(str(m.emoji) == THREAD_EMOJI for m in message.reactions):
                self._async_fetch_and_check_message(channel, message)

    async def _async_fetch_and_check_message(self, channel_or_id, message_or_id):
        channel = (self._context.client.get_channel(channel_or_id)
                   if isinstance(channel_or_id, int) else channel_or_id)
        message_id = getattr(message, 'id', None) or message_id
        if channel is None or message_id is None:
            return

        # Wait our turn to fetch and process this message
        # (to avoid race conditions with overlapping fetch operations).
        key = (channel.id, message_id)
        last_fetch_done = self._fetch_done_event.get(key)
        this_fetch_done = self._fetch_done_event[key] = asyncio.Event()
        if last_fetch_done:
            await last_fetch_done.wait()

        message = await channel.fetch_message(message_id)
        self._check_message(message)
        # TODO process message !!

        # Activate the next waiting fetch (if any).
        if self._fetch_done_event.get(key) is not this_fetch_done:
            this_fetch_done.set()
        else:
            del self._fetch_in_progress[key]

    def _check_message(self, message):
        process
