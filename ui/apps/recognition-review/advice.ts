// What the page may say about the engine: only from the server's own numbers (gap G2), never
// from a fixed assumption about the score. Pure.

export const ENGINES = ["oemer", "audiveris"] as const;

export function engineLabel(engine: string): string {
  return engine === "audiveris" ? "Audiveris" : engine;
}

/** The engine to offer next: Audiveris for anything but Audiveris. */
export function otherEngine(engine: string): "oemer" | "audiveris" {
  return engine === "audiveris" ? "oemer" : "audiveris";
}

export interface StaffCounts {
  /** `metadata.staff_systems_estimate`: staves per system, counted on the busiest page image. */
  estimate: number | undefined;
  /** `metadata.staves_detected`: the parts the engine produced. */
  detected: number | undefined;
  engine: string;
}

/** Advice when the page looks like it has more staves than the engine produced parts. */
export function staffAdvice({ estimate, detected, engine }: StaffCounts): string | undefined {
  if (estimate === undefined || detected === undefined || estimate <= detected) return undefined;
  const found = `Detected ${detected} ${detected === 1 ? "part" : "parts"}, but the page looks like it has ${estimate} staves per system.`;
  return engine === "audiveris"
    ? `${found} Audiveris was already used: check the voices against the photo.`
    : `${found} Try the Audiveris engine, which keeps SATB voices apart.`;
}
