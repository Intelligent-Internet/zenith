import {
  EPISODE_LEVEL_IDS,
  MAX_EPISODE_STARS,
  SCORING_POINTS,
  STAR_RATIOS,
  THREE_STAR_THRESHOLDS
} from '../constants/scoring.js';

export function scoreForPigDefeat() {
  return SCORING_POINTS.pigDefeated;
}

export function scoreForBlockDestroyed(material) {
  const score = SCORING_POINTS.blockDestroyed[material];
  if (score === undefined) {
    throw new Error(`Unknown block material score: ${material}`);
  }

  return score;
}

export function getStarThresholds(levelId) {
  const threeStar = THREE_STAR_THRESHOLDS[levelId];
  if (threeStar === undefined) {
    throw new Error(`Unknown scoring level id: ${levelId}`);
  }

  return {
    oneStar: threeStar * STAR_RATIOS.oneStar,
    twoStar: threeStar * STAR_RATIOS.twoStar,
    threeStar
  };
}

export function getStarCount(score, levelId) {
  const safeScore = Math.max(0, Number(score) || 0);
  const thresholds = getStarThresholds(levelId);

  if (safeScore >= thresholds.threeStar) {
    return 3;
  }

  if (safeScore >= thresholds.twoStar) {
    return 2;
  }

  if (safeScore >= thresholds.oneStar) {
    return 1;
  }

  return 0;
}

export function getClearStarCount(score, levelId) {
  return Math.max(1, getStarCount(score, levelId));
}

export function createFreshScoringSave(mute = false) {
  return {
    schemaVersion: 1,
    cleared: [],
    bestScore: {},
    bestStars: {},
    mute
  };
}

function normalizeSave(save = {}) {
  return {
    schemaVersion: 1,
    cleared: Array.isArray(save.cleared) ? [...save.cleared] : [],
    bestScore: { ...(save.bestScore ?? {}) },
    bestStars: { ...(save.bestStars ?? {}) },
    mute: Boolean(save.mute)
  };
}

function normalizeStars(stars) {
  return Math.max(0, Math.min(3, Math.floor(Number(stars) || 0)));
}

export function recordLevelClear(save, {
  levelId,
  score,
  stars = getClearStarCount(score, levelId)
}) {
  if (THREE_STAR_THRESHOLDS[levelId] === undefined) {
    throw new Error(`Unknown scoring level id: ${levelId}`);
  }

  const nextSave = normalizeSave(save);
  const safeScore = Math.max(0, Math.floor(Number(score) || 0));
  const safeStars = normalizeStars(stars);
  const previousScore = Number(nextSave.bestScore[levelId]) || 0;
  const previousStars = Number(nextSave.bestStars[levelId]) || 0;

  nextSave.bestScore[levelId] = Math.max(previousScore, safeScore);
  nextSave.bestStars[levelId] = Math.max(previousStars, safeStars);

  if (!nextSave.cleared.includes(levelId)) {
    nextSave.cleared.push(levelId);
  }

  return nextSave;
}

export function getEpisodeTotals(save, episode) {
  const normalizedSave = normalizeSave(save);
  const levelIds = EPISODE_LEVEL_IDS[episode];
  if (!levelIds) {
    throw new Error(`Unknown episode: ${episode}`);
  }

  return levelIds.reduce((totals, levelId) => ({
    score: totals.score + (Number(normalizedSave.bestScore[levelId]) || 0),
    stars: totals.stars + normalizeStars(normalizedSave.bestStars[levelId]),
    maxStars: MAX_EPISODE_STARS
  }), {
    score: 0,
    stars: 0,
    maxStars: MAX_EPISODE_STARS
  });
}
