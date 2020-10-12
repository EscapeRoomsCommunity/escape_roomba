import asyncio
import collections
import discord
import discord.utils
import logging
import regex
import unicodedata
from copy import deepcopy

from escape_roomba.format_util import fobj

_THREAD_EMOJI = '🧵'           # Reaction emoji trigger, and channel prefix.
_MAX_CHANNEL_NAME_LENGTH = 20  # Maximum length of generated channel name.
_CACHE_INTRO_MESSAGES = 2      # Track the first N messages in the thread.

# Extracts channel/message ID from existing thread channel topics.
# (The optional asterisk marks the "new to author" flag.)
_TOPIC_PARSE_REGEX = regex.compile(
    r'(?P<prefix>^.*)\[(?:id=)?'
    r'(?P<cref><#[0-9]+>|[0-9a-f]+)/'
    r'(?P<mref>[0-9a-f]+)'
    r'(?P<new>\*?)\][\s.]*$', regex.I)

# Strips text that can't be used in channel names.
_CHANNEL_CLEANUP_REGEX = regex.compile(
    r'([^\p{L}\p{M}\p{N}\p{Sk}\p{So}\p{Cf}]|https?://(www\.?))+')

# Identifies Discord mention syntax in message text.
_CHANNEL_MENTION_REGEX = regex.compile(r'<#([0-9]+)>')
_ROLE_MENTION_REGEX = regex.compile(r'<@&([0-9]+)>')
_USER_MENTION_REGEX = regex.compile(r'<@!?([0-9]+)>')

_logger = logging.getLogger('bot.thread')


# TODO:
# - let people set thread channel name & topic (commands start with emoji?)
# - use emoji (eg. 🔥) to indicate activity level in thread???
# - add unit test for this class specifically

