import { describe, expect, it } from 'vitest';

import {
  BLOCK_MATERIALS,
  PIG_DEFEAT_SCORE,
  PIG_TIERS
} from '../../src/constants/materials.js';
import {
  SettleStateMachine,
  applyDamageToHp,
  calculateCollisionDamage,
  calculateStructuralCollapseRadius,
  crossesStructuralCollapseThreshold
} from '../../src/systems/physics.js';

describe('physics damage rules', () => {
  it('keeps glass weaker than wood and wood weaker than stone', () => {
    expect(BLOCK_MATERIALS.glass.hp).toBeLessThan(BLOCK_MATERIALS.wood.hp);
    expect(BLOCK_MATERIALS.wood.hp).toBeLessThan(BLOCK_MATERIALS.stone.hp);
  });

  it('lets one Blues body shatter glass at a light launch impulse', () => {
    const damage = calculateCollisionDamage({
      relativeImpulseMagnitude: 12,
      birdType: 'blues',
      material: 'glass'
    });

    expect(damage).toBeGreaterThanOrEqual(BLOCK_MATERIALS.glass.hp);
  });

  it('keeps a full-power Red impact from destroying healthy stone', () => {
    const damage = calculateCollisionDamage({
      relativeImpulseMagnitude: 24,
      birdType: 'red',
      material: 'stone'
    });

    expect(damage).toBeLessThan(BLOCK_MATERIALS.stone.hp);
  });

  it('applies cumulative damage without regenerating HP', () => {
    const firstHit = applyDamageToHp(BLOCK_MATERIALS.wood.hp, 11);
    const secondHit = applyDamageToHp(firstHit.remainingHp, 12);

    expect(firstHit.remainingHp).toBe(19);
    expect(secondHit.remainingHp).toBe(7);
    expect(secondHit.destroyed).toBe(false);
  });

  it('awards exactly 5,000 points for every pig tier', () => {
    expect(PIG_DEFEAT_SCORE).toBe(5000);
    expect(Object.values(PIG_TIERS).map((tier) => tier.score)).toEqual([5000, 5000, 5000]);
  });

  it('lets a destroyed long roof threaten pigs standing under its span', () => {
    const radius = calculateStructuralCollapseRadius({ width: 430, height: 24 }, 26);

    expect(radius).toBeGreaterThan(Math.hypot(168, 34));
  });

  it('lets a destroyed column threaten an adjacent sheltered pig', () => {
    const radius = calculateStructuralCollapseRadius({ width: 32, height: 92 }, 26);

    expect(radius).toBeGreaterThan(150);
  });

  it('lets a destroyed tower floor threaten a ground pig beside the tower', () => {
    const radius = calculateStructuralCollapseRadius({ width: 270, height: 22 }, 26);

    expect(radius).toBeGreaterThan(Math.hypot(278, 66));
  });

  it('treats major support damage as a collapse hazard once it crosses 75% HP', () => {
    expect(crossesStructuralCollapseThreshold({
      previousHp: 30,
      remainingHp: 22,
      maxHp: 30
    })).toBe(true);
    expect(crossesStructuralCollapseThreshold({
      previousHp: 22,
      remainingHp: 20,
      maxHp: 30
    })).toBe(false);
  });
});

describe('settle state machine', () => {
  it('settles after every dynamic body stays below 5 px/s for 0.5 seconds', () => {
    const settle = new SettleStateMachine();

    settle.markLaunched(0);

    expect(settle.update(0, [4.9, 0])).toMatchObject({ settled: false });
    expect(settle.update(499, [4.9, 0])).toMatchObject({ settled: false });
    expect(settle.update(500, [4.9, 0])).toMatchObject({
      settled: true,
      reason: 'all-bodies-still'
    });
  });

  it('restarts the still timer when any body rises above the settle speed', () => {
    const settle = new SettleStateMachine();

    settle.markLaunched(0);
    settle.update(0, [4]);
    settle.update(400, [6]);

    expect(settle.update(800, [4])).toMatchObject({ settled: false });
    expect(settle.update(1300, [4])).toMatchObject({
      settled: true,
      reason: 'all-bodies-still'
    });
  });

  it('settles at the hard 8 second timeout even while bodies are moving', () => {
    const settle = new SettleStateMachine();

    settle.markLaunched(100);

    expect(settle.update(8099, [9])).toMatchObject({ settled: false });
    expect(settle.update(8100, [9])).toMatchObject({
      settled: true,
      reason: 'timeout'
    });
  });
});
