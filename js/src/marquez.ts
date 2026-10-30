// Typed, bounded client for the parts of the Marquez REST API (v1) that lineage-explorer reads.

export const RUN_STATES = ["NEW", "RUNNING", "COMPLETED", "ABORTED", "FAILED"] as const;
export type RunState = (typeof RUN_STATES)[number];

export interface DatasetId {
  namespace: string;
  name: string;
}

export interface Namespace {
  name: string;
  ownerName: string | null;
  description: string | null;
}

export interface Field {
  name: string;
  type: string | null;
  description: string | null;
}

export interface Dataset {
  namespace: string;
  name: string;
  type: string;
  sourceName: string | null;
  fields: Field[];
  lastModifiedAt: string | null;
}

export interface Run {
  id: string;
  state: RunState;
  startedAt: string | null;
  endedAt: string | null;
  durationMs: number | null;
}

export interface Job {
  namespace: string;
  name: string;
  type: string;
  inputs: DatasetId[];
  outputs: DatasetId[];
  latestRun: Run | null;
}

export interface Edge {
  origin: string;
  destination: string;
}

export interface LineageNode {
  id: string;
  type: "DATASET" | "JOB";
  inEdges: Edge[];
  outEdges: Edge[];
}

export interface ClientOptions {
  baseUrl: string;
  timeoutMs?: number;
  maxBytes?: number;
  maxItems?: number;
  fetchImpl?: typeof fetch;
}

/** Raised when Marquez answers with an unexpected status or body. */
export class MarquezError extends Error {
  readonly status: number | null;

  // Error with the HTTP status when there is one.
  constructor(message: string, status: number | null = null) {
    super(message);
    this.name = "MarquezError";
    this.status = status;
  }
}

type Json = unknown;

// Narrow a value to a plain object or fail with its path.
function obj(v: Json, path: string): Record<string, Json> {
  if (typeof v !== "object" || v === null || Array.isArray(v)) {
    throw new MarquezError(`${path}: expected an object`);
  }
  return v as Record<string, Json>;
}

// Narrow a value to an array or fail with its path.
function arr(v: Json, path: string): Json[] {
  if (!Array.isArray(v)) throw new MarquezError(`${path}: expected an array`);
  return v;
}

// Required string field.
function str(o: Record<string, Json>, key: string, path: string): string {
  const v = o[key];
  if (typeof v !== "string") throw new MarquezError(`${path}.${key}: expected a string`);
  return v;
}

// Optional string field (missing or null gives null).
function optStr(o: Record<string, Json>, key: string, path: string): string | null {
  const v = o[key];
  if (v === undefined || v === null) return null;
  if (typeof v !== "string") throw new MarquezError(`${path}.${key}: expected a string or null`);
  return v;
}

// Optional finite number field.
function optNum(o: Record<string, Json>, key: string, path: string): number | null {
  const v = o[key];
  if (v === undefined || v === null) return null;
  if (typeof v !== "number" || !Number.isFinite(v)) {
    throw new MarquezError(`${path}.${key}: expected a number or null`);
  }
  return v;
}

// Dataset or job id object.
function parseId(v: Json, path: string): DatasetId {
  const o = obj(v, path);
  return { namespace: str(o, "namespace", path), name: str(o, "name", path) };
}

/** Parse one namespace entry. */
export function parseNamespace(v: Json, path = "namespace"): Namespace {
  const o = obj(v, path);
  return {
    name: str(o, "name", path),
    ownerName: optStr(o, "ownerName", path),
    description: optStr(o, "description", path),
  };
}

/** Parse one dataset entry, including its schema fields. */
export function parseDataset(v: Json, path = "dataset"): Dataset {
  const o = obj(v, path);
  const id = parseId(o["id"], `${path}.id`);
  const fields = o["fields"] === undefined || o["fields"] === null ? [] : arr(o["fields"], `${path}.fields`);
  return {
    namespace: id.namespace,
    name: id.name,
    type: str(o, "type", path),
    sourceName: optStr(o, "sourceName", path),
    fields: fields.map((f, i) => {
      const fo = obj(f, `${path}.fields[${i}]`);
      return {
        name: str(fo, "name", `${path}.fields[${i}]`),
        type: optStr(fo, "type", `${path}.fields[${i}]`),
        description: optStr(fo, "description", `${path}.fields[${i}]`),
      };
    }),
    lastModifiedAt: optStr(o, "lastModifiedAt", path),
  };
}

