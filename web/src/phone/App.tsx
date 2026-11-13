// Phone remote (index.html). Screens are thin: they read the store and call store.run(controlId, command).
// Every interactive element carries a data-testid for the harness.
// `desk` is the laptop control page: all three screens side by side instead of tabs.

import type { JSX } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../wire/http";
import type { NowView } from "../wire/types";
import { NowPlaying } from "./NowPlaying";
import { Queue } from "./Queue";
import { SearchPanel } from "./Search";
import {
  createPhoneStore,
  loadIdentity,
  newBrowserId,
  saveIdentity,
  StoreContext,
  usePhone,
  useStore,
  type Identity,
} from "./store";
import { Art, Icon, Sheet, Spinner } from "./ui";

type Tab = "now" | "queue" | "search";

export function App(props: { desk?: boolean }): JSX.Element {
  const [identity, setIdentity] = useState<Identity | null>(loadIdentity);
  if (identity === null) {
    return (
      <NameGate
        onDone={(id) => {
          saveIdentity(id);
          setIdentity(id);
        }}
      />
    );
  }
  return <Connected identity={identity} desk={props.desk === true} />;
}

function Connected(props: { identity: Identity; desk: boolean }): JSX.Element {
  const store = useMemo(() => createPhoneStore(props.identity), [props.identity]);
  return (
    <StoreContext.Provider value={store}>
      <Shell desk={props.desk} />
    </StoreContext.Provider>
  );
}

