export const AFFINITY_BENCHMARK_BIRD_TYPES = Object.freeze([
  'red',
  'blues',
  'chuck',
  'matilda',
  'bomb',
  'hal'
]);

export const BENCHMARK_BLOCK_MATERIALS = Object.freeze([
  'wood',
  'glass',
  'stone'
]);

export const CHUCK_SPEED_BURST_MULTIPLIER = 2.5;

export const BIRD_MATERIAL_AFFINITY = Object.freeze({
  red: { wood: 1, glass: 1, stone: 0.5 },
  blues: { wood: 0.5, glass: 1, stone: 0.15 },
  chuck: { wood: 1, glass: 0.4, stone: 0.4 },
  matilda: { wood: 1, glass: 1, stone: 1 },
  bomb: { wood: 0.5, glass: 0.5, stone: 1 },
  hal: { wood: 1, glass: 1, stone: 0.04 }
});

export const BOMB_EXPLOSION_MATERIAL_AFFINITY = Object.freeze({
  wood: 2,
  glass: 2,
  stone: 1.5
});

export const MATERIAL_AFFINITY_BENCHMARK = Object.freeze({
  equalImpulseMagnitude: 10
});
