// In-process stand-in for the Marquez read API, serving fixed JSON shaped like Marquez 0.51 responses.

import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";

export type Handler = (url: URL, req: IncomingMessage, res: ServerResponse) => void;

export interface Fake {
  url: string;
  requests: string[];
  close: () => Promise<void>;
}

/** Start a server on 127.0.0.1 with routes keyed by decoded pathname. */
export async function startFake(routes: Record<string, Handler | Record<string, unknown> | string>): Promise<Fake> {
  const requests: string[] = [];
  const server = createServer((req, res) => {
    const url = new URL(req.url ?? "/", "http://127.0.0.1");
    requests.push(`${url.pathname}${url.search}`);
    const route = routes[decodeURIComponent(url.pathname)];
    if (typeof route === "function") {
      (route as Handler)(url, req, res);
      return;
    }
    if (route === undefined) {
      res.writeHead(404, { "content-type": "application/json" }).end('{"code":404,"message":"not found"}');
      return;
    }
    res.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify(route));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${port}`,
    requests,
    close: () =>
      new Promise<void>((resolve) => {
        server.closeAllConnections();
        server.close(() => resolve());
      }),
  };
}

const T = "2026-10-23T10:00:00.000Z";

/** A dataset entry as Marquez returns it. */
export function dataset(namespace: string, name: string, fields: [string, string][] = []): unknown {
  return {
    id: { namespace, name },
    type: "DB_TABLE",
    name,
    physicalName: name,
    createdAt: T,
    updatedAt: T,
    namespace,
    sourceName: namespace,
    fields: fields.map(([n, t]) => ({ name: n, type: t, tags: [], description: null })),
    tags: [],
    lastModifiedAt: T,
    lastLifecycleState: null,
    description: null,
    facets: {},
    currentVersion: "8d6b6f1e-0000-4000-8000-000000000001",
    deleted: false,
  };
}

/** A run entry as Marquez returns it. */
export function run(id: string, state: string): unknown {
  return {
    id,
    createdAt: T,
    updatedAt: T,
    nominalStartTime: null,
    nominalEndTime: null,
    state,
    startedAt: T,
    endedAt: state === "RUNNING" ? null : T,
    durationMs: state === "RUNNING" ? null : 1234,
    args: {},
    jobVersion: null,
    inputDatasetVersions: [],
    outputDatasetVersions: [],
    context: {},
    facets: {},
  };
}

/** A job entry as Marquez returns it. */
export function job(namespace: string, name: string, inputs: [string, string][], outputs: [string, string][], state: string | null): unknown {
  return {
    id: { namespace, name },
    type: "BATCH",
    name,
    simpleName: name,
    parentJobName: null,
    createdAt: T,
    updatedAt: T,
    namespace,
    inputs: inputs.map(([ns, n]) => ({ namespace: ns, name: n })),
    outputs: outputs.map(([ns, n]) => ({ namespace: ns, name: n })),
    location: null,
    description: null,
    latestRun: state === null ? null : run(`run-${name}`, state),
    facets: {},
    currentVersion: null,
  };
}

/** A lineage node; edges are given as [origin, destination]. */
export function node(id: string, inEdges: [string, string][], outEdges: [string, string][]): unknown {
  return {
    id,
    type: id.startsWith("job:") ? "JOB" : "DATASET",
    data: {},
    inEdges: inEdges.map(([origin, destination]) => ({ origin, destination })),
    outEdges: outEdges.map(([origin, destination]) => ({ origin, destination })),
  };
}

const W = "duckdb";

/** raw_orders, raw_customers -> stg_* -> customer_revenue, as one Marquez lineage response. */
export const chainLineage = {
  graph: [
    node(`dataset:${W}:raw_orders`, [], [[`dataset:${W}:raw_orders`, "job:dbt:stg_orders"]]),
    node(`dataset:${W}:raw_customers`, [], [[`dataset:${W}:raw_customers`, "job:dbt:stg_customers"]]),
    node("job:dbt:stg_orders", [[`dataset:${W}:raw_orders`, "job:dbt:stg_orders"]], [["job:dbt:stg_orders", `dataset:${W}:stg_orders`]]),
    node("job:dbt:stg_customers", [[`dataset:${W}:raw_customers`, "job:dbt:stg_customers"]], [["job:dbt:stg_customers", `dataset:${W}:stg_customers`]]),
    node(`dataset:${W}:stg_orders`, [["job:dbt:stg_orders", `dataset:${W}:stg_orders`]], [[`dataset:${W}:stg_orders`, "job:dbt:customer_revenue"]]),
    node(`dataset:${W}:stg_customers`, [["job:dbt:stg_customers", `dataset:${W}:stg_customers`]], [[`dataset:${W}:stg_customers`, "job:dbt:customer_revenue"]]),
    node(
      "job:dbt:customer_revenue",
      [
        [`dataset:${W}:stg_orders`, "job:dbt:customer_revenue"],
        [`dataset:${W}:stg_customers`, "job:dbt:customer_revenue"],
      ],
      [["job:dbt:customer_revenue", `dataset:${W}:customer_revenue`]],
    ),
    node(`dataset:${W}:customer_revenue`, [["job:dbt:customer_revenue", `dataset:${W}:customer_revenue`]], []),
  ],
};
