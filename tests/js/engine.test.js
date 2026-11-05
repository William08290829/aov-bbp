import { test } from "node:test";
import assert from "node:assert/strict";

import { DEFAULT_SETTINGS, UNFILLED_NOTE, createEngine } from "../../site/js/engine.js";

const hero = (name, lanes = {}, extra = {}) => ({
  name, main_class: "法師", sub_class: null, avatar: null, form_group: null, lanes, ...extra,
});

const state = (s = {}) => ({ side: "blue", bansUs: [], bansThem: [], picksUs: [], picksThem: [], ...s });

const close = (a, b) => Math.abs(a - b) < 1e-9;

function find(result, name) {
  return result.suggestions.find((s) => s.name === name);
}

function checkInvariants(result) {
  for (const s of result.suggestions) {
    for (const p of s.pros) assert.ok(p.value > 0, `${s.name} pro ${p.text} must be > 0`);
    for (const c of s.cons) assert.ok(c.value <= 0, `${s.name} con ${c.text} must be <= 0`);
    const sum = [...s.pros, ...s.cons].reduce((t, i) => t + i.value, 0);
    assert.ok(close(s.score, sum), `${s.name} score ${s.score} != ${sum}`);
  }
  const scores = result.suggestions.filter((s) => !s.blocked).map((s) => s.score);
  assert.deepEqual(scores, [...scores].sort((a, b) => b - a), "sorted by score");
}

// ---------------------------------------------------------------- lookup tables

test("getCounter is antisymmetric, getSynergy symmetric, unknown pairs are 0", () => {
  const e = createEngine({
    heroes: [hero("甲"), hero("乙"), hero("丙")],
    counters: [["甲", "乙", 2]],
    synergies: [["乙", "丙", 1]],
    settings: {},
  });
  assert.equal(e.getCounter("甲", "乙"), 2);
  assert.equal(e.getCounter("乙", "甲"), -2);
  assert.equal(e.getSynergy("丙", "乙"), 1);
  assert.equal(e.getCounter("甲", "丙"), 0);
  assert.equal(e.getSynergy("甲", "乙"), 0);
});

test("settings fall back to defaults", () => {
  const e = createEngine({ heroes: [], counters: [], synergies: [], settings: { w_risk: 2 } });
  assert.equal(e.settings.w_risk, 2);
  assert.equal(e.settings.w_tier, DEFAULT_SETTINGS.w_tier);
});

// ---------------------------------------------------------------- pick scoring

test("heroes that would clash on lanes are excluded", () => {
  const e = createEngine({
    heroes: [hero("打野A", { 打野: "T0" }), hero("打野B", { 打野: "T0" }), hero("中路C", { 中路: "T2" })],
    counters: [], synergies: [], settings: {},
  });
  const r = e.pickSuggestions(state({ picksUs: ["打野A"] }));
  assert.deepEqual(r.suggestions.map((s) => s.name), ["中路C"]);
  assert.deepEqual(r.openLanes.us, ["凱撒", "中路", "魔龍", "輔助"]);
});

test("if every candidate clashes, nothing is filtered", () => {
  const e = createEngine({
    heroes: [hero("A", { 打野: "T0" }), hero("B", { 打野: "T1" }), hero("C", { 打野: "T2" })],
    counters: [], synergies: [], settings: {},
  });
  const r = e.pickSuggestions(state({ picksUs: ["A"] }));
  assert.deepEqual(r.suggestions.map((s) => s.name), ["B", "C"]);
  assert.deepEqual(r.suggestions[0].lanes, []);
});

test("tier uses the best lane the hero can still fill", () => {
  const e = createEngine({
    heroes: [hero("我打野", { 打野: "T2" }), hero("彈性", { 打野: "T0", 凱撒: "T2" })],
    counters: [], synergies: [], settings: {},
  });
  const free = find(e.pickSuggestions(state()), "彈性");
  assert.equal(free.pros[0].text, "T0 打野");
  assert.equal(free.pros[0].value, 3);
  const blocked = find(e.pickSuggestions(state({ picksUs: ["我打野"] })), "彈性");
  assert.deepEqual(blocked.lanes, ["凱撒"]);
  assert.deepEqual(blocked.pros, [{ text: "T2 凱撒", value: 1 }]);
});

