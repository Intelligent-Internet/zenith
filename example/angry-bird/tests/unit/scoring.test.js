import { describe, expect, it } from 'vitest';

import {
  DEMO_HUD_SCORES,
  SCORING_POINTS,
  THEORETICAL_MAX_SCORES
} from '../../src/constants/scoring.js';
import {
  createFreshScoringSave,
  getEpisodeTotals,
  getStarCount,
  getStarThresholds,
  recordLevelClear,
  scoreForBlockDestroyed,
  scoreForPigDefeat
} from '../../src/systems/scoring.js';

describe('scoring point values', () => {
  it('awards exactly 5,000 per pig defeat', () => {
    expect(SCORING_POINTS.pigDefeated).toBe(5000);
    expect(scoreForPigDefeat()).toBe(5000);
  });

  it('keeps block destruction points in strict material order', () => {
    const wood = scoreForBlockDestroyed('wood');
    const glass = scoreForBlockDestroyed('glass');
    const stone = scoreForBlockDestroyed('stone');

    expect(wood).toBe(200);
    expect(glass).toBe(400);
    expect(stone).toBe(800);
    expect(wood).toBeLessThan(glass);
    expect(glass).toBeLessThan(stone);
  });
});

describe('star thresholds', () => {
  it('pins every 3-star threshold to the demo HUD score within contract bounds', () => {
    Object.entries(DEMO_HUD_SCORES).forEach(([levelId, demoScore]) => {
      const thresholds = getStarThresholds(levelId);

      expect(thresholds.threeStar).toBe(demoScore);
      expect(thresholds.threeStar).toBeGreaterThanOrEqual(demoScore * 0.8);
      expect(thresholds.threeStar).toBeLessThanOrEqual(demoScore * 1.2);
      expect(thresholds.threeStar).toBeLessThanOrEqual(THEORETICAL_MAX_SCORES[levelId]);
    });
  });

  it('derives 1-star and 2-star thresholds from fixed 0.50 and 0.75 ratios', () => {
    const thresholds = getStarThresholds('2-02');

    expect(thresholds.oneStar).toBeCloseTo(thresholds.threeStar * 0.5, 5);
    expect(thresholds.twoStar).toBeCloseTo(thresholds.threeStar * 0.75, 5);
    expect(thresholds.oneStar).toBeLessThan(thresholds.twoStar);
    expect(thresholds.twoStar).toBeLessThan(thresholds.threeStar);
  });

  it('calculates the ordinal star count from score and level id', () => {
    const thresholds = getStarThresholds('1-01');

    expect(getStarCount(thresholds.oneStar - 1, '1-01')).toBe(0);
    expect(getStarCount(thresholds.oneStar, '1-01')).toBe(1);
    expect(getStarCount(thresholds.twoStar, '1-01')).toBe(2);
    expect(getStarCount(thresholds.threeStar - 1, '1-01')).toBe(2);
    expect(getStarCount(thresholds.threeStar, '1-01')).toBe(3);
  });
});

describe('best-score save math', () => {
  it('never lowers best score or stars and updates them independently', () => {
    const fresh = createFreshScoringSave();
    const firstClear = recordLevelClear(fresh, {
      levelId: '1-01',
      score: 18000,
      stars: 1
    });
    const secondClear = recordLevelClear(firstClear, {
      levelId: '1-01',
      score: 33000,
      stars: 3
    });
    const thirdClear = recordLevelClear(secondClear, {
      levelId: '1-01',
      score: 25000,
      stars: 2
    });
    const independentStars = recordLevelClear({
      ...thirdClear,
      bestScore: { ...thirdClear.bestScore, '1-02': 50000 },
      bestStars: { ...thirdClear.bestStars, '1-02': 1 }
    }, {
      levelId: '1-02',
      score: 30000,
      stars: 3
    });

    expect(thirdClear.bestScore['1-01']).toBe(33000);
    expect(thirdClear.bestStars['1-01']).toBe(3);
    expect(independentStars.bestScore['1-02']).toBe(50000);
    expect(independentStars.bestStars['1-02']).toBe(3);
  });

  it('sums episode totals from best clear scores and stars only', () => {
    const save = {
      schemaVersion: 1,
      cleared: ['1-01', '1-03', '2-01'],
      bestScore: {
        '1-01': 33000,
        '1-03': 1000,
        '2-01': 99999
      },
      bestStars: {
        '1-01': 3,
        '1-03': 2,
        '2-01': 3
      },
      mute: false
    };

    expect(getEpisodeTotals(save, 1)).toEqual({
      score: 34000,
      stars: 5,
      maxStars: 15
    });
  });
});
