// verovio ships no type declarations; this covers the part ScoreView uses.

declare module "verovio/wasm" {
  export interface VerovioModule {
    cwrap: (...args: unknown[]) => unknown;
  }
  export default function createVerovioModule(options?: Record<string, unknown>): Promise<VerovioModule>;
}

declare module "verovio/esm" {
  import type { VerovioModule } from "verovio/wasm";

  export interface TimemapEntry {
    tstamp: number;
    qstamp: number;
    on?: string[];
    off?: string[];
    tempo?: number;
  }

  export class VerovioToolkit {
    constructor(module: VerovioModule);
    setOptions(options: Record<string, unknown>): void;
    loadData(data: string): boolean;
    redoLayout(options?: Record<string, unknown>): void;
    getPageCount(): number;
    renderToSVG(page?: number, xmlDeclaration?: boolean): string;
    renderToTimemap(options?: Record<string, unknown>): TimemapEntry[];
    getLog(): string;
    getVersion(): string;
  }

  export function enableLogToBuffer(value: boolean, module: VerovioModule): void;
}