test("counter and synergy are summed over every picked hero, one line each", () => {
  const e = createEngine({
    heroes: [
      hero("候選", { 中路: null }),
      hero("敵1", { 打野: null }), hero("敵2", { 凱撒: null }), hero("敵3", { 魔龍: null }),
      hero("友1", { 輔助: null }), hero("友2", { 魔龍: null }),
    ],
    counters: [["候選", "敵1", 1], ["候選", "敵2", 2], ["敵3", "候選", 1]],
    synergies: [["候選", "友1", 1], ["候選", "友2", 2]],
    settings: { w_synergy: 0.5 },
  });
  const s = find(e.pickSuggestions(state({ picksUs: ["友1", "友2"], picksThem: ["敵1", "敵2", "敵3"] })), "候選");
  const texts = Object.fromEntries([...s.pros, ...s.cons].map((i) => [i.text, i.value]));
  assert.equal(texts["剋制 敵1"], 1);
  assert.equal(texts["超剋 敵2"], 2);
  assert.equal(texts["被 敵3 剋"], -1);
  assert.equal(texts["與 友1 好搭"], 0.5);
  assert.equal(texts["與 友2 超好搭"], 1);
  assert.ok(close(s.score, 1 + 2 - 1 + 0.5 + 1));
});

test("risk grows with the number of enemy picks remaining", () => {
  const e = createEngine({
    heroes: [
      hero("候選", { 中路: "T1" }), hero("剋星", { 中路: null }),
      hero("敵A", { 打野: null }), hero("敵B", { 凱撒: null }), hero("敵C", { 輔助: null }),
    ],
    counters: [["剋星", "候選", 2]],
    synergies: [], settings: {},
  });
  const risk = (picksThem) => find(e.pickSuggestions(state({ picksThem })), "候選")
    .cons.find((c) => c.text === "對方仍可選 剋星 反制")?.value ?? 0;
  const early = risk([]);
  const late = risk(["敵A", "敵B", "敵C"]);
  assert.ok(close(early, -0.5 * 1 * 2));
  assert.ok(close(late, -0.5 * (2 / 5) * 2));
  assert.ok(early < late, "more remaining enemy picks => bigger penalty");
});

test("threats must be able to fill an enemy open lane", () => {
  const e = createEngine({
    heroes: [
      hero("候選", { 中路: "T1" }), hero("剋星", { 打野: null }), hero("敵打野", { 打野: null }),
    ],
    counters: [["剋星", "候選", 1]],
    synergies: [], settings: {},
  });
  const before = find(e.pickSuggestions(state()), "候選");
  assert.ok(before.cons.some((c) => c.text === "對方仍可選 剋星 反制"));
  const after = find(e.pickSuggestions(state({ picksThem: ["敵打野"] })), "候選");
  assert.ok(!after.cons.some((c) => c.text.includes("剋星")));
});

test("deny: taking a hero the enemy could use against our picks", () => {
  const e = createEngine({
    heroes: [hero("我方", { 中路: null }), hero("威脅", { 打野: "T2" })],
    counters: [["威脅", "我方", 2]],
    synergies: [], settings: {},
  });
  const s = find(e.pickSuggestions(state({ picksUs: ["我方"] })), "威脅");
  assert.deepEqual(s.pros.find((p) => p.text.startsWith("搶角")), { text: "搶角：避免對方用來剋 我方", value: 1 });
});

test("unfilled heroes are flagged and treated as any lane, unrated", () => {
  const e = createEngine({
    heroes: [hero("空白"), hero("有路", { 打野: "T0" })],
    counters: [], synergies: [], settings: {},
  });
  const s = find(e.pickSuggestions(state({ picksUs: ["有路"] })), "空白");
  assert.deepEqual(s.lanes, ["凱撒", "中路", "魔龍", "輔助"]);
  assert.deepEqual(s.cons, [{ text: UNFILLED_NOTE, value: 0 }]);
  assert.equal(s.score, 0);
});

