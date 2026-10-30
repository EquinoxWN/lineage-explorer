#!/usr/bin/env node
// Command-line reader for Marquez: list what it stores and check that expected runs landed.

import { parseArgs } from "node:util";
import { pathToFileURL } from "node:url";
import { buildGraph, walk } from "./graph.ts";
import { MarquezClient, MarquezError, type Job } from "./marquez.ts";

export interface Io {
  out: (line: string) => void;
  err: (line: string) => void;
  env: Record<string, string | undefined>;
  sleep?: (ms: number) => Promise<void>;
}

const USAGE = `usage: lineage-explorer [--url URL] <command>
  namespaces                     list namespaces
  datasets <namespace>           datasets with their columns
  jobs <namespace>               jobs with inputs, outputs and latest run state
  runs <namespace> <job>         runs of one job, newest first
  lineage <nodeId> [--depth N]   upstream and downstream of dataset:<ns>:<name> or job:<ns>:<name>
  summary                        datasets, jobs and latest run states per namespace
  check [--job NS::TEXT]... [--dataset TEXT]... [--wait SECONDS]
                                 exit 1 unless every expected job has a COMPLETED latest run
                                 and every expected dataset is found
URL defaults to $MARQUEZ_URL, then http://localhost:5000.`;

class UsageError extends Error {}

// One positional argument or a usage error.
function need(pos: string[], i: number, what: string): string {
  const v = pos[i];
  if (v === undefined || v === "") throw new UsageError(`missing ${what}`);
  return v;
}

// Integer option within bounds or a usage error.
function intOpt(v: string | undefined, name: string, def: number, min: number, max: number): number {
  if (v === undefined) return def;
  const n = Number(v);
  if (!Number.isInteger(n) || n < min || n > max) throw new UsageError(`--${name} must be an integer from ${min} to ${max}`);
  return n;
}

// Latest-run state or a dash.
function stateOf(j: Job): string {
  return j.latestRun?.state ?? "-";
}

// Split NS::TEXT into its two halves.
function splitJobSpec(spec: string): [string, string] {
  const i = spec.indexOf("::");
  if (i <= 0 || i + 2 >= spec.length) throw new UsageError(`--job expects NAMESPACE::TEXT, got ${JSON.stringify(spec)}`);
  return [spec.slice(0, i), spec.slice(i + 2)];
}

// One pass over every expectation; returns the lines and whether all passed.
async function checkOnce(client: MarquezClient, jobs: string[], datasets: string[]): Promise<{ ok: boolean; lines: string[] }> {
  const lines: string[] = [];
  let ok = true;
  const byNs = new Map<string, Job[]>();
  for (const spec of jobs) {
    const [ns, text] = splitJobSpec(spec);
    let list = byNs.get(ns);
    if (!list) {
      try {
        list = await client.jobs(ns);
      } catch (e) {
        if (!(e instanceof MarquezError) || e.status !== 404) throw e;
        list = [];
      }
      byNs.set(ns, list);
    }
    const hits = list.filter((j) => j.name.includes(text));
    const done = hits.filter((j) => j.latestRun?.state === "COMPLETED");
    if (done.length === 0) ok = false;
    const detail = hits.length === 0 ? "no matching job" : hits.map((j) => `${j.name}=${stateOf(j)}`).join(", ");
    lines.push(`${done.length > 0 ? "ok  " : "MISS"} job ${ns}::${text}: ${detail}`);
  }
  for (const text of datasets) {
    const hits = await client.search(text, "DATASET");
    if (hits.length === 0) ok = false;
    const detail = hits.length === 0 ? "not found" : hits.map((h) => `${h.namespace}/${h.name}`).join(", ");
    lines.push(`${hits.length > 0 ? "ok  " : "MISS"} dataset ${text}: ${detail}`);
  }
  return { ok, lines };
}

