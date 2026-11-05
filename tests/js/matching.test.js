import { test } from "node:test";
import assert from "node:assert/strict";

import { LANES, assignLanes, feasible, fillableLanes, openLanes } from "../../site/js/matching.js";

test("feasible: distinct lanes", () => {
  assert.equal(feasible([]), true);
  assert.equal(feasible([["打野"], ["中路"]]), true);
  assert.equal(feasible([["打野"], ["打野"]]), false);
});

test("feasible: multi-lane heroes are rearranged", () => {
  // A must move to 凱撒 so B can take 打野.
  assert.equal(feasible([["打野", "凱撒"], ["打野"]]), true);
  assert.equal(feasible([["打野", "凱撒"], ["打野"], ["凱撒"]]), false);
  const lanes = assignLanes([["打野", "凱撒"], ["打野"]]);
  assert.deepEqual(lanes, ["凱撒", "打野"]);
});

test("feasible: more than five heroes is never feasible", () => {
  assert.equal(feasible(Array(6).fill([])), false);
});

test("unfilled heroes (empty lane list) can play any lane", () => {
  assert.equal(feasible([[], ["打野"], ["中路"], ["魔龍"], ["輔助"]]), true);
  assert.deepEqual(fillableLanes([], [["打野"]]), LANES.filter((l) => l !== "打野"));
  assert.equal(feasible(Array(5).fill([])), true);
});

test("openLanes", () => {
  assert.deepEqual(openLanes([]), LANES);
  assert.deepEqual(openLanes([["打野"]]), ["凱撒", "中路", "魔龍", "輔助"]);
  // Either hero can go 打野 or 凱撒, but together they use both.
  assert.deepEqual(openLanes([["打野", "凱撒"], ["打野", "凱撒"]]), ["中路", "魔龍", "輔助"]);
  // A flexible hero does not block a lane it could vacate.
  assert.deepEqual(openLanes([["打野", "凱撒"]]), LANES);
  // An unfilled hero takes some lane, but no specific one.
  assert.deepEqual(openLanes([[]]), LANES);
  assert.deepEqual(openLanes(Array(5).fill([])), []);
});

test("fillableLanes respects the rest of the team", () => {
  assert.deepEqual(fillableLanes(["打野", "凱撒"], [["打野"]]), ["凱撒"]);
  assert.deepEqual(fillableLanes(["打野"], [["打野"]]), []);
  // Candidate can take 打野 because teammate can move to 凱撒.
  assert.deepEqual(fillableLanes(["打野"], [["打野", "凱撒"]]), ["打野"]);
});
