// Browse (spec "Browse for songs"): the search screen opens on boxes, one per place (香港 台灣 中國 日本 韓國 歐美),
// plus Ready to sing and My favourites. A place page shows its 熱門 shelves, its library songs, and its singers.

import type { JSX } from "react";
import { useEffect, useRef, useState } from "react";
import { api } from "../wire/http";
import type { BrowseResponse, LibrarySongHit, PlaceId, PlaceResponse, ReadyResponse } from "../wire/types";
import { FavouritesList } from "./Favourites";
import type { PickController, PickFlow } from "./pickVideo";
import { LibraryRow, OnlineRow, ResultSkeleton, Section, type LibraryAction } from "./Search";
import { Art, Icon } from "./ui";

export type Nav =
  | { kind: "place"; id: PlaceId; label: string }
  | { kind: "ready" }
  | { kind: "artist"; id: string; name: string };

/** One colour per place, so the boxes read at a glance. */
const TINT: Record<PlaceId, string> = {
  hk: "linear-gradient(135deg, #ff5f6d, #c2185b)",
  tw: "linear-gradient(135deg, #36d1dc, #2b6cb0)",
  cn: "linear-gradient(135deg, #f7971e, #d4380d)",
  jp: "linear-gradient(135deg, #ff9a9e, #e0567c)",
  kr: "linear-gradient(135deg, #a18cd1, #6a4fd8)",
  west: "linear-gradient(135deg, #43e97b, #138a72)",
};

const SUB: Record<PlaceId, string> = {
  hk: "廣東歌 熱門",
  tw: "華語 熱門",
  cn: "內地 熱門",
  jp: "J-Pop 熱門",
  kr: "K-Pop 熱門",
  west: "Western hits",
};

type Loaded<T> = { kind: "loading" } | { kind: "done"; data: T } | { kind: "error" };

function useLoad<T>(load: (key: string, signal: AbortSignal) => Promise<T>, key: string): Loaded<T> {
  const [state, setState] = useState<Loaded<T>>({ kind: "loading" });
  const loader = useRef(load);
  loader.current = load;
  useEffect(() => {
    const abort = new AbortController();
    setState({ kind: "loading" });
    loader.current(key, abort.signal).then(
      (data) => { setState({ kind: "done", data }); },
      () => { if (!abort.signal.aborted) setState({ kind: "error" }); },
    );
    return () => { abort.abort(); };
  }, [key]);
  return state;
}

