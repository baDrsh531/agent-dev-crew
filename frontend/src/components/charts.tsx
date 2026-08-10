import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Point } from "../stats";

/**
 * Charts drawn as SVG, sized to the element they are in.
 *
 * Measured rather than given a fixed `viewBox`, because a scaled viewBox scales
 * its text too: the same chart is unreadably small on a phone and cartoonish on
 * a wide monitor. Rendering at the real pixel width keeps every label at the
 * size it was chosen to be, at any width.
 *
 * Colour comes from CSS variables, so both themes are handled by the theme and
 * not by a second set of chart code.
 */
function useWidth(): [React.RefObject<HTMLDivElement>, number] {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      setWidth(entry.contentRect.width);
    });
    observer.observe(element);
    setWidth(element.getBoundingClientRect().width);
    return () => observer.disconnect();
  }, []);

  return [ref, width];
}

interface Tip {
  x: number;
  y: number;
  body: ReactNode;
}

function Tooltip({ tip }: { tip: Tip | null }) {
  if (!tip) return null;
  return (
    <div className="viz-tip" style={{ left: tip.x, top: tip.y }} role="status">
      {tip.body}
    </div>
  );
}

/** Ticks that land on round numbers rather than on the data's exact maximum. */
function niceTicks(max: number, count = 4): { ticks: number[]; top: number } {
  if (max <= 0) return { ticks: [0], top: 1 };
  const rough = max / count;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= rough) ?? magnitude * 10;
  const top = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let v = 0; v <= top + 1e-9; v += step) ticks.push(v);
  return { ticks, top };
}

const PAD = { left: 52, right: 14, top: 14, bottom: 40 };
const HEIGHT = 240;

/**
 * Trim a label to the room it actually has.
 *
 * A fixed 13-character cut turned every axis into "benchmark:jwt…",
 * "benchmark:pag…" — identical prefixes, and the part that told them apart was
 * exactly the part removed. Widening with the slot keeps the distinguishing
 * tail visible whenever there is space for it.
 */
const CHAR_PX = 6.2;

function clip(label: string, slot: number): string {
  const max = Math.max(6, Math.floor((slot - 6) / CHAR_PX));
  return label.length > max ? `${label.slice(0, max - 1)}…` : label;
}

export function BarChart({
  data,
  format,
  reference,
  onSelect,
  emptyLabel = "Rien à afficher pour l'instant.",
}: {
  data: Point[];
  format: (value: number) => string;
  /** A ceiling drawn as a dashed line — headroom is the point, not the bar. */
  reference?: { value: number; label: string };
  onSelect?: (point: Point) => void;
  emptyLabel?: string;
}) {
  const [ref, width] = useWidth();
  const [tip, setTip] = useState<Tip | null>(null);

  if (data.length === 0) return <p className="empty">{emptyLabel}</p>;

  const dataMax = Math.max(...data.map((d) => d.value), reference?.value ?? 0);
  const { ticks, top } = niceTicks(dataMax);
  const plotW = Math.max(0, width - PAD.left - PAD.right);
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const slot = data.length ? plotW / data.length : 0;
  const barW = Math.max(6, Math.min(48, slot - 16));
  const y = (v: number) => PAD.top + plotH - (top ? (v / top) * plotH : 0);
  // Past a handful of bars every label collides; show every other one instead
  // of rotating them into an unreadable fan.
  const labelEvery = slot < 64 ? 2 : 1;

  return (
    <div className="viz" ref={ref}>
      {width > 0 && (
        <svg width={width} height={HEIGHT} role="img" aria-label="Histogramme">
          {ticks.map((tick) => (
            <g key={tick}>
              <line
                x1={PAD.left} y1={y(tick)} x2={width - PAD.right} y2={y(tick)}
                stroke="var(--grid-line)" strokeWidth={1}
              />
              <text
                x={PAD.left - 8} y={y(tick) + 4} textAnchor="end"
                fontSize={10.5} fill="var(--text-tertiary)"
              >
                {format(tick)}
              </text>
            </g>
          ))}

          {reference && reference.value <= top && (
            <>
              <line
                x1={PAD.left} y1={y(reference.value)} x2={width - PAD.right} y2={y(reference.value)}
                stroke="var(--amber)" strokeWidth={1.5} strokeDasharray="5 4"
              />
              <text
                x={width - PAD.right} y={y(reference.value) - 6} textAnchor="end"
                fontSize={10.5} fill="var(--amber)" fontWeight={600}
              >
                {reference.label}
              </text>
            </>
          )}

          {data.map((point, i) => {
            const cx = PAD.left + (i + 0.5) * slot;
            const height = Math.max(1, PAD.top + plotH - y(point.value));
            return (
              <g key={point.id ?? i}>
                <rect
                  className={`bar ${point.tone ?? ""} ${onSelect ? "selectable" : ""}`}
                  x={cx - barW / 2}
                  y={y(point.value)}
                  width={barW}
                  height={height}
                  rx={4}
                  onMouseMove={(e) =>
                    setTip({
                      x: e.clientX + 14,
                      y: e.clientY - 8,
                      body: (
                        <>
                          <b>{point.label}</b>
                          {format(point.value)}
                        </>
                      ),
                    })
                  }
                  onMouseLeave={() => setTip(null)}
                  onClick={() => onSelect?.(point)}
                />
                {i % labelEvery === 0 && (
                  <text
                    x={cx} y={HEIGHT - PAD.bottom + 18} textAnchor="middle"
                    fontSize={11} fill="var(--text-secondary)"
                  >
                    {clip(point.label, slot)}
                  </text>
                )}
              </g>
            );
          })}

          <line
            x1={PAD.left} y1={PAD.top + plotH} x2={width - PAD.right} y2={PAD.top + plotH}
            stroke="var(--border-strong)" strokeWidth={1}
          />
        </svg>
      )}
      <Tooltip tip={tip} />
    </div>
  );
}

