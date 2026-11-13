// One search box over the library and YouTube Music, plus artist pages and the pick-a-video sheet.
// Shared with the import review page, which corrects a match with the same search and picker.

import type { JSX } from "react";
import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { api } from "../wire/http";
import type { ArtistResponse, LibrarySongHit, OnlineResults, OnlineSongHit, SearchResponse } from "../wire/types";
import type { PickController, PickFlow } from "./pickVideo";
import { formatTime } from "./text";
import { Art, Icon, Sheet, Spinner } from "./ui";

export function usePickFlow(pick: PickController): PickFlow {
  return useSyncExternalStore(pick.subscribe, pick.get);
}

export interface LibraryAction {
  label: string;
  busy: (songId: string) => boolean;
  run: (hit: LibrarySongHit) => void;
}

type Remote<T> = { kind: "idle" } | { kind: "loading"; last: T | null } | { kind: "done"; data: T } | { kind: "error" };

function useRemote<T>(key: string | null, load: (key: string, signal: AbortSignal) => Promise<T>, delayMs: number): Remote<T> {
  const [state, setState] = useState<Remote<T>>({ kind: "idle" });
  const loader = useRef(load);
  loader.current = load;
  useEffect(() => {
    if (key === null) {
      setState({ kind: "idle" });
      return;
    }
    setState((s) => ({ kind: "loading", last: s.kind === "done" ? s.data : s.kind === "loading" ? s.last : null }));
    const abort = new AbortController();
    const t = window.setTimeout(() => {
      loader.current(key, abort.signal).then(
        (data) => { setState({ kind: "done", data }); },
        () => {
          if (!abort.signal.aborted) setState({ kind: "error" });
        },
      );
    }, delayMs);
    return () => {
      window.clearTimeout(t);
      abort.abort();
    };
  }, [key, delayMs]);
  return state;
}

export function SearchPanel(props: {
  pick: PickController;
  /** Null hides library results (the import page can only correct to an online song). */
  library: LibraryAction | null;
  onPickFailed: (message: string) => void;
  autoFocus?: boolean;
}): JSX.Element {
  const [query, setQuery] = useState("");
  const [artist, setArtist] = useState<{ id: string; name: string } | null>(null);
  const trimmed = query.trim();
  const result = useRemote<SearchResponse>(trimmed === "" ? null : trimmed, api.search, 280);
  const flow = usePickFlow(props.pick);
  const { pick, onPickFailed } = props;

  useEffect(() => {
    if (flow.step === "failed") {
      onPickFailed(flow.message);
      pick.dispatch({ type: "cancel" });
    }
  }, [flow, pick, onPickFailed]);

  if (artist !== null) {
    return (
      <ArtistPage
        artist={artist}
        onBack={() => { setArtist(null); }}
        pick={props.pick}
        library={props.library}
      />
    );
  }

  const data = result.kind === "done" ? result.data : result.kind === "loading" ? result.last : null;
  return (
    <div className="search">
      <div className="search-bar">
        <label className="search-field">
          <Icon name="search" size={20} />
          <input
            data-testid="search-input"
            type="search"
            enterKeyHint="search"
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
            placeholder="Songs or artists"
            value={query}
            autoFocus={props.autoFocus}
            onChange={(e) => { setQuery(e.currentTarget.value); }}
          />
          {result.kind === "loading" && <Spinner size={16} />}
          {query !== "" && (
            <button className="search-clear" aria-label="Clear search" onClick={() => { setQuery(""); }}>
              <Icon name="close" size={18} />
            </button>
          )}
        </label>
      </div>
      {trimmed === "" ? (
        <div className="empty empty-search">
          <div className="empty-art">
            <Icon name="search" size={36} />
          </div>
          <h2>Find your song</h2>
          <p>Search by title or artist, in any language. Songs marked Ready start right away.</p>
        </div>
      ) : data === null ? (
        result.kind === "error" ? (
          <div className="notice">Search is not responding. Check the Wi-Fi and try again.</div>
        ) : (
          <ResultSkeleton />
        )
      ) : (
        <Results
          library={props.library === null ? [] : data.library}
          online={data.online}
          pick={props.pick}
          flow={flow}
          libraryAction={props.library}
          onArtist={(id, name) => { setArtist({ id, name }); }}
          query={trimmed}
        />
      )}
      <VideoPicker pick={props.pick} />
    </div>
  );
}

function ArtistPage(props: {
  artist: { id: string; name: string };
  onBack: () => void;
  pick: PickController;
  library: LibraryAction | null;
}): JSX.Element {
  const result = useRemote<ArtistResponse>(props.artist.id, api.artist, 0);
  const flow = usePickFlow(props.pick);
  const data = result.kind === "done" ? result.data : null;
  return (
    <div className="search" data-testid="artist-page">
      <div className="artist-head">
        <button className="round round-sm round-ghost" aria-label="Back to search" onClick={props.onBack} data-testid="artist-back">
          <Icon name="back" />
        </button>
        <Art title={props.artist.name} size="md" />
        <div>
          <div className="eyebrow">Artist</div>
          <h2>{data?.artist ?? props.artist.name}</h2>
        </div>
      </div>
      {data === null ? (
        result.kind === "error" ? <div className="notice">Couldn't load this artist.</div> : <ResultSkeleton />
      ) : (
        <Results
          library={props.library === null ? [] : data.library}
          online={data.online}
          pick={props.pick}
          flow={flow}
          libraryAction={props.library}
          onArtist={null}
          query={null}
        />
      )}
      <VideoPicker pick={props.pick} />
    </div>
  );
}

