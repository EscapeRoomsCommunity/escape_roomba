# escape_roomba

This is an experimental Discord bot to support the Escape Rooms Discord community.

## Developer setup instructions (Mac or Linux)

### Basic build setup
1. [Install "poetry"](https://python-poetry.org/docs/#installation), the Python dependency manager.
**Beware of [bug 721](https://github.com/python-poetry/poetry/issues/721) which affects installation.** 
2. [Install direnv](https://direnv.net/docs/installation.html) (optional, but recommended).
3. In this directory, run `poetry install`.
4. If you installed direnv, in this directory, run `direnv allow`.

You can now use `run_bot` (without direnv, `poetry run run_bot`) to start the program. However,
you need a secret bot token in `$ESCAPE_ROOMBA_TOKEN` to actually run and connect to Discord. For
the prod bot token, talk to egnor@. To make your own test bot account, keep reading...

### Setting up a test bot on Discord

Follow the
["Creating a Bot Account"](https://discordpy.readthedocs.io/en/latest/discord.html#discord-intro)
instructions from the discord.py docs.
* Name your test bot whatever you want, like "Jaxlyn's Test Bot".
* No need to make it a "Public Bot".
* Do _not_ check "Require OAuth2 Public Grant".
* Copy the *Token* (_not_ the ~~*Client Secret*~~).

If you're using direnv, create an `.envrc.private` file in this directory with these contents:
```
# DO NOT CHECK IN
export ESCAPE_ROOMBA_TOKEN='your token here'
```
(If you're not using direnv, find some other way to set `$ESCAPE_ROOMBA_TOKEN`.)
To refresh direnv, `cd` out and back into this directory. Now you should be able to start
`run_bot`. It should print an invite URL you can use to add it to any Discord server you
administer (you may wish to create your own test server to play with the bot).
