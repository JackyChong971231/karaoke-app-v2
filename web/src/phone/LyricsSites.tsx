// Lyrics from lyrics websites, to read on this phone (spec "Read the lyrics from a lyrics site"). View only: nothing
// here changes the TV's lyrics. The laptop reads each site and sends plain text; KKBOX blocks the laptop, so its tab
// is a button that opens KKBOX in this phone's own browser.

import type { JSX } from "react";
import { useEffect, useState } from "react";
import { api } from "../wire/http";
import { assertNever } from "../wire/socket";
import type { LyricsSite, SiteLyricsResponse } from "../wire/types";
import { Icon, Sheet, Spinner } from "./ui";

const SITE_NAMES: Record<LyricsSite, string> = {
  kkbox: "KKBOX",
  lrclib: "LRCLIB",
  utanet: "Uta-Net",
  genius: "Genius",
};

type Loaded = SiteLyricsResponse | { kind: "error" };

export function LyricsButton(props: { songId: string; title: string; artist: string }): JSX.Element {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className="lyrics-button"
        data-testid="lyrics-sites-open"
        aria-haspopup="dialog"
        onClick={() => { setOpen(true); }}
      >
        <Icon name="lyrics" size={18} /> Lyrics
      </button>
      <Sheet
        open={open}
        onClose={() => { setOpen(false); }}
        testId="lyrics-sites"
        title={
          <div className="lyrics-sheet-head">
            <div>
              <div className="sheet-heading">Lyrics</div>
              <div className="sheet-sub">
                {props.title} · {props.artist}
              </div>
            </div>
            <button
              type="button"
              className="round round-sm round-ghost"
              aria-label="Close lyrics"
              data-testid="lyrics-sites-close"
              onClick={() => { setOpen(false); }}
            >
              <Icon name="close" size={20} />
            </button>
          </div>
        }
      >
        {open && <SiteLyrics key={props.songId} songId={props.songId} />}
      </Sheet>
    </>
  );
}

function SiteLyrics(props: { songId: string }): JSX.Element {
  const [sites, setSites] = useState<LyricsSite[] | "error" | null>(null);
  const [site, setSite] = useState<LyricsSite | null>(null);
  const [loaded, setLoaded] = useState<Partial<Record<LyricsSite, Loaded>>>({});

  useEffect(() => {
    const abort = new AbortController();
    api.lyricsSites(props.songId, abort.signal).then(
      (r) => {
        setSites(r.sites);
        setSite(r.sites[0] ?? null);
      },
      () => { if (!abort.signal.aborted) setSites("error"); },
    );
    return () => { abort.abort(); };
  }, [props.songId]);

  const current = site === null ? undefined : loaded[site];
  useEffect(() => {
    if (site === null || current !== undefined) return undefined;
    const abort = new AbortController();
    const done = (answer: Loaded): void => { setLoaded((m) => ({ ...m, [site]: answer })); };
    api.siteLyrics(props.songId, site, abort.signal).then(done, () => {
      if (!abort.signal.aborted) done({ kind: "error" });
    });
    return () => { abort.abort(); };
  }, [props.songId, site, current]);

  if (sites === "error") return <p className="lyrics-note" data-testid="lyrics-sites-error">Lyrics sites are not available for this song.</p>;
  if (sites === null || site === null) return <div className="lyrics-loading"><Spinner size={24} /></div>;

  const retry = (): void => {
    setLoaded((m) => Object.fromEntries(Object.entries(m).filter(([s]) => s !== site)));
  };

  return (
    <div className="lyrics-sites">
      <div className="lyrics-tabs" role="tablist">
        {sites.map((s) => (
          <button
            key={s}
            type="button"
            role="tab"
            aria-selected={s === site}
            className={`lyrics-tab ${s === site ? "is-on" : ""}`}
            data-testid={`lyrics-tab-${s}`}
            onClick={() => { setSite(s); }}
          >
            {SITE_NAMES[s]}
          </button>
        ))}
      </div>
      <div className="lyrics-body" role="tabpanel" data-testid="lyrics-site-body">
        {current === undefined ? (
          <div className="lyrics-loading"><Spinner size={24} /></div>
        ) : (
          <SiteAnswer site={site} answer={current} onRetry={retry} />
        )}
      </div>
    </div>
  );
}

function SiteAnswer(props: { site: LyricsSite; answer: Loaded; onRetry: () => void }): JSX.Element {
  const name = SITE_NAMES[props.site];
  const a = props.answer;
  switch (a.kind) {
    case "text":
      return (
        <>
          <div className="lyrics-text" data-testid="lyrics-site-text">{a.text}</div>
          <p className="lyrics-source">
            From {name}
            {a.pageUrl !== null && (
              <>
                {" · "}
                <a href={a.pageUrl} target="_blank" rel="noopener noreferrer" data-testid="lyrics-site-page">
                  Open page <Icon name="external" size={13} />
                </a>
              </>
            )}
          </p>
        </>
      );
    case "link":
      return (
        <div className="lyrics-link">
          <p className="lyrics-note">
            {a.found
              ? `${name} doesn't let the app read its lyrics, but you can open them in your browser.`
              : `The app couldn't find this song on ${name} itself. Search ${name} in your browser instead.`}
          </p>
          <a className="btn btn-primary btn-block" href={a.pageUrl} target="_blank" rel="noopener noreferrer" data-testid="lyrics-site-link">
            {a.found ? `Open lyrics on ${name}` : `Search ${name}`} <Icon name="external" size={18} />
          </a>
        </div>
      );
    case "none":
      return <p className="lyrics-note" data-testid="lyrics-site-none">{name} has no lyrics for this song.</p>;
    case "down":
    case "error":
      return (
        <div className="lyrics-link">
          <p className="lyrics-note" data-testid="lyrics-site-down">Can't reach {name} right now.</p>
          <button type="button" className="btn btn-block" data-testid="lyrics-site-retry" onClick={props.onRetry}>
            Try again
          </button>
        </div>
      );
    default:
      return assertNever(a);
  }
}
