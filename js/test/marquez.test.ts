import { test } from "node:test";
import assert from "node:assert/strict";
import { MarquezClient, MarquezError, nodeId, parseDataset, parseJob, parseLineage, parseRun } from "../src/marquez.ts";
import { chainLineage, dataset, job, run, startFake } from "./fake-marquez.ts";

test("parsers keep the fields the explorer uses from real-shaped entries", () => {
  const d = parseDataset(dataset("duckdb", "main.orders", [["order_id", "INTEGER"], ["amount", "DOUBLE"]]));
  assert.deepEqual(d.fields.map((f) => [f.name, f.type]), [["order_id", "INTEGER"], ["amount", "DOUBLE"]]);
  assert.equal(d.namespace, "duckdb");
  const j = parseJob(job("dbt", "m.orders", [["duckdb", "raw"]], [["duckdb", "main.orders"]], "COMPLETED"));
  assert.equal(j.latestRun?.state, "COMPLETED");
  assert.deepEqual(j.outputs, [{ namespace: "duckdb", name: "main.orders" }]);
  assert.equal(parseJob(job("dbt", "never-ran", [], [], null)).latestRun, null);
  assert.equal(parseRun(run("r1", "RUNNING")).durationMs, null);
  assert.equal(parseLineage(chainLineage).length, 8);
});

test("parsers reject malformed bodies with the path of the problem", () => {
  assert.throws(() => parseRun({ ...(run("r", "DONE") as object) }), /run\.state: unknown run state "DONE"/);
  assert.throws(() => parseDataset({ id: { namespace: "n" }, type: "DB_TABLE" }), /dataset\.id\.name: expected a string/);
  assert.throws(() => parseDataset([]), /expected an object/);
  assert.throws(() => parseLineage({ graph: [{ id: "x", type: "TABLE", inEdges: [], outEdges: [] }] }), /unknown node type/);
  assert.throws(() => parseLineage({}), /lineage\.graph: expected an array/);
  assert.throws(() => parseRun({ ...(run("r", "COMPLETED") as object), durationMs: "5" }), /durationMs: expected a number/);
});

test("the client accepts only plain http(s) base URLs", () => {
  for (const bad of ["file:///etc/passwd", "ftp://host", "not a url", "http://h/?x=1", "http://h/#f"]) {
    assert.throws(() => new MarquezClient({ baseUrl: bad }), MarquezError, bad);
  }
  assert.equal(new MarquezClient({ baseUrl: "http://h:5000/marquez" }).baseUrl.href, "http://h:5000/marquez/");
  assert.equal(nodeId("dataset", "file", "/data/x.csv"), "dataset:file:/data/x.csv");
});

test("names are percent-encoded so they cannot change the request path", async () => {
  const fake = await startFake({ "/api/v1/namespaces/a b/jobs/../x?y/runs": { runs: [run("r", "COMPLETED")], totalCount: 1 } });
  try {
    const runs = await new MarquezClient({ baseUrl: fake.url }).runs("a b", "../x?y");
    assert.equal(runs.length, 1);
    assert.equal(fake.requests[0], "/api/v1/namespaces/a%20b/jobs/..%2Fx%3Fy/runs?limit=100&offset=0");
  } finally {
    await fake.close();
  }
});

test("list endpoints are read page by page until totalCount", async () => {
  const all = Array.from({ length: 250 }, (_, i) => dataset("ns", `t${i}`));
  const fake = await startFake({
    "/api/v1/namespaces/ns/datasets": (url, _req, res) => {
      const off = Number(url.searchParams.get("offset"));
      const lim = Number(url.searchParams.get("limit"));
      res.end(JSON.stringify({ totalCount: all.length, datasets: all.slice(off, off + lim) }));
    },
  });
  try {
    const got = await new MarquezClient({ baseUrl: fake.url }).datasets("ns");
    assert.equal(got.length, 250);
    assert.equal(got[249]?.name, "t249");
    assert.equal(fake.requests.length, 3);
  } finally {
    await fake.close();
  }
});

test("errors: HTTP status, non-JSON body, oversized body, timeout, item cap", async () => {
  const fake = await startFake({
    "/api/v1/namespaces": "plain",
    "/api/v1/namespaces/big/jobs": (_u, _q, res) => res.end(JSON.stringify({ jobs: [], pad: "x".repeat(5000) })),
    "/api/v1/namespaces/text/jobs": (_u, _q, res) => res.end("<html>"),
    "/api/v1/namespaces/slow/jobs": () => undefined,
    "/api/v1/namespaces/many/jobs": (_u, _q, res) => res.end(JSON.stringify({ jobs: Array.from({ length: 100 }, (_, i) => job("many", `j${i}`, [], [], null)) })),
  });
  const c = new MarquezClient({ baseUrl: fake.url, maxBytes: 4096, timeoutMs: 300, maxItems: 150 });
  try {
    await assert.rejects(c.jobs("missing"), (e: unknown) => e instanceof MarquezError && e.status === 404);
    await assert.rejects(c.namespaces(), /expected an object/);
    await assert.rejects(c.jobs("text"), /body is not JSON/);
    await assert.rejects(c.jobs("big"), /larger than 4096 bytes/);
    await assert.rejects(c.jobs("slow"), /request to .* failed/);
    await assert.rejects(new MarquezClient({ baseUrl: fake.url, maxItems: 150 }).jobs("many"), /more than 150 jobs/);
    await assert.rejects(c.lineage("dataset:a:b", 0), /depth/);
    await assert.rejects(c.search(" ", "DATASET"), /search term/);
  } finally {
    await fake.close();
  }
});

test("search and lineage send the query Marquez expects", async () => {
  const fake = await startFake({
    "/api/v1/search": { totalCount: 1, results: [{ type: "DATASET", name: "main.customer_revenue", namespace: "duckdb", nodeId: "dataset:duckdb:main.customer_revenue", updatedAt: "2026-10-23T10:00:00Z" }] },
    "/api/v1/lineage": chainLineage,
  });
  try {
    const c = new MarquezClient({ baseUrl: fake.url });
    const hits = await c.search("customer_revenue", "DATASET");
    assert.equal(hits[0]?.nodeId, "dataset:duckdb:main.customer_revenue");
    assert.equal((await c.lineage("dataset:duckdb:customer_revenue", 5)).length, 8);
    assert.deepEqual(fake.requests, [
      "/api/v1/search?q=customer_revenue&filter=DATASET&limit=100",
      "/api/v1/lineage?nodeId=dataset%3Aduckdb%3Acustomer_revenue&depth=5",
    ]);
  } finally {
    await fake.close();
  }
});
