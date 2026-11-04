import sqlite3

from discoop.cache import SCHEMA_VERSION, Cache, cache_path, clear_cache
from discoop.models import Channel, Server


def test_servers_and_channels_roundtrip():
    with Cache.default() as cache:
        assert cache.servers() == [] and cache.fetched_at("servers") is None
        cache.replace_servers([Server("2", "beta", 10), Server("1", "Alpha", None)])
        cache.replace_channels("1", [Channel("5", "1", "general", 0, None, 3, "topic")])
        assert [s.name for s in cache.servers()] == ["Alpha", "beta"]
        assert cache.channels("1") == [Channel("5", "1", "general", 0, None, 3, "topic")]
        assert cache.fetched_at("servers") is not None
        assert cache.fetched_at("channels:1") is not None


def test_replace_drops_old_rows():
    with Cache.default() as cache:
        cache.replace_servers([Server("1", "Old")])
        cache.replace_servers([Server("2", "New")])
        assert [s.id for s in cache.servers()] == ["2"]
        cache.replace_channels("2", [Channel("5", "2", "a", 0)])
        cache.replace_channels("2", [Channel("6", "2", "b", 0)])
        assert [c.id for c in cache.channels("2")] == ["6"]


def test_old_schema_is_rebuilt():
    path = cache_path()
    path.parent.mkdir(parents=True)
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE servers (whatever TEXT)")
    db.commit()
    db.close()
    with Cache.default() as cache:
        cache.replace_servers([Server("1", "A")])
        assert cache.servers() == [Server("1", "A")]
    db = sqlite3.connect(path)
    assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    db.close()


def test_clear_cache():
    Cache.default().close()
    assert cache_path().exists()
    clear_cache()
    assert not cache_path().exists()
    clear_cache()


from datetime import UTC, datetime, timedelta, timezone  # noqa: E402

from discoop.models import ForumTag, Thread  # noqa: E402
from discoop.snowflake import Window  # noqa: E402

V1_SCHEMA = """
CREATE TABLE servers (id TEXT PRIMARY KEY, name TEXT NOT NULL, member_count INTEGER);
CREATE TABLE channels (
    id TEXT PRIMARY KEY, server_id TEXT NOT NULL, name TEXT NOT NULL, type INTEGER NOT NULL,
    parent_id TEXT, position INTEGER NOT NULL, topic TEXT
);
CREATE INDEX channels_by_server ON channels (server_id);
CREATE TABLE fetched (what TEXT PRIMARY KEY, at REAL NOT NULL);
"""
THEN = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)


def make_thread(seq: int, last: datetime = THEN, **fields) -> Thread:
    defaults = dict(
        id=str(1000 + seq),
        parent_id="300",
        name=f"thread {seq}",
        type=11,
        created=last - timedelta(hours=2),
        last_activity=last,
        archived=True,
        locked=False,
        message_count=7,
        owner_id="900000000000000001",
        applied_tags=("11", "12"),
        last_message_id=str(2000 + seq),
    )
    return Thread(**{**defaults, **fields})


def test_channel_with_forum_fields_roundtrips():
    forum = Channel(
        "204",
        "1",
        "help-center",
        15,
        None,
        2,
        "Ask here",
        last_message_id="1566814241946738698",
        available_tags=(ForumTag("11", "Exam"), ForumTag("12", 'quote " and \\ slash')),
    )
    plain = Channel("5", "1", "general", 0)
    with Cache.default() as cache:
        cache.replace_channels("1", [forum, plain])
        assert sorted(cache.channels("1"), key=lambda c: int(c.id)) == [plain, forum]
        assert cache.channel("204") == forum
        assert cache.channel("204").available_tags[0].name == "Exam"
        assert cache.channel("5").last_message_id is None and cache.channel("5").available_tags == ()


def test_damaged_tag_cells_are_read_as_no_tags():
    with Cache.default() as cache:
        cache.replace_channels("1", [Channel("204", "1", "help", 15, available_tags=(ForumTag("11", "A"),))])
    db = sqlite3.connect(cache_path())
    db.execute("UPDATE channels SET available_tags = 'not json'")
    db.commit()
    db.close()
    with Cache.default() as cache:
        assert cache.channel("204").available_tags == ()


