// pitch-mcp's session view (engine.describe_session) for the four-bar Alto. Own module: scenarios.ts
// and pitch-backend.ts both need it, and tool-backends.ts imports scenarios.ts (no import cycle).
export const SESSION_ID = "mock-session";

export const SESSION_VIEW = { session_id: SESSION_ID, part_id: "P2", part_name: "Alto", measure_count: 4, duration_seconds: 16, tempo_bpm: 60 };
