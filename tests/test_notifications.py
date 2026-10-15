"""
tests/test_notifications.py — Mixtape

Tests for notification side effects on user actions.

Rating a song and adding a song to a playlist are parallel operations:
both should notify the person who originally shared the song, and neither
should notify someone about their own action.
"""

import pytest
from app import create_app, db
from models import User, Song, Playlist, Notification
from services.notification_service import (
    add_to_playlist,
    get_notifications,
    rate_song,
)


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def sharer_and_rater(app):
    """A user who shared a song, and another user who will act on it."""
    with app.app_context():
        sharer = User(username="aaliya", email="aaliya@example.com")
        actor = User(username="kenji", email="kenji@example.com")
        db.session.add_all([sharer, actor])
        db.session.flush()

        song = Song(title="Golden Hour", artist="Solange K", shared_by=sharer.id)
        playlist = Playlist(name="Study Mode", created_by=actor.id)
        db.session.add_all([song, playlist])
        db.session.commit()

        yield {"sharer": sharer, "actor": actor, "song": song, "playlist": playlist}


def test_rating_a_song_notifies_the_sharer(app, sharer_and_rater):
    """Rating someone else's shared song creates a notification for them."""
    with app.app_context():
        sharer = sharer_and_rater["sharer"]
        actor = sharer_and_rater["actor"]
        song = sharer_and_rater["song"]

        rate_song(actor.id, song.id, 5)

        notifications = get_notifications(sharer.id)
        assert len(notifications) == 1
        assert notifications[0]["type"] == "song_rated"
        assert "kenji" in notifications[0]["body"]
        assert "Golden Hour" in notifications[0]["body"]


def test_rating_your_own_song_notifies_nobody(app, sharer_and_rater):
    """A user rating their own shared song does not notify themselves."""
    with app.app_context():
        sharer = sharer_and_rater["sharer"]
        song = sharer_and_rater["song"]

        rate_song(sharer.id, song.id, 4)

        assert get_notifications(sharer.id) == []


def test_rating_and_playlist_add_both_notify(app, sharer_and_rater):
    """Both parallel actions reach the sharer's notification list."""
    with app.app_context():
        sharer = sharer_and_rater["sharer"]
        actor = sharer_and_rater["actor"]
        song = sharer_and_rater["song"]
        playlist = sharer_and_rater["playlist"]

        add_to_playlist(playlist.id, song.id, actor.id)
        rate_song(actor.id, song.id, 3)

        types = {n["type"] for n in get_notifications(sharer.id)}
        assert types == {"song_added_to_playlist", "song_rated"}


def test_invalid_score_creates_no_notification(app, sharer_and_rater):
    """A rejected rating must not leave a notification behind."""
    with app.app_context():
        sharer = sharer_and_rater["sharer"]
        actor = sharer_and_rater["actor"]
        song = sharer_and_rater["song"]

        with pytest.raises(ValueError):
            rate_song(actor.id, song.id, 9)

        assert db.session.query(Notification).count() == 0


def test_single_star_rating_is_not_pluralised(app, sharer_and_rater):
    """A score of 1 reads '1 star', not '1 stars'."""
    with app.app_context():
        sharer = sharer_and_rater["sharer"]
        actor = sharer_and_rater["actor"]
        song = sharer_and_rater["song"]

        rate_song(actor.id, song.id, 1)

        body = get_notifications(sharer.id)[0]["body"]
        assert "1 star." in body
        assert "1 stars" not in body
