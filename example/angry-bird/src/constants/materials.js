import {
  ABILITY_SFX,
  MATERIAL_BREAK_SFX,
  MATERIAL_IMPACT_SFX,
  PHYSICS_SFX
} from './audio.js';
import { SCORING_POINTS } from './scoring.js';
import {
  BIRD_MATERIAL_AFFINITY,
  BOMB_EXPLOSION_MATERIAL_AFFINITY
} from './birds.js';

export const PIG_DEFEAT_SCORE = SCORING_POINTS.pigDefeated;
export { BIRD_MATERIAL_AFFINITY, BOMB_EXPLOSION_MATERIAL_AFFINITY };

export const BLOCK_MATERIALS = {
  wood: {
    hp: 30,
    restitution: 0.2,
    density: 0.0008,
    score: SCORING_POINTS.blockDestroyed.wood,
    texture: 'block-wood',
    particleKey: 'particle-wood-splinter',
    particleCount: 12,
    particleLifespanMs: 600,
    impactSfx: MATERIAL_IMPACT_SFX.wood,
    breakSfx: MATERIAL_BREAK_SFX.wood
  },
  glass: {
    hp: 12,
    restitution: 0.05,
    density: 0.0006,
    score: SCORING_POINTS.blockDestroyed.glass,
    texture: 'block-glass',
    particleKey: 'particle-glass-shard',
    particleCount: 18,
    particleLifespanMs: 800,
    impactSfx: MATERIAL_IMPACT_SFX.glass,
    breakSfx: MATERIAL_BREAK_SFX.glass
  },
  stone: {
    hp: 80,
    restitution: 0.1,
    density: 0.0015,
    score: SCORING_POINTS.blockDestroyed.stone,
    texture: 'block-stone',
    particleKey: 'particle-stone-rubble',
    particleCount: 10,
    particleLifespanMs: 700,
    impactSfx: MATERIAL_IMPACT_SFX.stone,
    breakSfx: MATERIAL_BREAK_SFX.stone
  }
};

export const PIG_TIERS = {
  small: {
    hp: 10,
    radius: 26,
    texture: 'pig-small',
    score: PIG_DEFEAT_SCORE
  },
  medium: {
    hp: 25,
    radius: 34,
    texture: 'pig-medium',
    score: PIG_DEFEAT_SCORE
  },
  large: {
    hp: 50,
    radius: 42,
    texture: 'pig-large',
    score: PIG_DEFEAT_SCORE
  }
};

export const ENVIRONMENT_MATERIAL_AFFINITY = {
  wood: 0.35,
  glass: 0.5,
  stone: 0.25
};

export const PIG_PARTICLE = {
  key: 'particle-pig-puff',
  count: 14,
  lifespanMs: 550
};

export const BOULDER = {
  hp: 200,
  radius: 36,
  material: 'stone',
  texture: 'boulder-stone',
  score: SCORING_POINTS.blockDestroyed.stone,
  restitution: 0.12,
  density: 0.004,
  friction: 0.4,
  frictionAir: 0.0015,
  particleKey: BLOCK_MATERIALS.stone.particleKey,
  particleCount: BLOCK_MATERIALS.stone.particleCount,
  particleLifespanMs: BLOCK_MATERIALS.stone.particleLifespanMs
};

export const MATILDA_EGG_EXPLOSION = {
  particleKey: 'particle-matilda-egg-pop',
  particleCount: 16,
  particleLifespanMs: 520,
  audioEvent: 'sfx-matilda-egg-explode'
};

export const BOMB_EXPLOSION = {
  audioEvent: ABILITY_SFX.bomb,
  autoDelayMs: 1000,
  radiusPx: 132,
  radialImpulse: 12,
  baseBlockDamage: 80,
  pigDamage: 60,
  minDamageFalloff: 0.45,
  materialMultiplier: BOMB_EXPLOSION_MATERIAL_AFFINITY,
  particleKey: 'particle-smoke',
  particleCount: 24,
  particleLifespanMs: 700,
  woodSpeedLossFactor: 0.05
};

export const TNT_EXPLOSION = {
  hp: 1,
  width: 52,
  height: 52,
  texture: 'tnt-crate',
  score: SCORING_POINTS.tntTriggered,
  audioEvent: PHYSICS_SFX.tntExplosion,
  radiusPx: 132,
  chainDelayMs: 50,
  radialImpulse: 9,
  blockDamage: {
    wood: BLOCK_MATERIALS.wood.hp,
    glass: BLOCK_MATERIALS.glass.hp,
    stone: 40
  },
  pigDamage: 999,
  particleKey: BOMB_EXPLOSION.particleKey,
  particleCount: 22,
  particleLifespanMs: 680
};
