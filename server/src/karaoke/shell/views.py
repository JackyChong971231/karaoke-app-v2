"""Domain -> wire. Pure functions. The read boundary where per-owner state is merged:

    party state (reducer)  +  preparation board (Preparer)  +  last clock report (hub)  ->  view

Nothing here decides anything; it formats.
"""

from __future__ import annotations

from collections.abc import Mapping

from karaoke import contract as c
from karaoke.core import SongId, SongMeta
from karaoke.party import AwaitingRestartChoice, Filler, FromQueue, PartyState, Playing
from karaoke.songs.prepare import Device, PrepStatus


def song_view(song: SongMeta) -> c.SongView:
    return c.SongView(
        song_id=song.id, title=song.title, artist=song.artist.name, artist_id=song.artist.id,
        duration_s=song.duration_s,
    )


def readiness(song: SongId, state: PartyState, board: Mapping[SongId, PrepStatus]) -> c.ReadyState | c.PreparingState | c.FailedState:
    """`state.ready` wins (it is what the reducer acts on); else the board's stage; else waiting."""
    if song in state.ready:
        return c.ReadyState(kind="ready")
    return board_readiness(song, board)


def board_readiness(song: SongId, board: Mapping[SongId, PrepStatus]) -> c.ReadyState | c.PreparingState | c.FailedState:
    status = board.get(song)
    if status is None:
        return c.PreparingState(kind="preparing", stage="waiting", progress=None)
    if status.stage == "failed":
        return c.FailedState(kind="failed", reason=status.failure or "processing_crashed")
    if status.stage == "ready":
        return c.ReadyState(kind="ready")
    return c.PreparingState(kind="preparing", stage=status.stage, progress=status.progress)


def _restart_offer(state: PartyState) -> c.RestartOfferView | None:
    if not isinstance(state.phase, AwaitingRestartChoice):
        return None
    offer = state.phase.offer
    return c.RestartOfferView(entries=[song_view(e.song) for e in offer], singer_names=[e.singer_name for e in offer])


def _singer_name(state: PartyState, now: Playing) -> str | None:
    match now.origin:
        case FromQueue(entry):
            return entry.singer_name
        case Filler():
            return None


def phone_view(rev: int, state: PartyState, board: Mapping[SongId, PrepStatus], device: Device,
               flagged: frozenset[SongId]) -> c.PhoneView:
    """`flagged` = songs whose lyrics source is 'transcribed', for the 'may be wrong' badge."""
    now = state.now
    return c.PhoneView(
        rev=rev,
        restart_offer=_restart_offer(state),
        now=c.NowView(
            play_id=now.play_id, song=song_view(now.song), singer_name=_singer_name(state, now),
            is_filler=isinstance(now.origin, Filler), paused=now.paused, semitones=now.semitones,
            lyrics_flagged=now.song.id in flagged,
        ) if isinstance(now, Playing) else None,
        queue=[
            c.EntryView(
                entry_id=e.id, song=song_view(e.song), singer_id=e.singer,
                singer_name=e.singer_name, readiness=readiness(e.song.id, state, board),
            )
            for e in state.queue
        ],
        settings=c.SettingsView(vocal_level=state.settings.vocal_level, av_offset_s=state.settings.av_offset_s),
        tv_connected=state.tv_connected,
        device=device,
    )


def tv_view(rev: int, state: PartyState, resume_at: Mapping[int, float], join_url: str,
            flagged: frozenset[SongId]) -> c.TvView:
    """up_next = first queue entry (ready or not), per the spec 'the next song and its singer are shown'.
    resume_at = hub's last ClockReport position by play_id, so a reloaded TV continues where it was."""
    now = state.now
    first = state.queue[0] if state.queue else None
    return c.TvView(
        rev=rev,
        play=c.TvPlay(
            play_id=now.play_id, song=song_view(now.song), singer_name=_singer_name(state, now),
            paused=now.paused, semitones=now.semitones, lyrics_flagged=now.song.id in flagged,
            resume_at_s=resume_at.get(now.play_id, 0.0),
        ) if isinstance(now, Playing) else None,
        vocal_level=state.settings.vocal_level,
        av_offset_s=state.settings.av_offset_s,
        up_next=c.UpNext(
            title=first.song.title, singer_name=first.singer_name,
            ready=first.song.id in state.ready,
        ) if first else None,
        join_url=join_url,
        restart_offer=_restart_offer(state),
    )