class ThreadChannel:
    """Tracks and manages a thread channel created based on a 🧵 reaction;
    creates (and deletes) the thread channel and its intro message embedding.
    Callers must serialize calls to each ThreadChannel instance's methods.

    Attributes:
        thread_channel: discord.Channel - API object for the thread channel
        origin_channel_id: int - ID of the "root" message's channel
        origin_message_id: int - ID of the "root" message
        is_deleted: bool - the channel was deleted by user request
    """

    def __init__(self, channel, origin_cid, origin_mid):
        """Sets up a ThreadChannel instance. This is normally invoked through
        maybe_attach_to_thread_channel() / async_maybe_create_from_origin()."""

        self.thread_channel = channel
        self.origin_channel_id = origin_cid
        self.origin_message_id = origin_mid
        self.is_deleted = False
        self._new_to_author = True  # Add the origin message's author
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
            _logger.debug(f'\n    Nonthread: {fobj(c=channel)}')
            return None

        topic_match = _TOPIC_PARSE_REGEX.match(channel.topic or '')
        if not topic_match:
            _logger.debug(f'\n    Bad topic: {fobj(c=channel)}'
                          f'\n      "{channel.topic}"')
            return None

        cref, mref = topic_match.group('cref'), topic_match.group('mref')
        try:
            ci = int(cref[2:-1]) if cref.startswith('<#') else int(cref, 16)
            mi = int(mref, 16) if len(mref) <= 16 else int(mref)
        except ValueError:
            _logger.debug(f'\n    Bad topic ID: {fobj(c=channel)}'
                          f'\n      "{channel.topic}"')
            return None

        thread = ThreadChannel(channel, origin_cid=ci, origin_mid=mi)
        thread._new_to_author = bool(topic_match.group('new'))
        if _logger.isEnabledFor(logging.DEBUG):
            origin = fobj(c=ci, m=mi, g='', client=channel.guild)
            overwrites = fobj(p=channel.overwrites).replace('\n', '\n        ')
            _logger.debug(f'\n    Found thread {fobj(c=channel)}'
                          f'\n      topic: "{channel.topic}"'
                          f'\n      origin: {origin}'
                          f'\n        {overwrites}')

        return thread

    @staticmethod
    async def async_maybe_create_from_origin(client, channel_id, message_id):
        """If the identified message has an unhandled 🧵 reaction,
        creates a new thread channel and returns a new ThreadChannel,
        otherwise returns None."""

        ci, mi = channel_id, message_id
        channel = client.get_channel(ci)
        if channel is None:
            _logger.debug(f'\n    Bad cid: {fobj(c=ci, m=mi)}')
            return None

        try:
            message = await channel.fetch_message(mi)
        except discord.errors.NotFound:
            _logger.debug(f'\n    Bad mid: {fobj(c=channel, m=mi)}')
            return None

        if message.author == message.guild.me:
            _logger.debug(f'\n    Self-post: {fobj(m=message)}')
            return None

        # Thread creation requires a 🧵 reaction without pile-on from this bot.
        rxs = message.reactions
        rx = next((r for r in rxs if str(r.emoji) == _THREAD_EMOJI), None)
        rx_users = rx and not rx.me and [u async for u in rx.users()]
        if not rx_users:
            _logger.debug('\n    No 🧵: {fobj(m=message)}')
            return None

        # Generate a channel name from the message content.
        mash = ''
        text = (message.content or '').replace("'", '')
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

        # Make the channel name unique to minimize confusion (not foolproof!).
        basic_name = f'{_THREAD_EMOJI}{mash or "thread"}'
        name, number = basic_name, 1  # Add a suffix if needed for uniqueness.
        existing = set(c.name for c in message.guild.channels)
        while name in existing:
            number += 1
            name = f'{basic_name}-{number}'

        # Use a name and topic format that lets this bot recognize it later.
        # (Include the '*' for the _new_to_author flag.)
        ci, mi = channel.id, message.id
        topic = (f'Thread started by <@{rx_users[0].id}> for [<#{ci}>/{mi}*].')
        pos = message.channel.position + 1
        if _logger.isEnabledFor(logging.DEBUG):
            _logger.info(
                f'\n    Creating #{name} @p{pos} ({channel.guild.name})'
                f'\n      topic: "{topic}"'
                f'\n      origin: {fobj(m=message, g="")}' +
                (f' 🧵x{rx.count}{" w/me" if rx.me else ""}' if rx else '') +
                ''.join(f'\n        🧵 {fobj(u=u, g="")}' for u in rx_users))

        # Hidden at creation; _async_origin_updated() sets visibility.
        Overwrite = discord.PermissionOverwrite
        overwrites = {
            channel.guild.default_role: Overwrite(read_messages=False),
            channel.guild.me: Overwrite(read_messages=True),
        }

        thread_channel = await channel.guild.create_text_channel(
            name=name, category=message.channel.category, topic=topic,
            position=pos, reason='Thread creation', overwrites=overwrites)

        thread = ThreadChannel(thread_channel, origin_cid=ci, origin_mid=mi)
        thread._cached_intro = []  # New channel has no messages yet!

        # Perform final steps in parallel to minimize latency.
        await asyncio.gather(
            # Position doesn't take at creation (Discord bug), fix it up.
            thread_channel.edit(position=pos),

            # Pile on to the 🧵 as insurance against re-creation.
            message.add_reaction(rx),

            # Sync with origin (this will create the intro message).
            thread._async_origin_updated(origin=message, rx_users=rx_users))

        return thread

    async def async_refresh_intro(self):
        """Re-fetches the first few messages in the thread for tracking."""

        old_len = len(self._cached_intro or [])
        self._cached_intro = [
            m async for m in self.thread_channel.history(
                limit=_CACHE_INTRO_MESSAGES, oldest_first=True)]

        if _logger.isEnabledFor(logging.DEBUG):
            _logger.debug(
                f'\n    Refreshed intro for {fobj(c=self.thread_channel)}' +
                ''.join(f'\n      {fobj(m=m, c="", g="")}'
                        for m in self._cached_intro))

        # If the intro set shrinks, re-check the origin to handle the corner
        # case where the 🧵 was removed and *then* all channel posts deleted,
        # in which case the channel needs to get deleted.
        if len(self._cached_intro) < old_len:
            await self.async_refresh_origin()

    async def async_refresh_origin(self):
        """Re-fetches the state of the thread's origin message and updates
        the thread (updating the intro to match, checking reaction count, etc).
        """

        ci, mi = self.origin_channel_id, self.origin_message_id
        channel = self.thread_channel.guild.get_channel(ci)
        if channel is None:
            _logger.debug(f'\n    Bad cid: {fobj(c=ci, m=mi)}')
            await self._async_origin_updated(origin=None, rx_users=[])
            return

        try:
            message = await channel.fetch_message(mi)
        except discord.errors.NotFound:
            _logger.debug(f'\n    Bad mid: {fobj(c=channel, m=mi)}')
            await self._async_origin_updated(origin=None, rx_users=[])
            return

        rxs = message.reactions
        rx = next((r for r in rxs if str(r.emoji) == _THREAD_EMOJI), None)
        rx_users = [u async for u in rx.users()] if rx else []
        await self._async_origin_updated(origin=message, rx_users=rx_users)

    async def _async_origin_updated(self, origin, rx_users):
        """Updates the thread based on new origin message state.

        Args:
            message: discord.Message - New origin message (None if deleted)
            rx_users: list of discord.User - Users reacting with 🧵 emoji
        """

        if self.is_deleted:
            return  # This thread channel is already gone, nothing to update.

        # If the origin is deleted, keep the thread but mark the deletion.
        me = self.thread_channel.guild.me
        if origin is None:
            if (self._cached_intro is not None and
                    not any(m for m in self._cached_intro if m.author != me)):
                # The thread is empty (no added content), remove the channel.
                _logger.info(f'\n    Pruning {fobj(c=self.thread_channel)}')
                await self.thread_channel.delete()
                self.is_deleted = True
                return  # Thread channel is deleted, nothing more to update.

            # The thread still has messages, edit its intro but do not delete.
            description = f'🧵 The original message was **deleted**!'
            await self._async_post_intro(
                content='', embed=discord.Embed(description=description))
            return

        ci, mi = origin.channel.id, origin.id
        assert (ci, mi) == (self.origin_channel_id, self.origin_message_id)
        assert self.thread_channel is not None
        if _logger.isEnabledFor(logging.DEBUG):
            _logger.debug(
                f'\n    Syncing {fobj(c=self.thread_channel)}'
                f'\n      origin: {fobj(m=origin, g="")}' +
                ''.join(f'\n        🧵 {fobj(u=u, g="")}' for u in rx_users))

        # If 🧵 reactions are gone and the thread is empty, remove the channel.
        me = origin.guild.me
        if (self._cached_intro is not None and
                not any(u for u in rx_users if u != me) and
                not any(m for m in self._cached_intro if m.author != me)):
            _logger.info('\n    Unmaking {fobj(c=self.thread_channel)}')
            await asyncio.gather(
                self.thread_channel.delete(),
                origin.remove_reaction(_THREAD_EMOJI, me))
            self.is_deleted = True
            return  # Thread channel is deleted, nothing more to update.

        # Update the intro message embed which shows the origin message.
        embed = self._make_message_embed(origin)
        await self._async_post_intro(content='', embed=embed)

        # Use origin channel permissions as a baseline for the thread channel.
        overwrites = collections.defaultdict(
            discord.PermissionOverwrite,
            {u: deepcopy(o) for u, o in origin.channel.overwrites.items()})

        # Remove all member/role-specific overwrites for visibility --
        # they could conflict with our visibility assignments below
        # (discord.com/developers/docs/topics/permissions#permission-overwrites)
        for o in overwrites.values():
            o.update(read_messages=None)

        # Make the thread invisible for @everyone except as overridden.
        overwrites[origin.guild.default_role].update(read_messages=False)
        overwrites[me].update(read_messages=True)  # We get to see it!

        # Allow thread visibility for those who react with the 🧵 emoji.
        # TODO: Check access to the origin channel, in case that changes.
        for u in rx_users:
            overwrites[u].update(read_messages=True)

        # Add the origin message's author by default until they explicitly join.
        if self._new_to_author and origin.author in rx_users:
            self._new_to_author = False
        if self._new_to_author:
            overwrites[origin.author].update(read_messages=True)

        overwrites = {u: o for u, o in overwrites.items() if not o.is_empty()}
        old = self.thread_channel.overwrites
        if old != overwrites and _logger.isEnabledFor(logging.DEBUG):
            fold = fobj(p=old).replace('\n', '\n        ')
            fnew = fobj(p=overwrites).replace('\n', '\n        ')
            _logger.debug(
                f'\n    Setting permissions for {fobj(c=self.thread_channel)}):'
                f'\n    Old {fold}\n    New {fnew}')

        topic_match = _TOPIC_PARSE_REGEX.match(self.thread_channel.topic or '')
        topic_prefix = topic_match.group('prefix') if topic_match else ''
        topic_mark = '*' if self._new_to_author else ''
        topic = f'{topic_prefix}[<#{ci}>/{mi}{topic_mark}]'
        if old != overwrites or topic != self.thread_channel.topic:
            await self.thread_channel.edit(overwrites=overwrites, topic=topic)

    def _make_message_embed(self, origin):
        """Internal method to create an embed (content card) capturing
        the content of a thread's origin message."""

        # Build the body from the original content plus a footer.
        who = origin.author
        gi, ci, mi = origin.guild.id, origin.channel.id, origin.id
        origin_link = f'https://discordapp.com/channels/{gi}/{ci}/{mi}'
        foot = f'🧵 [original message]({origin_link}) in <#{ci}> by <@{who.id}>'
        description = (origin.content + '\n\xA0\n' + foot).strip()

        # Add items below the footer for attachments & embeds in the original.
        for a in origin.attachments:
            escaped_name = discord.utils.escape_markdown(a.filename)
            description += f'\n📎 [{escaped_name}]({a.proxy_url or a.url})'
            if a.is_spoiler():
                description += ' (spoiler!)'

        for e in origin.embeds:
            if e.title and e.url:
                escaped_title = discord.utils.escape_markdown(e.title)
                description += f'\n🔗 [{escaped_title}]({e.url})'

        # Replace channel/role/user mentions with direct hyperlinks
        # (sadly, mentions are unreliable in Discord embed content).
        def replace_channel(match):
            c = origin.guild.get_channel(int(match.group(1)))
            return (f'[#{c.name}](https://discordapp.com/channels/{gi}/{c.id})'
                    if c else match.group(0))

        def replace_role(match):
            r = origin.guild.get_role(int(match.group(1)))
            return (f'**@{r.name}**' if r else match.group(0))

        def replace_user(match):
            # (Could use discordapp.com/users/ID but that pops up a window.)
            u = origin.guild.get_member(int(match.group(1)))
            return (f'**@{u.display_name}**' if u else match.group(0))

        description = _CHANNEL_MENTION_REGEX.sub(replace_channel, description)
        description = _ROLE_MENTION_REGEX.sub(replace_role, description)
        description = _USER_MENTION_REGEX.sub(replace_user, description)

        embed = discord.Embed(description=description)
        embed.set_author(name=who.display_name, icon_url=who.avatar_url)
        return embed

    async def _async_post_intro(self, content, embed):
        """Internal method to add or edit the thread's intro message.

        Args:
            content: str - Body of intro message (can be '')
            embed: discord.Embed - "Embedded" rich content (can be None)
        """

        if self._cached_intro is None:
            return  # Intro not fetched yet; fetch completion will resync.

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
                _logger.debug(
                    f'\n    Updating intro for {fobj(c=self.thread_channel)}):'
                    f'\n    Old: [{old.content}] / {old_dict}'
                    f'\n    New: [{content}] / {new_dict}')
                await old.edit(content=content, embed=embed)
