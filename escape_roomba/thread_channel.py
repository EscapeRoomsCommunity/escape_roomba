import asyncio
import collections
import discord
import discord.utils
import logging
import regex
import unicodedata

from escape_roomba.format_util import fobj

_THREAD_EMOJI = '🧵'           # Reaction emoji trigger, and channel prefix.
_MAX_CHANNEL_NAME_LENGTH = 20  # Maximum length of generated channel name.
_CACHE_INTRO_MESSAGES = 2      # Track the first N messages in the thread.

# Used to extract channel/message ID from existing thread channel topics.
_TOPIC_PARSE_REGEX = regex.compile(
    r'.*\[(?:id=)?(<#[0-9]+>|[0-9a-f]+)/([0-9a-f]+)\][\s.]*', regex.I)

# Used to strip things when generating Discord channel names from text.
_CHANNEL_CLEANUP_REGEX = regex.compile(
    r'([^\p{L}\p{M}\p{N}\p{Sk}\p{So}\p{Cf}]|https?://(www\.?))+')

_logger = logging.getLogger('bot.thread')


# TODO:
# - manage visibility of thread channels (origin author + people who react?)
# - let people set thread channel name & topic (commands start with emoji?)
# - use emoji (eg. 🔥) to indicate activity level in thread???
# - add unit test for this class specifically

