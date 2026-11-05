import { test } from "node:test";
import assert from "node:assert/strict";

import { createEngine } from "../../site/js/engine.js";
import {
  BAN_ORDER, PICK_ORDER, emptyDraft, engineState, fillError, nextEmptySlot, pickTurn,
  sanitizeDraft, sanitizeSlot, setLane, setSlot, slotLabel,
} from "../../site/js/draft.js";

const hero = (name, extra = {}) => ({
  name, main_class: "法師", sub_class: null, avatar: null, form_group: null, lanes: {}, ...extra,
});
const engine = createEngine({
  heroes: [
    hero("甲"), hero("乙"), hero("丙"),
    hero("元流之子(法師)", { form_group: "元流之子" }),
    hero("元流之子(射手)", { form_group: "元流之子" }),
  ],
  counters: [], synergies: [], settings: {},
});

test("standard pick order is 藍1 紅2 藍2 紅2 藍2 紅1", () => {
  const teams = PICK_ORDER.map((s) => (s.team === "blue" ? "B" : "R")).join("");
  assert.equal(teams, "BRRBBRRBBR");
  assert.equal(pickTurn("blue", 0), 1);
  assert.equal(pickTurn("red", 1), 3);
  assert.equal(pickTurn("red", 4), 10);
});

test("default active slot: bans first, then picks in order", () => {
  let d = emptyDraft();
  assert.deepEqual(nextEmptySlot(d), BAN_ORDER[0]);
  for (const slot of BAN_ORDER) d = setSlot(d, slot, `ban-${slot.team}-${slot.index}`);
  assert.deepEqual(nextEmptySlot(d), { kind: "pick", team: "blue", index: 0 });
  d = setSlot(d, PICK_ORDER[0], "甲");
  assert.deepEqual(nextEmptySlot(d), { kind: "pick", team: "red", index: 0 });
  // A gap left earlier in the sequence is filled first.
  d = setSlot(d, BAN_ORDER[3], null);
  assert.deepEqual(nextEmptySlot(d), BAN_ORDER[3]);
});

test("setSlot does not mutate the original draft", () => {
  const d = emptyDraft();
  const next = setSlot(d, PICK_ORDER[0], "甲");
  assert.equal(d.picks.blue[0], null);
  assert.equal(next.picks.blue[0], "甲");
});

test("engineState is seen from our side", () => {
  let d = emptyDraft();
  d = setSlot(d, { kind: "pick", team: "blue", index: 0 }, "甲");
  d = setSlot(d, { kind: "pick", team: "red", index: 0 }, "乙");
  d = setSlot(d, { kind: "ban", team: "red", index: 2 }, "丙");
  d = setLane(d, "blue", 0, "打野");
  assert.deepEqual(engineState(d, "blue"), {
    side: "blue", bansUs: [], bansThem: ["丙"], picksUs: ["甲"], picksThem: ["乙"],
    lanesUs: { 甲: "打野" }, lanesThem: {},
  });
  assert.deepEqual(engineState(d, "red"), {
    side: "red", bansUs: ["丙"], bansThem: [], picksUs: ["乙"], picksThem: ["甲"],
    lanesUs: {}, lanesThem: { 甲: "打野" },
  });
});

test("fillError: duplicates, form groups, and replacing a slot", () => {
  const pick = (team, index) => ({ kind: "pick", team, index });
  const ban = (team, index) => ({ kind: "ban", team, index });
  let d = setSlot(emptyDraft(), pick("blue", 0), "元流之子(法師)");

  assert.match(fillError(d, pick("red", 0), "元流之子(法師)", engine), /已經被禁用或選走/);
  assert.match(fillError(d, pick("red", 0), "元流之子(射手)", engine), /其他型態/);
  assert.equal(fillError(d, ban("red", 0), "元流之子(射手)", engine), null, "other form can still be banned");
  assert.equal(fillError(d, pick("blue", 0), "元流之子(射手)", engine), null, "replacing the same slot is fine");
  assert.equal(fillError(d, pick("blue", 0), "元流之子(法師)", engine), null, "re-filling the same hero is fine");

  d = setSlot(emptyDraft(), ban("blue", 0), "元流之子(法師)");
  assert.equal(fillError(d, pick("red", 0), "元流之子(射手)", engine), null, "banning one form leaves the other pickable");
  assert.match(fillError(d, pick("red", 0), "不存在", engine), /找不到/);
});

test("slot labels", () => {
  assert.equal(slotLabel({ kind: "pick", team: "blue", index: 0 }, "blue"), "我方 1 樓 · 第 1 手");
  assert.equal(slotLabel({ kind: "pick", team: "blue", index: 1 }, "red"), "敵方 2 樓 · 第 4 手");
  assert.equal(slotLabel({ kind: "ban", team: "red", index: 4 }, "red"), "我方禁用 5");
});

test("sanitizeDraft drops unknown and duplicate names; sanitizeSlot validates", () => {
  const raw = {
    bans: { blue: ["甲", "不存在", null, 3, "甲"], red: "oops" },
    picks: { blue: ["乙"], red: [null, "甲"] },
  };
  const d = sanitizeDraft(raw, engine.heroes);
  assert.deepEqual(d.bans.blue, ["甲", null, null, null, null]);
  assert.deepEqual(d.bans.red, [null, null, null, null, null]);
  assert.deepEqual(d.picks.blue, ["乙", null, null, null, null]);
  assert.deepEqual(d.picks.red, [null, null, null, null, null], "duplicate 甲 dropped");
  assert.deepEqual(sanitizeDraft(null, engine.heroes), emptyDraft());

  assert.deepEqual(sanitizeSlot({ kind: "pick", team: "red", index: "2" }), { kind: "pick", team: "red", index: 2 });
  assert.equal(sanitizeSlot({ kind: "pick", team: "red", index: 5 }), null);
  assert.equal(sanitizeSlot({ kind: "x", team: "red", index: 0 }), null);
  assert.equal(sanitizeSlot(undefined), null);
});

test("lane choice: only on filled picks, reset when the hero changes, kept otherwise", () => {
  const slot = { kind: "pick", team: "blue", index: 0 };
  let d = setLane(emptyDraft(), "blue", 0, "中路");
  assert.equal(d.lanes.blue[0], null, "empty slot cannot have a lane");
  d = setSlot(d, slot, "甲");
  d = setLane(d, "blue", 0, "中路");
  assert.equal(d.lanes.blue[0], "中路");
  assert.equal(setLane(d, "blue", 0, "不是分路").lanes.blue[0], null);
  assert.equal(setSlot(d, slot, "甲").lanes.blue[0], "中路", "same hero keeps its lane");
  assert.equal(setSlot(d, slot, "乙").lanes.blue[0], null, "new hero resets the lane");
  assert.equal(setSlot(d, slot, null).lanes.blue[0], null, "clearing resets the lane");
  // Bans never touch lane choices.
  assert.equal(setSlot(d, { kind: "ban", team: "blue", index: 0 }, "丙").lanes.blue[0], "中路");
});

test("sanitizeDraft keeps valid lane choices only for kept picks", () => {
  const raw = {
    picks: { blue: ["甲", "不存在", "乙"], red: [] },
    lanes: { blue: ["打野", "中路", "亂打"], red: ["魔龍"] },
  };
  const d = sanitizeDraft(raw, engine.heroes);
  assert.deepEqual(d.lanes.blue, ["打野", null, null, null, null]);
  assert.deepEqual(d.lanes.red, [null, null, null, null, null]);
});
