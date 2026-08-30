import { demoWorkspace } from "./fixtures";

/** Lightweight component contract checks; runnable from a browser/test harness without backend access. */
export function assertOperatorWorkspaceContract(): void {
  if (demoWorkspace.projections.length < 3) throw new Error("decision projections missing");
  if (demoWorkspace.candidates.length < 3) throw new Error("intervention comparison missing");
  if (!demoWorkspace.evidence.some((item) => item.state.includes("contradicted"))) throw new Error("contradiction state missing");
  if (!demoWorkspace.resources.some((item) => item.task.includes("excluded"))) throw new Error("resource exclusion missing");
  if (!demoWorkspace.queue.length || !demoWorkspace.tasks.length) throw new Error("queue/task lifecycle missing");
  if (!demoWorkspace.places.every((place) => place.coordinates.includes(","))) throw new Error("spatial fallback missing");
}
