// Walks a Marquez lineage graph upstream or downstream from one node.

import type { LineageNode } from "./marquez.ts";

export interface Reached {
  id: string;
  type: "DATASET" | "JOB";
  hops: number;
}

/** Adjacency lists built from the edges of every node, deduplicated. */
export interface Graph {
  types: Map<string, "DATASET" | "JOB">;
  down: Map<string, Set<string>>;
  up: Map<string, Set<string>>;
}

// Add a directed edge to both adjacency maps.
function link(g: Graph, from: string, to: string): void {
  if (!g.down.has(from)) g.down.set(from, new Set());
  if (!g.up.has(to)) g.up.set(to, new Set());
  g.down.get(from)?.add(to);
  g.up.get(to)?.add(from);
}

/** Build adjacency from both in- and out-edges, so either half is enough. */
export function buildGraph(nodes: LineageNode[]): Graph {
  const g: Graph = { types: new Map(), down: new Map(), up: new Map() };
  for (const n of nodes) {
    g.types.set(n.id, n.type);
    for (const e of n.outEdges) link(g, e.origin, e.destination);
    for (const e of n.inEdges) link(g, e.origin, e.destination);
  }
  return g;
}

/** Breadth-first walk; each node is reported once at its shortest hop count. */
export function walk(g: Graph, start: string, direction: "up" | "down"): Reached[] {
  const adj = direction === "up" ? g.up : g.down;
  const seen = new Set([start]);
  const out: Reached[] = [];
  let frontier = [start];
  for (let hops = 1; frontier.length > 0; hops++) {
    const next: string[] = [];
    for (const id of frontier) {
      for (const n of [...(adj.get(id) ?? [])].sort()) {
        if (seen.has(n)) continue;
        seen.add(n);
        next.push(n);
        out.push({ id: n, type: g.types.get(n) ?? (n.startsWith("job:") ? "JOB" : "DATASET"), hops });
      }
    }
    frontier = next;
  }
  return out;
}
