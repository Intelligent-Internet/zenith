import { describe, expect, it } from 'vitest';

import {
  AFFINITY_BENCHMARK_BIRD_TYPES,
  BIRD_MATERIAL_AFFINITY,
  BOMB_EXPLOSION_MATERIAL_AFFINITY,
  BENCHMARK_BLOCK_MATERIALS
} from '../../src/constants/birds.js';
import {
  BLOCK_MATERIALS
} from '../../src/constants/materials.js';
import { createMaterialAffinityBench } from '../../src/systems/affinityBench.js';
import { registerDebugScene } from '../../src/systems/debug.js';

function fakeScene(key = 'Game') {
  return {
    sys: {
      settings: { key },
      game: {
        scene: {
          keys: { Game: {} }
        }
      }
    },
    scene: { key }
  };
}

describe('bird material affinity matrix', () => {
  it('matches the normalized matrix from library/birds.md', () => {
    expect(BIRD_MATERIAL_AFFINITY).toStrictEqual({
      red: { wood: 1, glass: 1, stone: 0.5 },
      blues: { wood: 0.5, glass: 1, stone: 0.15 },
      chuck: { wood: 1, glass: 0.4, stone: 0.4 },
      matilda: { wood: 1, glass: 1, stone: 1 },
      bomb: { wood: 0.5, glass: 0.5, stone: 1 },
      hal: { wood: 1, glass: 1, stone: 0.04 }
    });
    expect(BOMB_EXPLOSION_MATERIAL_AFFINITY).toStrictEqual({
      wood: 2,
      glass: 2,
      stone: 1.5
    });
  });

  it('runs every bird/material pair through the benchmark fixture', () => {
    const bench = createMaterialAffinityBench({ directImpulse: 10 });
    const results = {};

    AFFINITY_BENCHMARK_BIRD_TYPES.forEach((birdType) => {
      results[birdType] = {};
      BENCHMARK_BLOCK_MATERIALS.forEach((material) => {
        results[birdType][material] = bench.run(birdType, material);
      });
    });

    expect(Object.keys(results)).toHaveLength(6);
    expect(Object.values(results).flatMap((row) => Object.values(row))).toHaveLength(18);
    expect(results.chuck.wood.hpDelta).toBeGreaterThanOrEqual(results.chuck.stone.hpDelta * 2);
    expect(results.bomb.stone.hpDelta).toBeGreaterThanOrEqual(results.bomb.wood.hpDelta * 2);
    expect(results.hal.wood.hpDelta).toBeGreaterThanOrEqual(results.hal.stone.hpDelta * 20);
    expect(results.hal.glass.hpDelta).toBeGreaterThanOrEqual(results.hal.stone.hpDelta * 5);
    expect(results.blues.glass.hpDelta).toBeGreaterThanOrEqual(results.blues.stone.hpDelta * 5);
    expect(results.matilda.wood.hpDelta).toBe(BLOCK_MATERIALS.wood.hp);
    expect(results.matilda.glass.hpDelta).toBe(BLOCK_MATERIALS.glass.hp);
    expect(results.matilda.stone.hpDelta).toBe(BLOCK_MATERIALS.stone.hp);
  });

  it('keeps benchmark deltas numeric, finite, and capped by material HP', () => {
    const bench = createMaterialAffinityBench({ directImpulse: 10 });

    AFFINITY_BENCHMARK_BIRD_TYPES.forEach((birdType) => {
      BENCHMARK_BLOCK_MATERIALS.forEach((material) => {
        const result = bench.run(birdType, material);

        expect(Number.isFinite(result.damage)).toBe(true);
        expect(Number.isFinite(result.hpDelta)).toBe(true);
        expect(result.hpDelta).toBeGreaterThanOrEqual(0);
        expect(result.hpDelta).toBeLessThanOrEqual(BLOCK_MATERIALS[material].hp);
      });
    });
  });

  it('destroys adjacent stone with one point-blank Bomb explosion trigger', () => {
    const bench = createMaterialAffinityBench();
    const result = bench.run('bomb', 'stone', { trigger: 'bomb-explosion', distancePx: 0 });

    expect(result.destroyed).toBe(true);
    expect(result.initialHp).toBe(BLOCK_MATERIALS.stone.hp);
    expect(result.hpDelta).toBe(BLOCK_MATERIALS.stone.hp);
    expect(result.remainingHp).toBe(0);
    expect(result.damage).toBeGreaterThanOrEqual(BLOCK_MATERIALS.stone.hp);
  });

  it('destroys healthy wood with one full-power Chuck speed burst hit', () => {
    const bench = createMaterialAffinityBench();
    const result = bench.run('chuck', 'wood', { trigger: 'chuck-speed-burst' });

    expect(result.destroyed).toBe(true);
    expect(result.initialHp).toBe(BLOCK_MATERIALS.wood.hp);
    expect(result.hpDelta).toBe(BLOCK_MATERIALS.wood.hp);
    expect(result.remainingHp).toBe(0);
    expect(result.damage).toBeGreaterThanOrEqual(BLOCK_MATERIALS.wood.hp);
  });

  it('exposes the fixture through the dev-only __GAME__ debug hook', () => {
    const target = {};

    const state = registerDebugScene(fakeScene(), {}, {
      env: { ANGRY_BIRD_DEV: '1' },
      target
    });

    expect(state.debug.bench.run).toBeTypeOf('function');
    expect(target.__GAME__.debug.bench.run('chuck', 'wood', {
      trigger: 'chuck-speed-burst'
    })).toMatchObject({
      birdType: 'chuck',
      material: 'wood',
      destroyed: true,
      remainingHp: 0
    });

    const productionTarget = {};
    registerDebugScene(fakeScene(), {}, { env: {}, target: productionTarget });
    expect(productionTarget.__GAME__).toBeUndefined();
  });
});
