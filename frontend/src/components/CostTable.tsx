import { roleLabel } from "../labels";
import type { Role, RunEvent } from "../types";

/**
 * What each agent actually consumed.
 *
 * Built from `agent.finished` events rather than from a running total, so the
 * rows always add up to the same figure the KPI shows — there is only one
 * source. A repair loop runs the developer twice; the rows are summed per
 * role, and the call count says how many turns that was.
 */
interface Row {
  role: Role;
  calls: number;
  tokens: number;
  cost: number;
  toolCalls: number;
}

function rowsOf(events: RunEvent[]): Row[] {
  const byRole = new Map<Role, Row>();
  for (const event of events) {
    if (event.type !== "agent.finished" || !event.role) continue;
    const row = byRole.get(event.role) ?? {
      role: event.role, calls: 0, tokens: 0, cost: 0, toolCalls: 0,
    };
    row.calls += 1;
    row.tokens += event.payload.usage?.total_tokens ?? 0;
    row.cost += event.payload.usage?.cost_usd ?? 0;
    row.toolCalls += event.payload.tool_calls ?? 0;
    byRole.set(event.role, row);
  }
  return [...byRole.values()];
}

export function CostTable({
  events,
  selfHosted,
}: {
  events: RunEvent[];
  selfHosted: boolean;
}) {
  const rows = rowsOf(events);
  if (rows.length === 0) {
    return <p className="empty">Aucun agent n'a encore terminé son tour.</p>;
  }

  const total = rows.reduce(
    (acc, r) => ({
      tokens: acc.tokens + r.tokens,
      cost: acc.cost + r.cost,
      toolCalls: acc.toolCalls + r.toolCalls,
    }),
    { tokens: 0, cost: 0, toolCalls: 0 },
  );

  return (
    <div className="card">
      <div className="table-scroll">
        <table className="cost-table">
          <thead>
            <tr>
              <th scope="col">Agent</th>
              <th scope="col" className="num">Tours</th>
              <th scope="col" className="num">Outils</th>
              <th scope="col" className="num">Tokens</th>
              <th scope="col" className="num">Coût</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.role}>
                <td>{roleLabel(row.role)}</td>
                <td className="num">{row.calls}</td>
                <td className="num">{row.toolCalls}</td>
                <td className="num">{row.tokens.toLocaleString("fr-FR")}</td>
                <td className="num">${row.cost.toFixed(4)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td>Total</td>
              <td className="num">{rows.reduce((n, r) => n + r.calls, 0)}</td>
              <td className="num">{total.toolCalls}</td>
              <td className="num">{total.tokens.toLocaleString("fr-FR")}</td>
              <td className="num">${total.cost.toFixed(4)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
      {selfHosted && (
        <p className="empty" style={{ marginTop: 12 }}>
          Coût rapporté à 0 $ : le modèle est auto-hébergé, le coût marginal
          d'un token y est nul. L'estimer aux tarifs d'une API hébergée
          mettrait un chiffre inventé dans ce tableau.
        </p>
      )}
    </div>
  );
}