/** Run one command; returns the process exit code. */
export async function run(argv: string[], io: Io): Promise<number> {
  let parsed;
  try {
    parsed = parseArgs({
      args: argv,
      allowPositionals: true,
      options: {
        url: { type: "string" },
        depth: { type: "string" },
        job: { type: "string", multiple: true },
        dataset: { type: "string", multiple: true },
        wait: { type: "string" },
        help: { type: "boolean", short: "h" },
      },
    });
  } catch (e) {
    io.err(`${e instanceof Error ? e.message : String(e)}\n${USAGE}`);
    return 2;
  }
  const { values: v, positionals: pos } = parsed;
  if (v.help || pos.length === 0) {
    (v.help ? io.out : io.err)(USAGE);
    return v.help ? 0 : 2;
  }
  try {
    const client = new MarquezClient({ baseUrl: v.url ?? io.env["MARQUEZ_URL"] ?? "http://localhost:5000" });
    const cmd = pos[0];
    switch (cmd) {
      case "namespaces":
        for (const n of await client.namespaces()) io.out(`${n.name}\t${n.ownerName ?? "-"}`);
        return 0;
      case "datasets":
        for (const d of await client.datasets(need(pos, 1, "namespace"))) {
          io.out(`${d.name}\t${d.type}\t${d.fields.map((f) => `${f.name}:${f.type ?? "?"}`).join(", ") || "-"}`);
        }
        return 0;
      case "jobs":
        for (const j of await client.jobs(need(pos, 1, "namespace"))) {
          const ids = (xs: { namespace: string; name: string }[]): string => xs.map((x) => `${x.namespace}/${x.name}`).join(", ") || "-";
          io.out(`${j.name}\t${stateOf(j)}\tin: ${ids(j.inputs)}\tout: ${ids(j.outputs)}`);
        }
        return 0;
      case "runs":
        for (const r of await client.runs(need(pos, 1, "namespace"), need(pos, 2, "job"))) {
          io.out(`${r.id}\t${r.state}\t${r.startedAt ?? "-"}\t${r.durationMs ?? "-"} ms`);
        }
        return 0;
      case "lineage": {
        const id = need(pos, 1, "nodeId");
        if (!/^(dataset|job):[^:]+:.+$/.test(id)) throw new UsageError("nodeId must look like dataset:<namespace>:<name> or job:<namespace>:<name>");
        const g = buildGraph(await client.lineage(id, intOpt(v.depth, "depth", 20, 1, 100)));
        for (const dir of ["up", "down"] as const) {
          const reached = walk(g, id, dir);
          io.out(`${dir === "up" ? "upstream" : "downstream"} (${reached.length}):`);
          for (const r of reached) io.out(`  ${r.hops}  ${r.id}`);
        }
        return 0;
      }
      case "summary": {
        for (const n of await client.namespaces()) {
          const [ds, js] = await Promise.all([client.datasets(n.name), client.jobs(n.name)]);
          const states = new Map<string, number>();
          for (const j of js) states.set(stateOf(j), (states.get(stateOf(j)) ?? 0) + 1);
          const st = [...states].sort().map(([s, c]) => `${s}=${c}`).join(" ") || "-";
          io.out(`${n.name}: ${ds.length} datasets, ${js.length} jobs, latest runs ${st}`);
        }
        return 0;
      }
      case "check": {
        const jobs = v.job ?? [];
        const datasets = v.dataset ?? [];
        if (jobs.length + datasets.length === 0) throw new UsageError("check needs at least one --job or --dataset");
        jobs.forEach(splitJobSpec);
        const deadline = Date.now() + intOpt(v.wait, "wait", 0, 0, 600) * 1000;
        const sleep = io.sleep ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms)));
        for (;;) {
          const res = await checkOnce(client, jobs, datasets);
          if (res.ok || Date.now() >= deadline) {
            res.lines.forEach((l) => io.out(l));
            io.out(res.ok ? `CHECK OK: ${jobs.length} jobs, ${datasets.length} datasets` : "CHECK FAILED");
            return res.ok ? 0 : 1;
          }
          await sleep(2000);
        }
      }
      default:
        throw new UsageError(`unknown command ${JSON.stringify(cmd)}`);
    }
  } catch (e) {
    if (e instanceof UsageError) {
      io.err(`${e.message}\n${USAGE}`);
      return 2;
    }
    if (e instanceof MarquezError) {
      io.err(`error: ${e.message}`);
      return 1;
    }
    throw e;
  }
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  const code = await run(process.argv.slice(2), {
    out: (l) => process.stdout.write(`${l}\n`),
    err: (l) => process.stderr.write(`${l}\n`),
    env: process.env,
  });
  process.exitCode = code;
}
