import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
const frontend = fileURLToPath(new URL("../", import.meta.url));
const root = fileURLToPath(new URL("../../", import.meta.url));
const compose = [
  "compose",
  "-p",
  "urbexfinder-e2e",
  "--profile",
  "e2e",
  "-f",
  "docker-compose.test.yml",
];
function run(command, args, cwd = root, env = process.env) {
  const result = spawnSync(command, args, { cwd, env, stdio: "inherit" });
  if (result.error || result.status !== 0)
    throw new Error(
      `${command} failed (${result.status}): ${result.error || ""}`,
    );
}
try {
  run("docker", [
    ...compose,
    "up",
    ...(process.env.URBEX_E2E_NO_BUILD === "1" ? ["--no-build"] : ["--build"]),
    "--wait",
    "--wait-timeout",
    "120",
  ]);
  const env = {
    ...process.env,
    API_INTERNAL_URL: "http://127.0.0.1:58001",
    NEXT_PUBLIC_MAP_STYLE_URL: "/e2e-map-style.json",
  };
  run("npm", ["run", "build"], frontend, env);
  run("npx", ["playwright", "test"], frontend, env);
} catch (error) {
  console.error(error.message);
  spawnSync("docker", [...compose, "logs", "--tail", "60"], {
    cwd: root,
    stdio: "inherit",
  });
  process.exitCode = 1;
} finally {
  run("docker", [...compose, "down", "--volumes"]);
}
