"""Unit tests for thread_channel.ThreadChannel."""

from escape_roomba.thread_channel import ThreadChannel


def test_relevant_origin_update(discord_mock):
    assert not ThreadChannel.relevant_origin_update(emoji='🧶')
    assert ThreadChannel.relevant_origin_update(emoji='🧵')

    guild = discord_mock.context.discord().guilds[0]
    message = guild.channels[0].test_history[0]
    discord_mock.sim_reaction(message, '🧶', guild.members[0], +1)
    assert not ThreadChannel.relevant_origin_update(message=message)

    discord_mock.sim_reaction(message, '🧵', guild.members[0], +1)
    assert ThreadChannel.relevant_origin_update(message=message)

    discord_mock.sim_reaction(message, '🧵', guild.me, +1)
    assert not ThreadChannel.relevant_origin_update(message=message)


def test_


def test_relevant_intro_update(discord_mock):
    pass    


# TODO: Add more tests of more functionality.
