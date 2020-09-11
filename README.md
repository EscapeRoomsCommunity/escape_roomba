# Escape Roomba <!-- omit in toc -->

*Removing the dust bunnies from the Escape Rooms Discord, since 2020.*

This is an experimental Discord bot to support the Escape Rooms Discord
community.

- [Useful Resources](#useful-resources)
- [Developer setup instructions (Mac or Linux)](#developer-setup-instructions-mac-or-linux)
  - [Basic build setup](#basic-build-setup)
  - [Setting up a test bot on Discord](#setting-up-a-test-bot-on-discord)

## Useful Resources

* [Discord developer docs](https://discord.com/developers/docs/intro)
* [discord.py docs](https://discordpy.readthedocs.io/en/latest/index.html)
* [discord.py test framework](https://github.com/CraftSpider/dpytest)
(not very mature yet)

## Developer setup instructions (Mac or Linux)

### Basic build setup
1. [Install "poetry"](https://python-poetry.org/docs/#installation), the
Python dependency manager. **Beware of
[bug 721](https://github.com/python-poetry/poetry/issues/721) which affects
installation.**
2. [Install direnv](https://direnv.net/docs/installation.html) (optional, but
recommended).
3. In this directory, run `poetry install`.
4. If you installed direnv, in this directory, run `direnv allow`.

You can now use `run_bot` (without direnv: `poetry run run_bot`) to start the
program. However, you need a bot token in `$ESCAPE_ROOMBA_BOT_TOKEN` to
actually run and connect to Discord. For the prod bot token, talk to egnor@.
To make a test bot account to develop with, keep reading...

### Setting up a test bot on Discord

Follow the
["Creating a Bot Account"](https://discordpy.readthedocs.io/en/latest/discord.html#discord-intro)
instructions from the discord.py docs.
* Name your test bot whatever you want, like "Jaxlyn's Test Bot".
* No need to make it a "Public Bot".
* Do _not_ check "Require OAuth2 Public Grant".
* Copy the *Token* (_not_ the ~~*Client Secret*~~).

If you're using direnv, create an `.envrc.private` file in this directory with
these contents:
```
# DO NOT CHECK IN
export ESCAPE_ROOMBA_BOT_TOKEN='your token here'
```
(If you're not using direnv, set `$ESCAPE_ROOMBA_BOT_TOKEN` some other way.)
To refresh direnv, `cd` out and back into this directory. Now you should be
able to start `run_bot`, which should log an invite URL at startup:

```
09-11 11:51:17 root [INFO] Connected to Discord:
    wss://gateway.discord.gg?encoding=json&v=6&compress=zlib-stream
09-11 11:51:19 root [INFO] Ready in 1 servers (as Jaxlyn's Test Bot#1234):
    Jaxlyn's Test Server
09-11 11:51:19 root [INFO] Invite link to add servers:
    https://discord.com/oauth2/authorize?client_id=753465244491317259&scope=bot&permissions=268512336
```

Follow the invite link to add this bot to a Discord server you administer
(you may wish to create a new server for this purpose). You only need to
do this once; henceforth, whenever the bot is running with that bot token,
it should be active on all Discord servers it was invited to.
