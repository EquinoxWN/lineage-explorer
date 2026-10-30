import { test } from "node:test";
import assert from "node:assert/strict";
import { run } from "../src/cli.ts";
import { chainLineage, dataset, job, startFake } from "./fake-marquez.ts";

// Run the CLI in-process and capture its output.
async function cli(argv: string[], env: Record<string, string> = {}): Promise<{ code: number; out: string[]; err: string[] }> {
  const out: string[] = [];
  const err: string[] = [];
  const code = await run(argv, { out: (l) => out.push(l), err: (l) => err.push(l), env, sleep: async () => undefined });
  return { code, out, err };
}

const routes = {
  "/api/v1/namespaces": { namespaces: [{ name: "dbt", ownerName: "anonymous", description: null, createdAt: "", updatedAt: "", isHidden: false }] },
  "/api/v1/namespaces/dbt/datasets": { totalCount: 1, datasets: [dataset("dbt", "main.customer_revenue", [["customer_id", "INTEGER"], ["revenue", "DOUBLE"]])] },
  "/api/v1/namespaces/dbt/jobs": {
    totalCount: 2,
    jobs: [
      job("dbt", "shop.model.customer_revenue", [["dbt", "main.stg_orders"]], [["dbt", "main.customer_revenue"]], "COMPLETED"),
      job("dbt", "shop.model.stg_orders", [], [], "FAILED"),
    ],
  },
  "/api/v1/lineage": chainLineage,
  "/api/v1/search": { totalCount: 1, results: [{ type: "DATASET", name: "main.customer_revenue", namespace: "dbt", nodeId: "dataset:dbt:main.customer_revenue" }] },
};

test("list commands print what Marquez stores", async () => {
  const fake = await startFake(routes);
  try {
    assert.deepEqual((await cli(["namespaces"], { MARQUEZ_URL: fake.url })).out, ["dbt\tanonymous"]);
    assert.deepEqual((await cli(["--url", fake.url, "datasets", "dbt"])).out, ["main.customer_revenue\tDB_TABLE\tcustomer_id:INTEGER, revenue:DOUBLE"]);
    const jobs = (await cli(["--url", fake.url, "jobs", "dbt"])).out;
    assert.equal(jobs[0], "shop.model.customer_revenue\tCOMPLETED\tin: dbt/main.stg_orders\tout: dbt/main.customer_revenue");
    assert.deepEqual((await cli(["--url", fake.url, "summary"])).out, ["dbt: 1 datasets, 2 jobs, latest runs COMPLETED=1 FAILED=1"]);
  } finally {
    await fake.close();
  }
});

test("lineage prints upstream and downstream with hop counts", async () => {
  const fake = await startFake(routes);
  try {
    const r = await cli(["--url", fake.url, "lineage", "dataset:duckdb:stg_orders", "--depth", "3"]);
    assert.equal(r.code, 0);
    assert.deepEqual(r.out, [
      "upstream (2):",
      "  1  job:dbt:stg_orders",
      "  2  dataset:duckdb:raw_orders",
      "downstream (2):",
      "  1  job:dbt:customer_revenue",
      "  2  dataset:duckdb:customer_revenue",
    ]);
  } finally {
    await fake.close();
  }
});

test("check passes only when expected jobs completed and datasets exist", async () => {
  const fake = await startFake(routes);
  try {
    const ok = await cli(["--url", fake.url, "check", "--job", "dbt::customer_revenue", "--dataset", "customer_revenue"]);
    assert.equal(ok.code, 0);
    assert.equal(ok.out.at(-1), "CHECK OK: 1 jobs, 1 datasets");
    const failed = await cli(["--url", fake.url, "check", "--job", "dbt::stg_orders", "--job", "airflow::orders"]);
    assert.equal(failed.code, 1);
    assert.deepEqual(failed.out, ["MISS job dbt::stg_orders: shop.model.stg_orders=FAILED", "MISS job airflow::orders: no matching job", "CHECK FAILED"]);
  } finally {
    await fake.close();
  }
});

test("check --wait polls until a run lands", async () => {
  let calls = 0;
  const fake = await startFake({
    "/api/v1/namespaces/scripts/jobs": (_u, _q, res) => {
      calls++;
      res.end(JSON.stringify({ totalCount: 1, jobs: [job("scripts", "clean_orders", [], [], calls < 3 ? "RUNNING" : "COMPLETED")] }));
    },
  });
  try {
    const r = await cli(["--url", fake.url, "check", "--job", "scripts::clean_orders", "--wait", "30"]);
    assert.equal(r.code, 0);
    assert.equal(calls, 3);
  } finally {
    await fake.close();
  }
});

test("bad input exits 2 with usage; an unreachable server exits 1", async () => {
  for (const argv of [[], ["frobnicate"], ["datasets"], ["check"], ["check", "--job", "nonamespace"], ["lineage", "orders"], ["lineage", "dataset:a:b", "--depth", "500"], ["--url", "file:///x", "namespaces"], ["--bogus"]]) {
    const r = await cli(argv);
    assert.equal(r.code, argv[0] === "--url" ? 1 : 2, argv.join(" "));
  }
  assert.equal((await cli(["--help"])).code, 0);
  const down = await cli(["--url", "http://127.0.0.1:9", "namespaces"]);
  assert.equal(down.code, 1);
  assert.match(down.err[0] ?? "", /^error: request to \/api\/v1\/namespaces failed/);
});
