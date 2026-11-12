// Page boundaries, enforced. The TV and the phone share only src/wire.
import tseslint from "typescript-eslint";

export default tseslint.config(
  ...tseslint.configs.strictTypeChecked,
  { languageOptions: { parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname } } },
  {
    files: ["src/tv/**"],
    rules: { "no-restricted-imports": ["error", { patterns: ["../phone/*", "../import/*"] }] },
  },
  {
    files: ["src/phone/**"],
    rules: { "no-restricted-imports": ["error", { patterns: ["../tv/*", "../import/*"] }] },
  },
  {
    // Only audio.ts may touch the stretch library (its two traps are handled there once).
    files: ["src/**"],
    ignores: ["src/tv/audio.ts"],
    rules: { "no-restricted-imports": ["error", { paths: ["signalsmith-stretch"] }] },
  },
  {
    // Only the shared socket opens WebSockets.
    files: ["src/**"],
    ignores: ["src/wire/socket.ts"],
    rules: { "no-restricted-globals": ["error", "WebSocket"] },
  },
  {
    // The switch over a generated union must be exhaustive.
    files: ["src/**"],
    rules: { "@typescript-eslint/switch-exhaustiveness-check": "error" },
  },
);
