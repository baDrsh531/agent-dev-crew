import { useState } from "react";
import { autonomyHint, autonomyLabel } from "../labels";
import type { Template } from "../templates";
import type { ApprovalModeOption } from "../types";

/**
 * The autonomy setting is per run, not global: the same person wants a tight
 * leash on an unfamiliar project and a loose one on a scratch branch. The
 * labels come from the backend so the UI cannot describe a policy the engine
 * does not actually enforce.
 *
 * The three fixed examples became a library, because the same phrasings get
 * retyped run after run and a wording that worked once is worth keeping.
 */
export function NewTask({
  request,
  onRequest,
  modes,
  autonomy,
  onAutonomy,
  onStart,
  busy,
  templates,
  savedIds,
  onSaveTemplate,
  onRemoveTemplate,
}: {
  request: string;
  onRequest: (next: string) => void;
  modes: ApprovalModeOption[];
  autonomy: string;
  onAutonomy: (next: string) => void;
  onStart: () => void;
  busy: boolean;
  templates: Template[];
  savedIds: Set<string>;
  onSaveTemplate: (label: string, request: string) => void;
  onRemoveTemplate: (id: string) => void;
}) {
  const [naming, setNaming] = useState(false);
  const [label, setLabel] = useState("");

  const confirmSave = () => {
    onSaveTemplate(label, request);
    setLabel("");
    setNaming(false);
  };

  return (
    <section className="card">
      <h2 className="card-title">Nouvelle tâche</h2>

      <label className="sr-only" htmlFor="task-input">
        Décrivez ce que l'équipe doit construire
      </label>
      <textarea
        id="task-input"
        className="task-input"
        value={request}
        onChange={(e) => onRequest(e.target.value)}
        placeholder="Décrivez ce que l'équipe doit construire…"
      />

      <div className="tpl-row">
        {templates.map((template) => (
          <span key={template.id} className="tpl">
            <button
              type="button"
              className="tpl-use"
              onClick={() => onRequest(template.request)}
              title={template.request}
            >
              {template.label}
            </button>
            {savedIds.has(template.id) && (
              <button
                type="button"
                className="tpl-remove"
                onClick={() => onRemoveTemplate(template.id)}
                aria-label={`Supprimer le modèle ${template.label}`}
                title="Supprimer ce modèle"
              >
                ×
              </button>
            )}
          </span>
        ))}
      </div>

      {naming ? (
        <div className="tpl-save">
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Nom du modèle"
            aria-label="Nom du modèle"
            onKeyDown={(e) => e.key === "Enter" && confirmSave()}
          />
          <button type="button" className="btn small" onClick={confirmSave}>
            Enregistrer
          </button>
          <button type="button" className="btn small ghost" onClick={() => setNaming(false)}>
            Annuler
          </button>
        </div>
      ) : (
        <button
          type="button"
          className="link"
          disabled={request.trim().length < 8}
          onClick={() => setNaming(true)}
        >
          + Enregistrer comme modèle
        </button>
      )}

      <fieldset className="option-group">
        <legend className="sr-only">Niveau d'autonomie</legend>
        {modes.map((mode) => (
          <label key={mode.id} className="option">
            <input
              type="radio"
              name="autonomy"
              value={mode.id}
              checked={autonomy === mode.id}
              onChange={() => onAutonomy(mode.id)}
            />
            <span className="radio-dot" aria-hidden="true" />
            <span>
              <span className="option-title">{autonomyLabel(mode.id, mode.label)}</span>
              {autonomyHint(mode.id) && (
                <span className="option-desc">{autonomyHint(mode.id)}</span>
              )}
            </span>
          </label>
        ))}
      </fieldset>

      <button
        type="button"
        className="btn primary"
        onClick={onStart}
        disabled={busy || request.trim().length < 8}
      >
        {busy ? "Démarrage…" : "▶ Démarrer"}
      </button>
    </section>
  );
}
