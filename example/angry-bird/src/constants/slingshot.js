import { EPISODE_LEVEL_IDS } from './scoring.js';

export const SLINGSHOT = {
  clampRadius: 120,
  launchPower: 0.18,
  tapDeadZone: 8,
  tapMaxMs: 250,
  forwardDragDeadZone: 6,
  aimDotCount: 16,
  aimSampleStep: 1 / 30,
  trajectoryGravityPerSecond: 360,
  trajectoryVelocityScale: 63.75,
  matterGravityScale: 0.00036,
  settleSpeed: 0.35,
  settleDelayMs: 500,
  minSettleFlightMs: 1000,
  maxFlightMs: 8000,
  offWorldDelayMs: 2000
};

export const SLINGSHOT_ART = {
  texture: 'slingshot',
  width: 108,
  height: 155,
  originY: 0.355,
  leftTip: { x: -42, y: -55 },
  rightTip: { x: 42, y: -55 }
};

const KNOWN_LEVEL_IDS = new Set(Object.values(EPISODE_LEVEL_IDS).flat());

export const BIRD_VISUALS = {
  red: { texture: 'bird-red', radius: 24 },
  blues: { texture: 'bird-blues', radius: 18 },
  chuck: { texture: 'bird-chuck', radius: 22 },
  matilda: { texture: 'bird-matilda', radius: 24 },
  bomb: { texture: 'bird-bomb', radius: 26 },
  hal: { texture: 'bird-hal', radius: 24 }
};

const LEVEL_SLINGSHOT_CONFIGS = {
  '1-01': {
    anchor: { x: 210, y: 548 },
    groundY: 648,
    levelWidth: 1280,
    queue: ['red', 'red', 'red']
  },
  '1-05': {
    anchor: { x: 210, y: 548 },
    groundY: 648,
    levelWidth: 1800,
    queue: ['blues', 'blues', 'blues', 'blues', 'blues']
  },
  '2-02': {
    anchor: { x: 230, y: 430 },
    groundY: 648,
    levelWidth: 1500,
    queue: ['chuck', 'chuck', 'chuck', 'red']
  },
  '2-04': {
    anchor: { x: 230, y: 430 },
    groundY: 648,
    levelWidth: 1800,
    queue: ['red', 'blues', 'chuck', 'bomb']
  },
  '3-04': {
    anchor: { x: 230, y: 400 },
    groundY: 648,
    levelWidth: 1500,
    queue: ['hal', 'hal', 'hal']
  },
  '3-05': {
    anchor: { x: 230, y: 430 },
    groundY: 648,
    levelWidth: 1800,
    queue: ['matilda', 'bomb', 'matilda', 'chuck', 'blues', 'red']
  }
};

export function resolveSlingshotLevelConfig(levelId = '1-01') {
  const config = LEVEL_SLINGSHOT_CONFIGS[levelId] ?? LEVEL_SLINGSHOT_CONFIGS['1-01'];
  const resolvedId = LEVEL_SLINGSHOT_CONFIGS[levelId] || KNOWN_LEVEL_IDS.has(levelId)
    ? levelId
    : '1-01';

  return {
    id: resolvedId,
    anchor: { ...config.anchor },
    groundY: config.groundY,
    levelWidth: config.levelWidth,
    queue: config.queue.map((type) => ({ type }))
  };
}
