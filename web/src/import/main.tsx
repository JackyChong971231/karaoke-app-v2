// Import review page (import.html), opened on the laptop. HTTP only (no party socket): the importer is not part of
// the party. Correcting a match reuses the phone's search and video picker.

import type { JSX } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { api } from "../wire/http";
import { assertNever } from "../wire/socket";
import type { ImportItemView, ImportPlanView } from "../wire/types";
import { PickController } from "../phone/pickVideo";
import { SearchPanel } from "../phone/Search";
import { Art, Icon, ReadinessChip, Sheet, Spinner } from "../phone/ui";
import "../phone/phone.css";
import "./import.css";

type Load = { kind: "loading" } | { kind: "missing" } | { kind: "ready"; plan: ImportPlanView };

function useImportPlan(): [Load, () => void] {
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const refresh = useCallback(() => {
    api.importPlan().then(
      (plan) => {
        setLoad({ kind: "ready", plan });
      },
      () => {
        setLoad({ kind: "missing" });
      },
    );
  }, []);
  useEffect(() => {
    refresh();
    const t = window.setInterval(refresh, 2000);
    return () => { window.clearInterval(t); };
  }, [refresh]);
  return [load, refresh];
}

function ImportPage(): JSX.Element {
  const [load, refresh] = useImportPlan();
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [correcting, setCorrecting] = useState<ImportItemView | null>(null);

  const act = useCallback(
    async (key: string, work: () => Promise<unknown>): Promise<boolean> => {
      setBusy((b) => new Set([...b, key]));
      setError(null);
      try {
        await work();
        return true;
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        return false;
      } finally {
        setBusy((b) => new Set([...b].filter((k) => k !== key)));
        refresh();
      }
    },
    [refresh],
  );

  const plan = load.kind === "ready" ? load.plan : null;
  const items = plan?.items ?? [];
  const open = items.filter((i) => !i.imported && i.decision !== "skipped");
  const undecided = open.filter((i) => i.decision === "proposed").length;
  const toImport = open.filter((i) => i.decision === "confirmed" || i.decision === "corrected").length;
  const imported = items.filter((i) => i.imported).length;

  return (
    <div className="imp">
      <header className="imp-head">
        <div className="brand">
          <span className="brand-mark">
            <Icon name="mic" size={18} />
          </span>
          Import the v1 library
        </div>
        <div className="imp-actions">
          <button className="btn" disabled={busy.has("match")} onClick={() => void act("match", () => api.importMatch(20))} data-testid="import-match-20">
            {busy.has("match") && <Spinner size={16} />} Match next 20
          </button>
          <button className="btn" disabled={busy.has("matchAll")} onClick={() => void act("matchAll", () => api.importMatch(null))} data-testid="import-match-all">
            {busy.has("matchAll") && <Spinner size={16} />} Match the rest
          </button>
          <button
            className="btn btn-primary"
            disabled={undecided > 0 || toImport === 0 || busy.has("run")}
            onClick={() => void act("run", api.importRun)}
            data-testid="import-run"
            title={undecided > 0 ? "Confirm, correct, or skip every song first" : undefined}
          >
            {busy.has("run") && <Spinner size={16} />} Import {toImport} {toImport === 1 ? "song" : "songs"}
          </button>
        </div>
      </header>

      <div className="imp-summary">
        <Stat label="To review" value={undecided} />
        <Stat label="Ready to import" value={toImport} />
        <Stat label="Imported" value={imported} />
        <Stat label="Total matched" value={items.length} />
      </div>

      {error !== null && (
        <div className="notice">
          <Icon name="alert" size={18} /> {error}
        </div>
      )}

      {load.kind === "loading" ? (
        <div className="empty">
          <Spinner size={28} />
        </div>
      ) : load.kind === "missing" ? (
        <div className="empty">
          <div className="empty-art">
            <Icon name="alert" size={40} />
          </div>
          <h2>The importer is off</h2>
          <p>Start the server with the v1 folder, for example: uv run karaoke serve --v1 "C:path	o1".</p>
        </div>
      ) : items.length === 0 ? (
        <div className="empty">
          <div className="empty-art">
            <Icon name="queue" size={40} />
          </div>
          <h2>No songs matched yet</h2>
          <p>Press “Match next 20” to match the songs v1 played most. Matching takes a few seconds per song.</p>
        </div>
      ) : (
        <ol className="imp-list">
          {items.map((item) => (
            <ImportRow
              key={item.itemId}
              item={item}
              busy={busy}
              onDecide={(decision) =>
                void act(`${item.itemId}:${decision}`, () => api.importDecide({ itemId: item.itemId, decision, pickId: null }))
              }
              onCorrect={() => { setCorrecting(item); }}
            />
          ))}
        </ol>
      )}
      <CorrectSheet
        item={correcting}
        onClose={() => { setCorrecting(null); }}
        onPicked={(item, pickId) =>
          act(`${item.itemId}:correct`, () => api.importDecide({ itemId: item.itemId, decision: "correct", pickId }))
        }
      />
    </div>
  );
}

