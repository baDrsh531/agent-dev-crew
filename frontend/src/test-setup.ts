import "@testing-library/jest-dom/vitest";

/**
 * Shared by both environments, so everything DOM-specific has to be guarded:
 * the pure-module tests run without a DOM on purpose — it is far faster — and
 * an unguarded `Element` here took all four of those suites down with a
 * ReferenceError that had nothing to do with them.
 */
if (typeof window !== "undefined") {
  /**
   * The charts measure their container before drawing, and jsdom reports every
   * element as zero-sized. Without a ResizeObserver that answers with a real
   * width, every chart renders nothing and every assertion about one passes
   * for the wrong reason.
   */
  class StubResizeObserver {
    constructor(private readonly callback: ResizeObserverCallback) {}
    observe(): void {
      this.callback(
        [{ contentRect: { width: 800, height: 240 } } as ResizeObserverEntry],
        this as unknown as ResizeObserver,
      );
    }
    unobserve(): void {}
    disconnect(): void {}
  }

  globalThis.ResizeObserver ??= StubResizeObserver as unknown as typeof ResizeObserver;

  // jsdom has no layout, so this is a no-op that would otherwise throw.
  Element.prototype.scrollIntoView ??= () => {};
}
