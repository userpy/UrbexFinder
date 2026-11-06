import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
const layers = ["shared", "entities", "features", "widgets", "views"];
export default defineConfig([
  ...nextVitals,
  ...nextTs,
  ...layers.map((layer, index) => ({
    files: [`src/${layer}/**/*.{ts,tsx}`],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            ...layers
              .slice(index + 1)
              .map((upper) => ({
                group: [`@/${upper}`, `@/${upper}/**`],
                message: "FSD imports must point to a lower layer.",
              })),
            {
              group: [
                "@/entities/*/**",
                "@/features/*/**",
                "@/widgets/*/**",
                "@/views/*/**",
              ],
              message: "Use the public API of a slice.",
            },
          ],
        },
      ],
    },
  })),
  globalIgnores([
    ".next/**",
    "public/vendor/maplibre/**", // Generated, unmodified dependency assets.
    "next-env.d.ts",
    "playwright-report/**",
    "test-results/**",
  ]),
]);
