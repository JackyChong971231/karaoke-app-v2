import type { JSX } from "react";
import { FavHeart } from "./Favourites";
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
  type Modifier,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useState } from "react";
import type { EntryView, MoveTarget } from "../wire/types";
import { usePhone, useStore } from "./store";
import { Art, Icon, ReadinessChip, Sheet, Spinner } from "./ui";

const restrictToVerticalAxis: Modifier = ({ transform }) => ({ ...transform, x: 0 });

function ordered(queue: readonly EntryView[], reorder: readonly number[] | null): EntryView[] {
  if (reorder === null) return [...queue];
  const rank = new Map(reorder.map((id, i) => [id, i]));
  return [...queue].sort((a, b) => (rank.get(a.entryId) ?? Infinity) - (rank.get(b.entryId) ?? Infinity));
}

export function Queue(props: { onFindSong: () => void }): JSX.Element {
  const store = useStore();
  const { view, reorder, me, pending } = usePhone();
  const [menuFor, setMenuFor] = useState<number | null>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  if (view === null) return <ListSkeleton />;
  const entries = ordered(view.queue, reorder);
  const menuEntry = entries.find((e) => e.entryId === menuFor) ?? null;

  const onDragEnd = (ev: DragEndEvent): void => {
    const ids = entries.map((e) => e.entryId);
    const from = ids.indexOf(Number(ev.active.id));
    const to = ev.over === null ? -1 : ids.indexOf(Number(ev.over.id));
    if (from < 0 || to < 0 || from === to) return;
    const next = arrayMove(ids, from, to);
    const after = next[to + 1];
    const target: MoveTarget = after === undefined ? { at: "end" } : { at: "before", entryId: after };
    const entryId = ids[from];
    if (entryId === undefined) return;
    void store.run(`entry:${String(entryId)}:move`, { kind: "move", entryId, to: target }, { reorder: next });
  };

  if (entries.length === 0) {
    return (
      <div className="empty" data-testid="queue-empty">
        <div className="empty-art">
          <Icon name="queue" size={40} />
        </div>
        <h2>The queue is empty</h2>
        <p>
          {view.now?.isFiller === true
            ? "Sing-along songs play until someone queues a song."
            : "Add a song and everyone takes turns, one song each per round."}
        </p>
        <button className="btn btn-primary" onClick={props.onFindSong}>
          <Icon name="search" size={20} /> Find a song
        </button>
      </div>
    );
  }

  return (
    <div className="queue">
      <div className="screen-head">
        <h2>Queue</h2>
        <span className="muted">
          {entries.length} {entries.length === 1 ? "song" : "songs"}
        </span>
      </div>
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        modifiers={[restrictToVerticalAxis]}
        onDragEnd={onDragEnd}
      >
        <SortableContext items={entries.map((e) => e.entryId)} strategy={verticalListSortingStrategy}>
          <ol className="list" data-testid="queue-list">
            {entries.map((e, i) => (
              <QueueRow
                key={e.entryId}
                entry={e}
                index={i}
                mine={me !== null && e.singerId === me}
                busy={[...pending].some((p) => p.startsWith(`entry:${String(e.entryId)}:`))}
                onMenu={() => { setMenuFor(e.entryId); }}
              />
            ))}
          </ol>
        </SortableContext>
      </DndContext>
      <p className="hint">Drag the handle to reorder, or tap a song for more.</p>
      <Sheet
        open={menuEntry !== null}
        onClose={() => { setMenuFor(null); }}
        testId="entry-menu"
        title={
          menuEntry && (
            <div className="sheet-song">
              <Art songId={menuEntry.song.songId} title={menuEntry.song.title} />
              <div className="row-text">
                <div className="row-title">{menuEntry.song.title}</div>
                <div className="row-sub">
                  {menuEntry.song.artist} · {menuEntry.singerName}
                </div>
              </div>
              <FavHeart
                songRef={{ kind: "song", songId: menuEntry.song.songId }}
                title={menuEntry.song.title}
                artistId={menuEntry.song.artistId}
                size="md"
              />
            </div>
          )
        }
      >
        {menuEntry && <EntryActions entry={menuEntry} first={entries[0]?.entryId === menuEntry.entryId} last={entries.at(-1)?.entryId === menuEntry.entryId} onDone={() => { setMenuFor(null); }} />}
      </Sheet>
    </div>
  );
}