test("output: every pickable hero, valid pros/cons, score = sum", () => {
  const e = createEngine({
    heroes: [
      hero("A", { 打野: "T0", 凱撒: "T1" }), hero("B", { 中路: "T1" }), hero("C", { 魔龍: "T2" }),
      hero("D", { 輔助: null }), hero("E"), hero("F", { 中路: "T0" }), hero("G", { 打野: "T1" }),
    ],
    counters: [["A", "B", 1], ["C", "A", 2], ["F", "G", -1], ["E", "D", 1]],
    synergies: [["A", "D", 2]],
    settings: {},
  });
  const st = state({ bansUs: ["G"], bansThem: ["E"], picksUs: ["D"], picksThem: ["B"] });
  const r = e.pickSuggestions(st);
  assert.deepEqual(r.suggestions.map((s) => s.name).sort(), ["A", "C", "F"]);
  checkInvariants(r);
});

// ---------------------------------------------------------------- ban scoring

test("ban: banned and picked heroes never appear", () => {
  const e = createEngine({
    heroes: [hero("A", { 打野: "T0" }), hero("B", { 中路: "T1" }), hero("C"), hero("D")],
    counters: [], synergies: [], settings: {},
  });
  const r = e.banSuggestions(state({ bansUs: ["A"], picksThem: ["B"] }));
  assert.deepEqual(r.suggestions.map((s) => s.name).sort(), ["C", "D"]);
  checkInvariants(r);
});

test("ban: max tier plus threat to our picks", () => {
  const e = createEngine({
    heroes: [hero("我方", { 中路: null }), hero("強", { 打野: "T0" }), hero("剋我", { 凱撒: "T2", 打野: "T1" })],
    counters: [["剋我", "我方", 2]],
    synergies: [], settings: {},
  });
  const r = e.banSuggestions(state({ picksUs: ["我方"] }));
  assert.deepEqual(r.suggestions.map((s) => s.name), ["剋我", "強"]);
  assert.deepEqual(find(r, "剋我").pros, [{ text: "T1 打野", value: 2 }, { text: "超剋我方 我方", value: 2 }]);
  checkInvariants(r);
});

// ---------------------------------------------------------------- form groups

const formData = () => ({
  heroes: [
    hero("元流之子(法師)", { 中路: "T0" }, { form_group: "元流之子" }),
    hero("元流之子(射手)", { 魔龍: "T0" }, { form_group: "元流之子" }),
    hero("候選", { 打野: "T1" }),
    hero("敵", { 凱撒: null }),
  ],
  counters: [["元流之子(射手)", "候選", 1], ["元流之子(法師)", "候選", 1]],
  synergies: [], settings: {},
});

test("form groups: banning one form leaves the other pickable", () => {
  const e = createEngine(formData());
  const st = state({ bansThem: ["元流之子(法師)"] });
  assert.equal(e.isPickable("元流之子(法師)", st), false);
  assert.equal(e.isPickable("元流之子(射手)", st), true);
});

test("form groups: picking one form blocks the other for both sides, but it can still be banned", () => {
  const e = createEngine(formData());
  for (const st of [state({ picksUs: ["元流之子(法師)"] }), state({ picksThem: ["元流之子(法師)"] })]) {
    assert.equal(e.isPickable("元流之子(射手)", st), false);
    assert.ok(!e.pickSuggestions(st).suggestions.some((s) => s.name === "元流之子(射手)"));
    const ban = e.banSuggestions(st);
    const blocked = find(ban, "元流之子(射手)");
    assert.ok(blocked, "still listed for banning");
    assert.equal(blocked.score, 0);
    assert.equal(blocked.blocked, true);
    assert.equal(ban.suggestions.at(-1).name, "元流之子(射手)", "sorted last");
  }
});