function Results(props: {
  library: LibrarySongHit[];
  online: OnlineResults;
  pick: PickController;
  flow: PickFlow;
  libraryAction: LibraryAction | null;
  onArtist: ((id: string, name: string) => void) | null;
  query: string | null;
}): JSX.Element {
  const { library, online, flow, libraryAction, onArtist } = props;
  const onlineSongs = online.kind === "ok" ? online.songs : [];
  const artists = onArtist === null ? [] : uniqueArtists(library, onlineSongs, props.query);
  return (
    <div className="results">
      {artists.length > 0 && onArtist !== null && (
        <div className="artist-chips" data-testid="artist-chips">
          {artists.map((a) => (
            <button key={a.id} className="artist-chip" onClick={() => { onArtist(a.id, a.name); }} data-testid="artist-chip">
              <Art title={a.name} size="sm" />
              <span>{a.name}</span>
              <Icon name="back" size={16} className="flip" />
            </button>
          ))}
        </div>
      )}
      {library.length > 0 && libraryAction !== null && (
        <Section title="Ready to sing" count={library.length}>
          {library.map((hit) => (
            <li key={hit.song.songId} className="row" data-testid="library-result">
              <Art songId={hit.song.songId} title={hit.song.title} />
              <div className="row-text">
                <div className="row-title">{hit.song.title}</div>
                <div className="row-sub">
                  <ArtistLink id={hit.song.artistId} name={hit.song.artist} onArtist={onArtist} />
                </div>
                <div className="row-meta">
                  <span className="chip chip-ready" data-testid="ready-badge">
                    <span className="chip-dot" /> Ready
                  </span>
                  {hit.lyricsFlagged && <span className="chip chip-warn">Lyrics may be wrong</span>}
                  <button
                    className="link link-sm"
                    data-testid="library-other-videos"
                    onClick={() => { props.pick.dispatch({ type: "choose", song: libraryAsPickSong(hit) }); }}
                  >
                    <Icon name="video" size={14} /> Other videos
                  </button>
                </div>
              </div>
              <AddButton
                busy={libraryAction.busy(hit.song.songId)}
                label={`${libraryAction.label} ${hit.song.title}`}
                onClick={() => { libraryAction.run(hit); }}
                testId="queue-library"
              />
            </li>
          ))}
        </Section>
      )}
      {online.kind === "unavailable" ? (
        <div className="notice" data-testid="online-unavailable">
          <Icon name="alert" size={18} /> Online search is unavailable right now. Library songs still work.
        </div>
      ) : (
        onlineSongs.length > 0 && (
          <Section title="From YouTube Music" count={onlineSongs.length}>
            {onlineSongs.map((song) => {
                const busy =
                  (flow.step === "resolving" || (flow.step === "queuing" && flow.candidates === null)) &&
                  flow.song.onlineKey === song.onlineKey;
                return (
                  <li key={song.onlineKey} className="row" data-testid="online-result">
                    <Art src={song.thumbnailUrl} title={song.title} />
                    <div className="row-text">
                      <div className="row-title">{song.title}</div>
                      <div className="row-sub">
                        <ArtistLink id={song.artistId} name={song.artist} onArtist={onArtist} />
                        {song.durationS > 0 && <span className="muted"> · {formatTime(song.durationS)}</span>}
                      </div>
                    </div>
                    <AddButton
                      busy={busy}
                      label={`Add ${song.title}`}
                      onClick={() => { props.pick.dispatch({ type: "choose", song }); }}
                      testId="queue-online"
                    />
                  </li>
                );
              })}
          </Section>
        )
      )}
      {library.length === 0 && onlineSongs.length === 0 && online.kind === "ok" && (
        <div className="empty empty-compact">
          <h2>No songs found</h2>
          <p>Try another spelling, or search by the artist.</p>
        </div>
      )}
    </div>
  );
}

function uniqueArtists(
  library: LibrarySongHit[],
  online: OnlineSongHit[],
  query: string | null,
): { id: string; name: string }[] {
  const seen = new Map<string, string>();
  for (const h of library) if (!seen.has(h.song.artistId)) seen.set(h.song.artistId, h.song.artist);
  for (const s of online) if (!seen.has(s.artistId)) seen.set(s.artistId, s.artist);
  const all = [...seen].map(([id, name]) => ({ id, name }));
  const q = query?.toLowerCase() ?? "";
  // Lead with artists whose name matches what was typed, so "eason" shows Eason Chan first.
  all.sort((a, b) => Number(b.name.toLowerCase().includes(q)) - Number(a.name.toLowerCase().includes(q)));
  return all.slice(0, 4);
}

