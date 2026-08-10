import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

/**
 * Two environments in one run: the pure modules need no DOM and are far faster
 * without one, while the component tests cannot work without it. Splitting by
 * filename keeps both honest — a `.dom.test.tsx` says what it needs.
 */
export default defineConfig({
  plugins: [react()],
  test: {
    environmentMatchGlobs: [["**/*.dom.test.tsx", "jsdom"]],
    setupFiles: ["./src/test-setup.ts"],
    globals: true,
  },
});
