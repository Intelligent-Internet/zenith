import {
  AFFINITY_BENCHMARK_BIRD_TYPES,
  BENCHMARK_BLOCK_MATERIALS,
  CHUCK_SPEED_BURST_MULTIPLIER,
  MATERIAL_AFFINITY_BENCHMARK
} from '../constants/birds.js';
import {
  BLOCK_MATERIALS,
  BOMB_EXPLOSION
} from '../constants/materials.js';
import { SLINGSHOT } from '../constants/slingshot.js';
import {
  applyDamageToHp,
  calculateBombExplosionFalloff,
  calculateCollisionDamage
} from './physics.js';

function finiteNonNegative(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(0, number) : fallback;
}

function assertKnownBirdType(birdType) {
  if (!AFFINITY_BENCHMARK_BIRD_TYPES.includes(birdType)) {
    throw new Error(`Unknown affinity benchmark bird type: ${birdType}`);
  }
}

function assertKnownMaterial(material) {
  if (!BENCHMARK_BLOCK_MATERIALS.includes(material)) {
    throw new Error(`Unknown affinity benchmark material: ${material}`);
  }
}

function resolveTrigger(options = {}) {
  return options.trigger ?? options.mode ?? 'collision';
}

function calculateFullPowerChuckBurstImpulse() {
  return SLINGSHOT.clampRadius
    * SLINGSHOT.launchPower
    * CHUCK_SPEED_BURST_MULTIPLIER;
}

function calculateBenchmarkDamage({
  birdType,
  material,
  trigger,
  options
}) {
  if (trigger === 'bomb-explosion') {
    const distancePx = finiteNonNegative(options.distancePx);
    const falloff = calculateBombExplosionFalloff(distancePx);

    return {
      damage: BOMB_EXPLOSION.baseBlockDamage
        * (BOMB_EXPLOSION.materialMultiplier[material] ?? 1)
        * falloff,
      impulse: 0,
      falloff,
      distancePx
    };
  }

  if (trigger === 'chuck-speed-burst') {
    const impulse = finiteNonNegative(
      options.relativeImpulseMagnitude,
      calculateFullPowerChuckBurstImpulse()
    );

    return {
      damage: calculateCollisionDamage({
        relativeImpulseMagnitude: impulse,
        birdType: 'chuck',
        material
      }),
      impulse,
      falloff: null,
      distancePx: null
    };
  }

  if (trigger !== 'collision') {
    throw new Error(`Unknown affinity benchmark trigger: ${trigger}`);
  }

  if (birdType === 'matilda') {
    return {
      damage: BLOCK_MATERIALS[material].hp,
      impulse: 0,
      falloff: null,
      distancePx: null
    };
  }

  const impulse = finiteNonNegative(
    options.relativeImpulseMagnitude,
    options.directImpulse ?? MATERIAL_AFFINITY_BENCHMARK.equalImpulseMagnitude
  );

  return {
    damage: calculateCollisionDamage({
      relativeImpulseMagnitude: impulse,
      birdType,
      material
    }),
    impulse,
    falloff: null,
    distancePx: null
  };
}

export function runMaterialAffinityBenchmark(birdType, material, options = {}) {
  assertKnownBirdType(birdType);
  assertKnownMaterial(material);

  const trigger = resolveTrigger(options);
  const initialHp = BLOCK_MATERIALS[material].hp;
  const {
    damage,
    impulse,
    falloff,
    distancePx
  } = calculateBenchmarkDamage({
    birdType,
    material,
    trigger,
    options
  });
  const result = applyDamageToHp(initialHp, damage);

  return {
    birdType,
    material,
    trigger,
    initialHp,
    damage,
    hpDelta: initialHp - result.remainingHp,
    remainingHp: result.remainingHp,
    destroyed: result.destroyed,
    impulse,
    falloff,
    distancePx
  };
}

export function createMaterialAffinityBench(defaultOptions = {}) {
  return {
    birds: AFFINITY_BENCHMARK_BIRD_TYPES,
    materials: BENCHMARK_BLOCK_MATERIALS,
    run(birdType, material, options = {}) {
      return runMaterialAffinityBenchmark(birdType, material, {
        ...defaultOptions,
        ...options
      });
    }
  };
}