function Stat(props: { label: string; value: number }): JSX.Element {
  return (
    <div className="imp-stat">
      <div className="imp-stat-value">{props.value}</div>
      <div className="imp-stat-label">{props.label}</div>
    </div>
  );
}

function ImportRow(props: {
  item: ImportItemView;
  busy: ReadonlySet<string>;
  onDecide: (d: "confirm" | "skip") => void;
  onCorrect: () => void;
}): JSX.Element {
  const { item, busy } = props;
  const anyBusy = [...busy].some((k) => k.startsWith(`${item.itemId}:`));
  return (
    <li className={`imp-row is-${item.decision} ${item.imported ? "is-imported" : ""}`} data-testid="import-row">
      <div className="imp-v1">
        <div className="eyebrow">v1 · played {item.v1PlayCount}×</div>
        <div className="imp-v1-title">{item.v1Title}</div>
      </div>
      <Icon name="back" size={20} className="flip imp-arrow" />
      <div className="imp-match">
        {item.proposed === null ? (
          <div className="muted">No match found. Use Correct to search.</div>
        ) : (
          <>
            <Art songId={item.proposed.songId} title={item.proposed.title} />
            <div className="row-text">
              <div className="row-title">{item.proposed.title}</div>
              <div className="row-sub">{item.proposed.artist}</div>
              <div className="row-meta">
                <VideoNote item={item} />
              </div>
            </div>
          </>
        )}
      </div>
      <div className="imp-status">
        <Status item={item} />
      </div>
      <div className="imp-buttons">
        {item.imported ? null : (
          <>
            <button
              className={`btn btn-sm ${item.decision === "confirmed" ? "btn-on" : ""}`}
              disabled={anyBusy || item.proposed === null}
              onClick={() => { props.onDecide("confirm"); }}
              data-testid="import-confirm"
            >
              {busy.has(`${item.itemId}:confirm`) ? <Spinner size={14} /> : <Icon name="check" size={16} />} Confirm
            </button>
            <button className="btn btn-sm" disabled={anyBusy} onClick={props.onCorrect} data-testid="import-correct">
              Correct…
            </button>
            <button
              className={`btn btn-sm ${item.decision === "skipped" ? "btn-on" : ""}`}
              disabled={anyBusy}
              onClick={() => { props.onDecide("skip"); }}
              data-testid="import-skip"
            >
              Skip
            </button>
          </>
        )}
      </div>
    </li>
  );
}

function VideoNote(props: { item: ImportItemView }): JSX.Element {
  const video = props.item.video;
  if (props.item.reuseV1Video) return <span className="chip chip-warn">Reuses the v1 video</span>;
  if (video === null) return <span className="chip chip-ready">Official music video</span>;
  switch (video.kind) {
    case "official":
      return <span className="chip chip-ready">Official music video</span>;
    case "choose":
      return <span className="chip chip-warn">No official video</span>;
    default:
      return assertNever(video);
  }
}

function Status(props: { item: ImportItemView }): JSX.Element {
  const { item } = props;
  if (item.imported) {
    return (
      <span className="chip chip-ready">
        <Icon name="check" size={14} /> Imported
      </span>
    );
  }
  if (item.readiness !== null) return <ReadinessChip readiness={item.readiness} />;
  const label: Record<ImportItemView["decision"], string> = {
    proposed: "Needs review",
    confirmed: "Confirmed",
    corrected: "Corrected",
    skipped: "Skipped",
  };
  return <span className={`chip imp-decision is-${item.decision}`}>{label[item.decision]}</span>;
}

function CorrectSheet(props: {
  item: ImportItemView | null;
  onClose: () => void;
  onPicked: (item: ImportItemView, pickId: string) => Promise<boolean>;
}): JSX.Element {
  const { item, onClose, onPicked } = props;
  const pick = useMemo(
    () =>
      new PickController(
        async (pickId) => {
          if (item === null) return null;
          const ok = await onPicked(item, pickId);
          return ok ? { kind: "accepted" } : null;
        },
        () => { onClose(); },
      ),
    [item, onPicked, onClose],
  );
  const [message, setMessage] = useState<string | null>(null);
  return (
    <Sheet
      open={item !== null}
      onClose={onClose}
      testId="import-correct-sheet"
      title={
        <div>
          <div className="sheet-heading">Correct the match</div>
          <div className="sheet-sub">
            {item ? `Find the right song for “${item.v1Title}”.` : ""} {message}
          </div>
        </div>
      }
    >
      {item !== null && <SearchPanel key={item.itemId} pick={pick} library={null} onPickFailed={setMessage} autoFocus />}
    </Sheet>
  );
}

const root = document.getElementById("root");
if (root === null) throw new Error("import.html is missing #root");
createRoot(root).render(<ImportPage />);
