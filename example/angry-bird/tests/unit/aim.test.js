import { describe, expect, it } from 'vitest';

import {
  clampDragVector,
  computeLaunchVelocity,
  predictTrajectory
} from '../../src/utils/aim.js';

const ANCHOR = { x: 220, y: 520 };
const CLAMP_RADIUS = 120;
const POWER = 0.18;

function magnitude(vector) {
  return Math.hypot(vector.x, vector.y);
}

describe('aim utilities', () => {
  it('keeps a half-radius drag unchanged', () => {
    const clamped = clampDragVector({ x: CLAMP_RADIUS * 0.5, y: 0 }, CLAMP_RADIUS);

    expect(clamped.x).toBeCloseTo(60, 5);
    expect(clamped.y).toBeCloseTo(0, 5);
    expect(clamped.clamped).toBe(false);
  });

  it('keeps an exact-radius drag unchanged', () => {
    const clamped = clampDragVector({ x: 0, y: -CLAMP_RADIUS }, CLAMP_RADIUS);

    expect(clamped.x).toBeCloseTo(0, 5);
    expect(clamped.y).toBeCloseTo(-120, 5);
    expect(clamped.distance).toBeCloseTo(CLAMP_RADIUS, 5);
  });

  it('clamps a double-radius drag to exactly one radius', () => {
    const clamped = clampDragVector({ x: CLAMP_RADIUS * 2, y: 0 }, CLAMP_RADIUS);

    expect(clamped.x).toBeCloseTo(CLAMP_RADIUS, 5);
    expect(clamped.y).toBeCloseTo(0, 5);
    expect(clamped.distance).toBeCloseTo(CLAMP_RADIUS, 5);
    expect(clamped.clamped).toBe(true);
  });

  it('launches opposite the drag vector', () => {
    const launch = computeLaunchVelocity({ x: 90, y: -60 }, {
      clampRadius: CLAMP_RADIUS,
      power: POWER
    });

    expect(launch.x).toBeCloseTo(-16.2, 5);
    expect(launch.y).toBeCloseTo(10.8, 5);
  });

  it('launch speed increases monotonically until clamp saturation', () => {
    const speeds = [30, 60, 120, 240].map((distance) => magnitude(computeLaunchVelocity(
      { x: -distance, y: 0 },
      { clampRadius: CLAMP_RADIUS, power: POWER }
    )));

    expect(speeds[0]).toBeLessThan(speeds[1]);
    expect(speeds[1]).toBeLessThanOrEqual(speeds[2]);
    expect(speeds[2]).toBeCloseTo(speeds[3], 1);
  });

  it('samples the predicted path at 1/30 second and keeps sample 8 within tolerance', () => {
    const launch = computeLaunchVelocity({ x: -100, y: -80 }, {
      clampRadius: CLAMP_RADIUS,
      power: POWER
    });
    const dots = predictTrajectory({
      origin: ANCHOR,
      velocity: launch,
      gravityPerSecond: 360,
      sampleCount: 16,
      sampleStep: 1 / 30
    });

    const t = 8 / 30;
    const expected = {
      x: ANCHOR.x + launch.x * 60 * t,
      y: ANCHOR.y + launch.y * 60 * t + 0.5 * 360 * t * t
    };

    expect(dots).toHaveLength(16);
    expect(dots[1].time).toBeCloseTo(1 / 30, 5);
    expect(dots[8].x).toBeCloseTo(expected.x, 0);
    expect(dots[8].y).toBeCloseTo(expected.y, 0);
    expect(Math.abs(dots[8].x - expected.x)).toBeLessThanOrEqual(20);
    expect(Math.abs(dots[8].y - expected.y)).toBeLessThanOrEqual(20);
  });
});
