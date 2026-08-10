import { useEffect, useMemo, useRef, useState } from "react";

export interface Command {
  id: string;
  label: string;
  hint?: string;
  group: string;
  run: () => void;
}

/**
 * Everything reachable from the keyboard, in one list.
 *
 * Deliberately not a router: the commands are supplied by whoever opens it, so
 * this file knows nothing about runs or themes and cannot drift out of step
 * with them.
 *
 * Every typed word must appear somewhere, in any order — "auth jwt" and
 * "jwt auth" both find "Ajouter l'authentification JWT". Order-independence is
 * the point: recalling a couple of words from a task is easy, recalling the
 * order they appear in is not.
 */
function matches(needle: string, haystack: string): boolean {
  const target = haystack.toLowerCase();
  return needle
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((word) => target.includes(word));
}

export function CommandPalette({
  open,
  commands,
  onClose,
}: {
  open: boolean;
  commands: Command[];
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setQuery("");
      setCursor(0);
      // Focus after paint, or the browser moves it back to whatever had it.
      requestAnimationFrame(() => input.current?.focus());
    }
  }, [open]);

  const shown = useMemo(
    () => commands.filter((c) => matches(query, `${c.group} ${c.label} ${c.hint ?? ""}`)),
    [commands, query],
  );

  useEffect(() => setCursor(0), [query]);

  if (!open) return null;

  const choose = (command: Command | undefined) => {
    if (!command) return;
    onClose();
    command.run();
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") return onClose();
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setCursor((c) => Math.min(c + 1, shown.length - 1));
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setCursor((c) => Math.max(c - 1, 0));
    }
    if (event.key === "Enter") {
      event.preventDefault();
      choose(shown[cursor]);
    }
  };

  let lastGroup = "";

  return (
    <div className="palette-backdrop" onClick={onClose} role="presentation">
      <div
        className="palette"
        role="dialog"
        aria-modal="true"
        aria-label="Palette de commandes"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={onKeyDown}
      >
        <input
          ref={input}
          className="palette-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Chercher une commande ou un run…"
          aria-label="Chercher une commande"
          role="combobox"
          aria-expanded="true"
          aria-controls="palette-list"
          aria-activedescendant={shown[cursor] ? `cmd-${shown[cursor].id}` : undefined}
        />
        <ul className="palette-list" id="palette-list" role="listbox">
          {shown.map((command, i) => {
            const header = command.group !== lastGroup ? command.group : null;
            lastGroup = command.group;
            return (
              <li key={command.id}>
                {header && <div className="palette-group">{header}</div>}
                <button
                  type="button"
                  id={`cmd-${command.id}`}
                  role="option"
                  aria-selected={i === cursor}
                  className={`palette-item ${i === cursor ? "on" : ""}`}
                  onMouseEnter={() => setCursor(i)}
                  onClick={() => choose(command)}
                >
                  <span className="palette-label">{command.label}</span>
                  {command.hint && <span className="palette-hint">{command.hint}</span>}
                </button>
              </li>
            );
          })}
          {shown.length === 0 && <li className="palette-empty">Aucune commande ne correspond.</li>}
        </ul>
        <div className="palette-foot">
          <kbd>↑</kbd><kbd>↓</kbd> naviguer · <kbd>↵</kbd> exécuter · <kbd>Esc</kbd> fermer
        </div>
      </div>
    </div>
  );
}
