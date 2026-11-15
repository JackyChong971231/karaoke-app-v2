"""THE wire contract. The single source of truth for every byte between the server and the pages.

Pydantic v2 models. `python -m karaoke.shell.export_schema` dumps `Contract.model_json_schema()` and
`web/scripts/gen-wire.mjs` turns it into `web/src/wire/generated.ts`. That generated file is gitignored and
rebuilt by `predev`, `prebuild`, and `pretypecheck`, so TypeScript can never compile against a stale copy.
There is no hand-written TS mirror of any type in this file.

Rules (each enforced, not just written down):
- Every union has a `kind: Literal[...]` discriminator -> TS discriminated union -> exhaustive `switch` with
  `assertNever` on the pages; Python side matches with `assert_never`.
- Closed vocabularies come from karaoke.vocab, never re-listed here.
- No domain type crosses this file. shell/parse.py turns these into party inputs; wire/views.py builds the views
  from party state. Domain types never import this module (import-linter `party-is-pure`).
- Leaf: imports only karaoke.core and karaoke.vocab (so songs/prepare/_lyrics.py may write LyricsDoc).
- camelCase on the wire via alias_generator; snake_case in Python.
- Named unions (PhoneCommand, Readiness, ...) become `RootModel[...]` in the real file so the schema has a $def and
  TypeScript gets a named type. The sketch writes them as Annotated aliases for readability.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from karaoke.vocab import FailReason, ImportDecision, LyricsSite, LyricsSource, PlaceId, PrepStage, RejectReason


class Wire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", alias_generator=to_camel, populate_by_name=True)


# =====================================================================================
# Lyrics file (written by the Preparer, served as /media/<id>/lyrics.json, read by the TV)
# =====================================================================================

class LyricsWord(Wire):
    text: str
    start: float
    end: float
    gap_before: bool
    """True when the source text had a space before this word. CJK characters are words with gap_before False."""


class LyricsLine(Wire):
    words: list[LyricsWord]
    estimated: bool | None = None
    """Advanced lyrics only: True when the line's time was guessed, not heard. The TV draws it the same."""


class LyricsBreak(Wire):
    """Advanced lyrics only: a stretch of 8 s or more where nobody sings the song."""

    start: float
    end: float
    kind: Literal["intro", "break", "outro"]


class LyricsDoc(Wire):
    """lyrics.json is version 1. lyrics.advanced.json (advanced lyrics matching) is version 2 and may carry breaks."""

    version: Literal[1, 2]
    source: LyricsSource
    language: str
    lines: list[LyricsLine]
    breaks: list[LyricsBreak] | None = None


# =====================================================================================
# Shared view pieces
# =====================================================================================

class SongView(Wire):
    song_id: str
    title: str
    artist: str
    artist_id: str
    duration_s: float


class ReadyState(Wire):
    kind: Literal["ready"]


class PreparingState(Wire):
    kind: Literal["preparing"]
    stage: PrepStage
    progress: float | None


class FailedState(Wire):
    kind: Literal["failed"]
    reason: FailReason


Readiness = Annotated[ReadyState | PreparingState | FailedState, Field(discriminator="kind")]


class EntryView(Wire):
    entry_id: int
    song: SongView
    singer_id: str
    singer_name: str
    readiness: Readiness


class NowView(Wire):
    play_id: int
    song: SongView
    singer_name: str | None
    """None for a filler song."""
    is_filler: bool
    paused: bool
    semitones: int
    lyrics_flagged: bool


class RestartOfferView(Wire):
    entries: list[SongView]
    singer_names: list[str]


class SettingsView(Wire):
    vocal_level: float
    av_offset_s: float
    advanced_lyrics: bool


# =====================================================================================
# Server -> page snapshots. Full snapshots, every time, with a monotonically increasing rev.
# Reconnect and update are the same message, so a page never has a "missed patch" bug.
# =====================================================================================

class PhoneView(Wire):
    rev: int
    restart_offer: RestartOfferView | None
    now: NowView | None
    queue: list[EntryView]
    settings: SettingsView
    tv_connected: bool
    device: Literal["cuda", "cpu"]


class TvPlay(Wire):
    play_id: int
    song: SongView
    singer_name: str | None
    paused: bool
    semitones: int
    lyrics_flagged: bool
    resume_at_s: float
    """0 for a fresh play. After a TV reload, the last position the TV reported for this play_id."""


