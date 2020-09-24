import asyncio
import collections
import discord
import logging
import re

from dataclasses import dataclass
from typing import Optional

from escape_roomba.format_util import fid


# TODO:
# - put a card at the top of new thread channels
# - manage visibility of thread channels (origin author + people who react?)
# - allow people to drop out of a thread channel (emoji on top card?)
# - allow specifying where people can/can't create threads?
# - let people set thread channel name & topic (commands start with emoji?)
# - archive thread channels once inactive for a while
# - handle orphaned threads (post something and edit the top card?)
# - maybe use emoji to indicate number/recency of messages in thread???


class ThreadManager:
    """Allows users to spawn thread channels by adding a 🧵 reaction.

    When a 🧵 reaction is added to any text channel message, a new thread
    channel is created, initially named "#🧵" plus the first few words of the
    origin message, added to the end of the original message's category.

    The origin message channel/message ID are added to the thread channel's
    topic, allowing them to be reassociated if the bot restart.
    """

    _THREAD_EMOJI = '🧵'  # Reaction emoji trigger, and channel prefix.
    _ELLIPSIS = '…'  # Used at the end of thread channel names.

    # Used to extract channel/message ID from existing thread channel topics.
    _TOPIC_REGEX = re.compile(r'.*\[id=([0-9a-f]*)/([0-9a-f]*)\] *', re.I)

    @dataclass
    class _Thread:
        """Tracks a created thread channel, and its origin message."""
        thread_channel: discord.TextChannel
        origin_channel_id: int
        origin_message_id: int

    def __init__(self, context):
        self._context = context
        self._logger = context.logger.getChild('thread')
        self._loop = asyncio.get_event_loop()

        # _Thread objects are indexed by origin message *and* thread channel.
        self._thread_by_origin = {}   # {orig_chan_id: {orig_msg_id: _Thread}}
        self._thread_by_channel = {}  # {thread_channel.id: _Thread}

        # Used to serialize message processing; see _async_maybe_update.
        self._update_done = {}   # {(chan_id, msg_id): asyncio.Future}

        context.add_listener_methods(self)

    #
    # Discord event listeners
    # (https://discordpy.readthedocs.io/en/latest/api.html#event-reference).
    #
    # This code uses "raw" events to avoid depending on cache coverage,
    # so updates often require a message fetch to get context. Fetches are
    # independent and asynchronous; to avoid races that could have out-of-date
    # data arriving last, all message updates go through _async_maybe_update().
    #

    async def _on_ready(self):
        # Forget everything from previous connections and re-sync.
        self._thread_by_origin = {}
        self._thread_by_channel = {}

        # On startup, initialize the guilds we're already joined to.
        await asyncio.gather(
            *[self._on_guild_join(g) for g in self._context.client.guilds])

    async def _on_guild_join(self, guild):
        # For a new guild, scan all channels and recent channel history.
        # (Scan existing channels first to avoid double-creation!)
        await asyncio.gather(
            *[self._async_check_channel(channel=c) for c in guild.channels])
        await asyncio.gather(
            *[self._async_fetch_history(channel=c) for c in guild.channels])

    async def _on_guild_remove(self, guild):
        # Remove _Thread objects on departure (avoid confusion when rejoining).
        await asyncio.gather(
            *[self._async_forget_channel(channel=c) for c in guild.channels])

    async def _on_message(self, message):
        await self._async_maybe_update(channel=message.channel,
                                       message=message)

    async def _on_raw_message_delete(self, p):
        await self._async_maybe_update(
            channel_id=p.channel_id, message_id=p.message_id)

    async def _on_raw_bulk_message_delete(self, p):
        for mi in p.message_ids:
            await self._async_maybe_update(
                channel_id=p.channel_id, message_id=mi)

    async def _on_raw_message_edit(self, p):
        await self._async_maybe_update(
            channel_id=p.channel_id, message_id=p.message_id)

    async def _on_raw_reaction_add(self, p):
        # Don't react to our own emoji reactions (superfluous).
        if p.user_id != self._context.client.user.id:
            await self._async_maybe_update(
                channel_id=p.channel_id, message_id=p.message_id,
                emoji=p.emoji)

    async def _on_raw_reaction_remove(self, p):
        # Don't react to our own emoji reactions (superfluous).
        if p.user_id != self._context.client.user.id:
            await self._async_maybe_update(
                channel_id=p.channel_id, message_id=p.message_id,
                emoji=p.emoji)

    async def _on_raw_reaction_clear(self, p):
        await self._async_maybe_update(
            channel_id=p.channel_id, message_id=p.message_id)

    async def _on_raw_reaction_clear_emoji(self, payload):
        await self._async_update_message(
            channel_id=p.channel_id, message_id=p.message_id, emoji=p.emoji)

    async def _on_guild_channel_delete(self, channel):
        # Take note when a thread channel is deleted.
        await self._async_forget_channel(channel)

    async def _on_guild_channel_create(self, channel):
        # Check if a new channel is a thread channel.
        await self._async_check_channel(channel)
        await self._async_fetch_history(channel=channel)

    async def _on_guild_channel_update(self, channel):
        # Check if a modified channel is a thread channel.
        await self._async_check_channel(channel)

    #
    # Internal methods
    #

    async def _async_maybe_update(self, channel_id=None, channel=None,
                                  message=None, message_id=None, emoji=None):
        """If a message update is relevant, fetches and processes its latest
        version, serializing multiple fetches of the same message.
        One each of message/message_id and channel/channel_id must be given.

        Args:
            channel_id: int - ID of channel containing message *OR*
            channel: discord.TextChannel - channel object containing message
            message_id: int - ID of message to fetch and process *OR*
            message: discord.Message - contents of updated message
            emoji: str, discord.*Emoji - emoji of reaction change (or None)
        """

        # Handle various ways channel and message can be supplied
        ci = channel_id or channel.id
        mi = message_id or message.id

        # Skip irrelevant changes; a change is "relevant" if:
        # - there is an existing fetch in progress for the message OR
        # - the message is an existing thread channel origin OR
        # - the message has a thread emoji reaction OR
        # - there was a change to thread emoji reactions
        if ((ci, mi) not in self._update_done and
            mi not in self._thread_by_origin.get(ci, {}) and
            (emoji is None or str(emoji) != self._THREAD_EMOJI) and
            (message is None or
             all(str(r) != self._THREAD_EMOJI for r in message.reactions))):
            return

        # Serialize with per-message Futures. (Locks would accumulate.)
        # Fetch operations are implicitly chained; the _update_done map
        # holds a Future which will be true when all fetches are complete.
        # Each new fetch captures the existing Future, installs a new Future,
        # waits for the previous one, performs its fetch, and sets the new one.
        last_update_done = self._update_done.get((ci, mi))
        this_update_done = self._loop.create_future()
        self._update_done[(ci, mi)] = this_update_done
        try:
            if last_update_done is not None:
                await last_update_done

            channel = channel or self._context.client.get_channel(channel_id)
            if channel:
                self._logger.debug('Fetch m=%s ...', fid(mi))
                try:
                    fetched_message = await channel.fetch_message(mi)
                    await self._async_process_message(fetched_message)
                except discord.errors.NotFound:
                    self._logger.debug('Fetch m=%s: Gone', fid(mi))
                    await self._async_message_gone(channel_id=ci, message_id=mi)
            else:
                # No channel available, treat the message as missing.
                self._logger.debug('Fetch m=%s: !Chan', fid(mi))
                await self._async_message_gone(channel_id=ci, message_id=mi)

            # If another fetch is waiting for this message, let it run.
            if self._update_done.get((ci, mi)) is this_update_done:
                del self._update_done[(ci, mi)]  # Nobody took it; OK to del.

        finally:
            this_update_done.set_result(True)  # Run the next fetch (if any).

    async def _async_process_message(self, message):
        """Examines the state of a message of interest.
        Called by _async_update_message with serialization enforced."""

        ci, mi, rs = message.channel.id, message.id, message.reactions
        thread = self._thread_by_origin.get(ci, {}).get(mi)
        r = next((r for r in rs if str(r.emoji) == self._THREAD_EMOJI), None)

        if self._logger.isEnabledFor(logging.DEBUG):
            tid = thread.thread_channel.id if thread else None
            rt = f'x{r.count}{" w/me" if r.me else ""}' if r else 'None'
            self._logger.debug(
                f'Check m={fid(mi)}:\n'
                f'    reaction={rt} existing={fid(tid) if tid else "None"}')

        # If there is no existing thread channel and we have not already piled
        # on to the thread emoji, create a new channel (and pile on the emoji).
        if r is not None and r.count > 0 and not r.me:
            if thread is None:
                await self._async_create_thread_channel(message)
            await message.add_reaction(r)  # Only after creation.

    async def _async_create_thread_channel(self, message):
        """Creates a new thread channel based on an origin message thas
        someone has just added a thread emoji reaction to."""

        first_words = ''
        for match in re.finditer(r'\w+', message.content):
            word, dash = match.group(), ('-' if first_words else '')
            remaining = 20 - len(first_words) - len(dash) - len(word)
            if remaining >= 0:
                first_words += f'{dash}{word}'
                continue
            if len(first_words) < 10:
                first_words += f'{dash}{word[:remaining]}'
            first_words += self._ELLIPSIS
            break

        ci, mi = message.channel.id, message.id
        name = f'{self._THREAD_EMOJI}{first_words}'
        topic = f'[id={ci:x}/{mi:x}]'
        if self._logger.isEnabledFor(logging.DEBUG):
            self._logger.debug(f'Creating #{name}:\n'
                               f'    oc={fid(ci)} om={fid(mi)}\n'
                               f'    topic="{topic}"')

        channel = await message.guild.create_text_channel(
            name=name, category=message.channel.category,
            position=len(message.guild.channels), topic=topic,
            reason='Thread creation')

        t = self._Thread(origin_channel_id=ci, origin_message_id=mi,
                         thread_channel=channel)
        self._thread_by_origin.setdefault(ci, {})[mi] = t
        self._thread_by_channel[channel.id] = t

    async def _async_message_gone(self, channel_id, message_id):
        """Handles a message that was deleted."""

        t = self._thread_by_origin.setdefault(channel_id, {}).get(message_id)
        if t is not None:
            # TODO: mark the thread as orphaned (in its intro card?)
            pass

    async def _async_fetch_history(self, channel):
        """Fetches and examines the recent history of a channel that appeared
        (startup, server join, channel creation, visibility change)."""

        if channel.type != discord.ChannelType.text:
            return

        # Go through the history and trigger updates for unprocessed messages;
        # skip anything we already made a channel for (no need to re-update).
        await asyncio.gather(*[
            self._async_maybe_update(channel=channel, message=m)
            async for m in channel.history(limit=100, oldest_first=False)
            if m.id not in self._thread_by_origin.get(channel.id, {})])

    async def _async_check_channel(self, channel):
        """Examines a channel; add existing thread channels to tracking."""

        if channel.type != discord.ChannelType.text:
            return

        # Deindex any existing _Thread object for this thread channel ID.
        old_t = self._thread_by_channel.pop(channel.id, None)
        old_ci = old_t and old_t.origin_channel_id
        old_mi = old_t and old_t.origin_message_id
        if old_ci and old_mi:
            del self._thread_by_origin[old_ci][old_mi]

        # If this is a thread channel, create and index the _Thread.
        topic_match = self._TOPIC_REGEX.match(channel.topic or '')
        if topic_match and channel.name.startswith(self._THREAD_EMOJI):
            ci, mi = (int(g, 16) for g in topic_match.groups())
            t = old_t if (ci, mi) == (old_ci, old_mi) else self._Thread(
                origin_channel_id=ci, origin_message_id=mi,
                thread_channel=channel)
            self._thread_by_origin.setdefault(ci, {})[mi] = t
            self._thread_by_channel[channel.id] = t

            if t is not old_t:
                if self._logger.isEnabledFor(logging.DEBUG):
                    self._logger.debug(f'Found #{channel.name}:\n'
                                       f'    oc={fid(ci)} om={fid(mi)}\n'
                                       f'    tc={fid(channel.id)}\n'
                                       f'    topic="{channel.topic}"')

                # For a new channel, update the origin message.
                # TODO - avoid redundancy if we just created the thread?
                await self._async_maybe_update(channel_id=ci, message_id=mi)

    async def _async_forget_channel(self, channel):
        """Handles a channel that is no longer visible (server detach,
        channel deleted, visibility change)."""

        # If it was a thread channel, remove it from tracking.
        t = self._thread_by_channel.pop(channel.id, None)
        if t is not None:
            ci, mi = t.origin_channel_id, t.origin_message_id
            del self._thread_by_origin[ci][mi]
            if self._logger.isEnabledFor(logging.DEBUG):
                self._logger.debug(f'Removed #{channel.name}:\n'
                                   f'    oc={fid(ci)} om={fid(mi)}\n'
                                   f'    tc={fid(channel.id)}')
