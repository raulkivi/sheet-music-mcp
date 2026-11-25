// Pure functions over the apps registry (apps.config.mjs): no fs, no process, unit-tested in
// test/apps-registry.test.ts. Paths are relative to ui/.

const NAME = /^[a-z][a-z0-9-]*$/;
const SERVER = /^[a-z][a-z0-9-]*$/;
const PKG = /^[a-z][a-z0-9_]*$/;

export const appNames = (apps) => Object.keys(apps);

/** Returns one message per problem; empty when the registry is usable. */
export function validateRegistry(apps) {
  const problems = [];
  for (const [name, app] of Object.entries(apps ?? {})) {
    if (!NAME.test(name)) problems.push(`app "${name}": name must match ${NAME}`);
    const targets = app?.targets;
    if (!Array.isArray(targets) || targets.length === 0) {
      problems.push(`app "${name}": needs at least one target`);
      continue;
    }
    const seen = new Set();
    for (const t of targets) {
      if (!SERVER.test(t?.server ?? "") || !PKG.test(t?.pkg ?? "")) {
        problems.push(`app "${name}": target ${JSON.stringify(t)} needs server (${SERVER}) and pkg (${PKG})`);
        continue;
      }
      const key = `${t.server}/${t.pkg}`;
      if (seen.has(key)) problems.push(`app "${name}": target ${key} listed twice`);
      seen.add(key);
    }
  }
  return problems;
}

/** Returns the name if registered; otherwise throws, listing the registered names. */
export function requireApp(apps, name) {
  if (typeof name === "string" && Object.hasOwn(apps, name)) return name;
  throw new Error(`Unknown app "${name}"; registered: ${appNames(apps).join(", ")}`);
}

export const distFile = (name) => `dist/${name}.html`;

export const assetDir = ({ server, pkg }) => `../${server}/src/${pkg}/ui/assets`;

/** Every (built page -> server asset) copy, in registry order. */
export function copyPlan(apps) {
  return Object.entries(apps).flatMap(([name, app]) =>
    app.targets.map((target) => ({ from: distFile(name), to: `${assetDir(target)}/${name}.html` })),
  );
}

/** The apps to build: those named, or all of them when none is. */
export const selectApps = (apps, requested) =>
  requested.length === 0 ? appNames(apps) : requested.map((name) => requireApp(apps, name));

/** Servers that serve at least one page; the release workflow builds the UI only for these. */
export const serversWithPages = (apps) => [
  ...new Set(Object.values(apps).flatMap((app) => app.targets.map((t) => t.server))),
];
