import { useEffect, useState } from "react";
import { api } from "../api";
import type { EndpointHealth } from "../types";

/**
 * A local model's name is the path to its weights — `E:\models\gguf\Qwen_
 * Qwen3.6-35B-A3B-Q4_K_M.gguf`. Shown whole it swamps every row it appears in
 * and the part that distinguishes two models is the part that gets clipped.
 * The full name stays in the title attribute.
 */
export function shortModel(model: string): string {
  const leaf = model.split(/[\\/]/).pop() ?? model;
  return leaf.replace(/\.gguf$/i, "");
}

/**
 * Which servers answer, and which roles go somewhere other than the default.
 *
 * Two different rules share this panel, so it says which is which: pooled
 * servers are interchangeable and *must* agree on the model, while a routed
 * role is pointed at a different model on purpose. Reporting the second as a
 * disagreement would turn a deliberate choice into a warning.
 */
export function ModelServers() {
  const [health, setHealth] = useState<EndpointHealth | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .endpointHealth()
      .then((h) => live && setHealth(h))
      .catch((e) => live && setError(String(e)));
    return () => {
      live = false;
    };
  }, []);

  if (error) return <p className="empty">Could not reach the model servers: {error}</p>;
  if (!health) return <p className="empty">Checking the model servers…</p>;

  const routes = Object.entries(health.role_routes ?? {});
  if (!health.pooled && routes.length === 0) {
    return <p className="empty">One model server, every role.</p>;
  }

  return (
    <div className="servers">
      {health.pooled && (
        <>
          <ul className="server-list">
            {health.endpoints.map((endpoint) => (
              <li key={endpoint.url} className={endpoint.healthy ? "" : "down"}>
                <span
                  className={`status-dot ${endpoint.healthy ? "tone-ok" : "tone-bad"}`}
                  aria-hidden="true"
                />
                <code>{endpoint.url}</code>
                <span className="server-meta">
                  {endpoint.healthy
                    ? `${endpoint.leases} run${endpoint.leases === 1 ? "" : "s"}`
                    : `back in ${Math.ceil(endpoint.cooldown_remaining)}s`}
                </span>
              </li>
            ))}
          </ul>
          {!health.agree && (
            <p className="warn">
              These servers do not run the same model, so a single run's turns would
              land on different models. Every comparison across them is meaningless
              until they match.
            </p>
          )}
        </>
      )}

      {routes.length > 0 && (
        <>
          <h3>Sent elsewhere on purpose</h3>
          <ul className="server-list">
            {routes.map(([role, route]) => (
              <li key={role}>
                <span className="role-name">{role}</span>
                <code title={route.model}>{shortModel(route.model)}</code>
                <span className="server-meta">{route.url}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
