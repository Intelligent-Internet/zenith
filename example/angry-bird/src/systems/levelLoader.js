import { resolveSlingshotLevelConfig } from '../constants/slingshot.js';
import { BOULDER, TNT_EXPLOSION } from '../constants/materials.js';
import level101 from '../data/levels/1-01.json';
import level102 from '../data/levels/1-02.json';
import level103 from '../data/levels/1-03.json';
import level104 from '../data/levels/1-04.json';
import level105 from '../data/levels/1-05.json';
import level201 from '../data/levels/2-01.json';
import level202 from '../data/levels/2-02.json';
import level203 from '../data/levels/2-03.json';
import level204 from '../data/levels/2-04.json';
import level205 from '../data/levels/2-05.json';
import level301 from '../data/levels/3-01.json';
import level302 from '../data/levels/3-02.json';
import level303 from '../data/levels/3-03.json';
import level304 from '../data/levels/3-04.json';
import level305 from '../data/levels/3-05.json';

const DEFAULT_LEVEL_ID = '1-01';
const LEVEL_DATA = {
  [level101.id]: level101,
  [level102.id]: level102,
  [level103.id]: level103,
  [level104.id]: level104,
  [level105.id]: level105,
  [level201.id]: level201,
  [level202.id]: level202,
  [level203.id]: level203,
  [level204.id]: level204,
  [level205.id]: level205,
  [level301.id]: level301,
  [level302.id]: level302,
  [level303.id]: level303,
  [level304.id]: level304,
  [level305.id]: level305
};
const BIRD_TYPES = new Set(['red', 'blues', 'chuck', 'matilda', 'bomb', 'hal']);
const BLOCK_MATERIALS = new Set(['wood', 'glass', 'stone']);
const PIG_TIERS = new Set(['small', 'medium', 'large']);

