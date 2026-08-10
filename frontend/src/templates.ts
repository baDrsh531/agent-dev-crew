import { useCallback, useState } from "react";

/**
 * Saved task formulations.
 *
 * Replaces three hardcoded examples: the same phrasings get retyped run after
 * run while testing, and a wording that worked once is worth keeping. Stored
 * in the browser rather than the database on purpose — these are one person's
 * shorthand, not part of the run history, and putting them in SQLite would
 * mean a migration and an API for something a single user owns.
 */

const KEY = "adc-templates";

export interface Template {
  id: string;
  label: string;
  request: string;
  /** Built in, so it can be restored rather than permanently deleted. */
  builtin?: boolean;
}

export const BUILTIN: Template[] = [
  {
    id: "builtin-jwt",
    label: "Authentification JWT",
    request:
      "Ajouter l'authentification JWT : garder les routes de lecture publiques, exiger un token valide pour les écritures, et exiger un rôle admin pour /admin/*.",
    builtin: true,
  },
  {
    id: "builtin-pagination",
    label: "Pagination",
    request:
      "Ajouter la pagination limit/offset à GET /notes, plafonner limit à 100, préserver le filtre par tag.",
    builtin: true,
  },
  {
    id: "builtin-search",
    label: "Recherche plein texte",
    request:
      "Ajouter un endpoint de recherche GET /notes/search?q= qui cherche dans le titre et le corps.",
    builtin: true,
  },
];

function read(): Template[] {
  try {
    const raw = localStorage.getItem(KEY);
    const saved: Template[] = raw ? JSON.parse(raw) : [];
    return Array.isArray(saved) ? saved : [];
  } catch {
    // A corrupted entry must not take the whole app down with it.
    return [];
  }
}

export function useTemplates() {
  const [saved, setSaved] = useState<Template[]>(read);

  const persist = useCallback((next: Template[]) => {
    localStorage.setItem(KEY, JSON.stringify(next));
    setSaved(next);
  }, []);

  const save = useCallback(
    (label: string, request: string) => {
      const trimmed = label.trim() || request.trim().slice(0, 40);
      // Re-saving under an existing name replaces it, rather than leaving two
      // entries with the same label and no way to tell them apart.
      const without = read().filter((t) => t.label !== trimmed);
      persist([...without, { id: `t-${Date.now()}`, label: trimmed, request }]);
    },
    [persist],
  );

  const remove = useCallback(
    (id: string) => persist(read().filter((t) => t.id !== id)),
    [persist],
  );

  return { templates: [...BUILTIN, ...saved], saved, save, remove };
}
