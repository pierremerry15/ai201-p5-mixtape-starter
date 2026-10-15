"""
tests/test_feed.py — Mixtape

Tests for the "Friends Listening Now" feed.

These cover the calendar-day boundary: the feed is scoped to today, so an
event from late yesterday must not appear even though only a few hours have
elapsed since it happened.
"""

import pytest
from datetime import datetime, timedelta, timezone
from app import create_app, db
from models import User, Song, ListeningEvent, friendships
from services.feed_service import get_friends_listening_now


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


def _start_of_today():
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


@pytest.fixture
def listener_and_friend(app):
    """A user with one friend, and a song the friend can listen to."""
    with app.app_context():
        me = User(username="nova", email="nova@example.com")
        friend = User(username="darius", email="darius@example.com")
        db.session.add_all([me, friend])
        db.session.flush()

        db.session.execute(
            friendships.insert().values(user_id=me.id, friend_id=friend.id)
        )
        db.session.execute(
            friendships.insert().values(user_id=friend.id, friend_id=me.id)
        )

        song = Song(title="Midnight Drive", artist="The Wanderers", shared_by=me.id)
        db.session.add(song)
        db.session.commit()

        yield {"me": me, "friend": friend, "song": song}


def _record_listen(friend_id, song_id, listened_at):
    db.session.add(
        ListeningEvent(user_id=friend_id, song_id=song_id, listened_at=listened_at)
    )
    db.session.commit()


def test_listen_from_today_appears(app, listener_and_friend):
    """A friend who listened earlier today shows up in the feed."""
    with app.app_context():
        me = listener_and_friend["me"]
        friend = listener_and_friend["friend"]
        song = listener_and_friend["song"]

        _record_listen(friend.id, song.id, datetime.now(timezone.utc) - timedelta(seconds=30))

        feed = get_friends_listening_now(me.id)
        assert [entry["friend"]["username"] for entry in feed] == ["darius"]


def test_listen_from_late_yesterday_is_excluded(app, listener_and_friend):
    """
    An event from just before midnight must not appear, even though only a
    few hours have elapsed. A rolling 24-hour window would still include it.
    """
    with app.app_context():
        me = listener_and_friend["me"]
        friend = listener_and_friend["friend"]
        song = listener_and_friend["song"]

        late_yesterday = _start_of_today() - timedelta(minutes=1)
        _record_listen(friend.id, song.id, late_yesterday)

        # Guard: this only demonstrates the bug while the elapsed time is
        # still under 24h, i.e. every moment of the day except the last minute.
        elapsed = datetime.now(timezone.utc) - late_yesterday
        assert elapsed < timedelta(hours=24), "test ran in the final minute of the day"

        feed = get_friends_listening_now(me.id)
        assert feed == []


def test_only_most_recent_listen_per_friend(app, listener_and_friend):
    """A friend with several listens today is represented once, by the latest."""
    with app.app_context():
        me = listener_and_friend["me"]
        friend = listener_and_friend["friend"]
        song = listener_and_friend["song"]

        now = datetime.now(timezone.utc)
        older = max(now - timedelta(hours=2), _start_of_today())
        _record_listen(friend.id, song.id, older)
        _record_listen(friend.id, song.id, now - timedelta(seconds=30))

        feed = get_friends_listening_now(me.id)
        assert len(feed) == 1
        assert feed[0]["listened_at"].startswith(
            (now - timedelta(seconds=30)).isoformat()[:13]
        )


def test_user_with_no_friends_gets_empty_feed(app):
    """A user with no friendships gets an empty feed rather than an error."""
    with app.app_context():
        loner = User(username="solo", email="solo@example.com")
        db.session.add(loner)
        db.session.commit()

        assert get_friends_listening_now(loner.id) == []
