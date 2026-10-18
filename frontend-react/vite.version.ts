import { readFileSync } from "node:fs";

const packageJson = JSON.parse(
  readFileSync(new URL("./package.json", import.meta.url), "utf8"),
) as { version?: string };

if (!packageJson.version) {
  throw new Error("frontend-react/package.json is missing a version");
}

export const APP_VERSION = packageJson.version;
