import { describe, expect, it } from 'vitest';

import { loadLevelConfig } from '../../src/systems/levelLoader.js';

describe('level 1-03 data', () => {
  it('defines Poached Eggs 1-5 as a four-Red tall tower puzzle', () => {
    const level = loadLevelConfig('1-03');

    expect(level.id).toBe('1-03');
    expect(level.name).toBe('Poached Eggs 1-5');
    expect(level.levelWidth).toBe(1280);
    expect(level.cameraWide).toBe(false);
    expect(level.slingshotElevated).toBe(false);
    expect(level.queue.map((entry) => entry.type)).toEqual(['red', 'red', 'red', 'red']);
    expect(level.tntCrates).toEqual([]);

    expect(level.pigs).toHaveLength(4);
    expect(level.pigs.every((pig) => pig.tier === 'small')).toBe(true);
    expect(new Set(level.pigs.map((pig) => pig.x)).size).toBe(1);
    expect(level.pigs.map((pig) => pig.y)).toEqual(
      [...level.pigs.map((pig) => pig.y)].sort((a, b) => b - a)
    );

    const materials = new Set(level.blocks.map((block) => block.material));
    expect(materials).toEqual(new Set(['glass', 'wood', 'stone']));

    const glassWalls = level.blocks.filter((block) => (
      block.material === 'glass'
      && block.height >= 90
      && block.width <= 36
    ));
    expect(glassWalls.length).toBeGreaterThanOrEqual(6);
    expect(Math.max(...glassWalls.map((block) => block.x)) - Math.min(...glassWalls.map((block) => block.x)))
      .toBeGreaterThanOrEqual(110);

    const woodPlanks = level.blocks.filter((block) => (
      block.material === 'wood'
      && block.width >= 64
      && block.height <= 28
    ));
    expect(woodPlanks.length).toBeGreaterThanOrEqual(4);
    expect(woodPlanks.some((block) => block.y < level.pigs[3].y)).toBe(true);

    const stoneLegs = level.blocks.filter((block) => (
      block.material === 'stone'
      && block.height >= 120
      && block.width <= 42
    ));
    expect(stoneLegs).toHaveLength(2);

    expect(level.boulders).toEqual([
      expect.objectContaining({
        radius: expect.any(Number),
        isStatic: true
      })
    ]);
    expect(level.boulders[0].radius).toBeGreaterThanOrEqual(30);
    expect(level.boulders[0].x).toBe(level.pigs[0].x);
    expect(level.blocks).toContainEqual(expect.objectContaining({
      material: 'glass',
      x: level.boulders[0].x,
      y: expect.any(Number),
      width: expect.any(Number),
      height: expect.any(Number)
    }));
  });
});