/** Parse one run entry and check its state. */
export function parseRun(v: Json, path = "run"): Run {
  const o = obj(v, path);
  const state = str(o, "state", path);
  if (!(RUN_STATES as readonly string[]).includes(state)) {
    throw new MarquezError(`${path}.state: unknown run state ${JSON.stringify(state)}`);
  }
  return {
    id: str(o, "id", path),
    state: state as RunState,
    startedAt: optStr(o, "startedAt", path),
    endedAt: optStr(o, "endedAt", path),
    durationMs: optNum(o, "durationMs", path),
  };
}

/** Parse one job entry with its inputs, outputs and latest run. */
export function parseJob(v: Json, path = "job"): Job {
  const o = obj(v, path);
  const id = parseId(o["id"], `${path}.id`);
  const ids = (key: string): DatasetId[] =>
    o[key] === undefined || o[key] === null ? [] : arr(o[key], `${path}.${key}`).map((d, i) => parseId(d, `${path}.${key}[${i}]`));
  const latest = o["latestRun"];
  return {
    namespace: id.namespace,
    name: id.name,
    type: str(o, "type", path),
    inputs: ids("inputs"),
    outputs: ids("outputs"),
    latestRun: latest === undefined || latest === null ? null : parseRun(latest, `${path}.latestRun`),
  };
}

/** Parse the graph returned by /api/v1/lineage. */
export function parseLineage(v: Json): LineageNode[] {
  const graph = arr(obj(v, "lineage")["graph"], "lineage.graph");
  return graph.map((n, i) => {
    const path = `lineage.graph[${i}]`;
    const o = obj(n, path);
    const type = str(o, "type", path);
    if (type !== "DATASET" && type !== "JOB") throw new MarquezError(`${path}.type: unknown node type ${JSON.stringify(type)}`);
    const edges = (key: string): Edge[] =>
      arr(o[key] ?? [], `${path}.${key}`).map((e, j) => {
        const eo = obj(e, `${path}.${key}[${j}]`);
        return { origin: str(eo, "origin", path), destination: str(eo, "destination", path) };
      });
    return { id: str(o, "id", path), type, inEdges: edges("inEdges"), outEdges: edges("outEdges") };
  });
}

export interface SearchHit {
  type: "DATASET" | "JOB";
  namespace: string;
  name: string;
  nodeId: string;
}

/** Parse one /search result. */
export function parseSearchHit(v: Json, path = "result"): SearchHit {
  const o = obj(v, path);
  const type = str(o, "type", path);
  if (type !== "DATASET" && type !== "JOB") throw new MarquezError(`${path}.type: unknown result type ${JSON.stringify(type)}`);
  return { type, namespace: str(o, "namespace", path), name: str(o, "name", path), nodeId: str(o, "nodeId", path) };
}

/** Node id Marquez uses for a dataset or a job in the lineage graph. */
export function nodeId(kind: "dataset" | "job", namespace: string, name: string): string {
  return `${kind}:${namespace}:${name}`;
}

const PAGE = 100;

/** Reads namespaces, datasets, jobs, runs and lineage from one Marquez server. */
export class MarquezClient {
  readonly baseUrl: URL;
  private readonly timeoutMs: number;
  private readonly maxBytes: number;
  private readonly maxItems: number;
  private readonly fetchImpl: typeof fetch;

  // Validate the base URL and the limits.
  constructor(opts: ClientOptions) {
    let url: URL;
    try {
      url = new URL(opts.baseUrl);
    } catch {
      throw new MarquezError(`not a URL: ${JSON.stringify(opts.baseUrl)}`);
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      throw new MarquezError(`only http and https URLs are allowed, got ${url.protocol}`);
    }
    if (url.search || url.hash) throw new MarquezError("the base URL must not have a query or fragment");
    if (!url.pathname.endsWith("/")) url.pathname += "/";
    this.baseUrl = url;
    this.timeoutMs = opts.timeoutMs ?? 10_000;
    this.maxBytes = opts.maxBytes ?? 16 * 1024 * 1024;
    this.maxItems = opts.maxItems ?? 10_000;
    this.fetchImpl = opts.fetchImpl ?? fetch;
  }

