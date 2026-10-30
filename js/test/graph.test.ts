import { test } from "node:test";
import assert from "node:assert/strict";
import { buildGraph, walk } from "../src/graph.ts";
import { parseLineage, type LineageNode } from "../src/marquez.ts";
import { chainLineage } from "./fake-marquez.ts";

const g = buildGraph(parseLineage(chainLineage));

test("upstream of the mart reaches both raw tables through their jobs", () => {
  const up = walk(g, "dataset:duckdb:customer_revenue", "up");
  assert.deepEqual(
    up.map((r) => `${r.hops} ${r.id}`),
    [
      "1 job:dbt:customer_revenue",
      "2 dataset:duckdb:stg_customers",
      "2 dataset:duckdb:stg_orders",
      "3 job:dbt:stg_customers",
      "3 job:dbt:stg_orders",
      "4 dataset:duckdb:raw_customers",
      "4 dataset:duckdb:raw_orders",
    ],
  );
  assert.ok(up.every((r) => r.type === (r.id.startsWith("job:") ? "JOB" : "DATASET")));
});

test("downstream of a raw table stops at the mart and skips the other branch", () => {
  const down = walk(g, "dataset:duckdb:raw_orders", "down").map((r) => r.id);
  assert.deepEqual(down, ["job:dbt:stg_orders", "dataset:duckdb:stg_orders", "job:dbt:customer_revenue", "dataset:duckdb:customer_revenue"]);
});

test("edges listed on one side only, duplicates and cycles are handled", () => {
  const nodes: LineageNode[] = [
    { id: "dataset:n:a", type: "DATASET", inEdges: [], outEdges: [{ origin: "dataset:n:a", destination: "job:n:j" }] },
    { id: "job:n:j", type: "JOB", inEdges: [{ origin: "dataset:n:a", destination: "job:n:j" }], outEdges: [] },
    // Only the dataset side lists j -> b, and b -> j forms a cycle back.
    { id: "dataset:n:b", type: "DATASET", inEdges: [{ origin: "job:n:j", destination: "dataset:n:b" }], outEdges: [{ origin: "dataset:n:b", destination: "job:n:j" }] },
  ];
  const cg = buildGraph(nodes);
  assert.deepEqual(walk(cg, "dataset:n:a", "down").map((r) => [r.id, r.hops]), [["job:n:j", 1], ["dataset:n:b", 2]]);
  assert.deepEqual(walk(cg, "dataset:n:b", "up").map((r) => r.id), ["job:n:j", "dataset:n:a"]);
  assert.deepEqual(walk(cg, "dataset:n:unknown", "up"), []);
});

test("random DAGs: every reached node is reachable and hop counts are shortest", () => {
  let seed = 7;
  const rnd = (): number => ((seed = (seed * 1103515245 + 12345) % 2 ** 31) / 2 ** 31);
  for (let round = 0; round < 25; round++) {
    const n = 12;
    const edges: [number, number][] = [];
    for (let a = 0; a < n; a++) for (let b = a + 1; b < n; b++) if (rnd() < 0.2) edges.push([a, b]);
    const id = (i: number): string => `dataset:n:d${i}`;
    const nodes: LineageNode[] = Array.from({ length: n }, (_, i) => ({
      id: id(i),
      type: "DATASET",
      inEdges: [],
      outEdges: edges.filter(([a]) => a === i).map(([a, b]) => ({ origin: id(a), destination: id(b) })),
    }));
    // Reference: Bellman-style relaxation over the edge list.
    const dist = new Array<number>(n).fill(Infinity);
    dist[0] = 0;
    for (let k = 0; k < n; k++) for (const [a, b] of edges) dist[b] = Math.min(dist[b] ?? Infinity, (dist[a] ?? Infinity) + 1);
    const got = new Map(walk(buildGraph(nodes), id(0), "down").map((r) => [r.id, r.hops]));
    for (let i = 1; i < n; i++) assert.equal(got.get(id(i)) ?? Infinity, dist[i], `round ${round} node ${i}`);
  }
});
