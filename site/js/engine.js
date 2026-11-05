// Recommendation engine. Pure functions: no DOM, no fetch.
// app.js loads data.json and calls createEngine(data).

import { LANES, feasible, fillableLanes, openLanes } from "./matching.js";

export { LANES };

export const DEFAULT_SETTINGS = {
  w_tier: 1.0,
  w_counter: 1.0,
  w_synergy: 0.7,
  w_risk: 0.5,
  w_deny: 0.5,
  w_ban_threat: 1.0,
  tier_T0: 3,
  tier_T1: 2,
  tier_T2: 1,
  tier_none: 0,
};

export const UNFILLED_NOTE = "分路資料未填";

const pairKey = (a, b) => `${a}\u0000${b}`;

/** Keep only lane choices for heroes that are actually picked, with valid lane names. */
function cleanLaneChoices(choices, picks) {
  const result = {};
  for (const name of picks) {
    const lane = choices?.[name];
    if (LANES.includes(lane)) result[name] = lane;
  }
  return result;
}

/** Drop unknown names and duplicates so stale session state cannot break scoring. */
function normalizeState(state, heroes) {
  const clean = (list) => [...new Set((list || []).filter((n) => heroes.has(n)))];
  const picksUs = clean(state.picksUs);
  const picksThem = clean(state.picksThem);
  return {
    side: state.side === "red" ? "red" : "blue",
    bansUs: clean(state.bansUs),
    bansThem: clean(state.bansThem),
    picksUs,
    picksThem,
    // Optional user-chosen lanes for picked heroes: { name: lane }.
    lanesUs: cleanLaneChoices(state.lanesUs, picksUs),
    lanesThem: cleanLaneChoices(state.lanesThem, picksThem),
  };
}

function byValueDesc(a, b) {
  return b.value - a.value;
}

function byValueAsc(a, b) {
  return a.value - b.value;
}

