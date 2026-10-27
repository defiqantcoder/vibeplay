import pytest

from vibeplay.db import get_connection, init_db, insert_track
from vibeplay.plugins.maintenance.duplicates import find_duplicates


@pytest.fixture
def dup_db(tmp_path):
    db_path = tmp_path / "dup.db"
    init_db(db_path)

    with get_connection(db_path) as conn:
        # 1. MB Recording match
        insert_track(
            conn,
            path="/a.mp3",
            mtime=1,
            size=1,
            file_hash="1",
            duration=100.0,
            bitrate=128000,
            title="T1",
            artist="A1",
        )
        insert_track(
            conn,
            path="/b.flac",
            mtime=2,
            size=2,
            file_hash="2",
            duration=100.0,
            bitrate=900000,
            title="T1",
            artist="A1",
        )

        conn.execute("INSERT INTO enrichment (track_id, mb_recording_id, source, raw_metadata) VALUES (1, 'mb-123', 'test', '{}')")
        conn.execute("INSERT INTO enrichment (track_id, mb_recording_id, source, raw_metadata) VALUES (2, 'mb-123', 'test', '{}')")

        # 2. Artist/Title/Duration match
        insert_track(
            conn,
            path="/c.mp3",
            mtime=3,
            size=3,
            file_hash="3",
            duration=200.0,
            bitrate=192000,
            title="T2",
            artist="A2",
        )
        insert_track(
            conn,
            path="/d.mp3",
            mtime=4,
            size=4,
            file_hash="4",
            duration=201.0,
            bitrate=320000,
            title="T2",
            artist="A2",
        )

        # 3. Not a duplicate (duration too far)
        insert_track(
            conn,
            path="/e.mp3",
            mtime=5,
            size=5,
            file_hash="5",
            duration=205.0,
            bitrate=320000,
            title="T2",
            artist="A2",
        )

    return db_path


def test_find_duplicates(dup_db):
    groups = find_duplicates(dup_db)
    assert len(groups) == 2

    mb_group = next(g for g in groups if g.reason == "MusicBrainz Recording ID match")
    assert mb_group.keep_track_id == 2  # flac preferred

    text_group = next(g for g in groups if g.reason == "Artist, Title, and Duration match")
    assert text_group.keep_track_id == 4  # higher bitrate preferred
    assert len(text_group.tracks) == 2