function EntryActions(props: { entry: EntryView; first: boolean; last: boolean; onDone: () => void }): JSX.Element {
  const store = useStore();
  const { pending } = usePhone();
  const id = props.entry.entryId;
  const act = async (control: string, cmd: Parameters<typeof store.run>[1]): Promise<void> => {
    const outcome = await store.run(control, cmd);
    if (outcome?.kind === "accepted") props.onDone();
  };
  const action = (control: string, label: string, icon: Parameters<typeof Icon>[0]["name"], cmd: Parameters<typeof store.run>[1], opts: { danger?: boolean; disabled?: boolean; testId: string }): JSX.Element => {
    const key = `entry:${String(id)}:${control}`;
    const busy = pending.has(key);
    return (
      <button
        className={`action ${opts.danger === true ? "action-danger" : ""}`}
        data-testid={opts.testId}
        disabled={busy || opts.disabled === true}
        onClick={() => void act(key, cmd)}
      >
        <span className="action-icon">{busy ? <Spinner /> : <Icon name={icon} size={22} />}</span>
        {label}
      </button>
    );
  };
  return (
    <div className="actions">
      {action("front", "Play next", "up", { kind: "move", entryId: id, to: { at: "front" } }, { testId: "entry-play-next", disabled: props.first })}
      {action("end", "Move to the end", "queue", { kind: "move", entryId: id, to: { at: "end" } }, { testId: "entry-move-end", disabled: props.last })}
      {action("remove", "Remove from queue", "trash", { kind: "remove", entryId: id }, { testId: "entry-remove", danger: true })}
    </div>
  );
}

function QueueRow(props: {
  entry: EntryView;
  index: number;
  mine: boolean;
  busy: boolean;
  onMenu: () => void;
}): JSX.Element {
  const { entry } = props;
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({
    id: entry.entryId,
  });
  return (
    <li
      ref={setNodeRef}
      className={`row row-queue ${isDragging ? "is-dragging" : ""}`}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      data-testid="queue-row"
      data-entry-id={entry.entryId}
    >
      <button className="row-main" onClick={props.onMenu} data-testid="queue-row-open">
        <span className="row-index">{props.index + 1}</span>
        <Art songId={entry.song.songId} title={entry.song.title} />
        <span className="row-text">
          <span className="row-title" data-testid="queue-row-title">
            {entry.song.title}
          </span>
          <span className="row-sub">
            {entry.song.artist}
          </span>
          <span className="row-meta">
            <span className={`singer ${props.mine ? "is-me" : ""}`} data-testid="queue-row-singer">
              <Icon name="mic" size={12} /> {props.mine ? `${entry.singerName} (you)` : entry.singerName}
            </span>
            <ReadinessChip readiness={entry.readiness} />
          </span>
        </span>
      </button>
      <span className="row-trail">
        {props.busy ? (
          <Spinner />
        ) : (
          <button
            ref={setActivatorNodeRef}
            className="grip"
            aria-label={`Reorder ${entry.song.title}`}
            {...attributes}
            {...listeners}
          >
            <Icon name="grip" size={22} />
          </button>
        )}
      </span>
    </li>
  );
}

function ListSkeleton(): JSX.Element {
  return (
    <div className="queue">
      <div className="screen-head">
        <div className="skeleton-line skeleton-lg" style={{ width: "30%" }} />
      </div>
      <ol className="list">
        {[0, 1, 2].map((i) => (
          <li key={i} className="row">
            <div className="art art-sm skeleton" />
            <div className="row-text">
              <div className="skeleton-line" style={{ width: "70%" }} />
              <div className="skeleton-line" style={{ width: "45%" }} />
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
