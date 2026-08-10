import type { Theme } from "../theme";
import type { AppConfig } from "../types";

export function TopBar({
  config,
  expert,
  onExpert,
  theme,
  onTheme,
}: {
  config: AppConfig | null;
  expert: boolean;
  onExpert: (next: boolean) => void;
  theme: Theme;
  onTheme: (next: Theme) => void;
}) {
  const fake = config?.provider === "fake";

  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-mark" aria-hidden="true">AC</div>
        <div className="brand-text">
          <h1>Agent Dev Crew</h1>
          <p>Cinq agents spécialisés, des relais typés, un orchestrateur déterministe.</p>
        </div>
      </div>

      <div className="topbar-right">
        {config && (
          <span className={`stat-pill ${fake ? "warn" : ""}`}>
            {!fake && <span className="live-dot" aria-hidden="true" />}
            fournisseur&nbsp;: <b>{config.provider}</b>
          </span>
        )}
        {expert && config && (
          <>
            <span className="stat-pill">
              boucles max&nbsp;: <b>{config.limits.max_qa_iterations}</b>
            </span>
            <span className="stat-pill">
              budget&nbsp;: <b>{config.limits.max_tokens_per_run.toLocaleString("fr-FR")}</b>
            </span>
          </>
        )}

        <button
          type="button"
          className="mode-toggle"
          aria-pressed={expert}
          onClick={() => onExpert(!expert)}
        >
          Mode expert
        </button>

        {/* A radio group rather than a single switch: with two buttons the
            current theme is legible without having to guess what the icon
            means, and each has its own accessible name. */}
        <div className="toggle-group" role="group" aria-label="Thème de l'interface">
          <button
            type="button"
            aria-pressed={theme === "dark"}
            aria-label="Thème sombre"
            title="Thème sombre"
            onClick={() => onTheme("dark")}
          >
            ☾
          </button>
          <button
            type="button"
            aria-pressed={theme === "light"}
            aria-label="Thème clair"
            title="Thème clair"
            onClick={() => onTheme("light")}
          >
            ☀
          </button>
        </div>
      </div>
    </header>
  );
}
