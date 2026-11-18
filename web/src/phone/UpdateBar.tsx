// Control page only: "Karaoke 2.1.0 is available" with an Upgrade button. The installed app checks GitHub once
// when it starts; nothing upgrades until someone presses the button. Dismissing hides the bar until the next start.

import type { JSX } from "react";
import { useEffect, useState } from "react";
import { api } from "../wire/http";
import type { UpdateResponse } from "../wire/types";
import { Spinner } from "./ui";

export function UpdateBar(): JSX.Element | null {
  const [info, setInfo] = useState<UpdateResponse | null>(null);
  const [hidden, setHidden] = useState(false);
  const [pressed, setPressed] = useState(false);

  useEffect(() => {
    let live = true;
    // The check runs in the background at start, so ask again a few times while it may still be answering.
    const ask = (): void => {
      api.update().then((r) => { if (live) setInfo(r); }, () => undefined);
    };
    ask();
    const timers = [5_000, 20_000, 60_000].map((ms) => window.setTimeout(ask, ms));
    return () => {
      live = false;
      timers.forEach((t) => { window.clearTimeout(t); });
    };
  }, []);

  useEffect(() => {
    if (!pressed) return undefined;
    // While downloading, watch for a failure; on success the app closes and this page goes offline.
    const t = window.setInterval(() => {
      api.update().then(setInfo, () => undefined);
    }, 2_000);
    return () => { window.clearInterval(t); };
  }, [pressed]);

  if (info === null || hidden) return null;

  if (info.failedVersion != null && info.available === null) {
    return (
      <div className="update-bar is-failed" data-testid="update-failed">
        Upgrading to Karaoke {info.failedVersion} failed. You are still on {info.current}.
        <button className="update-bar-close" aria-label="Dismiss" onClick={() => { setHidden(true); }}>×</button>
      </div>
    );
  }
  const offer = info.available;
  if (offer == null) return null;

  const upgrade = (): void => {
    if (!window.confirm(
      `Upgrade to Karaoke ${offer.version}?\n\nThe app closes for about a minute, then starts again by itself. ` +
      "Prepared songs and settings are kept.",
    )) return;
    setPressed(true);
    api.upgrade().then(() => {
      setInfo({ ...info, phase: "downloading" });
    }, () => {
      setPressed(false);
      setInfo({ ...info, phase: "failed" });
    });
  };

  const busy = info.phase === "downloading" || (pressed && info.phase !== "failed");
  return (
    <div className={`update-bar ${info.phase === "failed" ? "is-failed" : ""}`} data-testid="update-bar">
      {busy ? (
        <><Spinner size={14} /> Downloading Karaoke {offer.version}. The app restarts when it is ready…</>
      ) : (
        <>
          {info.phase === "failed"
            ? `Downloading Karaoke ${offer.version} failed. Check the internet and try again.`
            : `Karaoke ${offer.version} is available.`}
          <a href={offer.notesUrl} target="_blank" rel="noreferrer">What&apos;s new</a>
          <button className="btn btn-primary" data-testid="upgrade" onClick={upgrade}>Upgrade</button>
          <button className="update-bar-close" aria-label="Dismiss" onClick={() => { setHidden(true); }}>×</button>
        </>
      )}
    </div>
  );
}
