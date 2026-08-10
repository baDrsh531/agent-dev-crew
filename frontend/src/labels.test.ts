import { describe, expect, it } from "vitest";
import { compactNumber, durationLabel, phaseLabel, statusLabel, statusTone } from "./labels";

describe("durationLabel", () => {
  it("shows seconds below a minute", () => {
    expect(durationLabel(45)).toBe("45 s");
  });

  it("never renders sixty seconds inside a minute", () => {
    // Flooring the minutes and rounding the remainder separately produced
    // "1 min 60". Durations are a subtraction of two timestamps, so a
    // fractional value like this is the normal case, not an edge one.
    expect(durationLabel(119.7)).toBe("2 min 00");
    expect(durationLabel(59.6)).toBe("1 min 00");
  });

  it("pads the seconds so the column stays aligned", () => {
    expect(durationLabel(305)).toBe("5 min 05");
  });

  it("refuses to invent a duration it does not have", () => {
    expect(durationLabel(Number.NaN)).toBe("—");
    expect(durationLabel(-3)).toBe("—");
  });
});

describe("compactNumber", () => {
  it("leaves small numbers alone", () => {
    expect(compactNumber(0)).toBe("0");
    expect(compactNumber(942)).toBe("942");
  });

  it("keeps one decimal while it still carries information", () => {
    expect(compactNumber(1500)).toBe("1.5k");
  });

  it("drops the decimal once the number is large enough not to need it", () => {
    expect(compactNumber(175_000)).toBe("175k");
  });

  it("steps up to millions instead of rounding to a four-digit k", () => {
    // 999,999 used to render as "1000k", which reads as a bigger unit anyway.
    expect(compactNumber(999_999)).toBe("1.0M");
    expect(compactNumber(2_360_000)).toBe("2.4M");
  });
});

describe("statusTone", () => {
  it("does not paint an escalation like a crash", () => {
    // An escalation is the orchestrator stopping where it was told to; red
    // would report a working safety mechanism as a defect.
    expect(statusTone("escalated")).toBe("warn");
    expect(statusTone("failed")).toBe("bad");
    expect(statusTone("succeeded")).toBe("ok");
  });

  it("marks a run waiting on a person as needing attention", () => {
    expect(statusTone("waiting_for_human")).toBe("waiting");
  });
});

describe("labels", () => {
  it("translates every status and phase the backend can emit", () => {
    for (const s of ["pending", "running", "waiting_for_human", "succeeded",
                     "escalated", "failed", "cancelled"] as const) {
      expect(statusLabel(s)).not.toBe(s);
    }
    for (const p of ["intake", "intake_approval", "analyze", "design", "plan_approval",
                     "implement", "review", "fix", "document", "done"] as const) {
      expect(phaseLabel(p)).not.toBe(p);
    }
  });

  it("falls back to the raw name rather than showing nothing", () => {
    expect(phaseLabel("une_phase_inconnue")).toBe("une_phase_inconnue");
  });
});
