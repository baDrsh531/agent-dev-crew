import { useEffect, useRef, useState } from "react";
import { phaseLabel, roleLabel } from "../labels";
import { elapsedLabel, gapsBetween } from "../projection";
import type { Phase, RunEvent } from "../types";

const SPEEDS = [1, 4, 10, 40] as const;

interface Props {
  events: RunEvent[];
  cursor: number;
  onCursor: (cursor: number) => void;
  onExit: () => void;
  phase: Phase;
}

/**
 * Rewind a run.
 *
 * This is what an event store buys that a status column cannot: the whole run
 * is kept as an ordered log, so any moment in it can be rebuilt exactly. The
 * scrubber is not a video — it re-projects the same events the live view
 * projects, so the pipeline, the artifacts and the counters at position N are
 * the state the run was actually in at position N. Nothing here can show
 * something the live view could not.
 *
 * Playback follows the run's own timing rather than a fixed tick, so the pause
 * while an agent thinks and the burst while it calls three tools in a row both
 * read as they happened — which is what makes watching it useful rather than
 * decorative. When a run goes wrong, this is how you find the exact event
 * where it turned.
 */
export function ReplayControls({ events, cursor, onCursor, onExit, phase }: Props) {
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState<number>(4);
  const timer = useRef<number>();
  const gaps = useRef<number[]>([]);

  if (gaps.current.length !== events.length) {
    gaps.current = gapsBetween(events);
  }

  useEffect(() => {
    if (!playing) return;
    if (cursor >= events.length) {
      setPlaying(false);
      return;
    }
    const delay = (gaps.current[cursor] ?? 200) / speed;
    timer.current = window.setTimeout(() => onCursor(cursor + 1), delay);
    return () => window.clearTimeout(timer.current);
  }, [playing, cursor, speed, events.length, onCursor]);

  // Keyboard, because scrubbing to one specific event with a mouse is
  // miserable and finding one specific event is the whole point.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      switch (event.key) {
        case " ":
          event.preventDefault();
          setPlaying((p) => !p);
          break;
        case "ArrowLeft":
          event.preventDefault();
          setPlaying(false);
          onCursor(Math.max(0, cursor - (event.shiftKey ? 10 : 1)));
          break;
        case "ArrowRight":
          event.preventDefault();
          setPlaying(false);
          onCursor(Math.min(events.length, cursor + (event.shiftKey ? 10 : 1)));
          break;
        case "Home":
          event.preventDefault();
          onCursor(0);
          break;
        case "End":
          event.preventDefault();
          setPlaying(false);
          onCursor(events.length);
          break;
        case "Escape":
          onExit();
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cursor, events.length, onCursor, onExit]);

  const atEnd = cursor >= events.length;
  const at = events[Math.min(cursor, events.length - 1)];

  return (
    <section className="replay" aria-label="Rejeu du run">
      <div className="replay-row">
        <button
          type="button"
          className="btn small"
          onClick={() => (atEnd ? (onCursor(0), setPlaying(true)) : setPlaying(!playing))}
          aria-label={atEnd ? "Rejouer depuis le début" : playing ? "Pause" : "Lecture"}
        >
          {atEnd ? "↻ Rejouer" : playing ? "❚❚ Pause" : "▶ Lecture"}
        </button>

        <input
          className="replay-scrub"
          type="range"
          min={0}
          max={events.length}
          value={cursor}
          onChange={(e) => {
            setPlaying(false);
            onCursor(Number(e.target.value));
          }}
          aria-label="Position dans le run"
          aria-valuetext={`${Math.min(cursor, events.length)} sur ${events.length} événements`}
        />

        <span className="replay-time">
          {elapsedLabel(events, cursor)} · {Math.min(cursor, events.length)}/{events.length}
        </span>

        <div className="speeds" role="group" aria-label="Vitesse de lecture">
          {SPEEDS.map((s) => (
            <button
              key={s}
              type="button"
              className={`speed ${s === speed ? "on" : ""}`}
              aria-pressed={s === speed}
              onClick={() => setSpeed(s)}
            >
              ×{s}
            </button>
          ))}
        </div>

        <button type="button" className="btn small ghost" onClick={onExit}>
          Quitter le rejeu
        </button>
      </div>

      {/* What the rest of the screen is currently showing. Without this the
          reconstructed state is correct but nobody can tell what it is of. */}
      <div className="replay-at">
        <span className="replay-at-phase">{phaseLabel(phase)}</span>
        {at && (
          <>
            <span className="replay-at-sep" aria-hidden="true">·</span>
            <span>{at.type}</span>
            {at.role && <span className="replay-at-role">{roleLabel(at.role)}</span>}
            <span className="replay-at-clock">
              {new Date(at.at).toLocaleTimeString("fr-FR")}
            </span>
          </>
        )}
        <span className="replay-keys">
          <kbd>espace</kbd> <kbd>←</kbd> <kbd>→</kbd> <kbd>⇧←→</kbd> ×10 · <kbd>Esc</kbd>
        </span>
      </div>
    </section>
  );
}
