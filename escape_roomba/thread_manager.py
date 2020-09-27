import asyncio
import collections
import discord
import discord.utils
import logging
import regex
import unicodedata

from escape_roomba.format_util import fobj
from escape_roomba.async_exclusive import AsyncExclusive


# TODO:
# - manage visibility of thread channels (origin author + people who react?)
# - allow specifying where people can/can't create threads?
# - let people set thread channel name & topic (commands start with emoji?)
# - archive thread channels once inactive for a while (or on request)
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
    _ELLIPSIS = '…'       # Used at the end of thread channel names.
    _CHANNEL_LENGTH = 20  # Maximum length of generated channel name

    _FETCH_INTRO = 2     # Look for our embed & one other.
    _FETCH_RECENT = 100  # Scan on startup for missed commands.

    # Used to extract channel/message ID from existing thread channel topics.
    _TOPIC_REGEX = regex.compile(
        r'.*\[(?:id=)?(<#[0-9]+>|[0-9a-f]+)/([0-9a-f]+)\][\s.]*', regex.I)

    # Used to strip things when generating Discord channel names from text.
    _CHANNEL_CLEANUP_REGEX = regex.compile(
        r'([^\p{L}\p{M}\p{N}\p{Sk}\p{So}\p{Cf}]|https?://(www\.?))+')

    class _Thread:
        """Tracks a created thread channel, and its origin message."""

        def __init__(self, channel, origin_cid, origin_mid):
            self.thread_channel = channel
            self.origin_channel_id = origin_cid
            self.origin_message_id = origin_mid
            self.intro_messages = None  # None for not loaded (vs [] for empty)

    def __init__(self, context):
        self._context = context
        self._logger = context.logger.getChild('thread')
        self._message_exclusive = AsyncExclusive()  # To serialize updates.

        # _Thread objects are indexed by origin message *and* thread channel.
        self._thread_by_origin = {}   # {orig_chan_id: {orig_msg_id: _Thread}}
        self._thread_by_channel = {}  # {thread_channel.id: _Thread}

        context.add_listener_methods(self)

    #
    # Discord event listeners
    # (https://discordpy.readthedocs.io/en/latest/api.html#event-reference).
    #
    # This code uses "raw" events to avoid depending on cache coverage,
    # so updates often require a message fetch to get context. Fetches are
    # independent and asynchronous; to avoid races that could have out-of-date
    # data arriving last, message updates go through _async_check_message().
    #

    async def _on_ready(self):
        # Forget everything from previous connections and re-sync.
        self._thread_by_origin = {}
        self._thread_by_channel = {}

        # On startup, initialize the guilds we're already joined to.
        await asyncio.gather(
            *[self._on_guild_join(g) for g in self._context.client.guilds])
        self._logger.info('🧵🧵🧵 Ready! 🧵🧵🧵')

    async def _on_guild_join(self, guild):
        # Scan *all* existing channels *before* checking history to avoid
        # double-creating previously existing thread channels.
        await asyncio.gather(
            *[self._async_check_channel(channel=c) for c in guild.channels])
        await asyncio.gather(
            *[self._async_fetch_recents(channel=c)
              for c in guild.channels])

    async def _on_guild_remove(self, guild):
        # Remove _Thread objects on departure (avoid confusion when rejoining).
        await asyncio.gather(
            *[self._async_forget_channel(channel=c) for c in guild.channels])

    async def _on_message(self, m):
        if m.author.id != self._context.client.user.id:
            await self._async_check_message(message=m)

    async def _on_raw_message_delete(self, p):
        await self._async_check_message(
            channel_id=p.channel_id, message_id=p.message_id)

    async def _on_raw_bulk_message_delete(self, p):
        for mi in p.message_ids:
            await self._async_check_message(
                channel_id=p.channel_id, message_id=mi)

    async def _on_raw_message_edit(self, p):
        me = self._context.client.user  # Skip our own edits.
        if p.data.get('author', {}).get('id', '') != str(me.id):
            await self._async_check_message(
                channel_id=p.channel_id, message_id=p.message_id)

    async def _on_raw_reaction_add(self, p):
        if p.user_id != self._context.client.user.id:
            await self._async_check_message(
                channel_id=p.channel_id, message_id=p.message_id, emoji=p.emoji)

    async def _on_raw_reaction_remove(self, p):
        if p.user_id != self._context.client.user.id:
            await self._async_check_message(
                channel_id=p.channel_id, message_id=p.message_id, emoji=p.emoji)

    async def _on_raw_reaction_clear(self, p):
        await self._async_check_message(
            channel_id=p.channel_id, message_id=p.message_id)

    async def _on_raw_reaction_clear_emoji(self, payload):
        await self._async_update_message(
            channel_id=p.channel_id, message_id=p.message_id, emoji=p.emoji)

    async def _on_guild_channel_delete(self, channel):
        await self._async_forget_channel(channel)

    async def _on_guild_channel_create(self, channel):
        await asyncio.gather(self._async_check_channel(channel),
                             self._async_fetch_recents(channel))

    async def _on_guild_channel_update(self, before, after):
        await self._async_check_channel(after)

    #
    # Internal methods
    #

    async def _async_check_message(self, channel_id=None, channel=None,
                                   message=None, message_id=None, emoji=None):
        """If an update looks relevant, re-fetches a message (locally locked).
        One of channel_id/message_id or message must be given.

        Args:
            channel_id: int - ID of channel containing message
            message_id: int - ID of message to fetch and process *OR*
            message: discord.Message - contents of updated message
            emoji: str, discord.*Emoji - emoji of reaction change
        """

        # Handle various ways channel and message can be supplied
        ci = channel_id or message.channel.id
        mi = message_id or message.id

        # The change could be a relevant *origin* message update if:
        #   there is an existing fetch in progress for the message OR
        #   the message is an existing thread channel origin OR
        #   the message has a 🧵 emoji reaction OR
        #   there was a change to 🧵 emoji reactions (not by ourselves)
        if (self._message_exclusive.is_locked(id) or
            mi in self._thread_by_origin.get(ci, {}) or
            str(emoji or '') == self._THREAD_EMOJI or
            (message is not None and
             any(str(r) == self._THREAD_EMOJI for r in message.reactions))):
            self._logger.debug('Fetching message after update...\n'
                               f'    {fobj(c=ci, m=message or mi)}')
            async with self._message_exclusive.locker(mi):
                await self._async_fetch_locked_message(ci, mi)

        # The change could be a relevant *intro* message update if:
        #   the message's channel is a thread channel AND
        #   ( we haven't found a full set of intro messages OR
        #     the update is for an existing intro messages )
        t = self._thread_by_channel.get(ci)
        if (t is not None and t.intro_messages is not None and (
                len(t.intro_messages) < self._FETCH_INTRO or
                any(message_id == mi for m in t.intro_messages))):
            self._logger.debug('Fetching intro after update...\n'
                               f'    {fobj(c=ci, m=message or mi)}')
            async with self._message_exclusive.locker(t.origin_message_id):
                await self._async_fetch_locked_intro(t)

    async def _async_fetch_locked_message(self, channel_id, message_id):
        """Re-fetches and processes a message (caller must hold lock)."""

        assert self._message_exclusive.is_locked(message_id)
        channel = self._context.client.get_channel(channel_id)
        if channel is None:
            # Channel not available, treat the message as missing.
            self._logger.debug('Fetch failed (no channel):\n'
                               f'    {fobj(c=channel_id, m=message_id)}')
            await self._async_locked_message_gone(
                channel_id=channel.id, message_id=message_id)
        else:
            try:
                message = await channel.fetch_message(message_id)
            except discord.errors.NotFound:
                self._logger.debug('Fetch failed (NotFound):\n'
                                   f'    {fobj(c=channel, m=message_id)}')
                await self._async_locked_message_gone(
                    channel_id=channel.id, message_id=message_id)
            else:
                await self._async_locked_message_update(message)

    async def _async_locked_message_update(self, message):
        """Processes a thread origin re-fetch (caller must hold lock)."""

        assert self._message_exclusive.is_locked(message.id)
        gi, ci, mi = message.channel.guild.id, message.channel.id, message.id
        t = self._thread_by_origin.get(ci, {}).get(mi)

        rxs = message.reactions
        rx = next((r for r in rxs if str(r.emoji) == self._THREAD_EMOJI), None)
        if self._logger.isEnabledFor(logging.DEBUG):
            tid = t.thread_channel.id if t is not None else None
            rt = f'x{rx.count}{" w/me" if rx.me else ""}' if rx else 'None'
            self._logger.debug(
                'Fetched message:\n'
                f'    {fobj(m=message)}\n'
                f'    reaction={rt} existing={fobj(c=tid) if tid else "None"}')

        # If there is no existing thread channel and we have not already piled
        # on to the 🧵 emoji, create a new channel (and pile on the emoji).
        if rx is not None and rx.count > 0 and not rx.me:
            if t is None:
                users = [u async for u in rx.users(limit=1)]
                t = await self._async_create_thread_for_locked_message(
                    origin_message=message,
                    creating_user=users[0] if users else None)
            await message.add_reaction(rx)  # Acknowledge after creation.

        # If there *is* an existing channel but other reactions are gone
        # and there is no added content, remove the channel (quick undo).
        me = self._context.client.user
        if (rx is not None and (rx.count - rx.me) == 0 and
            t is not None and t.intro_messages is not None and
                not any(m for m in t.intro_messages if m.author != me)):
            await self._async_delete_locked_thread(t)
            await message.remove_reaction(rx, self._context.client.user)

        # Post or edit the thread intro as appropriate.
        if t is not None and t.intro_messages is not None:
            # Update intro message content and attached embed.
            who = message.author
            description = (message.content + '\n\xA0\n🧵 [original message]'
                f'(https://discordapp.com/channels/{gi}/{ci}/{mi})'
                f' in <#{ci}> by <@{who.id}>').strip()

            for a in message.attachments:
                escaped_name = discord.utils.escape_markdown(a.filename)
                description += f'\n📎 [{escaped_name}]({a.proxy_url or a.url})'
                if a.is_spoiler():
                    a.description += ' (spoiler!)'

            for e in message.embeds:
                if e.title and e.url:
                    escaped_title = discord.utils.escape_markdown(e.title)
                    description += f'\n🔗 [{escaped_title}]({e.url})'

            embed = discord.Embed(description=description)
            embed.set_author(name=who.display_name, icon_url=who.avatar_url)
            await self._async_update_locked_thread_intro(
                thread=t, content='', embed=embed)

    async def _async_locked_message_gone(self, channel_id, message_id):
        """Handles a message that was deleted (caller must hold lock)."""

        assert self._message_exclusive.is_locked(message_id)
        t = self._thread_by_origin.setdefault(channel_id, {}).get(message_id)
        me = self._context.client.user  # Skip our own edits.

        # If the thread has no added content, remove the channel.
        if (t is not None and t.intro_messages is not None and
                not any(m for m in t.intro_messages if m.author != me)):
            await self._async_delete_locked_thread(t)
        elif t is not None:
            content = f'🧵 original message in <#{channel_id}> was **deleted**'
            await self._async_update_locked_thread_intro(
                thread=t, content=content, embed=None)

    async def _async_update_locked_thread_intro(self, thread, content, embed):
        """Adds or edits a _Thread's intro message (caller must lock)."""

        assert self._message_exclusive.is_locked(thread.origin_message_id)
        me = self._context.client.user

        # Look for the first intro post by us.
        old = next((m for m in thread.intro_messages if m.author == me), None)

        # Post or edit the intro if actual != desired.
        if old is None and len(thread.intro_messages) >= self._FETCH_INTRO:
            self._logger.error(
                'Someone else made the first posts!\n'
                f'    {fobj(m=thread.intro_messages[0])}')
        elif old is None and len(thread.intro_messages) < self._FETCH_INTRO:
            m = await thread.thread_channel.send(content=content, embed=embed)
            thread.intro_messages.append(m)
            self._logger.info(f'Posted intro:\n    {fobj(m=m)}')
        elif old is not None:
            old_dict = old.embeds[0].to_dict() if old.embeds else {}
            old_dict.get('author', {}).pop('proxy_icon_url', None)
            new_dict = embed.to_dict() if embed else {}
            if (old.content or '') != content or old_dict != new_dict:
                self._logger.debug(
                    'Updating intro:\n'
                    f'    old: [{old.content}] / {old_dict}\n'
                    f'    new: [{content}] / {new_dict}')
                await old.edit(content=content, embed=embed)
                self._logger.info(f'Edited intro:\n    {fobj(m=old)}')

    async def _async_create_thread_for_locked_message(
            self, origin_message, creating_user):
        """Creates & returns a _Thread for an origin (caller must lock)."""

        assert self._message_exclusive.is_locked(origin_message.id)
        ci, mi = origin_message.channel.id, origin_message.id

        # Generate a channel name from the message content.
        # For better length trimming, take a stab at character culling
        # (note, emoji ("So") and the ZWJ ("Cf") are valid in channel names);
        # see wikipedia.org/wiki/Unicode_character_property#General_Category.
        mash = ''
        text = origin_message.content or ''
        words = self._CHANNEL_CLEANUP_REGEX.sub(' ', text).split()
        for word in words:
            to_add = ('-' if mash else '') + word
            remaining = self._CHANNEL_LENGTH - len(mash) - len(to_add)
            if remaining >= 0:
                mash += to_add
                continue  # The word fits in its entirety; keep going.
            if len(mash) < self._CHANNEL_LENGTH // 2:
                # Chop long words if needed to get a reasonable channel mash.
                mash += f'{to_add[:remaining]}'
            mash += self._ELLIPSIS
            break

        basic_name = f'{self._THREAD_EMOJI}{mash or "thread"}'
        name, number = basic_name, 1  # Add a suffix if needed for uniqueness.
        existing = set(c.name for c in origin_message.guild.channels)
        while name in existing:
            number += 1
            name = f'{basic_name}-{number}'

        # Special name and topic format enables recognizability.
        tag = f' started by <@{creating_user.id}>' if creating_user else ''
        topic = (f'Thread{tag} for [<#{ci}>/{mi:x}].')
        if self._logger.isEnabledFor(logging.DEBUG):
            self._logger.info('Creating channel:\n'
                              f'    "{origin_message.guild.name}" #{name}\n'
                              f'    topic "{topic}"\n'
                              f'    origin {fobj(m=origin_message)}')

        channel = await origin_message.guild.create_text_channel(
            name=name, category=origin_message.channel.category,
            position=len(origin_message.guild.channels), topic=topic,
            reason='Thread creation')

        thread = self._Thread(channel=channel, origin_cid=ci, origin_mid=mi)
        thread.intro_messages = []  # New channel is empty!
        self._thread_by_origin.setdefault(ci, {})[mi] = thread
        self._thread_by_channel[channel.id] = thread
        return thread

    async def _async_delete_locked_thread(self, thread):
        """Deletes and unregisters a thread channel (caller must lock)."""

        assert self._message_exclusive.is_locked(thread.origin_message_id)
        ci, mi = thread.origin_channel_id, thread.origin_message_id

        self._logger.info('Deleting channel:\n'
                          f'    {fobj(c=thread.thread_channel)}')
        await thread.thread_channel.delete()
        del self._thread_by_channel[thread.thread_channel.id]
        del self._thread_by_origin[ci][mi]

    async def _async_check_channel(self, channel):
        """Examines channel metadata; registers existing thread channels."""

        if (channel.type != discord.ChannelType.text or
                not channel.name.startswith(self._THREAD_EMOJI)):
            return  # Not the channel type or name used for thread channels.

        topic_match = self._TOPIC_REGEX.match(channel.topic or '')
        if not topic_match:
            return  # Not the channel topic format used for thread channels.

        cref = topic_match.group(1)
        ci = int(cref[2:-1]) if cref.startswith('<#') else int(cref, 16)
        mi = int(topic_match.group(2), 16)
        async with self._message_exclusive.locker(mi):
            if channel.id in self._thread_by_channel:
                return  # The channel is already registered.

            t = self._thread_by_origin.get(ci, {}).get(mi)
            if t:
                self._logger.error(
                    'Multiple channels for same origin!!\n'
                    f'    {fobj(c=t.thread_channel)}\n'
                    f'    {fobj(c=channel)}')
                return

            if self._logger.isEnabledFor(logging.DEBUG):
                self._logger.debug('Found thread (fetching origin, intro):\n'
                                   f'    {fobj(c=channel)}\n'
                                   f'    topic: "{channel.topic}"\n'
                                   f'    origin: {fobj(c=ci, m=mi)}')

            t = self._Thread(channel=channel, origin_cid=ci, origin_mid=mi)
            self._thread_by_origin.setdefault(ci, {})[mi] = t
            self._thread_by_channel[channel.id] = t
            await self._async_fetch_locked_intro(t)
            await self._async_fetch_locked_message(channel_id=ci, message_id=mi)

    async def _async_fetch_locked_intro(self, thread):
        """Re-fetches the first messages of a thread (caller must hold lock)."""

        assert self._message_exclusive.is_locked(thread.origin_message_id)
        if self._thread_by_channel.get(thread.thread_channel.id) is not thread:
            return  # Thread was removed at some point.

        old_len = len(thread.intro_messages or [])
        thread.intro_messages = [
            m async for m in thread.thread_channel.history(
                limit=self._FETCH_INTRO, oldest_first=True)]
        if self._logger.isEnabledFor(logging.DEBUG):
            ims = thread.intro_messages
            self._logger.debug(
                f'Fetched #{thread.thread_channel.name} intro '
                f'({old_len} => {len(ims)}m):' +
                ''.join(f'\n    {fobj(m=m)}' for m in ims))

        # When the intro *shrinks*, re-check the origin in case the
        # thread channel is now eligible for removal.
        if len(thread.intro_messages) < old_len:
            await self._async_fetch_locked_message(
                thread.origin_channel_id, thread.origin_message_id)

    async def _async_fetch_recents(self, channel):
        """Fetches and examines the recent history of a channel that appeared
        (startup, server join, channel creation, visibility change)."""

        if channel.type != discord.ChannelType.text:
            return

        # Go through the history and trigger updates for unprocessed messages;
        # avoid re-fetching any message that is already a thread origin.
        await asyncio.gather(*[
            self._async_check_message(message=m)
            async for m in channel.history(
                limit=self._FETCH_RECENT, oldest_first=False)
            if m.id not in self._thread_by_origin.get(channel.id, {})])

    async def _async_forget_channel(self, channel):
        """Handles a channel that is no longer visible (server detach,
        channel deleted, visibility change)."""

        # If it was a thread channel, remove it from tracking.
        t = self._thread_by_channel.get(channel.id)
        if t is not None:
            # Lock and check again to avoid conflicts.
            async with self._message_exclusive.locker(t.origin_message_id):
                if self._thread_by_channel.get(channel.id) is t:
                    ci, mi = t.origin_channel_id, t.origin_message_id
                    del self._thread_by_channel[channel.id]
                    del self._thread_by_origin[ci][mi]
                    if self._logger.isEnabledFor(logging.DEBUG):
                        self._logger.debug('Thread channel was deleted:\n'
                                           f'    {fobj(c=channel)}\n'
                                           f'    origin={fobj(c=ci, m=mi)}')


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
