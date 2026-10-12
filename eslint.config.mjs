// Correctness-focused lint for the temporary frontend (inline <script> blocks in app/static/*.html and any app/static/*.js).
// Not a style or formatting check. Run through lint.bat. Third-party code, runtime data and scratch copies are never linted.
import js from "@eslint/js";
import globals from "globals";
import html from "eslint-plugin-html";

export default [
  {
    ignores: [
      "node_modules/**", "runtime/**", "secrets/**", "backups/**", "demo/**", "research/**", ".scratch/**", "prompts/**", ".venv-*/**",
      "**/__pycache__/**", "**/*.min.js",
    ],
  },
  {
    // eslint-plugin-html lints each <script> block of an HTML file; blocks of one file share one global scope for no-undef.
    files: ["app/static/**/*.html", "app/static/**/*.js"],
    plugins: { html },
    languageOptions: { ecmaVersion: 2022, sourceType: "script", globals: { ...globals.browser } },
    linterOptions: { reportUnusedDisableDirectives: "error" },
    rules: {
      ...js.configs.recommended.rules,   // no-undef, no-unused-vars, no-dupe-keys, no-redeclare, no-unreachable, no-empty, ...
    },
  },
];
