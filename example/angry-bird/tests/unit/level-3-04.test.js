import { describe, expect, it } from 'vitest';

import { getEpisodeBackgroundKey } from '../../src/constants/assets.js';
import { SLINGSHOT } from '../../src/constants/slingshot.js';
import { loadLevelConfig } from '../../src/systems/levelLoader.js';
import { computeLaunchVelocity, predictTrajectory } from '../../src/utils/aim.js';

const VALIDATOR_RELEASE = { x: 110, y: 410 };
const BIRD_RADIUS = 24;
const PIG_RADIUS = 26;

function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
}

function getWoodStackMetrics(level) {
  const centerColumnPieces = level.blocks.filter((block) => (
    block.material === 'wood'
    && Math.abs(block.angle) <= 5
    && block.width >= 70
  ));
  const centerX = median(centerColumnPieces.map((block) => block.x));
  const stackPieces = level.blocks.filter((block) => (
    block.material === 'wood'
    && Math.abs(block.x - centerX) <= 120
  ));

  return {
    centerColumnPieces,
    centerX,
    minY: Math.min(...stackPieces.map((block) => block.y - block.height / 2))
  };
}

function predictedForwardYAt(level, worldX) {
  const dragVector = {
    x: VALIDATOR_RELEASE.x - level.anchor.x,
    y: VALIDATOR_RELEASE.y - level.anchor.y
  };
  const velocity = computeLaunchVelocity(dragVector, {
    clampRadius: SLINGSHOT.clampRadius,
    power: SLINGSHOT.launchPower
  });
  const samples = predictTrajectory({
    origin: {
      x: level.anchor.x + velocity.drag.x,
      y: level.anchor.y + velocity.drag.y
    },
    velocity,
    gravityPerSecond: SLINGSHOT.trajectoryGravityPerSecond,
    sampleCount: 24,
    sampleStep: SLINGSHOT.aimSampleStep,
    velocityScale: SLINGSHOT.trajectoryVelocityScale
  });
  const rightSample = samples.find((sample) => sample.x >= worldX);
  const rightIndex = samples.indexOf(rightSample);
  const leftSample = samples[Math.max(0, rightIndex - 1)];

  if (!leftSample || !rightSample || leftSample === rightSample) {
    return rightSample?.y ?? samples.at(-1).y;
  }

  const t = (worldX - leftSample.x) / (rightSample.x - leftSample.x);
  return leftSample.y + (rightSample.y - leftSample.y) * t;
}

describe('level 3-04 data', () => {
  it('defines Danger Above 6-5 as the elevated Hal boomerang debut', () => {
    const level = loadLevelConfig('3-04');

    expect(level.id).toBe('3-04');
    expect(level.name).toBe('Danger Above 6-5');
    expect(getEpisodeBackgroundKey(level.id)).toBe('bg-episode-3');
    expect(level.levelWidth).toBeGreaterThanOrEqual(1500);
    expect(level.cameraWide).toBe(true);
    expect(level.tntCrates).toEqual([]);
    expect(level.boulders).toEqual([]);

    expect(level.queue.map((entry) => entry.type)).toEqual(['hal', 'hal', 'hal']);
    expect(level.slingshotElevated).toBe(true);
    expect(level.groundY - level.anchor.y).toBeGreaterThanOrEqual(220);

    const slingWedge = level.mounds.find((mound) => (
      Math.abs(mound.x - level.anchor.x) <= 80
      && mound.width >= 320
      && mound.height >= 220
    ));
    expect(slingWedge).toBeDefined();

    const targetRamp = level.mounds.find((mound) => (
      mound.x > 760
      && mound.width >= 300
      && mound.height >= 250
    ));
    expect(targetRamp).toBeDefined();

    expect(level.pigs).toHaveLength(3);
    expect(level.pigs.every((pig) => pig.isStatic)).toBe(true);
    const pigXs = level.pigs.map((pig) => pig.x);
    expect(Math.max(...pigXs) - Math.min(...pigXs)).toBeLessThanOrEqual(110);
    expect(Math.min(...pigXs)).toBeGreaterThanOrEqual(540);
    expect(Math.max(...pigXs)).toBeLessThanOrEqual(650);

    const woodBoxStack = level.blocks.filter((block) => (
      block.material === 'wood'
      && block.x >= 460
      && block.x <= 1220
      && Math.abs(block.angle) <= 5
    ));
    const triangularFrame = level.blocks.filter((block) => (
      block.material === 'wood'
      && block.x >= 460
      && block.x <= 1230
      && Math.abs(block.angle) >= 25
      && Math.abs(block.angle) <= 65
    ));

    expect(woodBoxStack.length).toBeGreaterThanOrEqual(8);
    expect(triangularFrame.length).toBeGreaterThanOrEqual(3);
    expect(level.blocks.every((block) => block.material === 'wood')).toBe(true);
  });

  it('keeps every pig paired under the wood stack center column', () => {
    const level = loadLevelConfig('3-04');
    const stack = getWoodStackMetrics(level);

    expect(stack.centerColumnPieces.length).toBeGreaterThanOrEqual(4);

    level.pigs.forEach((pig) => {
      expect(Math.abs(pig.x - stack.centerX)).toBeLessThanOrEqual(100);
      expect(pig.y).toBeGreaterThan(stack.minY);
    });
  });

  it('blocks the validator straight Hal lane while leaving an off-lane pig pocket for the return arc', () => {
    const level = loadLevelConfig('3-04');
    const pigXs = level.pigs.map((pig) => pig.x);
    const rightmostPigX = Math.max(...pigXs);
    const directPigClearance = level.pigs.map((pig) => (
      Math.abs(pig.y - predictedForwardYAt(level, pig.x))
    ));

    expect(Math.min(...directPigClearance)).toBeGreaterThan(BIRD_RADIUS + PIG_RADIUS + 6);

    const blocker = level.platforms.find((platform) => {
      const left = platform.x - platform.width / 2;
      const top = platform.y - platform.height;
      const straightY = predictedForwardYAt(level, platform.x);

      return platform.x > rightmostPigX
        && left - rightmostPigX <= 360
        && platform.width >= 70
        && platform.height >= 240
        && top <= straightY + BIRD_RADIUS - 8;
    });

    expect(blocker).toBeDefined();
  });
});
