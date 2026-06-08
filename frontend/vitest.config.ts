import { defineConfig } from "vitest/config";

/**
 * Vitest config for the frontend unit tests.
 *
 * The SSE parser in lib/api.ts is pure (web ReadableStream + TextEncoder/Decoder,
 * no DOM), so a "node" environment is sufficient and fast. Test files live next to
 * the code they cover as `*.test.ts` under lib/.
 */
export default defineConfig({
  test: {
    environment: "node",
    include: ["lib/**/*.test.ts"],
  },
});