function sortSuggestions(list) {
  return list.sort((a, b) =>
    (a.blocked ? 1 : 0) - (b.blocked ? 1 : 0) ||
    b.score - a.score ||
    (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
}

function finish(name, lanes, pros, cons, extra = {}) {
  pros.sort(byValueDesc);
  cons.sort(byValueAsc);
  const score = [...pros, ...cons].reduce((sum, item) => sum + item.value, 0);
  return { name, score, lanes, pros, cons, ...extra };
}

export function createEngine(data) {
  const heroes = new Map(data.heroes.map((h) => [h.name, h]));
  const settings = { ...DEFAULT_SETTINGS, ...(data.settings || {}) };

  const counters = new Map();
  for (const [a, b, v] of data.counters || []) {
    counters.set(pairKey(a, b), v);
    counters.set(pairKey(b, a), -v);
  }
  const synergies = new Map();
  for (const [a, b, v] of data.synergies || []) {
    synergies.set(pairKey(a, b), v);
    synergies.set(pairKey(b, a), v);
  }

  /** >0: x counters y; <0: y counters x; 0 when unknown. */
  const getCounter = (x, y) => counters.get(pairKey(x, y)) || 0;
  const getSynergy = (x, y) => synergies.get(pairKey(x, y)) || 0;

  const hasLaneData = (name) => Object.keys(heroes.get(name)?.lanes || {}).length > 0;
  /** Lanes a hero can play; unfilled heroes may play any lane. */
  const lanesOf = (name) => (hasLaneData(name) ? Object.keys(heroes.get(name).lanes) : LANES);
  /** Lane options of picked heroes; a user-chosen lane pins the hero to that lane. */
  const laneLists = (names, choices = {}) => names.map((n) => (choices[n] ? [choices[n]] : lanesOf(n)));

  function tierValue(name, lane) {
    const tier = heroes.get(name)?.lanes?.[lane];
    return tier ? settings[`tier_${tier}`] ?? settings.tier_none : settings.tier_none;
  }

  function tierLabel(name, lane) {
    if (!hasLaneData(name)) return "未評（分路未填）";
    return `${heroes.get(name).lanes[lane] || "未評"} ${lane}`;
  }

  /** Best (lane, value) among `lanes`, preferring the earlier lane on ties. */
  function bestTier(name, lanes) {
    let best = null;
    for (const lane of lanes) {
      const value = tierValue(name, lane);
      if (!best || value > best.value) best = { lane, value };
    }
    return best;
  }

  function formGroup(name) {
    return heroes.get(name)?.form_group || null;
  }

  function isPickable(name, state) {
    if (!heroes.has(name)) return false;
    const taken = [...state.bansUs, ...state.bansThem, ...state.picksUs, ...state.picksThem];
    if (taken.includes(name)) return false;
    const group = formGroup(name);
    if (!group) return true;
    return ![...state.picksUs, ...state.picksThem].some((p) => formGroup(p) === group);
  }

  function counterText(target, value) {
    if (value > 0) return value >= 2 ? `超剋 ${target}` : `剋制 ${target}`;
    return value <= -2 ? `被 ${target} 完剋` : `被 ${target} 剋`;
  }

  function synergyText(ally, value) {
    if (value > 0) return value >= 2 ? `與 ${ally} 超好搭` : `與 ${ally} 好搭`;
    return `與 ${ally} 難搭`;
  }

  function openLanesOf(state) {
    const s = normalizeState(state, heroes);
    return {
      us: openLanes(laneLists(s.picksUs, s.lanesUs)),
      them: openLanes(laneLists(s.picksThem, s.lanesThem)),
    };
  }

  /** Pick suggestions for our next pick: every pickable hero, best first. */
  function pickSuggestions(rawState) {
    const state = normalizeState(rawState, heroes);
    const { picksUs: us, picksThem: them } = state;
    const usLanes = laneLists(us, state.lanesUs);
    const themLanes = laneLists(them, state.lanesThem);
    const enemyRemaining = Math.max(0, 5 - them.length);
    const w = settings;

    const pickable = [...heroes.keys()].filter((n) => isPickable(n, state));
    const fitsUs = pickable.filter((n) => feasible([...usLanes, lanesOf(n)]));
    const candidates = fitsUs.length ? fitsUs : pickable;

    // Heroes the enemy could still pick into an open lane (independent of the candidate).
    const enemyCanPick = new Set(
      pickable.filter((x) => enemyRemaining > 0 && fillableLanes(lanesOf(x), themLanes).length > 0),
    );

    const suggestions = candidates.map((h) => {
      const pros = [];
      const cons = [];
      const lanes = fillableLanes(lanesOf(h), usLanes);

      const tier = bestTier(h, lanes.length ? lanes : lanesOf(h));
      const tierScore = w.w_tier * tier.value;
      if (tierScore > 0) pros.push({ text: tierLabel(h, tier.lane), value: tierScore });
      else if (tierScore < 0) cons.push({ text: tierLabel(h, tier.lane), value: tierScore });

      for (const e of them) {
        const c = getCounter(h, e);
        const value = w.w_counter * c;
        if (value > 0) pros.push({ text: counterText(e, c), value });
        else if (value < 0) cons.push({ text: counterText(e, c), value });
      }

      for (const a of us) {
        const s = getSynergy(h, a);
        const value = w.w_synergy * s;
        if (value > 0) pros.push({ text: synergyText(a, s), value });
        else if (value < 0) cons.push({ text: synergyText(a, s), value });
      }

      // Picking h makes its other forms unpickable, so they are not threats.
      const group = formGroup(h);
      for (const x of enemyCanPick) {
        if (x === h || (group && formGroup(x) === group)) continue;
        const c = getCounter(x, h);
        if (c <= 0) continue;
        const value = -w.w_risk * (enemyRemaining / 5) * c;
        if (value < 0) cons.push({ text: `對方仍可選 ${x} 反制`, value });
      }

      if (enemyCanPick.has(h)) {
        for (const a of us) {
          const value = w.w_deny * Math.max(0, getCounter(h, a));
          if (value > 0) pros.push({ text: `搶角：避免對方用來剋 ${a}`, value });
        }
      }

      if (!hasLaneData(h)) cons.push({ text: UNFILLED_NOTE, value: 0 });
      return finish(h, lanes, pros, cons);
    });

    return {
      suggestions: sortSuggestions(suggestions),
      openLanes: { us: openLanes(usLanes), them: openLanes(themLanes) },
    };
  }

  /** Ban suggestions: every hero not yet banned or picked, best first. */
  function banSuggestions(rawState) {
    const state = normalizeState(rawState, heroes);
    const taken = new Set([...state.bansUs, ...state.bansThem, ...state.picksUs, ...state.picksThem]);
    const w = settings;

    const suggestions = [...heroes.keys()]
      .filter((h) => !taken.has(h))
      .map((h) => {
        const pros = [];
        const cons = [];
        const ownLanes = hasLaneData(h) ? lanesOf(h) : [];
        // Another form of this hero was picked: it can never be picked, so banning is pointless.
        if (!isPickable(h, state)) {
          return finish(h, ownLanes, pros, [{ text: "同英雄的其他型態已被選", value: 0 }], { blocked: true });
        }

        const tier = bestTier(h, lanesOf(h));
        const tierScore = w.w_tier * tier.value;
        if (tierScore > 0) pros.push({ text: tierLabel(h, tier.lane), value: tierScore });
        else if (tierScore < 0) cons.push({ text: tierLabel(h, tier.lane), value: tierScore });

        for (const a of state.picksUs) {
          const c = Math.max(0, getCounter(h, a));
          const value = w.w_ban_threat * c;
          if (value > 0) pros.push({ text: `${c >= 2 ? "超剋" : "剋制"}我方 ${a}`, value });
        }

        if (!hasLaneData(h)) cons.push({ text: UNFILLED_NOTE, value: 0 });
        return finish(h, ownLanes, pros, cons, { blocked: false });
      });

    return { suggestions: sortSuggestions(suggestions) };
  }

  return {
    heroes,
    settings,
    exportedAt: data.exported_at || null,
    getCounter,
    getSynergy,
    lanesOf,
    hasLaneData,
    /** Lane options for a team's picks, honouring user-chosen lanes. */
    teamLaneLists: laneLists,
    tierValue,
    isPickable: (name, state) => isPickable(name, normalizeState(state, heroes)),
    openLanes: openLanesOf,
    pickSuggestions,
    banSuggestions,
  };
}