function toFiniteNumber(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function normalizeBirdQueue(rawQueue = [], levelId = DEFAULT_LEVEL_ID) {
  if (!Array.isArray(rawQueue) || rawQueue.length === 0) {
    throw new Error(`Level ${levelId} must define at least one bird`);
  }

  return rawQueue.map((entry, index) => {
    const type = typeof entry === 'string' ? entry : entry?.type;
    if (!BIRD_TYPES.has(type)) {
      throw new Error(`Level ${levelId} has unknown bird at queue index ${index}: ${type}`);
    }

    return { type };
  });
}

function normalizeBlock(block = {}, index = 0, levelId = DEFAULT_LEVEL_ID) {
  if (!BLOCK_MATERIALS.has(block.material)) {
    throw new Error(`Level ${levelId} has unknown block material at index ${index}: ${block.material}`);
  }

  return {
    material: block.material,
    x: toFiniteNumber(block.x, 0),
    y: toFiniteNumber(block.y, 0),
    width: toFiniteNumber(block.width, 88),
    height: toFiniteNumber(block.height, 88),
    angle: toFiniteNumber(block.angle, 0),
    isStatic: Boolean(block.isStatic)
  };
}

function normalizePig(pig = {}, index = 0, levelId = DEFAULT_LEVEL_ID) {
  if (!PIG_TIERS.has(pig.tier)) {
    throw new Error(`Level ${levelId} has unknown pig tier at index ${index}: ${pig.tier}`);
  }

  return {
    tier: pig.tier,
    x: toFiniteNumber(pig.x, 0),
    y: toFiniteNumber(pig.y, 0),
    isStatic: Boolean(pig.isStatic)
  };
}

function normalizeTntCrate(crate = {}) {
  return {
    x: toFiniteNumber(crate.x, 0),
    y: toFiniteNumber(crate.y, 0),
    hp: toFiniteNumber(crate.hp, TNT_EXPLOSION.hp),
    width: toFiniteNumber(crate.width, TNT_EXPLOSION.width),
    height: toFiniteNumber(crate.height, TNT_EXPLOSION.height),
    isStatic: Boolean(crate.isStatic)
  };
}

function normalizeBoulder(boulder = {}) {
  return {
    x: toFiniteNumber(boulder.x, 0),
    y: toFiniteNumber(boulder.y, 0),
    radius: toFiniteNumber(boulder.radius, BOULDER.radius),
    hp: toFiniteNumber(boulder.hp, BOULDER.hp),
    isStatic: Boolean(boulder.isStatic)
  };
}

function normalizeMound(mound = {}) {
  return {
    x: toFiniteNumber(mound.x, 0),
    y: toFiniteNumber(mound.y, 648),
    width: toFiniteNumber(mound.width, 300),
    height: toFiniteNumber(mound.height, 120)
  };
}

function normalizePlatform(platform = {}) {
  return {
    x: toFiniteNumber(platform.x, 0),
    y: toFiniteNumber(platform.y, 648),
    width: toFiniteNumber(platform.width, 240),
    height: toFiniteNumber(platform.height, 110)
  };
}

function parseUrlLevelId(search = '') {
  if (!search) {
    return null;
  }

  return new globalThis.URLSearchParams(search).get('level');
}

function normalizeLevelData(rawLevel, fallbackId = DEFAULT_LEVEL_ID) {
  const id = rawLevel?.id ?? fallbackId;
  const fallbackSlingshot = resolveSlingshotLevelConfig(id);
  const groundY = toFiniteNumber(rawLevel?.world?.groundY, fallbackSlingshot.groundY);
  const levelWidth = toFiniteNumber(rawLevel?.world?.width, fallbackSlingshot.levelWidth);
  const anchor = {
    x: toFiniteNumber(rawLevel?.slingshot?.anchor?.x, fallbackSlingshot.anchor.x),
    y: toFiniteNumber(rawLevel?.slingshot?.anchor?.y, fallbackSlingshot.anchor.y)
  };
  const queue = normalizeBirdQueue(rawLevel?.birds ?? rawLevel?.queue ?? fallbackSlingshot.queue, id);
  const blocks = (rawLevel?.blocks ?? []).map((block, index) => normalizeBlock(block, index, id));
  const pigs = (rawLevel?.pigs ?? []).map((pig, index) => normalizePig(pig, index, id));
  const tntCrates = (rawLevel?.tntCrates ?? rawLevel?.tnt ?? []).map(normalizeTntCrate);
  const boulders = (rawLevel?.boulders ?? []).map(normalizeBoulder);
  const mounds = (rawLevel?.mounds ?? []).map(normalizeMound);
  const platforms = (rawLevel?.platforms ?? []).map(normalizePlatform);
  const slingshotElevated = rawLevel?.slingshot?.elevated ?? anchor.y < groundY - 150;
  const cameraWide = levelWidth > 1280;

  return {
    id,
    name: rawLevel?.name ?? id,
    levelWidth,
    groundY,
    anchor,
    slingshot: { anchor: { ...anchor } },
    slingshotElevated,
    cameraWide,
    queue,
    blocks,
    pigs,
    tntCrates,
    boulders,
    mounds,
    platforms
  };
}

export function resolveLevelId({
  sceneData = {},
  search = typeof window === 'undefined' ? '' : window.location.search
} = {}) {
  return sceneData.levelConfig?.id
    ?? sceneData.levelData?.id
    ?? sceneData.level
    ?? sceneData.levelId
    ?? parseUrlLevelId(search)
    ?? DEFAULT_LEVEL_ID;
}

export function loadLevelConfig(levelId = DEFAULT_LEVEL_ID) {
  const id = levelId || DEFAULT_LEVEL_ID;
  const rawLevel = LEVEL_DATA[id];
  if (rawLevel) {
    return normalizeLevelData(rawLevel, rawLevel.id);
  }

  const fallbackSlingshot = resolveSlingshotLevelConfig(id);
  return normalizeLevelData({
    ...LEVEL_DATA[DEFAULT_LEVEL_ID],
    id: fallbackSlingshot.id,
    world: {
      width: fallbackSlingshot.levelWidth,
      groundY: fallbackSlingshot.groundY
    },
    slingshot: {
      anchor: fallbackSlingshot.anchor,
      elevated: fallbackSlingshot.anchor.y < fallbackSlingshot.groundY - 150
    },
    birds: fallbackSlingshot.queue.map((entry) => entry.type)
  }, fallbackSlingshot.id);
}

export function resolveLevelConfig({
  sceneData = {},
  search = typeof window === 'undefined' ? '' : window.location.search
} = {}) {
  if (sceneData.levelConfig || sceneData.levelData) {
    return normalizeLevelData(sceneData.levelConfig ?? sceneData.levelData, resolveLevelId({ sceneData, search }));
  }

  return loadLevelConfig(resolveLevelId({ sceneData, search }));
}