export function LineChart({
  data,
  format,
  onSelect,
  emptyLabel = "Rien à afficher pour l'instant.",
}: {
  data: Point[];
  format: (value: number) => string;
  onSelect?: (point: Point) => void;
  emptyLabel?: string;
}) {
  const [ref, width] = useWidth();
  const [tip, setTip] = useState<Tip | null>(null);

  if (data.length === 0) return <p className="empty">{emptyLabel}</p>;

  const { ticks, top } = niceTicks(Math.max(...data.map((d) => d.value)));
  const plotW = Math.max(0, width - PAD.left - PAD.right);
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  // A single point has no line to draw; centre it rather than divide by zero.
  const x = (i: number) =>
    data.length === 1 ? PAD.left + plotW / 2 : PAD.left + (i / (data.length - 1)) * plotW;
  const y = (v: number) => PAD.top + plotH - (top ? (v / top) * plotH : 0);
  const path = data.map((d, i) => `${i ? "L" : "M"}${x(i)},${y(d.value)}`).join(" ");
  const area = `${path} L${x(data.length - 1)},${PAD.top + plotH} L${x(0)},${PAD.top + plotH} Z`;
  const labelEvery = plotW / data.length < 64 ? 2 : 1;

  return (
    <div className="viz" ref={ref}>
      {width > 0 && (
        <svg width={width} height={HEIGHT} role="img" aria-label="Courbe">
          <defs>
            <linearGradient id="areaFade" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--series-2)" stopOpacity="0.22" />
              <stop offset="100%" stopColor="var(--series-2)" stopOpacity="0" />
            </linearGradient>
          </defs>

          {ticks.map((tick) => (
            <g key={tick}>
              <line
                x1={PAD.left} y1={y(tick)} x2={width - PAD.right} y2={y(tick)}
                stroke="var(--grid-line)" strokeWidth={1}
              />
              <text
                x={PAD.left - 8} y={y(tick) + 4} textAnchor="end"
                fontSize={10.5} fill="var(--text-tertiary)"
              >
                {format(tick)}
              </text>
            </g>
          ))}

          {data.length > 1 && <path d={area} fill="url(#areaFade)" />}
          <path
            d={path} fill="none" stroke="var(--series-2)" strokeWidth={2}
            strokeLinejoin="round" strokeLinecap="round"
          />

          {data.map((point, i) => (
            <g key={point.id ?? i}>
              <circle
                className={onSelect ? "line-pt selectable" : "line-pt"}
                cx={x(i)} cy={y(point.value)} r={4.5}
                fill="var(--series-2)" stroke="var(--bg-elevated)" strokeWidth={2}
                onMouseMove={(e) =>
                  setTip({
                    x: e.clientX + 14,
                    y: e.clientY - 8,
                    body: (
                      <>
                        <b>{point.label}</b>
                        {format(point.value)}
                      </>
                    ),
                  })
                }
                onMouseLeave={() => setTip(null)}
                onClick={() => onSelect?.(point)}
              />
              {i % labelEvery === 0 && (
                <text
                  x={x(i)} y={HEIGHT - PAD.bottom + 18} textAnchor="middle"
                  fontSize={11} fill="var(--text-secondary)"
                >
                  {point.label.length > 14 ? `${point.label.slice(0, 13)}…` : point.label}
                </text>
              )}
            </g>
          ))}

          {/* The last value labelled directly, so the eye does not have to
              travel to an axis to read the figure that matters most. */}
          <text
            x={x(data.length - 1)} y={y(data.at(-1)!.value) - 12} textAnchor="end"
            fontSize={11.5} fontWeight={700} fill="var(--text)"
          >
            {format(data.at(-1)!.value)}
          </text>
        </svg>
      )}
      <Tooltip tip={tip} />
    </div>
  );
}

/** A labelled proportion bar. Used where a pie would be read less accurately. */
export function BreakdownBar({
  rows,
  total,
}: {
  rows: { label: string; count: number; tone: string }[];
  total: number;
}) {
  if (total === 0) return <p className="empty">Rien à répartir pour l'instant.</p>;
  return (
    <div className="breakdown">
      {rows.map((row) => {
        const pct = Math.round((row.count / total) * 100);
        return (
          <div className="breakdown-row" key={row.label}>
            <span className="breakdown-label">{row.label}</span>
            <div className="breakdown-track">
              <div className={`breakdown-fill tone-${row.tone}`} style={{ width: `${pct}%` }} />
            </div>
            <span className="breakdown-count">
              {row.count} · {pct}&nbsp;%
            </span>
          </div>
        );
      })}
    </div>
  );
}