class UpNext(Wire):
    title: str
    singer_name: str
    ready: bool


class TvView(Wire):
    rev: int
    play: TvPlay | None
    vocal_level: float
    av_offset_s: float
    advanced_lyrics: bool
    """Draw lyrics.advanced.json when the song has one. Switching mid-song swaps the lyrics on the next frame."""
    up_next: UpNext | None
    join_url: str
    restart_offer: RestartOfferView | None


# =====================================================================================
# Commands
# =====================================================================================

class ToFront(Wire):
    at: Literal["front"]


class ToEnd(Wire):
    at: Literal["end"]


class ToBefore(Wire):
    at: Literal["before"]
    entry_id: int


MoveTarget = Annotated[ToFront | ToEnd | ToBefore, Field(discriminator="at")]


class QueueLibraryCmd(Wire):
    kind: Literal["queueLibrary"]
    song_id: str


class QueuePickCmd(Wire):
    kind: Literal["queuePick"]
    pick_id: str
    """From GET /api/video-choice. The server resolves it to SongMeta; the phone never sends titles."""


class RemoveCmd(Wire):
    kind: Literal["remove"]
    entry_id: int


class MoveCmd(Wire):
    kind: Literal["move"]
    entry_id: int
    to: MoveTarget


class SetPausedCmd(Wire):
    kind: Literal["setPaused"]
    play_id: int
    paused: bool


class SkipCmd(Wire):
    kind: Literal["skip"]
    play_id: int


class SetKeyCmd(Wire):
    kind: Literal["setKey"]
    play_id: int
    semitones: int


class StepKeyCmd(Wire):
    """The key + and - buttons. A step, not a target, so a phone behind on updates cannot move the key back."""

    kind: Literal["stepKey"]
    play_id: int
    step: Literal[-1, 1]


class SetVocalCmd(Wire):
    kind: Literal["setVocal"]
    level: float


class SetVocalOnCmd(Wire):
    """The vocal switch. On restores the level the server remembers, the same for every phone."""

    kind: Literal["setVocalOn"]
    on: bool


class SetAvOffsetCmd(Wire):
    kind: Literal["setAvOffset"]
    seconds: float


class QueueFavouriteCmd(Wire):
    """Queue a song from this browser's favourites. Checked against the stored list, so a phone cannot queue an
    arbitrary video id."""

    kind: Literal["queueFavourite"]
    song_id: str


class RenameCmd(Wire):
    kind: Literal["rename"]
    name: str


class ResolveRestartCmd(Wire):
    kind: Literal["resolveRestart"]
    keep: bool


class SetAdvancedLyricsCmd(Wire):
    """The advanced lyrics matching switch, app-wide."""

    kind: Literal["setAdvancedLyrics"]
    on: bool


PhoneCommand = Annotated[
    QueueLibraryCmd | QueuePickCmd | QueueFavouriteCmd | RemoveCmd | MoveCmd | SetPausedCmd | SkipCmd | SetKeyCmd | StepKeyCmd
    | SetVocalCmd | SetVocalOnCmd | SetAvOffsetCmd | RenameCmd | ResolveRestartCmd | SetAdvancedLyricsCmd,
    Field(discriminator="kind"),
]


class TrackEndedCmd(Wire):
    kind: Literal["trackEnded"]
    play_id: int


class TrackFailedCmd(Wire):
    kind: Literal["trackFailed"]
    play_id: int
    reason: str


TvCommand = Annotated[TrackEndedCmd | TrackFailedCmd | ResolveRestartCmd, Field(discriminator="kind")]


# =====================================================================================
# WebSocket envelopes
# =====================================================================================

class PhoneHello(Wire):
    kind: Literal["phoneHello"]
    browser_id: str
    """The random ID this browser keeps. It keys favourites only. The singer is the phone's Wi-Fi address,
    which the server reads from the connection, so a private tab or a cleared browser is the same singer."""
    name: str


class TvHello(Wire):
    kind: Literal["tvHello"]


class PhoneCommandMsg(Wire):
    kind: Literal["phoneCommand"]
    request_id: int
    command: PhoneCommand


class TvCommandMsg(Wire):
    kind: Literal["tvCommand"]
    request_id: int
    command: TvCommand


class ClockReport(Wire):
    """TV -> server, 4 Hz while playing. Telemetry: relayed, never reduced."""

    kind: Literal["clock"]
    play_id: int
    position_s: float
    paused: bool