def test_version_1_database_is_rebuilt_with_the_new_tables():
    path = cache_path()
    path.parent.mkdir(parents=True)
    db = sqlite3.connect(path)
    db.executescript(V1_SCHEMA)
    db.execute("INSERT INTO servers VALUES ('1', 'Old server', 5)")
    db.execute("INSERT INTO channels VALUES ('5', '1', 'general', 0, NULL, 3, 'topic')")
    db.execute("INSERT INTO fetched VALUES ('servers', 1.0)")
    db.execute("PRAGMA user_version = 1")
    db.commit()
    db.close()
    assert SCHEMA_VERSION >= 2
    with Cache.default() as cache:
        assert cache.servers() == [] and cache.channels("1") == [] and cache.fetched_at("servers") is None
        assert cache.cached_threads("300") is None
        cache.replace_channels("1", [Channel("5", "1", "general", 0, last_message_id="9")])
        cache.replace_threads("300", [make_thread(1)], covered_from=None)
        assert cache.channel("5").last_message_id == "9"
        assert cache.thread("1001") == make_thread(1)
    db = sqlite3.connect(path)
    assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    db.close()
    with Cache.default() as cache:  # a second open keeps what the first stored
        assert cache.thread("1001") == make_thread(1)


def test_threads_roundtrip_with_every_field():
    cet = timezone(timedelta(hours=1))
    full = make_thread(1, created=THEN.astimezone(cet) - timedelta(days=2), locked=True)
    bare = make_thread(
        2,
        THEN - timedelta(hours=1),
        message_count=None,
        owner_id=None,
        applied_tags=(),
        archived=False,
        last_message_id=None,
    )
    with Cache.default() as cache:
        cache.replace_threads("300", [bare, full], covered_from=None)
        assert cache.threads("300") == [full, bare]  # newest activity first
        assert cache.thread("1001") == full and cache.thread("1002") == bare
        assert cache.thread("1001").created.utcoffset() is not None
        assert cache.thread("404") is None
        assert cache.fetched_at("threads:300") is not None


def test_threads_are_sorted_by_activity_then_id():
    same_time = [make_thread(3), make_thread(1), make_thread(2)]
    newer = make_thread(4, THEN + timedelta(hours=1))
    with Cache.default() as cache:
        cache.replace_threads("300", [*same_time, newer], covered_from=None)
        assert [t.id for t in cache.threads("300")] == ["1004", "1003", "1002", "1001"]


def test_replace_threads_only_replaces_its_own_parent():
    with Cache.default() as cache:
        cache.replace_threads("300", [make_thread(1), make_thread(2)], covered_from=None)
        cache.replace_threads("301", [make_thread(5, parent_id="301")], covered_from=None)
        cache.replace_threads("300", [make_thread(3)], covered_from=None)
        assert [t.id for t in cache.threads("300")] == ["1003"]
        assert [t.id for t in cache.threads("301")] == ["1005"]
        assert cache.thread("1001") is None
        assert cache.threads("999") == []


def test_replace_threads_stores_under_the_given_parent():
    with Cache.default() as cache:
        cache.replace_threads("300", [make_thread(1, parent_id="elsewhere")], covered_from=None)
        assert [t.id for t in cache.threads("300")] == ["1001"]
        assert cache.thread("1001").parent_id == "300"


def test_an_empty_list_of_threads_is_cached_and_has_an_age():
    with Cache.default() as cache:
        assert cache.cached_threads("300") is None and cache.fetched_at("threads:300") is None
        cache.replace_threads("300", [], covered_from=None)
        cached = cache.cached_threads("300")
        assert cached is not None and cached.threads == () and cached.covered_from is None
        assert 0 <= cached.age() < 5
        assert cached.fetched_at == cache.fetched_at("threads:300")


def test_cached_threads_remember_what_they_cover():
    start = THEN - timedelta(days=7)
    with Cache.default() as cache:
        cache.replace_threads("300", [make_thread(1)], covered_from=start)
        cached = cache.cached_threads("300")
        assert cached.covered_from == start and cached.threads == (make_thread(1),)
        assert cached.covers(Window(start, THEN))
        assert cached.covers(Window(start + timedelta(days=1), THEN))
        assert not cached.covers(Window(start - timedelta(seconds=1), THEN))
        assert not cached.covers(Window(None, THEN))
        cache.replace_threads("300", [make_thread(1)], covered_from=None)  # the whole history
        everything = cache.cached_threads("300")
        assert everything.covered_from is None
        assert everything.covers(Window(None, THEN)) and everything.covers(Window(start, THEN))


def test_clear_cache_drops_the_threads_too():
    with Cache.default() as cache:
        cache.replace_threads("300", [make_thread(1)], covered_from=None)
    clear_cache()
    with Cache.default() as cache:
        assert cache.threads("300") == [] and cache.cached_threads("300") is None
