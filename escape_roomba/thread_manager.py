import asyncio
import collections
import discord
import discord.utils
import logging
import regex
import unicodedata

from escape_roomba.format_util import fobj
from escape_roomba.async_exclusive import AsyncExclusive
from escape_roomba.thread_channel import ThreadChannel

_RECENT_COUNT = 100  # Number of recent messages to scan on startup.

_logger = logging.getLogger('bot.thread')


# TODO:
# - manage visibility of thread channels (origin author + people who react?)
# - allow specifying where people can/can't create threads?
# - let people set thread channel name & topic (commands start with emoji?)
# - archive thread channels once inactive for a while (or on request)
# - use emoji (eg. 🔥) to indicate activity level in thread???

class ThreadManager:
    """Allows users to spawn thread channels by adding a 🧵 reaction.

    When a 🧵 reaction is added to any text channel message, a new thread
    channel is created, initially named "#🧵" plus the first few words of the
    origin message, added to the end of the original message's category.

    The origin message channel/message ID are added to the thread channel's
    topic, allowing them to be reassociated if the bot restart.
    """

    def __init__(self, context):
        self._context = context
        self._message_exclusive = AsyncExclusive()  # To serialize updates.

        # ThreadChannel objects indexed by origin message *and* thread channel.
        self._thread_by_origin = {}   # {orig_chan_id: {orig_msg_id: _Thread}}
        self._thread_by_channel = {}  # {thread_channel.id: _Thread}

        context.add_listener_methods(self)

    #
    # Discord event listeners
    # (https://discordpy.readthedocs.io/en/latest/api.html#event-reference)
    #
    # Many events require asynchronous steps to get context; to avoid races,
    # handlers call _async_message_update() and/or _async_channel_update(),
    # which acquire locks and then take appropriate action.
    #

    async def _on_ready(self):
        # Forget everything from previous connections and re-sync.
        self._thread_by_origin = {}
        self._thread_by_channel = {}

        # On startup, initialize the guilds we're already joined to.
        await asyncio.gather(
            *[self._on_guild_join(g) for g in self._context.discord().guilds])
        _logger.info('🧵🧵🧵 Ready! 🧵🧵🧵')

    async def _on_guild_join(self, guild):
        # Scan *all* existing channels *before* checking history to avoid
        # double-creating previously existing thread channels.
        await asyncio.gather(
            *[self._async_channel_update(channel=c) for c in guild.channels])
        await asyncio.gather(
            *[self._async_fetch_recents(channel=c) for c in guild.channels])

    async def _on_guild_remove(self, guild):
        # Remove _Thread objects on departure (avoid confusion when rejoining).
        await asyncio.gather(
            *[self._async_forget_channel(channel=c) for c in guild.channels])

    async def _on_message(self, m):
        if m.author.id != self._context.discord().user.id:
            await self._async_message_update(message=m)

    async def _on_raw_message_delete(self, p):
        await self._async_message_update(
            channel_id=p.channel_id, message_id=p.message_id)

    async def _on_raw_bulk_message_delete(self, p):
        for mi in p.message_ids:
            await self._async_message_update(
                channel_id=p.channel_id, message_id=mi)

    async def _on_raw_message_edit(self, p):
        me = self._context.discord().user  # Skip our own edits.
        if p.data.get('author', {}).get('id', '') != str(me.id):
            await self._async_message_update(
                channel_id=p.channel_id, message_id=p.message_id)

    async def _on_raw_reaction_add(self, p):
        if p.user_id != self._context.discord().user.id:
            await self._async_message_update(
                channel_id=p.channel_id, message_id=p.message_id, emoji=p.emoji)

    async def _on_raw_reaction_remove(self, p):
        if p.user_id != self._context.discord().user.id:
            await self._async_message_update(
                channel_id=p.channel_id, message_id=p.message_id, emoji=p.emoji)

    async def _on_raw_reaction_clear(self, p):
        await self._async_message_update(
            channel_id=p.channel_id, message_id=p.message_id)

    async def _on_raw_reaction_clear_emoji(self, payload):
        await self._async_message_update(
            channel_id=p.channel_id, message_id=p.message_id, emoji=p.emoji)

    async def _on_guild_channel_delete(self, channel):
        await self._async_forget_channel(channel)

    async def _on_guild_channel_create(self, channel):
        await asyncio.gather(self._async_channel_update(channel),
                             self._async_fetch_recents(channel))

    async def _on_guild_channel_update(self, before, after):
        await self._async_channel_update(after)

    #
    # Internal methods
    #
    # Operations lock self._exclusive_message using the origin message ID (int)
    # of the thread (or thread-to-be) to avoid races.
    #

    async def _async_message_update(self, channel_id=None, channel=None,
                                    message=None, message_id=None, emoji=None):
        """If an update looks relevant, acquires a lock, re-fetches, and
        processes a message. Requires one of channel_id/message_id or message.

        Args:
            channel_id: int - ID of channel containing message
            message_id: int - ID of message to fetch and process *OR*
            message: discord.Message - contents of updated message
            emoji: str, discord.*Emoji - emoji of reaction change
        """

        ci = channel_id or message.channel.id
        mi = message_id or message.id

        # The change could be a relevant *origin* message update if:
        #   there is an existing fetch in progress for the message OR
        #   the message is an existing thread channel origin OR
        #   the message has a 🧵 emoji reaction OR
        #   there was a change to 🧵 emoji reactions (not by this bot)
        if (self._message_exclusive.is_locked(id) or
            mi in self._thread_by_origin.get(ci, {}) or
                ThreadChannel.relevant_origin_update(
                    emoji=emoji, message=message)):
            async with self._message_exclusive.locker(mi):  # Lock & refresh.
                t = self._thread_by_origin.get(ci, {}).get(mi)
                if t is not None:  # Message is an existing thread origin.
                    if not await t.async_refresh_origin():  # Thread deleted!
                        del self._thread_by_origin[ci][mi]
                        del self._thread_by_channel[t.thread_channel.id]
                else:  # No thread based on this message; maybe make one?
                    t = await ThreadChannel.async_maybe_create_from_origin(
                        self._context.discord(), ci, mi)
                    if t is not None:  # New thread!
                        self._thread_by_origin.setdefault(ci, {})[mi] = t
                        self._thread_by_channel[t.thread_channel.id] = t

        # The change could be a relevant *intro* message update if:
        #   the message's channel is a thread channel AND
        #   ( there isn't a full set of intro messages OR
        #     the update is for an existing intro message )
        t = self._thread_by_channel.get(ci)
        if t is not None and t.relevant_intro_update(message_id=mi):
            _logger.debug('Fetching intro after update...\n'
                         f'    {fobj(c=ci, m=message or mi)}')
            async with self._message_exclusive.locker(t.origin_message_id):
                await t.async_refresh_intro()

    async def _async_channel_update(self, channel):
        """Examines channel metadata; registers existing thread channels."""

        if channel.id in self._thread_by_channel:
            return  # The channel is already registered.

        thread = ThreadChannel.maybe_attach_to_thread_channel(channel)
        if thread is None:
            return  # Not identified as a preexisting thread channel.

        ci, mi = thread.origin_channel_id, thread.origin_message_id
        async with self._message_exclusive.locker(mi):
            if channel.id in self._thread_by_channel:
                return  # The channel was registered while locking.

            dup = self._thread_by_origin.get(ci, {}).get(mi)
            if dup:
                _logger.error(
                    'Multiple channels for the same origin!!\n'
                    f'    {fobj(c=dup.thread_channel)}\n'
                    f'    {fobj(c=channel)}')
                return

            self._thread_by_origin.setdefault(ci, {})[mi] = thread
            self._thread_by_channel[channel.id] = thread
            await thread.async_refresh_intro()
            if not await thread.async_refresh_origin():  # Deleted already!
                del self._thread_by_origin[ci][mi]
                del self._thread_by_channel[channel.id]

    async def _async_fetch_recents(self, channel):
        """Examines the recent history of a channel that just appeared
        (startup, server join, channel creation, visibility change)."""

        if channel.type != discord.ChannelType.text:
            return

        # Go through the history and check for unprocessed new threads.
        async for m in channel.history(limit=_RECENT_COUNT, oldest_first=False):
            if not ThreadChannel.relevant_origin_update(message=m):
                async with self._message_exclusive.locker(mi):
                    ci, mi = message.channel.id, message.id
                    if self._thread_by_origin.get(ci, {}).get(mi) is None:
                        t = await ThreadChannel.async_maybe_create_from_origin(
                            self._context.discord(), ci, mi)
                        if t is not None:
                            self._thread_by_origin.setdefault(ci, {})[mi] = t
                            self._thread_by_channel[t.thread_channel.id] = t

    async def _async_forget_channel(self, channel):
        """Handles a channel that is no longer visible (server detach,
        channel deleted, visibility change)."""

        # Find the ThreadChannel to know which message ID to lock.
        thread = self._thread_by_channel.get(channel.id)
        if thread is None:
            return

        async with self._message_exclusive.locker(thread.origin_message_id):
            recheck = self._thread_by_channel.get(channel.id)
            if recheck is None:
                # The ThreadChannel may have been removed while locking.
                return

            assert recheck is thread  # If not removed, should be the same.
            assert channel.id == thread.thread_channel.id
            ci, mi = thread.origin_channel_id, thread.origin_message_id
            del self._thread_by_channel[channel.id]
            del self._thread_by_origin[ci][mi]
            if _logger.isEnabledFor(logging.DEBUG):
                _logger.debug('Thread channel was deleted:\n'
                             f'    {fobj(c=channel)}\n'
                             f'    origin: {fobj(c=ci, m=mi)}')


def thread_bot_main():
    """Main entry point from 'thread_bot' wrapper script (pyproject.yaml)."""

    import argparse

    import escape_roomba.context
    import escape_roomba.event_logger

    arg_parser = argparse.ArgumentParser(parents=[escape_roomba.context.args])
    context = escape_roomba.context.Context(
        parsed_args=arg_parser.parse_args(),
        max_messages=None,
        fetch_offline_members=False,
        guild_subscriptions=False)

    escape_roomba.event_logger.EventLogger(context)
    escape_roomba.thread_manager.ThreadManager(context)
    context.run_forever()