function ArtistLink(props: {
  id: string;
  name: string;
  onArtist: ((id: string, name: string) => void) | null;
}): JSX.Element {
  if (props.onArtist === null) return <span>{props.name}</span>;
  const onArtist = props.onArtist;
  return (
    <button className="artist-link" onClick={() => { onArtist(props.id, props.name); }}>
      {props.name}
    </button>
  );
}

function AddButton(props: { busy: boolean; label: string; onClick: () => void; testId: string }): JSX.Element {
  return (
    <button
      className="add"
      aria-label={props.label}
      disabled={props.busy}
      onClick={props.onClick}
      data-testid={props.testId}
    >
      {props.busy ? <Spinner size={18} /> : <Icon name="plus" size={22} />}
    </button>
  );
}

function Section(props: { title: string; count: number; children: ReactNode }): JSX.Element {
  return (
    <section className="section">
      <h3 className="section-title">
        {props.title} <span className="section-count">{props.count}</span>
      </h3>
      <ul className="list">{props.children}</ul>
    </section>
  );
}

function ResultSkeleton(): JSX.Element {
  return (
    <section className="section">
      <div className="skeleton-line" style={{ width: "35%", marginBottom: 14 }} />
      <ul className="list">
        {[0, 1, 2, 3].map((i) => (
          <li key={i} className="row">
            <div className="art art-sm skeleton" />
            <div className="row-text">
              <div className="skeleton-line" style={{ width: `${String(70 - i * 8)}%` }} />
              <div className="skeleton-line" style={{ width: "40%" }} />
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** A library song as a pick-flow song, so "Other videos" reuses the same sheet. */
export function libraryAsPickSong(hit: LibrarySongHit): OnlineSongHit {
  return {
    onlineKey: `lib:${hit.song.songId}`,
    title: hit.song.title,
    artist: hit.song.artist,
    artistId: hit.song.artistId,
    durationS: hit.song.durationS,
    thumbnailUrl: "",
  };
}

/** Bottom sheet of videos. Phones always see it: the official music video first, marked, with one button to queue
 *  it. The import page sees it only when no official video was found. */
export function VideoPicker(props: { pick: PickController }): JSX.Element {
  const flow = usePickFlow(props.pick);
  const candidates =
    flow.step === "choosing" ? flow.candidates : flow.step === "queuing" ? flow.candidates : null;
  const open = candidates !== null;
  const song = flow.step === "choosing" || flow.step === "queuing" ? flow.song : null;
  const lastSong = useRef(song);
  if (song !== null) lastSong.current = song;
  const shownSong = song ?? lastSong.current;
  const lastCandidates = useRef(candidates);
  if (candidates !== null) lastCandidates.current = candidates;
  const shown = candidates ?? lastCandidates.current ?? [];
  const best = shown[0];
  const hasOfficial = best?.official === true;
  const otherVideos = shownSong?.onlineKey.startsWith("lib:") === true;

  return (
    <Sheet
      open={open}
      onClose={() => { props.pick.dispatch({ type: "cancel" }); }}
      testId="video-picker"
      title={
        <div>
          <div className="sheet-heading">{otherVideos ? "Other videos" : "Choose the video"}</div>
          <div className="sheet-sub">
            {otherVideos
              ? `Sing “${shownSong.title}” with another video. It is prepared as a new copy.`
              : hasOfficial
                ? "The official music video is first. Tap another video to sing with that one instead."
                : `No official music video found${shownSong ? ` for “${shownSong.title}”` : ""}. Choose the one to sing with.`}
          </div>
        </div>
      }
    >
      {best !== undefined && !otherVideos && (
        <button
          className="btn btn-primary btn-block"
          data-testid="video-queue-best"
          disabled={flow.step !== "choosing"}
          onClick={() => { props.pick.dispatch({ type: "tap", pickId: best.pickId }); }}
        >
          <Icon name="plus" size={20} /> {hasOfficial ? "Queue the official MV" : "Queue the top video"}
        </button>
      )}
      <ul className="videos">
        {shown.map((c) => {
          const busy = flow.step === "queuing" && flow.pickId === c.pickId;
          return (
            <li key={c.pickId}>
              <button
                className={`video ${busy ? "is-busy" : ""}`}
                disabled={flow.step !== "choosing"}
                onClick={() => { props.pick.dispatch({ type: "tap", pickId: c.pickId }); }}
                data-testid="video-candidate"
              >
                <span className="video-thumb">
                  <img src={c.thumbnailUrl} alt="" loading="lazy" />
                  {c.durationS > 0 && <span className="video-dur">{formatTime(c.durationS)}</span>}
                  {busy && (
                    <span className="video-busy">
                      <Spinner size={28} />
                    </span>
                  )}
                </span>
                <span className="video-text">
                  {c.official && (
                    <span className="chip chip-ready video-official" data-testid="video-official">
                      <Icon name="star" size={12} /> Official MV
                    </span>
                  )}
                  <span className="video-title">{c.title}</span>
                  <span className="video-channel">{c.channel}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </Sheet>
  );
}
