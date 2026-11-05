// Draft board state: slots, standard order, filling rules, persistence.
// Pure functions (no DOM). Slots are stored by team colour, so switching
// "our side" only changes the point of view, never the board contents.

export const TEAMS = ["blue", "red"];
export const SLOTS = 5;

/** Standard pick order: 藍1 → 紅2 → 藍2 → 紅2 → 藍2 → 紅1. */
export const PICK_ORDER = [
  ["blue", 0], ["red", 0], ["red", 1], ["blue", 1], ["blue", 2],
  ["red", 2], ["red", 3], ["blue", 3], ["blue", 4], ["red", 4],
].map(([team, index]) => ({ kind: "pick", team, index }));

/** Bans have no real order; alternate so the default active slot is predictable. */
export const BAN_ORDER = Array.from({ length: SLOTS * 2 }, (_, i) => ({
  kind: "ban", team: TEAMS[i % 2], index: Math.floor(i / 2),
}));

export const SEQUENCE = [...BAN_ORDER, ...PICK_ORDER];

export function emptyDraft() {
  const row = () => Array(SLOTS).fill(null);
  return { bans: { blue: row(), red: row() }, picks: { blue: row(), red: row() } };
}

export const other = (team) => (team === "blue" ? "red" : "blue");

export function sameSlot(a, b) {
  return !!a && !!b && a.kind === b.kind && a.team === b.team && a.index === b.index;
}

export function getSlot(draft, slot) {
  return (slot.kind === "ban" ? draft.bans : draft.picks)[slot.team][slot.index];
}

export function setSlot(draft, slot, name) {
  const key = slot.kind === "ban" ? "bans" : "picks";
  const next = {
    bans: { blue: [...draft.bans.blue], red: [...draft.bans.red] },
    picks: { blue: [...draft.picks.blue], red: [...draft.picks.red] },
  };
  next[key][slot.team][slot.index] = name;
  return next;
}

export function nextEmptySlot(draft) {
  return SEQUENCE.find((slot) => !getSlot(draft, slot)) || null;
}

/** 1-based global pick number of a pick slot (第 K 手). */
export function pickTurn(team, index) {
  return PICK_ORDER.findIndex((s) => s.team === team && s.index === index) + 1;
}

/** DraftState for the engine, seen from `side`. */
export function engineState(draft, side) {
  const filled = (list) => list.filter(Boolean);
  const them = other(side);
  return {
    side,
    bansUs: filled(draft.bans[side]),
    bansThem: filled(draft.bans[them]),
    picksUs: filled(draft.picks[side]),
    picksThem: filled(draft.picks[them]),
  };
}

export function allNames(draft) {
  return [...draft.bans.blue, ...draft.bans.red, ...draft.picks.blue, ...draft.picks.red].filter(Boolean);
}

/**
 * Can `name` go into `slot`? The slot's current occupant is ignored (it is being replaced).
 * Returns null when allowed, otherwise a user-facing reason.
 */
export function fillError(draft, slot, name, engine) {
  if (!engine.heroes.has(name)) return "找不到這隻英雄";
  const without = setSlot(draft, slot, null);
  if (allNames(without).includes(name)) return `${name} 已經被禁用或選走`;
  if (slot.kind === "pick" && !engine.isPickable(name, engineState(without, "blue"))) {
    return `${name} 的其他型態已經被選，不能再選`;
  }
  return null;
}

export function slotLabel(slot, side) {
  const who = slot.team === side ? "我方" : "敵方";
  if (slot.kind === "ban") return `${who}禁用 ${slot.index + 1}`;
  return `${who} ${slot.index + 1} 樓 · 第 ${pickTurn(slot.team, slot.index)} 手`;
}

// ---------------------------------------------------------------- persistence

/** Rebuild a valid draft from untrusted stored data, dropping unknown or duplicate names. */
export function sanitizeDraft(raw, heroNames) {
  const draft = emptyDraft();
  const seen = new Set();
  for (const slot of SEQUENCE) {
    const key = slot.kind === "ban" ? "bans" : "picks";
    const name = raw?.[key]?.[slot.team]?.[slot.index];
    if (typeof name === "string" && heroNames.has(name) && !seen.has(name)) {
      draft[key][slot.team][slot.index] = name;
      seen.add(name);
    }
  }
  return draft;
}

export function sanitizeSlot(raw) {
  if (!raw || !["ban", "pick"].includes(raw.kind) || !TEAMS.includes(raw.team)) return null;
  const index = Number(raw.index);
  return Number.isInteger(index) && index >= 0 && index < SLOTS ? { kind: raw.kind, team: raw.team, index } : null;
}
