import { describe, expect, it } from 'vitest';

import { loadLevelConfig } from '../../src/systems/levelLoader.js';

describe('level 1-05 data', () => {
  it('defines Poached Eggs 1-10 as the wide Blues twin glass-pyramid debut', () => {
    const level = loadLevelConfig('1-05');

    expect(level.id).toBe('1-05');
    expect(level.name).toBe('Poached Eggs 1-10');
    expect(level.levelWidth).toBeGreaterThan(1280);
    expect(level.cameraWide).toBe(true);
    expect(level.slingshotElevated).toBe(false);
    expect(level.queue.map((entry) => entry.type)).toEqual([
      'blues',
      'blues',
      'blues',
      'blues',
      'blues'
    ]);
    expect(level.tntCrates).toEqual([]);
    expect(level.boulders).toEqual([]);

    expect(level.pigs).toHaveLength(2);
    expect(level.pigs.every((pig) => pig.tier === 'small')).toBe(true);

    expect(level.mounds).toHaveLength(2);
    expect(level.mounds[0].x).toBeLessThan(level.mounds[1].x);
    expect(level.mounds[0].height).toBeLessThan(level.mounds[1].height);
    expect(level.mounds.every((mound) => mound.y === level.groundY)).toBe(true);

    const glassBlocks = level.blocks.filter((block) => block.material === 'glass');
    expect(glassBlocks).toHaveLength(level.blocks.length);
    expect(glassBlocks.length).toBeGreaterThanOrEqual(18);

    const leftMound = level.mounds[0];
    const rightMound = level.mounds[1];
    expect(level.pigs[0].x).toBeGreaterThan(leftMound.x - leftMound.width / 2);
    expect(level.pigs[0].x).toBeLessThan(leftMound.x + leftMound.width / 2);
    expect(level.pigs[0].y).toBeLessThan(leftMound.y);
    expect(level.pigs[1].x).toBeGreaterThan(rightMound.x - rightMound.width / 2);
    expect(level.pigs[1].x).toBeLessThan(rightMound.x + rightMound.width / 2);
    expect(level.pigs[1].y).toBeLessThan(rightMound.y);

    const leftGlass = glassBlocks.filter((block) => block.x < (leftMound.x + rightMound.x) / 2);
    const rightGlass = glassBlocks.filter((block) => block.x > (leftMound.x + rightMound.x) / 2);
    expect(leftGlass.length).toBeGreaterThanOrEqual(6);
    expect(rightGlass.length).toBeGreaterThan(leftGlass.length);
    expect(Math.min(...rightGlass.map((block) => block.y))).toBeLessThan(
      Math.min(...leftGlass.map((block) => block.y))
    );

    [
      { pig: level.pigs[0], blocks: leftGlass },
      { pig: level.pigs[1], blocks: rightGlass }
    ].forEach(({ pig, blocks }) => {
      const topGlassY = Math.min(...blocks.map((block) => block.y));
      const topColumnBlocks = blocks.filter((block) => block.y === topGlassY);
      const centerColumnX = topColumnBlocks.reduce(
        (total, block) => total + block.x,
        0
      ) / topColumnBlocks.length;

      expect(Math.abs(pig.x - centerColumnX)).toBeLessThanOrEqual(20);
      expect(pig.y).toBeLessThan(topGlassY);
    });

    expect(level.blocks.some((block) => (
      block.material === 'glass'
      && block.angle !== 0
    ))).toBe(true);
  });
});