  // GET a path under /api/v1 and return the parsed JSON body, size- and time-bounded.
  private async get(segments: string[], query: Record<string, string> = {}): Promise<Json> {
    const url = new URL(`api/v1/${segments.map(encodeURIComponent).join("/")}`, this.baseUrl);
    for (const [k, v] of Object.entries(query)) url.searchParams.set(k, v);
    let res: Response;
    try {
      res = await this.fetchImpl(url, { headers: { accept: "application/json" }, signal: AbortSignal.timeout(this.timeoutMs) });
    } catch (e) {
      throw new MarquezError(`request to ${url.pathname} failed: ${e instanceof Error ? e.message : String(e)}`);
    }
    const text = await this.readBounded(res);
    if (!res.ok) throw new MarquezError(`${url.pathname}: HTTP ${res.status}`, res.status);
    try {
      return JSON.parse(text) as Json;
    } catch {
      throw new MarquezError(`${url.pathname}: body is not JSON`, res.status);
    }
  }

  // Read the body as text, stopping once it passes maxBytes.
  private async readBounded(res: Response): Promise<string> {
    if (!res.body) return "";
    const reader = res.body.getReader();
    const chunks: Uint8Array[] = [];
    let total = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > this.maxBytes) {
        await reader.cancel();
        throw new MarquezError(`response larger than ${this.maxBytes} bytes`, res.status);
      }
      chunks.push(value);
    }
    return Buffer.concat(chunks).toString("utf8");
  }

  // Fetch every page of a paged list endpoint, up to maxItems.
  private async paged<T>(segments: string[], key: string, parse: (v: Json, path: string) => T): Promise<T[]> {
    const out: T[] = [];
    for (let offset = 0; ; offset += PAGE) {
      const body = obj(await this.get(segments, { limit: String(PAGE), offset: String(offset) }), key);
      const items = arr(body[key], key);
      items.forEach((it, i) => out.push(parse(it, `${key}[${offset + i}]`)));
      const total = optNum(body, "totalCount", key);
      if (out.length > this.maxItems) throw new MarquezError(`more than ${this.maxItems} ${key}`);
      if (items.length < PAGE || (total !== null && out.length >= total)) return out;
    }
  }

  /** Every namespace. */
  async namespaces(): Promise<Namespace[]> {
    const body = obj(await this.get(["namespaces"]), "namespaces");
    return arr(body["namespaces"], "namespaces").map((n, i) => parseNamespace(n, `namespaces[${i}]`));
  }

  /** Every dataset in a namespace. */
  async datasets(namespace: string): Promise<Dataset[]> {
    return this.paged(["namespaces", namespace, "datasets"], "datasets", parseDataset);
  }

  /** Every job in a namespace. */
  async jobs(namespace: string): Promise<Job[]> {
    return this.paged(["namespaces", namespace, "jobs"], "jobs", parseJob);
  }

  /** Runs of one job, newest first. */
  async runs(namespace: string, job: string): Promise<Run[]> {
    return this.paged(["namespaces", namespace, "jobs", job, "runs"], "runs", parseRun);
  }

  /** Datasets or jobs whose name matches a search term (Marquez /search). */
  async search(q: string, filter: "DATASET" | "JOB", limit = 100): Promise<SearchHit[]> {
    if (q.trim() === "" || q.length > 256) throw new MarquezError("search term must be 1 to 256 characters");
    const body = obj(await this.get(["search"], { q, filter, limit: String(limit) }), "search");
    return arr(body["results"], "search.results").map((r, i) => parseSearchHit(r, `search.results[${i}]`));
  }

  /** The lineage graph around one node, up to depth hops. */
  async lineage(node: string, depth = 20): Promise<LineageNode[]> {
    if (!Number.isInteger(depth) || depth < 1 || depth > 100) throw new MarquezError("depth must be an integer from 1 to 100");
    return parseLineage(await this.get(["lineage"], { nodeId: node, depth: String(depth) }));
  }
}
