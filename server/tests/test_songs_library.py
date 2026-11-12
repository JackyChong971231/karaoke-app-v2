import os
import shutil
from pathlib import Path

import pytest

from karaoke.core import ArtistId, ArtistRef, SongId, SongMeta
from karaoke.songs.library import CloudSyncedRoot, IncompleteSong, Library, SongRecord

FILES = ("video.mp4", "instrumental.opus", "vocals.opus", "lyrics.json")


def record(vid: str, title: str, artist_id: str, names: tuple[str, ...], alt: tuple[str, ...] = ()) -> SongRecord:
    meta = SongMeta(SongId(vid), title, ArtistRef(ArtistId(artist_id), names[0]), 200.0)
    return SongRecord(meta, names, alt or (title,), "zh", "lrclib", f"https://www.youtube.com/watch?v={vid}")


def put(lib: Library, r: SongRecord) -> None:
    d = lib.staging_dir(r.meta.id)
    for f in FILES:
        (d / f).write_bytes(b"data")
    lib.install(r.meta.id, r)


@pytest.fixture
def lib(tmp_path: Path) -> Library:
    library = Library(tmp_path / "library")
    library.open()
    return library


def test_install_publishes_a_complete_folder_and_clears_staging(lib: Library) -> None:
    r = record("vid00000001", "陀飛輪", "UCeason", ("陳奕迅",))
    put(lib, r)
    assert lib.has(r.meta.id) and lib.get(r.meta.id) == r
    assert sorted(p.name for p in (lib.root / r.meta.id).iterdir()) == sorted([*FILES, "song.json"])
    assert not (lib.root / ".staging" / r.meta.id).exists()
    assert lib.media_path(r.meta.id, "vocals.opus") == lib.root / r.meta.id / "vocals.opus"


def test_incomplete_staging_is_refused_and_not_published(lib: Library) -> None:
    r = record("vid00000002", "x", "UCx", ("x",))
    d = lib.staging_dir(r.meta.id)
    (d / "video.mp4").write_bytes(b"v")
    with pytest.raises(IncompleteSong):
        lib.install(r.meta.id, r)
    assert not lib.has(r.meta.id)
    assert lib.media_path(r.meta.id, "video.mp4") is None


def test_install_is_idempotent(lib: Library) -> None:
    r = record("vid00000003", "x", "UCx", ("x",))
    put(lib, r)
    lib.staging_dir(r.meta.id)
    lib.install(r.meta.id, r)
    assert lib.count() == 1 and not (lib.root / ".staging" / r.meta.id).exists()


def test_search_finds_any_artist_spelling_title_and_script(lib: Library) -> None:
    put(lib, record("vid00000004", "陀飛輪", "UCeason", ("陳奕迅",)))
    put(lib, record("vid00000005", "富士山下", "UCeason", ("Eason Chan",)))
    put(lib, record("vid00000006", "Complicated", "UCavril", ("Avril Lavigne",), ("Complicated", "超複雜")))
    ids = lambda q: sorted(r.meta.id for r in lib.search(q))
    assert ids("eason") == ["vid00000004", "vid00000005"]
    assert ids("陳奕迅") == ["vid00000004", "vid00000005"]
    assert ids("陈奕迅 陀飞轮") == ["vid00000004"]
    assert ids("ＣＯＭＰＬＩＣＡＴＥＤ") == ["vid00000006"]
    assert ids("超複雜") == ["vid00000006"]
    assert ids("nothing") == []
    entry = lib.artist(ArtistId("UCeason"))
    assert entry and set(entry.names) == {"陳奕迅", "Eason Chan"} and len(entry.songs) == 2


def test_index_is_rebuilt_from_the_folders(lib: Library) -> None:
    put(lib, record("vid00000007", "a", "UCa", ("A",)))
    put(lib, record("vid00000008", "b", "UCb", ("B",)))
    shutil.rmtree(lib.root / "vid00000008")
    again = Library(lib.root)
    again.open()
    assert again.count() == 1 and again.search("b") == []


def test_random_pick_avoids_recent_fillers_until_none_are_left(lib: Library) -> None:
    for i in range(3):
        put(lib, record(f"vid0000001{i}", f"t{i}", "UCa", ("A",)))
    picks = {lib.random_pick({SongId("vid00000010"), SongId("vid00000011")}).id for _ in range(10)}  # type: ignore[union-attr]
    assert picks == {"vid00000012"}
    assert lib.random_pick({SongId(f"vid0000001{i}") for i in range(3)}) is not None


def test_empty_library_has_no_filler(lib: Library) -> None:
    assert lib.random_pick(()) is None


def test_cloud_synced_root_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OneDrive", str(tmp_path / "sync"))
    with pytest.raises(CloudSyncedRoot):
        Library(tmp_path / "sync" / "Music" / "karaoke").open()
    with pytest.raises(CloudSyncedRoot):
        Library(tmp_path / "Dropbox" / "karaoke").open()
    Library(tmp_path / "local" / "karaoke").open()


def test_old_staging_is_deleted_and_young_staging_kept(lib: Library) -> None:
    old = lib.staging_dir(SongId("oldoldoldol"))
    (old / "video.mp4").write_bytes(b"x")
    young = lib.staging_dir(SongId("youngyoungy"))
    (young / "video.mp4").write_bytes(b"x")
    ancient = 1_000_000_000
    for p in (old, old / "video.mp4"):
        os.utime(p, (ancient, ancient))
    Library(lib.root).open()
    assert not old.exists() and young.exists()
