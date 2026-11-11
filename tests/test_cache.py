import os
import time

from conftest import make_item

from civitai_widget.cache import DiskCache


def _write(path, size=10, age_s=0):
    path.write_bytes(b"x" * size)
    stamp = time.time() - age_s
    os.utime(path, (stamp, stamp))


def test_image_path_is_sanitized(tmp_path):
    cache = DiskCache(tmp_path)
    assert cache.image_path("123").name == "123_450.jpg"
    assert cache.image_path("../../etc/passwd").parent == tmp_path
    assert "/" not in cache.image_path("a/b").name


def test_has_image_requires_non_empty_file(tmp_path):
    cache = DiskCache(tmp_path)
    assert not cache.has_image("1")
    cache.image_path("1").write_bytes(b"")
    assert not cache.has_image("1")
    cache.image_path("1").write_bytes(b"data")
    assert cache.has_image("1")
    cache.drop_image("1")
    assert not cache.has_image("1")


def test_feed_roundtrip_keeps_cursor(tmp_path):
    cache = DiskCache(tmp_path)
    items = [make_item(1), make_item(2)]
    cache.save_feed("key", items, "cursor-1")
    loaded, cursor, age = cache.load_feed("key")
    assert loaded == items
    assert cursor == "cursor-1"
    assert age < 5
    assert not list(tmp_path.glob("*.tmp"))


def test_load_feed_survives_damaged_file(tmp_path):
    cache = DiskCache(tmp_path)
    assert cache.load_feed("missing") is None
    cache.feed_path("bad").write_text("{not json")
    assert cache.load_feed("bad") is None
    cache.feed_path("odd").write_text('{"items": 5}')
    assert cache.load_feed("odd") is None


def test_cleanup_by_age_and_leftovers(tmp_path):
    cache = DiskCache(tmp_path)
    _write(cache.image_path("fresh"))
    _write(cache.image_path("old"), age_s=8 * 86400)
    _write(tmp_path / "metadata_sfw.json")
    _write(tmp_path / "1_450.jpg.tmp", age_s=2 * 3600)
    _write(tmp_path / "2_450.jpg.AbCdEf", age_s=60)
    cache.save_feed("k", [], "")

    assert cache.cleanup() == 3
    names = {path.name for path in tmp_path.iterdir()}
    assert names == {"fresh_450.jpg", "2_450.jpg.AbCdEf", cache.feed_path("k").name}


def test_cleanup_enforces_size_limit_oldest_first(tmp_path):
    cache = DiskCache(tmp_path)
    for index, age in enumerate((300, 200, 100)):
        _write(cache.image_path(str(index)), size=100, age_s=age)
    cache.cleanup(max_bytes=250)
    assert not cache.has_image("0")
    assert cache.has_image("1") and cache.has_image("2")


def test_touch_protects_recently_used(tmp_path):
    cache = DiskCache(tmp_path)
    _write(cache.image_path("1"), age_s=8 * 86400)
    cache.touch("1")
    cache.cleanup()
    assert cache.has_image("1")