ClientMessage = Annotated[
    PhoneHello | TvHello | PhoneCommandMsg | TvCommandMsg | ClockReport, Field(discriminator="kind")
]


class Accepted(Wire):
    kind: Literal["accepted"]


class Rejected(Wire):
    kind: Literal["rejected"]
    reason: RejectReason


Outcome = Annotated[Accepted | Rejected, Field(discriminator="kind")]


class ReplyMsg(Wire):
    kind: Literal["reply"]
    request_id: int
    outcome: Outcome


class PhoneViewMsg(Wire):
    kind: Literal["phoneView"]
    view: PhoneView


class TvViewMsg(Wire):
    kind: Literal["tvView"]
    view: TvView


class ClockMsg(Wire):
    """Server -> phones. Relay of the TV's ClockReport with the server receive time for interpolation."""

    kind: Literal["clock"]
    play_id: int
    position_s: float
    paused: bool
    server_time_ms: int


class SupersededMsg(Wire):
    """Sent to an older TV page when a newer one connects. It stops playback and shows 'Opened elsewhere'."""

    kind: Literal["superseded"]


class YouMsg(Wire):
    """Server -> one phone, after its hello: which singer this connection is. The PhoneView is shared by every
    phone, so this is how a phone knows which queue entries are its own."""

    kind: Literal["you"]
    singer_id: str


class ServerHello(Wire):
    """First message on every connection. A page whose generated PROTOCOL differs reloads itself, so a page
    built against an older contract never talks to a newer server."""

    kind: Literal["serverHello"]
    protocol: str


ServerMessage = Annotated[
    ServerHello | YouMsg | ReplyMsg | PhoneViewMsg | TvViewMsg | ClockMsg | SupersededMsg, Field(discriminator="kind")
]


# =====================================================================================
# HTTP (queries that never touch party state)
# =====================================================================================

class LibrarySongHit(Wire):
    song: SongView
    lyrics_flagged: bool


class OnlineSongHit(Wire):
    online_key: str
    title: str
    artist: str
    artist_id: str
    duration_s: float
    thumbnail_url: str


class OnlineOk(Wire):
    kind: Literal["ok"]
    songs: list[OnlineSongHit]


class OnlineDown(Wire):
    kind: Literal["unavailable"]


OnlineResult = Annotated[OnlineOk | OnlineDown, Field(discriminator="kind")]


class SearchResponse(Wire):
    library: list[LibrarySongHit]
    online: OnlineResult


class ArtistResponse(Wire):
    artist: str
    artist_id: str
    library: list[LibrarySongHit]
    online: OnlineResult
    place_id: PlaceId | None = None
    """Where the singer is from, for the browse boxes. None when no shelf has shown them yet."""
    place_chosen: bool = False
    """The user set the place on the control page, rather than the app guessing it."""


# ---- browse (spec "Browse for songs") ----

class PlaceSummary(Wire):
    place_id: PlaceId
    label: str


class BrowseResponse(Wire):
    places: list[PlaceSummary]
    ready_count: int


class LibraryShelfItem(Wire):
    kind: Literal["library"]
    hit: LibrarySongHit


class OnlineShelfItem(Wire):
    kind: Literal["online"]
    song: OnlineSongHit


ShelfItem = Annotated[LibraryShelfItem | OnlineShelfItem, Field(discriminator="kind")]


class ShelfView(Wire):
    title: str
    items: list[ShelfItem]


class SingerView(Wire):
    artist_id: str
    name: str
    photo_url: str
    """Empty until the singer's photo has been fetched; the page shows their initial instead."""


class PlaceResponse(Wire):
    place_id: PlaceId
    label: str
    shelves: list[ShelfView]
    """熱門 lists: the place's chart first, then playlists."""
    library: list[LibrarySongHit]
    """Library songs whose singer is from this place."""
    singers: list[SingerView]
    online_ok: bool


class WhoAmIResponse(Wire):
    is_laptop: bool
    """True when the request comes from the laptop running the app. Its songs show as "System", so the page
    skips asking for a name there. A guest's own laptop is false: it names itself like a phone."""


class ReadyResponse(Wire):
    songs: list[LibrarySongHit]
    """Every library song, newest first."""


class ArtistPlaceRequest(Wire):
    """Control page: set where a singer is from. None returns the singer to the app's guess."""

    artist_id: str
    name: str
    place_id: PlaceId | None


