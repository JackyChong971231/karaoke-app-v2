from karaoke.shell.updates import is_newer, parse_version, pick_release


def test_versions_compare_as_numbers_not_text() -> None:
    assert is_newer("v2.10.0", "2.9.0")
    assert is_newer("2.0.1", "2.0.0")
    assert not is_newer("v2.0.0", "2.0.0")
    assert not is_newer("v1.9.9", "2.0.0")


def test_pre_releases_and_junk_are_never_newer() -> None:
    assert parse_version("v2.1.0-beta") is None
    assert not is_newer("v9.0.0-rc1", "2.0.0")
    assert not is_newer("latest", "2.0.0")


def _release(tag: str, assets: list[dict[str, object]]) -> dict[str, object]:
    return {"tag_name": tag, "html_url": f"https://github.com/x/y/releases/tag/{tag}", "assets": assets}


def test_pick_release_finds_the_installer_for_its_tag() -> None:
    r = pick_release(_release("v2.1.0", [
        {"name": "notes.txt", "browser_download_url": "https://e/notes.txt", "size": 1},
        {"name": "Karaoke-Setup-2.1.0.exe", "browser_download_url": "https://e/setup.exe", "size": 123},
    ]))
    assert r is not None
    assert (r.version, r.installer_url, r.installer_size) == ("2.1.0", "https://e/setup.exe", 123)


def test_pick_release_without_its_installer_offers_nothing() -> None:
    assert pick_release(_release("v2.1.0", [])) is None
    assert pick_release(_release("v2.1.0", [{"name": "Karaoke-Setup-2.0.0.exe",
                                             "browser_download_url": "https://e/old.exe", "size": 1}])) is None
    assert pick_release({"message": "Not Found"}) is None
    assert pick_release(None) is None
