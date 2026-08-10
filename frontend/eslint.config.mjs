import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),

  // tailwind.config.js and postcss.config.js are CommonJS by design -- Tailwind
  // and PostCSS load them with require(), so `require()` inside them is correct
  // rather than a lapse. The TypeScript preset flags it anyway, which made
  // `npm run lint` fail on two lines that cannot be written another way.
  {
    files: ["*.config.js", "*.config.cjs"],
    rules: {
      "@typescript-eslint/no-require-imports": "off",
      "import/no-anonymous-default-export": "off",
    },
  },
]);

export default eslintConfig;
