export const SCORING_POINTS = {
  pigDefeated: 5000,
  unusedBirdBonus: 10000,
  tntTriggered: 1000,
  blockDestroyed: {
    wood: 200,
    glass: 400,
    stone: 800
  }
};

export const STAR_RATIOS = {
  oneStar: 0.5,
  twoStar: 0.75,
  threeStar: 1
};

export const DEMO_HUD_SCORES = {
  '1-01': 33000,
  '1-02': 42060,
  '1-03': 64760,
  '1-04': 45780,
  '1-05': 55300,
  '2-01': 62100,
  '2-02': 56690,
  '2-03': 57310,
  '2-04': 100450,
  '2-05': 54830,
  '3-01': 63650,
  '3-02': 73870,
  '3-03': 78160,
  '3-04': 69540,
  '3-05': 92350
};

export const THREE_STAR_THRESHOLDS = { ...DEMO_HUD_SCORES };

export const EPISODE_LEVEL_IDS = {
  1: ['1-01', '1-02', '1-03', '1-04', '1-05'],
  2: ['2-01', '2-02', '2-03', '2-04', '2-05'],
  3: ['3-01', '3-02', '3-03', '3-04', '3-05']
};

export const MAX_EPISODE_STARS = 15;

export const THEORETICAL_MAX_SCORES = Object.fromEntries(
  Object.entries(THREE_STAR_THRESHOLDS).map(([levelId, threshold]) => [levelId, threshold])
);