class ThreadChannel:
    """Tracks and manages a thread channel created based on a 🧵 reaction;
    creates (and deletes) the thread channel and its intro message embedding.
    Callers must serialize calls to each ThreadChannel instance's methods.

    Attributes:
        thread_channel: discord.Channel - API object for the thread channel
        thread_deleted: bool - True if the channel was deleted by user request
        origin_channel_id: int - ID of the "root" message's channel
        origin_message_id: int - ID of the "root" message
    """

    def __init__(self, channel, origin_cid, origin_mid):
        """Sets up a ThreadChannel instance. This is normally invoked through
        maybe_attach_to_thread_channel() / async_maybe_create_from_origin()."""

        self.thread_channel = channel
        self.thread_deleted = False
        self.origin_channel_id = origin_cid
        self.origin_message_id = origin_mid
        self._cached_intro = None  # First few messages (None = not loaded)

    @staticmethod
    def relevant_origin_update(message=None, emoji=None):
        """Quick check that returns True if the given message or emoji reaction
        indicates that an update may reflect a thread creation request
        (so async_maybe_create_from_origin() should be called)."""

        return ((emoji and str(emoji) == _THREAD_EMOJI) or
                (message and any(not r.me and str(r) == _THREAD_EMOJI
                                 for r in message.reactions)))

    def relevant_intro_update(self, message_id):
        """Quick check that returns True if the given message ID is part of
        this thread's "intro" (so async_update_intro() should be called)."""

        return (
            len(self._cached_intro) < _CACHE_INTRO_MESSAGES or
            any(message_id == m.id for m in self._cached_intro or []))

    @staticmethod
    def maybe_attach_to_thread_channel(channel):
        """If the Discord channel appears to be a previously created thread,
        creates and returns a new ThreadChannel, otherwise returns None.

        If a new instance was generated, the caller should invoke
        async_update_origin() and async_update_intro() (after locking)."""

        if (channel is None or channel.type != discord.ChannelType.text or
                not channel.name.startswith(_THREAD_EMOJI)):
            _logger.debug(f'Nonthread: {fobj(c=channel)}')
            return None

        topic_match = _TOPIC_PARSE_REGEX.match(channel.topic or '')
        if not topic_match:
            _logger.debug(f'Bad topic: {fobj(c=channel)}\n'
                          f'    "{channel.topic}"')
            return None

        cref = topic_match.group(1)
        ci = int(cref[2:-1]) if cref.startswith('<#') else int(cref, 16)
        mi = int(topic_match.group(2), 16)
        if _logger.isEnabledFor(logging.DEBUG):
            _logger.debug(f'Thread: {fobj(c=channel)}\n'
                          f'    "{channel.topic}"\n'
                          f'    origin: {fobj(c=ci, m=mi)}')

        return ThreadChannel(channel, origin_cid=ci, origin_mid=mi)

    @staticmethod
    async def async_maybe_create_from_origin(client, channel_id, message_id):
        """If the identified message has an unhandled 🧵 reaction,
        creates a new thread channel and returns a new ThreadChannel,
        otherwise returns None."""

        channel = client.get_channel(channel_id)
        if channel is None:
            _logger.debug('No channel for candidate:\n'
                          f'    {fobj(c=channel_id, m=message_id)}')
            return None

        try:
            message = await channel.fetch_message(message_id)
        except discord.errors.NotFound:
            _logger.debug('Fetch failed for candidate (NotFound):\n'
                          f'    {fobj(c=channel, m=message_id)}')
            return None

        if message.author == channel.guild.me:
            _logger.debug('Skipping candidate authored by this bot:\n'
                          f'    {fobj(m=message)}')
            return None

        # Thread creation requires a 🧵 reaction without pile-on from this bot.
        rxs = message.reactions
        rx = next((r for r in rxs if str(r.emoji) == _THREAD_EMOJI), None)
        users = rx and not rx.me and [u async for u in rx.users(limit=1)]
        if not users:
            _logger.debug('No unhandled 🧵 for candidate:\n'
                          f'    {fobj(m=message)}')
            return None

        # Generate a channel name from the message content.
        # For better length trimming, take a stab at character culling
        # (note, emoji ("So") and the ZWJ ("Cf") are valid in channel names);
        # see wikipedia.org/wiki/Unicode_character_property#General_Category.
        mash = ''
        text = message.content or ''
        words = _CHANNEL_CLEANUP_REGEX.sub(' ', text).split()
        for word in words:
            to_add = ('-' if mash else '') + word
            remaining = _MAX_CHANNEL_NAME_LENGTH - len(mash) - len(to_add)
            if remaining >= 0:
                mash += to_add
                continue  # The word fits in its entirety; keep going.
            if len(mash) < _MAX_CHANNEL_NAME_LENGTH // 2:
                # Chop long words if needed to get a reasonable channel mash.
                mash += f'{to_add[:remaining]}'
            mash += '…'
            break

        basic_name = f'{_THREAD_EMOJI}{mash or "thread"}'
        name, number = basic_name, 1  # Add a suffix if needed for uniqueness.
        existing = set(c.name for c in message.guild.channels)
        while name in existing:
            number += 1
            name = f'{basic_name}-{number}'

        # Special name and topic format enables recognizability.
        ci, mi = message.channel.id, message.id
        topic = (f'Thread started by <@{users[0].id}> for [<#{ci}>/{mi:x}].')
        if _logger.isEnabledFor(logging.DEBUG):
            _logger.info('Creating channel:\n'
                         f'    "{message.guild.name}" #{name}\n'
                         f'    topic "{topic}"\n'
                         f'    origin {fobj(m=message)}')

        thread_channel = await message.guild.create_text_channel(
            name=name, category=message.channel.category,
            position=len(message.guild.channels), topic=topic,
            reason='Thread creation')

        # Pile on to the 🧵 after creation as insurance against re-creation.
        await message.add_reaction(rx)

        thread = ThreadChannel(thread_channel, origin_cid=ci, origin_mid=mi)
        thread._cached_intro = []  # New channel has no messages yet!
        await thread._async_origin_updated(message)
        return thread

    async def async_refresh_intro(self):
        """Re-fetches the first few messages in the thread for tracking."""

        old_len = len(self._cached_intro or [])
        self._cached_intro = [
            m async for m in self.thread_channel.history(
                limit=_CACHE_INTRO_MESSAGES, oldest_first=True)]

        if _logger.isEnabledFor(logging.DEBUG):
            _logger.debug(
                f'Fetched #{self.thread_channel.name} intro '
                f'({old_len} => {len(self._cached_intro)}m):' +
                ''.join(f'\n    {fobj(m=m)}' for m in self._cached_intro))

        # Intro messages are tracked to know if there are other channel posts,
        # which prevent channel deletion if the original 🧵 is removed.
        # If the intro set shrinks, re-check the origin to handle the corner
        # case where the 🧵 was removed and *then* all channel posts deleted.
        if len(self._cached_intro) < old_len:
            await self.refresh_origin()

    async def async_refresh_origin(self):
        """Re-fetches the state of the thread's origin message and updates
        the thread (updating the intro to match, checking reaction count, etc).
        """

        channel = self.thread_channel.guild.get_channel(self.origin_channel_id)
        message = None
        if channel is None:
            _logger.debug('No channel for refresh:\n'
                          f'    {fobj(c=channel_id, m=message_id)}')
        else:
            try:
                message = await channel.fetch_message(self.origin_message_id)
            except discord.errors.NotFound:
                _logger.debug('Fetch failed for refresh (NotFound):\n'
                              f'    {fobj(c=channel, m=message_id)}')

        self._async_origin_updated(message)

    async def _async_origin_updated(self, message):
        """Updates the thread based on new origin message state.

        Args:
            message: discord.Message - New origin message (None if deleted)
        """

        if message is None:  # The message has been deleted!
            me = self.thread_channel.guild.me
            if (self._cached_intro is not None and
                    not any(m for m in self._cached_intro if m.author != me)):
                # The thread is empty (no added content), remove the channel.
                _logger.info('Deleting channel (origin gone):\n'
                             f'    {fobj(c=self.thread_channel)}')
                await self.thread_channel.delete()
                self.thread_deleted = True

            # The thread still has messages in it, edit intro but do not
            # delete.
            content = f'🧵 original message in <#{channel_id}> was **deleted**'
            await self._async_post_intro(content=content, embed=None)

        gi, ci, mi = message.channel.guild.id, message.channel.id, message.id
        assert (ci, mi) == (self.origin_channel_id, self.origin_message_id)
        assert self.thread_channel is not None

        rxs = message.reactions
        rx = next((r for r in rxs if str(r.emoji) == _THREAD_EMOJI), None)
        if _logger.isEnabledFor(logging.DEBUG):
            _logger.debug(
                f'Refetched origin:\n'
                f'    thread: ({fobj(c=self.thread_channel)}):\n'
                f'    origin: {fobj(m=message)}\n'
                f'    reaction: '
                f'x{rx.count}{" w/me" if rx.me else ""}' if rx else 'None')

        # If 🧵 reactions are gone and the thread is empty, remove the channel.
        me = message.guild.me
        if ((rx is None or (rx.count - rx.me) == 0) and
            self._cached_intro is not None and
                not any(m for m in self._cached_intro if m.author != me)):
            _logger.info('Deleting channel (reactions removed):\n'
                         f'    {fobj(c=self.thread_channel)}')
            await self.thread_channel.delete()
            await message.remove_reaction(rx, me)
            self.thread_deleted = True

        # Update the thread intro with a copy of the origin message.
        if self._cached_intro is not None:
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
            await self._async_post_intro(content='', embed=embed)

    async def _async_post_intro(self, content, embed):
        """Internal method to add or edit the thread's intro message.

        Args:
            content: str - Body of intro message (can be '')
            embed: discord.Embed - "Embedded" rich content (can be None)
        """

        # Look for the first intro post by us.
        me = self.thread_channel.guild.me
        old = next((m for m in self._cached_intro if m.author == me), None)

        # Post or edit the intro if actual != desired.
        if old is None and len(self._cached_intro) >= _CACHE_INTRO_MESSAGES:
            _logger.error('Another user sniped the first post!\n'
                          f'    {fobj(m=thread._cached_intro[0])}')
        elif old is None and len(self._cached_intro) < _CACHE_INTRO_MESSAGES:
            m = await self.thread_channel.send(content=content, embed=embed)
            self._cached_intro.append(m)
            _logger.info(f'Posted intro:\n    {fobj(m=m)}')
        elif old is not None:
            old_dict = old.embeds[0].to_dict() if old.embeds else {}
            old_dict.get('author', {}).pop('proxy_icon_url', None)
            new_dict = embed.to_dict() if embed else {}
            if (old.content or '') != content or old_dict != new_dict:
                _logger.debug('Updating intro:\n'
                              f'    old: [{old.content}] / {old_dict}\n'
                              f'    new: [{content}] / {new_dict}')
                await old.edit(content=content, embed=embed)
                _logger.info('Edited intro:\n'
                             f'    {fobj(m=old)}')