class VideoCandidateView(Wire):
    pick_id: str
    title: str
    channel: str
    thumbnail_url: str
    duration_s: float
    official: bool = False
    """The official music video. At most one, and first in the list."""


class OfficialFound(Wire):
    kind: Literal["official"]
    pick_id: str


class ChooseVideoResponse(Wire):
    kind: Literal["choose"]
    candidates: list[VideoCandidateView]


VideoChoiceResponse = Annotated[OfficialFound | ChooseVideoResponse, Field(discriminator="kind")]


# ---- lyrics sites (view only, on the singer's phone) ----

class LyricsSitesResponse(Wire):
    sites: list[LyricsSite]
    """Every site, the song language's own site first."""


class SiteTextView(Wire):
    kind: Literal["text"]
    site: LyricsSite
    text: str
    page_url: str | None
    """The site's song page. None for LRCLIB, which has no song pages."""


class SiteLinkView(Wire):
    kind: Literal["link"]
    site: LyricsSite
    page_url: str
    found: bool
    """True: the song's own page on the site. False: the site's search results for the song."""


class SiteNoneView(Wire):
    kind: Literal["none"]
    site: LyricsSite


class SiteDownView(Wire):
    kind: Literal["down"]
    site: LyricsSite


SiteLyricsResponse = Annotated[SiteTextView | SiteLinkView | SiteNoneView | SiteDownView, Field(discriminator="kind")]


# ---- favourites (one list per browser) ----

class FavouriteView(Wire):
    song: SongView
    ready: bool
    """In the library, so it starts at once when queued."""


class FavouritesResponse(Wire):
    songs: list[FavouriteView]
    """Newest first."""


class LibrarySongRef(Wire):
    """A song the server already knows by video id: in the library, queued, or playing."""

    kind: Literal["song"]
    song_id: str


class OnlineSongRef(Wire):
    """A search result. The server stores it with its best video, the official one when there is one."""

    kind: Literal["online"]
    online_key: str


FavouriteRef = Annotated[LibrarySongRef | OnlineSongRef, Field(discriminator="kind")]


class FavouriteAddRequest(Wire):
    browser_id: str
    name: str
    ref: FavouriteRef


class FavouriteRemoveRequest(Wire):
    browser_id: str
    name: str
    song_id: str


class RestoreOfferFound(Wire):
    kind: Literal["offer"]
    token: str
    name: str
    count: int


class NoRestoreOffer(Wire):
    kind: Literal["none"]


RestoreOfferResponse = Annotated[RestoreOfferFound | NoRestoreOffer, Field(discriminator="kind")]


class RestoreClaimRequest(Wire):
    token: str
    browser_id: str
    name: str


# ---- importer (review page) ----

class ImportItemView(Wire):
    item_id: str
    v1_title: str
    v1_play_count: int
    proposed: SongView | None
    video: VideoChoiceResponse | None
    reuse_v1_video: bool
    decision: ImportDecision
    imported: bool
    """Derived: the library has final song id."""
    readiness: Readiness | None
    """Derived from the preparation board while importing."""


class ImportPlanView(Wire):
    batch_limit: int
    items: list[ImportItemView]


class ImportDecideRequest(Wire):
    item_id: str
    decision: Literal["confirm", "skip", "correct"]
    pick_id: str | None
    """For 'correct': a pick from a normal search + video choice on the review page."""


# =====================================================================================
# Root. Lists only top-level FAMILIES; every member is reached through its union, so adding a
# message means adding it to one union above and nothing else.
# =====================================================================================

class Contract(Wire):
    client: ClientMessage
    server: ServerMessage
    search: SearchResponse
    artist: ArtistResponse
    browse: BrowseResponse
    place: PlaceResponse
    ready: ReadyResponse
    whoami: WhoAmIResponse
    artist_place: ArtistPlaceRequest
    video_choice: VideoChoiceResponse
    favourites: FavouritesResponse
    favourite_add: FavouriteAddRequest
    favourite_remove: FavouriteRemoveRequest
    restore_offer: RestoreOfferResponse
    restore_claim: RestoreClaimRequest
    lyrics: LyricsDoc
    lyrics_sites: LyricsSitesResponse
    site_lyrics: SiteLyricsResponse
    import_plan: ImportPlanView
    import_decide: ImportDecideRequest
