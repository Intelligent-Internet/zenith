import { EPISODE_LEVEL_IDS } from '../constants/scoring.js';

export function resolveProgressionDevOverride(env = import.meta.env) {
  return Boolean(env?.ANGRY_BIRD_DEV);
}

function createUnlockShape(value = false) {
  return {
    episodes: Object.fromEntries(
      Object.keys(EPISODE_LEVEL_IDS).map((episode) => [Number(episode), value])
    ),
    levels: Object.fromEntries(
      Object.values(EPISODE_LEVEL_IDS)
        .flat()
        .map((levelId) => [levelId, value])
    )
  };
}

export function computeUnlocks(save = {}, {
  env = import.meta.env,
  devOverride = resolveProgressionDevOverride(env)
} = {}) {
  if (devOverride) {
    return createUnlockShape(true);
  }

  const cleared = new Set(Array.isArray(save.cleared) ? save.cleared : []);
  const unlocks = createUnlockShape(false);

  Object.entries(EPISODE_LEVEL_IDS).forEach(([episodeText, levelIds]) => {
    const episode = Number(episodeText);
    const hasClearedLevelInEpisode = levelIds.some((levelId) => cleared.has(levelId));
    unlocks.episodes[episode] = episode === 1
      || cleared.has(`${episode - 1}-05`)
      || hasClearedLevelInEpisode;

    levelIds.forEach((levelId, index) => {
      if (index === 0) {
        unlocks.levels[levelId] = unlocks.episodes[episode];
        return;
      }

      unlocks.levels[levelId] = cleared.has(levelIds[index - 1]);
    });
  });

  return unlocks;
}
