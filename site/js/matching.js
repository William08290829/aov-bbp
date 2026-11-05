// Lane assignment via bipartite matching (heroes -> lanes).
// Pure functions: no DOM, no fetch. Each hero is represented by the list of
// lanes it can play; an empty list means "lane data not filled" = any lane.

export const LANES = ["凱撒", "打野", "中路", "魔龍", "輔助"];

function options(lanes) {
  return lanes && lanes.length ? lanes : LANES;
}

/**
 * Maximum matching (Kuhn's algorithm). Returns { size, assignment } where
 * assignment[i] is the lane given to hero i (or null).
 */
export function maxMatching(laneLists) {
  const owner = new Map(); // lane -> hero index
  const tryAssign = (i, seen) => {
    for (const lane of options(laneLists[i])) {
      if (seen.has(lane)) continue;
      seen.add(lane);
      if (!owner.has(lane) || tryAssign(owner.get(lane), seen)) {
        owner.set(lane, i);
        return true;
      }
    }
    return false;
  };
  let size = 0;
  for (let i = 0; i < laneLists.length; i++) {
    if (tryAssign(i, new Set())) size++;
  }
  const assignment = laneLists.map(() => null);
  for (const [lane, i] of owner) assignment[i] = lane;
  return { size, assignment };
}

/** True when every hero can be given a distinct lane. */
export function feasible(laneLists) {
  if (laneLists.length > LANES.length) return false;
  return maxMatching(laneLists).size === laneLists.length;
}

/** Lanes the team can still fill: adding a hero that only plays `l` stays feasible. */
export function openLanes(teamLaneLists) {
  return LANES.filter((l) => feasible([...teamLaneLists, [l]]));
}

/** Lanes the candidate could take while the team (plus the candidate) stays feasible. */
export function fillableLanes(candidateLanes, teamLaneLists) {
  return options(candidateLanes).filter((l) => feasible([...teamLaneLists, [l]]));
}

/** One valid lane per hero (null for heroes that cannot be placed). */
export function assignLanes(laneLists) {
  return maxMatching(laneLists).assignment;
}
