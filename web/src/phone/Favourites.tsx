// Favourite songs: one list per browser, saved on the laptop (spec "Favourite songs").
// FavHeart marks a song from search, the queue, or now playing. FavouritesList queues from the list in one tap.

import type { JSX } from "react";
import type { FavouriteRef, FavouriteView } from "../wire/types";
import { usePhone, useStore } from "./store";
import { formatTime } from "./text";
import { Art, Icon, Spinner } from "./ui";

/** A song in the list by video id, or, for an online result that has no video yet, by title and artist. */
function isFavourite(list: readonly FavouriteView[] | null, songId: string | null, title: string, artistId: string): boolean {
  return (list ?? []).some((f) =>
    songId !== null ? f.song.songId === songId : f.song.title === title && f.song.artistId === artistId,
  );
}

export function FavHeart(props: {
  songRef: FavouriteRef;
  title: string;
  artistId: string;
  size?: "sm" | "md";
}): JSX.Element {
  const store = useStore();
  const { favourites, pending } = usePhone();
  const songId = props.songRef.kind === "song" ? props.songRef.songId : null;
  const on = isFavourite(favourites, songId, props.title, props.artistId);
  // An online result that is already a favourite is removed by its stored video id.
  const stored = !on || songId !== null
    ? null
    : (favourites ?? []).find((f) => f.song.title === props.title && f.song.artistId === props.artistId) ?? null;
  const ref: FavouriteRef = stored ? { kind: "song", songId: stored.song.songId } : props.songRef;
  const control = `fav:${songId ?? (props.songRef.kind === "online" ? props.songRef.onlineKey : "")}`;
  const busy = pending.has(control) || (stored !== null && pending.has(`fav:${stored.song.songId}`));
  return (
    <button
      className={`heart heart-${props.size ?? "sm"} ${on ? "is-on" : ""}`}
      aria-label={on ? `Remove ${props.title} from favourites` : `Add ${props.title} to favourites`}
      aria-pressed={on}
      disabled={busy}
      data-testid="fav-heart"
      onClick={() => void store.toggleFavourite(ref, props.title)}
    >
      {busy ? <Spinner size={16} /> : <Icon name={on ? "heartFill" : "heart"} size={props.size === "md" ? 24 : 20} />}
    </button>
  );
}

export function FavouritesList(props: { emptyHint?: boolean }): JSX.Element | null {
  const store = useStore();
  const { favourites, pending } = usePhone();
  if (favourites === null) return null;
  if (favourites.length === 0) {
    return props.emptyHint === true ? (
      <div className="empty empty-compact" data-testid="favourites-empty">
        <h2>No favourites yet</h2>
        <p>Tap the heart on any song to keep it here for next time.</p>
      </div>
    ) : null;
  }
  return (
    <ul className="list" data-testid="favourites-list">
      {favourites.map((f) => {
        const busy = pending.has(`favq:${f.song.songId}`);
        return (
          <li key={f.song.songId} className="row" data-testid="favourite-row">
            <Art songId={f.song.songId} title={f.song.title} />
            <div className="row-text">
              <div className="row-title">{f.song.title}</div>
              <div className="row-sub">
                {f.song.artist}
                {f.song.durationS > 0 && <span className="muted"> · {formatTime(f.song.durationS)}</span>}
              </div>
              {f.ready && (
                <div className="row-meta">
                  <span className="chip chip-ready">
                    <span className="chip-dot" /> Ready
                  </span>
                </div>
              )}
            </div>
            <FavHeart songRef={{ kind: "song", songId: f.song.songId }} title={f.song.title} artistId={f.song.artistId} />
            <button
              className="add"
              aria-label={`Add ${f.song.title}`}
              disabled={busy}
              data-testid="queue-favourite"
              onClick={() => void store.queueFavourite(f.song.songId, f.song.title)}
            >
              {busy ? <Spinner size={18} /> : <Icon name="plus" size={22} />}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