test("form groups: unpickable forms are not counted as threats", () => {
  const e = createEngine(formData());
  const free = find(e.pickSuggestions(state()), "候選");
  assert.equal(free.cons.filter((c) => c.text.startsWith("對方仍可選")).length, 2);
  const st = state({ picksUs: ["元流之子(法師)"] });
  const s = find(e.pickSuggestions(st), "候選");
  assert.ok(!s.cons.some((c) => c.text.includes("元流之子")));
});

test("form groups: a candidate's own sibling form is not its threat", () => {
  const data = formData();
  data.counters = [["元流之子(射手)", "元流之子(法師)", 1]];
  const e = createEngine(data);
  const s = find(e.pickSuggestions(state()), "元流之子(法師)");
  assert.ok(!s.cons.some((c) => c.text.includes("元流之子(射手)")));
});

test("unknown names in state are ignored", () => {
  const e = createEngine(formData());
  const r = e.pickSuggestions(state({ picksUs: ["不存在"], bansThem: ["也不存在"] }));
  assert.equal(r.suggestions.length, 4);
});

// ---------------------------------------------------------------- user-chosen lanes

test("a chosen lane pins a picked hero for matching and open lanes", () => {
  const e = createEngine({
    heroes: [
      hero("彈性", { 打野: "T0", 凱撒: "T1" }),
      hero("打野候選", { 打野: "T1" }),
      hero("凱撒候選", { 凱撒: "T1" }),
    ],
    counters: [], synergies: [], settings: {},
  });
  // Automatic: 彈性 can move, so both candidates still fit.
  const auto = e.pickSuggestions(state({ picksUs: ["彈性"] }));
  assert.deepEqual(auto.suggestions.map((s) => s.name).sort(), ["凱撒候選", "打野候選"]);
  assert.deepEqual(auto.openLanes.us, ["凱撒", "打野", "中路", "魔龍", "輔助"]);

  // User says 彈性 plays 打野: the jungle candidate now clashes.
  const pinned = e.pickSuggestions(state({ picksUs: ["彈性"], lanesUs: { 彈性: "打野" } }));
  assert.deepEqual(pinned.suggestions.map((s) => s.name), ["凱撒候選"]);
  assert.deepEqual(pinned.openLanes.us, ["凱撒", "中路", "魔龍", "輔助"]);
  assert.deepEqual(e.openLanes(state({ picksUs: ["彈性"], lanesUs: { 彈性: "打野" } })).us,
    ["凱撒", "中路", "魔龍", "輔助"]);
});

test("a chosen lane may be outside the hero's usual lanes; invalid choices are ignored", () => {
  const e = createEngine({
    heroes: [hero("輔助王", { 輔助: "T0" }), hero("另一輔助", { 輔助: "T1" })],
    counters: [], synergies: [], settings: {},
  });
  const offMeta = e.pickSuggestions(state({ picksUs: ["輔助王"], lanesUs: { 輔助王: "中路" } }));
  assert.deepEqual(offMeta.suggestions.map((s) => s.name), ["另一輔助"]);
  assert.deepEqual(offMeta.suggestions[0].lanes, ["輔助"]);

  const bogus = e.openLanes(state({ picksUs: ["輔助王"], lanesUs: { 輔助王: "亂打", 沒選: "中路" } }));
  assert.deepEqual(bogus.us, ["凱撒", "打野", "中路", "魔龍"]);
});

test("enemy lane choices narrow the threats that can still come", () => {
  const e = createEngine({
    heroes: [
      hero("候選", { 中路: "T1" }), hero("剋星", { 打野: null }),
      hero("敵", { 打野: null, 凱撒: null }),
    ],
    counters: [["剋星", "候選", 1]],
    synergies: [], settings: {},
  });
  const risk = (lanesThem) => find(e.pickSuggestions(state({ picksThem: ["敵"], lanesThem })), "候選")
    .cons.some((c) => c.text.includes("剋星"));
  assert.equal(risk({}), true, "敵 could move to 凱撒, so 剋星 can still jungle");
  assert.equal(risk({ 敵: "打野" }), false, "敵 pinned to 打野: 剋星 has no lane left");
});
