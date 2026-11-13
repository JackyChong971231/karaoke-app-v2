"""Spec 00-product.md "Favourite songs": one list per browser, saved on the laptop, restorable after the laptop's
address changes (the phone's browser then starts empty, with a new browser id)."""

from __future__ import annotations

from pathlib import Path

from karaoke.core import ArtistId, ArtistRef, SongId, SongMeta
from karaoke.songs.favourites import Favourites


def song(n: str) -> SongMeta:
    return SongMeta(SongId(f"vid{n}"), f"Song {n}", ArtistRef(ArtistId("UCx"), "Artist"), 200.0)


def fresh(tmp_path: Path) -> Favourites:
    f = Favourites(tmp_path / "favourites.json")
    f.load()
    return f


def test_lists_are_per_browser_newest_first_and_survive_a_restart(tmp_path: Path) -> None:
    f = fresh(tmp_path)
    f.add("b1", "Amy", "net:10.0.0.5", song("1"))
    f.add("b1", "Amy", "net:10.0.0.5", song("2"))
    f.add("b1", "Amy", "net:10.0.0.5", song("1"))
    f.add("b2", "Ben", "net:10.0.0.6", song("3"))
    assert [s.id for s in f.songs("b1")] == ["vid1", "vid2"], "re-adding moves a song to the top"
    f.remove("b1", SongId("vid2"), "Amy", "net:10.0.0.5")
    again = fresh(tmp_path)
    assert again.songs("b1") == (song("1"),)
    assert again.songs("b2") == (song("3"),)
    assert again.get("b2", SongId("vid3")) == song("3") and again.get("b1", SongId("vid3")) is None


def test_restore_offer_by_phone_address_then_by_name_and_claim_moves_the_list(tmp_path: Path) -> None:
    f = fresh(tmp_path)
    f.add("old", "Amy Chan", "net:10.0.0.5", song("1"))
    f.add("old", "Amy Chan", "net:10.0.0.5", song("2"))
    f.add("other", "Ben", "net:10.0.0.6", song("3"))

    by_address = f.offer("net:10.0.0.5", None)
    assert by_address is not None and (by_address.name, by_address.count) == ("Amy Chan", 2)
    assert f.offer("net:10.0.0.9", None) is None
    by_name = f.offer("net:10.0.0.9", "  amy chan ")
    assert by_name is not None and by_name.name == "Amy Chan"
    assert f.offer("net:10.0.0.9", "Nobody") is None

    f.add("new", "Amy", "net:10.0.0.9", song("9"))
    assert f.claim(by_name.token, "new", "Amy", "net:10.0.0.9") == 3
    assert [s.id for s in f.songs("new")] == ["vid9", "vid2", "vid1"]
    assert f.songs("old") == ()
    assert f.claim(by_name.token, "new", "Amy", "net:10.0.0.9") is None, "a token works once"
    assert f.claim("forged", "new", "Amy", None) is None
    assert fresh(tmp_path).songs("new") == f.songs("new")


def test_an_empty_list_or_the_asking_browser_is_never_offered(tmp_path: Path) -> None:
    f = fresh(tmp_path)
    f.add("b1", "Amy", "net:10.0.0.5", song("1"))
    f.remove("b1", SongId("vid1"), "Amy", "net:10.0.0.5")
    assert f.offer("net:10.0.0.5", "Amy") is None
    f.add("b1", "Amy", "net:10.0.0.5", song("1"))
    assert f.offer("net:10.0.0.5", "Amy", exclude="b1") is None


def test_a_corrupt_file_is_moved_aside_not_lost(tmp_path: Path) -> None:
    (tmp_path / "favourites.json").write_text("{not json", encoding="utf-8")
    f = fresh(tmp_path)
    assert f.songs("b1") == ()
    assert len(list(tmp_path.glob("favourites.json.bad-*"))) == 1