function Shell(props: { desk: boolean }): JSX.Element {
  const { desk } = props;
  const { view, link, toasts } = usePhone();
  const [tab, setTab] = useState<Tab>("now");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const goSearch = useCallback(() => {
    if (desk) document.querySelector<HTMLInputElement>('[data-testid="search-input"]')?.focus();
    else setTab("search");
  }, [desk]);
  const queueCount = view?.queue.length ?? 0;
  const shows = (t: Tab): boolean => desk || tab === t;

  return (
    <div className={`app ${desk ? "is-desk" : ""}`}>
      <TopBar onSettings={() => { setSettingsOpen(true); }} />
      {link === "connecting" && view !== null && (
        <div className="banner" data-testid="reconnecting">
          <Spinner size={14} /> Reconnecting…
        </div>
      )}
      <main className="screens">
        <section className={`screen ${shows("now") ? "is-active" : ""}`} aria-hidden={!shows("now")}>
          <NowPlaying onFindSong={goSearch} />
        </section>
        <section className={`screen ${shows("queue") ? "is-active" : ""}`} aria-hidden={!shows("queue")}>
          <Queue onFindSong={goSearch} />
        </section>
        <section className={`screen ${shows("search") ? "is-active" : ""}`} aria-hidden={!shows("search")}>
          <PhoneSearch />
        </section>
      </main>
      {!desk && tab !== "now" && view?.now != null && <MiniPlayer now={view.now} onOpen={() => { setTab("now"); }} />}
      {!desk && (
        <nav className="tabbar" aria-label="Sections">
          <TabButton tab="now" current={tab} onSelect={setTab} icon="mic" label="Now playing" />
          <TabButton tab="queue" current={tab} onSelect={setTab} icon="queue" label="Queue" badge={queueCount} />
          <TabButton tab="search" current={tab} onSelect={setTab} icon="search" label="Search" />
        </nav>
      )}
      <div className="toasts" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.tone}`} data-testid="toast">
            {t.tone === "success" && <Icon name="check" size={18} />}
            {t.tone === "error" && <Icon name="alert" size={18} />}
            {t.message}
          </div>
        ))}
      </div>
      <RestartPrompt />
      <SettingsSheet open={settingsOpen} onClose={() => { setSettingsOpen(false); }} />
    </div>
  );
}

function TopBar(props: { onSettings: () => void }): JSX.Element {
  const { identity, view } = usePhone();
  const tv = view?.tvConnected ?? false;
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark">
          <Icon name="mic" size={18} />
        </span>
        Karaoke
      </div>
      <div className="topbar-right">
        <span className={`status ${tv ? "is-on" : ""}`} data-testid="tv-status">
          <Icon name="tv" size={14} /> {tv ? "TV on" : "TV off"}
        </span>
        <button className="avatar" onClick={props.onSettings} aria-label="Settings" data-testid="open-settings">
          {[...identity.name.trim()][0]?.toUpperCase() ?? "?"}
        </button>
      </div>
    </header>
  );
}

function TabButton(props: {
  tab: Tab;
  current: Tab;
  onSelect: (t: Tab) => void;
  icon: "mic" | "queue" | "search";
  label: string;
  badge?: number;
}): JSX.Element {
  const active = props.tab === props.current;
  return (
    <button
      className={`tab ${active ? "is-active" : ""}`}
      onClick={() => { props.onSelect(props.tab); }}
      aria-current={active ? "page" : undefined}
      data-testid={`tab-${props.tab}`}
    >
      <span className="tab-icon">
        <Icon name={props.icon} size={24} />
        {props.badge !== undefined && props.badge > 0 && <span className="tab-badge">{props.badge}</span>}
      </span>
      <span className="tab-label">{props.label}</span>
    </button>
  );
}

function MiniPlayer(props: { now: NowView; onOpen: () => void }): JSX.Element {
  const store = useStore();
  const { pending } = usePhone();
  const { now } = props;
  const busy = pending.has("pause");
  return (
    <div className="mini" data-testid="mini-player">
      <button className="mini-main" onClick={props.onOpen}>
        <Art songId={now.song.songId} title={now.song.title} />
        <span className="row-text">
          <span className="row-title">{now.song.title}</span>
          <span className="row-sub">{now.isFiller ? "Sing-along filler" : now.singerName}</span>
        </span>
      </button>
      <button
        className="round round-sm"
        aria-label={now.paused ? "Resume" : "Pause"}
        disabled={busy}
        onClick={() => void store.run("pause", { kind: "setPaused", playId: now.playId, paused: !now.paused })}
      >
        {busy ? <Spinner size={16} /> : <Icon name={now.paused ? "play" : "pause"} size={20} />}
      </button>
    </div>
  );
}

function PhoneSearch(): JSX.Element {
  const store = useStore();
  const { pending } = usePhone();
  const onFailed = useCallback((message: string) => { store.toast(message, "error"); }, [store]);
  return (
    <SearchPanel
      pick={store.pick}
      onPickFailed={onFailed}
      hearts
      library={{
        label: "Add",
        busy: (songId) => pending.has(`lib:${songId}`),
        run: (hit) => {
          void store.run(`lib:${hit.song.songId}`, { kind: "queueLibrary", songId: hit.song.songId }).then((o) => {
            if (o?.kind === "accepted") store.toast(`Queued “${hit.song.title}”`, "success");
          });
        },
      }}
    />
  );
}

type Offer = { token: string; name: string; count: number };

// First visit from this browser. A phone whose browser starts empty because the laptop's address changed is offered
// its old favourites: first by its Wi-Fi address before it types anything, then by the name it types. Nothing is
// restored unless the singer says yes (spec "Favourite songs").
function NameGate(props: { onDone: (id: Identity) => void }): JSX.Element {
  const [browserId] = useState(newBrowserId);
  const [name, setName] = useState("");
  const [offer, setOffer] = useState<Offer | null>(null);
  const [declined, setDeclined] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ok = name.trim().length > 0;
  useEffect(() => {
    let live = true;
    api.restoreOffer(null).then(
      (r) => { if (live && r.kind === "offer") setOffer(r); },
      () => undefined,
    );
    return () => { live = false; };
  }, []);
  const finish = (finalName: string): void => { props.onDone({ browserId, name: finalName }); };
  const accept = async (o: Offer): Promise<void> => {
    setBusy(true);
    const finalName = name.trim() || o.name;
    try {
      await api.restoreClaim({ token: o.token, browserId, name: finalName });
    } catch {
      // The offer expired; start with an empty list rather than block the singer.
    }
    finish(finalName);
  };
  const submit = async (): Promise<void> => {
    if (!ok) return;
    setBusy(true);
    try {
      const r = await api.restoreOffer(name.trim());
      if (r.kind === "offer" && r.name !== declined) {
        setOffer(r);
        setBusy(false);
        return;
      }
    } catch {
      // No offer when the laptop cannot be reached; the singer still gets in.
    }
    finish(name.trim());
  };
  if (offer !== null) {
    return (
      <div className="gate">
        <div className="gate-glow" />
        <div className="gate-card" data-testid="restore-offer">
          <span className="brand-mark brand-mark-lg">
            <Icon name="heartFill" size={34} />
          </span>
          <h1>Welcome back, {offer.name}</h1>
          <p>
            Keep your {offer.count} favourite {offer.count === 1 ? "song" : "songs"}? They are saved on the karaoke
            laptop from your last visit.
          </p>
          <div className="button-row">
            <button
              className="btn"
              data-testid="restore-no"
              disabled={busy}
              onClick={() => {
                setDeclined(offer.name);
                setOffer(null);
                if (ok) finish(name.trim());
              }}
            >
              No, start fresh
            </button>
            <button className="btn btn-primary" data-testid="restore-yes" disabled={busy} onClick={() => void accept(offer)}>
              {busy ? <Spinner size={16} /> : null} Yes, keep them
            </button>
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="gate">
      <div className="gate-glow" />
      <form
        className="gate-card"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <span className="brand-mark brand-mark-lg">
          <Icon name="mic" size={34} />
        </span>
        <h1>Welcome to karaoke</h1>
        <p>What should we call you? Your name shows on the TV when it is your turn.</p>
        <input
          className="input"
          data-testid="name-input"
          placeholder="Your name"
          maxLength={24}
          autoComplete="nickname"
          value={name}
          onChange={(e) => { setName(e.currentTarget.value); }}
        />
        <button className="btn btn-primary btn-block" type="submit" disabled={!ok || busy} data-testid="name-submit">
          {busy ? <Spinner size={16} /> : null} Let's sing
        </button>
      </form>
    </div>
  );
}

function RestartPrompt(): JSX.Element | null {
  const store = useStore();
  const { view, pending } = usePhone();
  const offer = view?.restartOffer ?? null;
  return (
    <Sheet open={offer !== null} onClose={() => undefined} testId="restart-prompt">
      {offer && (
        <div className="restart">
          <div className="eyebrow">Welcome back</div>
          <h2>Keep the last queue?</h2>
          <p className="muted">
            {offer.entries.length} {offer.entries.length === 1 ? "song was" : "songs were"} waiting when the app
            closed. The first answer from any phone or the TV wins.
          </p>
          <ul className="list list-compact">
            {offer.entries.slice(0, 5).map((s, i) => (
              <li key={`${s.songId}-${String(i)}`} className="row">
                <Art songId={s.songId} title={s.title} />
                <div className="row-text">
                  <div className="row-title">{s.title}</div>
                  <div className="row-sub">{s.artist}</div>
                </div>
              </li>
            ))}
          </ul>
          {offer.entries.length > 5 && <p className="muted">and {offer.entries.length - 5} more</p>}
          <div className="button-row">
            <button
              className="btn"
              data-testid="restart-new"
              disabled={pending.has("restart")}
              onClick={() => void store.run("restart", { kind: "resolveRestart", keep: false })}
            >
              Start new
            </button>
            <button
              className="btn btn-primary"
              data-testid="restart-keep"
              disabled={pending.has("restart")}
              onClick={() => void store.run("restart", { kind: "resolveRestart", keep: true })}
            >
              {pending.has("restart") ? <Spinner size={16} /> : null} Keep queue
            </button>
          </div>
        </div>
      )}
    </Sheet>
  );
}

function SettingsSheet(props: { open: boolean; onClose: () => void }): JSX.Element {
  const store = useStore();
  const { identity, view, pending } = usePhone();
  const [name, setName] = useState(identity.name);
  const offset = view?.settings.avOffsetS ?? 0;
  const setOffset = (seconds: number): void =>
    void store.run("avOffset", { kind: "setAvOffset", seconds: Math.round(seconds * 100) / 100 });
  const renaming = pending.has("rename");
  const changed = name.trim() !== "" && name.trim() !== identity.name;
  return (
    <Sheet open={props.open} onClose={props.onClose} testId="settings" title={<div className="sheet-heading">Settings</div>}>
      <div className="settings">
        <label className="field">
          <span className="field-label">Your name</span>
          <div className="field-row">
            <input
              className="input"
              data-testid="rename-input"
              maxLength={24}
              value={name}
              onChange={(e) => { setName(e.currentTarget.value); }}
            />
            <button
              className="btn btn-primary"
              data-testid="rename-save"
              disabled={!changed || renaming}
              onClick={() =>
                void store.rename(name.trim()).then((ok) => {
                  if (ok) store.toast("Name saved", "success");
                })
              }
            >
              {renaming ? <Spinner size={16} /> : "Save"}
            </button>
          </div>
        </label>
        <div className="field">
          <span className="field-label">TV picture delay</span>
          <p className="field-help">If the lyrics and video run behind the music, raise this until they match.</p>
          <div className="stepper stepper-inline">
            <button className="round round-sm round-ghost" aria-label="Less delay" disabled={pending.has("avOffset")} onClick={() => { setOffset(offset - 0.05); }}>
              <Icon name="minus" size={20} />
            </button>
            <div className="stepper-value" data-testid="av-offset">
              {pending.has("avOffset") ? <Spinner size={16} /> : `${offset.toFixed(2)} s`}
            </div>
            <button className="round round-sm round-ghost" aria-label="More delay" disabled={pending.has("avOffset")} onClick={() => { setOffset(offset + 0.05); }}>
              <Icon name="plus" size={20} />
            </button>
          </div>
        </div>
        {view !== null && (
          <div className="field">
            <span className="field-label">Song preparation</span>
            <p className="field-help">
              {view.device === "cuda"
                ? "Using the laptop's graphics card. A new song takes about half a minute."
                : "Using the laptop's processor. A new song takes a few minutes."}
            </p>
          </div>
        )}
      </div>
    </Sheet>
  );
}
