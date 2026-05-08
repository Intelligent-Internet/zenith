import { EPISODE_LEVEL_IDS, SCORING_POINTS } from '../constants/scoring.js';
import { getClearStarCount, recordLevelClear } from './scoring.js';

const LAST_EPISODE = 3;

function parseLevelId(levelId) {
  const [episodeText, levelText] = String(levelId).split('-');
  const episode = Number(episodeText);
  const levelNumber = Number(levelText);

  if (!Number.isInteger(episode) || !Number.isInteger(levelNumber)) {
    throw new Error(`Invalid level id: ${levelId}`);
  }

  return { episode, levelNumber };
}

function getEpisodeLevels(episode) {
  const levels = EPISODE_LEVEL_IDS[episode];
  if (!levels) {
    throw new Error(`Unknown episode: ${episode}`);
  }

  return levels;
}

function action(id, label, target, extra = {}) {
  return { id, label, target, ...extra };
}

export function resolveLevelOutcome({
  settled,
  pigsLeft,
  birdsLeft
}) {
  if (!settled) {
    return null;
  }

  if (Number(pigsLeft) <= 0) {
    return 'cleared';
  }

  if (Number(birdsLeft) <= 0) {
    return 'failed';
  }

  return null;
}

export function buildClearResult({
  levelId,
  baseScore,
  unusedBirdCount,
  save
}) {
  const safeBaseScore = Math.max(0, Math.floor(Number(baseScore) || 0));
  const safeUnusedBirdCount = Math.max(0, Math.floor(Number(unusedBirdCount) || 0));
  const bonus = safeUnusedBirdCount * SCORING_POINTS.unusedBirdBonus;
  const finalScore = safeBaseScore + bonus;
  const stars = getClearStarCount(finalScore, levelId);

  return {
    levelId,
    baseScore: safeBaseScore,
    unusedBirdCount: safeUnusedBirdCount,
    bonus,
    finalScore,
    stars,
    save: recordLevelClear(save, {
      levelId,
      score: finalScore,
      stars
    })
  };
}

export function getNextLevelId(levelId) {
  const { episode } = parseLevelId(levelId);
  const levels = getEpisodeLevels(episode);
  const index = levels.indexOf(levelId);

  if (index === -1) {
    throw new Error(`Unknown level id: ${levelId}`);
  }

  return levels[index + 1] ?? null;
}

export function getEpisodeForLevel(levelId) {
  return parseLevelId(levelId).episode;
}

export function isEpisodeFinalLevel(levelId) {
  const { episode } = parseLevelId(levelId);
  const levels = getEpisodeLevels(episode);
  return levels[levels.length - 1] === levelId;
}

export function isEpisodeUnlocked(episode, save = {}) {
  if (Number(episode) === 1) {
    return true;
  }

  const previousEpisode = Number(episode) - 1;
  return Array.isArray(save.cleared) && save.cleared.includes(`${previousEpisode}-05`);
}

export function getClearedCardActions({
  levelId,
  save = {}
}) {
  const { episode } = parseLevelId(levelId);

  if (episode === LAST_EPISODE && isEpisodeFinalLevel(levelId)) {
    return [
      action('replay', 'Replay', 'game', { levelId }),
      action('episode-select', 'Episode Select', 'episode-select')
    ];
  }

  const replay = action('replay', 'Replay', 'game', { levelId });
  const levelSelect = action('level-select', 'Level Select', 'level-select', { episode });
  const nextLevelId = getNextLevelId(levelId);

  if (nextLevelId) {
    return [
      replay,
      action('next-level', 'Next Level', 'game', { levelId: nextLevelId }),
      levelSelect
    ];
  }

  const nextEpisode = episode + 1;
  const middleAction = isEpisodeUnlocked(nextEpisode, save)
    ? action('next-episode', 'Next Episode', 'level-select', { episode: nextEpisode })
    : action('episode-select', 'Episode Select', 'episode-select');

  return [
    replay,
    middleAction,
    levelSelect
  ];
}

export function getFailedCardActions(levelId) {
  return [
    action('retry', 'Retry', 'game', { levelId }),
    action('level-select', 'Level Select', 'level-select', {
      episode: getEpisodeForLevel(levelId)
    })
  ];
}
