// Only frontend settings cross into the Next.js process; bot secrets stay in .env.
import { readFileSync } from "node:fs";
import { parseEnv } from "node:util";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const env = { ...process.env };
try {
  const values = parseEnv(readFileSync(new URL("../../.env", import.meta.url), "utf8"));
  for (const key of ["NEXT_PUBLIC_MAP_STYLE_URL", "API_INTERNAL_URL"])
    if (env[key] === undefined && values[key] !== undefined) env[key] = values[key];
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}
const child = spawn(process.execPath, [require.resolve("next/dist/bin/next"), ...process.argv.slice(2)], { env, stdio: "inherit" });
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.kill(signal));
child.on("error", (error) => { console.error(error.message); process.exitCode = 1; });
child.on("exit", (code, signal) => { process.exitCode = code ?? (signal ? 1 : 0); });
