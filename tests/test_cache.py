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