export function BrowseHome(props: { onOpen: (nav: Nav) => void }): JSX.Element {
  const browse = useLoad<BrowseResponse>(api.browse, "browse");
  const data = browse.kind === "done" ? browse.data : null;
  return (
    <div className="browse" data-testid="browse">
      <div className="boxes">
        {(data?.places ?? []).map((p) => (
          <button
            key={p.placeId}
            className="box"
            style={{ background: TINT[p.placeId] }}
            data-testid={`box-${p.placeId}`}
            onClick={() => { props.onOpen({ kind: "place", id: p.placeId, label: p.label }); }}
          >
            <span className="box-label">{p.label}</span>
            <span className="box-sub">{SUB[p.placeId]}</span>
          </button>
        ))}
        {data !== null && (
          <button className="box box-ready" data-testid="box-ready" onClick={() => { props.onOpen({ kind: "ready" }); }}>
            <span className="box-label">
              <Icon name="check" size={18} /> Ready to sing
            </span>
            <span className="box-sub">{data.readyCount} songs start at once</span>
          </button>
        )}
        {data === null &&
          [0, 1, 2, 3, 4, 5].map((i) => <div key={i} className="box skeleton" />)}
      </div>
      {browse.kind === "error" && <div className="notice">Couldn't reach the karaoke laptop. Check the Wi-Fi.</div>}
      <section className="section" data-testid="favourites">
        <h3 className="section-title">
          <Icon name="heartFill" size={14} /> My favourites
        </h3>
        <FavouritesList emptyHint />
      </section>
    </div>
  );
}

function PageHead(props: { title: string; eyebrow: string; onBack: () => void; testId: string }): JSX.Element {
  return (
    <div className="artist-head">
      <button className="round round-sm round-ghost" aria-label="Back" onClick={props.onBack} data-testid={`${props.testId}-back`}>
        <Icon name="back" />
      </button>
      <div>
        <div className="eyebrow">{props.eyebrow}</div>
        <h2>{props.title}</h2>
      </div>
    </div>
  );
}

export function PlacePage(props: {
  place: { id: PlaceId; label: string };
  onBack: () => void;
  onArtist: (id: string, name: string) => void;
  pick: PickController;
  flow: PickFlow;
  library: LibraryAction | null;
  hearts: boolean;
}): JSX.Element {
  const page = useLoad<PlaceResponse>(api.place, props.place.id);
  const library = props.library;
  const data = page.kind === "done" ? page.data : null;
  const rows = (items: PlaceResponse["shelves"][number]["items"]): JSX.Element[] =>
    items.flatMap((item) => {
      if (item.kind === "online") {
        return [<OnlineRow key={item.song.onlineKey} song={item.song} pick={props.pick} flow={props.flow} onArtist={props.onArtist} hearts={props.hearts} />];
      }
      return props.library === null ? [] : [
        <LibraryRow key={item.hit.song.songId} hit={item.hit} pick={props.pick} action={props.library} onArtist={props.onArtist} hearts={props.hearts} />,
      ];
    });
  return (
    <div className="search" data-testid="place-page">
      <PageHead title={props.place.label} eyebrow="熱門" onBack={props.onBack} testId="place" />
      {data === null ? (
        page.kind === "error" ? <div className="notice">Couldn't load this page.</div> : <ResultSkeleton />
      ) : (
        <div className="results">
          {data.shelves.length === 0 && (
            <div className="notice" data-testid="place-offline">
              <Icon name="alert" size={18} />
              {data.onlineOk ? " No 熱門 songs found right now." : " 熱門 songs are unavailable right now. Library songs still work."}
            </div>
          )}
          {data.shelves.map((shelf) => (
            <div key={shelf.title} data-testid="shelf">
              <Section title={shelf.title} count={shelf.items.length}>
                {rows(shelf.items)}
              </Section>
            </div>
          ))}
          {data.library.length > 0 && library !== null && (
            <div data-testid="place-library">
              <Section title="Ready to sing" count={data.library.length}>
                {data.library.map((hit) => (
                  <LibraryRow key={hit.song.songId} hit={hit} pick={props.pick} action={library} onArtist={props.onArtist} hearts={props.hearts} />
                ))}
              </Section>
            </div>
          )}
          {data.singers.length > 0 && (
            <section className="section">
              <h3 className="section-title">Singers</h3>
              <div className="singers" data-testid="singers">
                {data.singers.map((s) => (
                  <button key={s.artistId} className="artist-tile" data-testid="singer" onClick={() => { props.onArtist(s.artistId, s.name); }}>
                    {s.photoUrl === "" ? <Art title={s.name} size="md" /> : <Art src={s.photoUrl} title={s.name} size="md" />}
                    <span className="artist-tile-name">{s.name}</span>
                  </button>
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}

export function ReadyPage(props: {
  onBack: () => void;
  onArtist: (id: string, name: string) => void;
  pick: PickController;
  library: LibraryAction;
  hearts: boolean;
}): JSX.Element {
  const page = useLoad<ReadyResponse>(api.ready, "ready");
  const songs: LibrarySongHit[] = page.kind === "done" ? page.data.songs : [];
  return (
    <div className="search" data-testid="ready-page">
      <PageHead title="Ready to sing" eyebrow="On the laptop" onBack={props.onBack} testId="ready" />
      {page.kind === "loading" ? (
        <ResultSkeleton />
      ) : page.kind === "error" ? (
        <div className="notice">Couldn't load the library.</div>
      ) : (
        <div className="results">
          <Section title="Newest first" count={songs.length}>
            {songs.map((hit) => (
              <LibraryRow key={hit.song.songId} hit={hit} pick={props.pick} action={props.library} onArtist={props.onArtist} hearts={props.hearts} />
            ))}
          </Section>
        </div>
      )}
    </div>
  );
}
