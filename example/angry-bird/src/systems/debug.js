import { createMaterialAffinityBench } from './affinityBench.js';

export const DEFAULT_SCENE_KEYS = [
  'Boot',
  'Preloader',
  'Menu',
  'DebugRoster',
  'EpisodeSelect',
  'LevelSelect',
  'Game',
  'PauseOverlay',
  'GameOver',
  'ClearedCard',
  'FailedCard'
];

const DEFAULT_SLINGSHOT = {
  clampRadius: 0,
  anchor: { x: 0, y: 0 }
};
const DEFAULT_BENCH = createMaterialAffinityBench();

export function resolveDebugEnabled(env = import.meta.env) {
  return Boolean(env?.ANGRY_BIRD_DEV);
}

function freshSave(mute = false) {
  return {
    schemaVersion: 1,
    cleared: [],
    bestScore: {},
    bestStars: {},
    mute
  };
}

function normalizeAudio(audio = {}, mute = false) {
  return {
    lastEvent: audio.lastEvent ?? null,
    lastAbilityEvent: audio.lastAbilityEvent ?? null,
    muted: audio.muted ?? mute,
    paused: Boolean(audio.paused),
    recentEvents: Array.isArray(audio.recentEvents) ? audio.recentEvents.slice(-64) : []
  };
}

function getSceneKey(scene) {
  return scene?.sys?.settings?.key ?? scene?.scene?.key ?? 'Unknown';
}

function getRegisteredSceneKeys(scene) {
  const keys = scene?.sys?.game?.scene?.keys;
  return keys ? Object.keys(keys) : DEFAULT_SCENE_KEYS;
}

function appendSceneHistory(history, key) {
  const nextHistory = Array.isArray(history) ? [...history] : [];
  if (nextHistory[nextHistory.length - 1] !== key) {
    nextHistory.push(key);
  }
  return nextHistory;
}

function buildRosterRenderer(scene) {
  return () => {
    if (scene?.scene?.start && getRegisteredSceneKeys(scene).includes('DebugRoster')) {
      scene.scene.start('DebugRoster');
      return true;
    }

    if (!scene?.add) {
      return false;
    }

    const overlay = scene.add.container(640, 360)
      .setDepth(1000)
      .setName('debug-roster');
    overlay.add(scene.add.rectangle(0, 0, 760, 260, 0x17212b, 0.9));
    overlay.add(scene.add.text(0, -62, 'Debug Roster', {
      fontFamily: 'Arial, sans-serif',
      fontSize: '30px',
      color: '#ffffff'
    }).setOrigin(0.5));
    overlay.add(scene.add.text(0, 18, 'red  blues  chuck  matilda  bomb  hal\nwood  glass  stone blocks + particles\nsmall  medium  large  helmeted pigs', {
      fontFamily: 'Arial, sans-serif',
      fontSize: '20px',
      color: '#f8d24a',
      align: 'center'
    }).setOrigin(0.5));

    return true;
  };
}

export function createDebugState({
  key,
  previousState,
  sceneKeys = DEFAULT_SCENE_KEYS,
  scene = {},
  mute = false,
  save,
  audio,
  slingshot = DEFAULT_SLINGSHOT,
  showRoster = () => false,
  bench = DEFAULT_BENCH
}) {
  const score = scene.score ?? 0;
  const birdsLeft = scene.birdsLeft ?? 0;
  const pigsLeft = scene.pigsLeft ?? 0;
  const settled = scene.settled ?? false;
  const normalizedAudio = normalizeAudio(audio, mute);
  const normalizedSave = save ?? freshSave(mute);

  return {
    scene: {
      key,
      score,
      birdsLeft,
      pigsLeft,
      settled,
      queue: scene.queue ?? [],
      flyingBird: scene.flyingBird ?? null,
      bird: scene.bird ?? null,
      slingshot: scene.slingshot ?? slingshot,
      aimTrail: scene.aimTrail ?? [],
      renderedQueue: scene.renderedQueue ?? [],
      paused: scene.paused ?? false,
      levelId: scene.levelId ?? null,
      tntCrates: scene.tntCrates ?? [],
      boulders: scene.boulders ?? [],
      mounds: scene.mounds ?? [],
      platforms: scene.platforms ?? [],
      cameraWide: scene.cameraWide ?? false,
      slingshotElevated: scene.slingshotElevated ?? false,
      ground: scene.ground ?? null,
      cameras: scene.cameras ?? null,
      threeStarThreshold: scene.threeStarThreshold ?? {},
      endCard: scene.endCard ?? null,
      blocks: scene.blocks ?? [],
      pigs: scene.pigs ?? [],
      eggs: scene.eggs ?? [],
      physics: scene.physics ?? null,
      lastResolveReason: scene.lastResolveReason ?? null,
      lastSettleReason: scene.lastSettleReason ?? null,
      lastPigDefeatReason: scene.lastPigDefeatReason ?? null,
      lastMatildaEggExplosion: scene.lastMatildaEggExplosion ?? null,
      lastMatildaBlockContact: scene.lastMatildaBlockContact ?? null,
      lastBombExplosion: scene.lastBombExplosion ?? null,
      lastTntExplosion: scene.lastTntExplosion ?? null,
      lastBombWoodContact: scene.lastBombWoodContact ?? null
    },
    score,
    birdsLeft,
    pigsLeft,
    settled,
    mute,
    audio: normalizedAudio,
    save: normalizedSave,
    debug: {
      sceneHistory: appendSceneHistory(previousState?.debug?.sceneHistory, key),
      sceneKeys,
      showRoster,
      bench,
      slingshot
    }
  };
}

export function registerDebugScene(scene, fields = {}, options = {}) {
  const env = options.env ?? import.meta.env;
  if (!resolveDebugEnabled(env)) {
    return null;
  }

  const target = options.target ?? globalThis.window;
  if (!target) {
    return null;
  }

  const key = getSceneKey(scene);
  const sceneFields = fields.scene ?? fields;
  const mute = fields.mute ?? fields.save?.mute ?? false;
  const nextState = createDebugState({
    key,
    previousState: target.__GAME__,
    sceneKeys: fields.sceneKeys ?? getRegisteredSceneKeys(scene),
    scene: sceneFields,
    mute,
    save: fields.save,
    audio: fields.audio,
    slingshot: fields.slingshot ?? sceneFields.slingshot ?? DEFAULT_SLINGSHOT,
    showRoster: fields.showRoster ?? buildRosterRenderer(scene),
    bench: fields.bench ?? target.__GAME__?.debug?.bench ?? DEFAULT_BENCH
  });

  target.__GAME__ = nextState;
  return nextState;
}
