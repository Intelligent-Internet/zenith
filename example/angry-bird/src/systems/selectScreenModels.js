import {
  EPISODE_HERO_TITLES,
  getEpisodeHeroKey
} from '../constants/assets.js';
import { EPISODE_LEVEL_IDS } from '../constants/scoring.js';
import { getEpisodeTotals } from './scoring.js';

export const EPISODE_SELECT_LAYOUT = {
  centerX: 640,
  cardY: 382,
  cardWidth: 238,
  cardHeight: 456,
  cardSpacing: 320,
  heroWidth: 204,
  heroHeight: 196
};

export const LEVEL_SELECT_LAYOUT = {
  centerX: 640,
  cardY: 424,
  cardWidth: 174,
  cardHeight: 176,
  cardSpacing: 206
};

function formatScore(score) {
  return Math.max(0, Math.floor(Number(score) || 0)).toLocaleString('en-US');
}

function getCardX(index, count, {
  centerX,
  cardSpacing
}) {
  return centerX - ((count - 1) * cardSpacing) / 2 + index * cardSpacing;
}

function getClearedSet(save = {}) {
  return new Set(Array.isArray(save.cleared) ? save.cleared : []);
}

export function buildEpisodeSelectCards(save = {}, unlocks = {}, layout = EPISODE_SELECT_LAYOUT) {
  const episodes = Object.keys(EPISODE_LEVEL_IDS).map(Number);

  return episodes.map((episode, index) => {
    const totals = getEpisodeTotals(save, episode);
    const unlocked = Boolean(unlocks.episodes?.[episode]);
    const x = getCardX(index, episodes.length, layout);

    return {
      episode,
      title: EPISODE_HERO_TITLES[episode] ?? `Episode ${episode}`,
      heroKey: getEpisodeHeroKey(episode),
      levelIds: [...EPISODE_LEVEL_IDS[episode]],
      x,
      y: layout.cardY,
      width: layout.cardWidth,
      height: layout.cardHeight,
      heroRegion: {
        x,
        y: layout.cardY - 118,
        width: layout.heroWidth,
        height: layout.heroHeight
      },
      scoreTotal: totals.score,
      scoreTotalText: `Score ${formatScore(totals.score)}`,
      starTally: totals.stars,
      maxStars: totals.maxStars,
      starTallyText: `${totals.stars}/${totals.maxStars}`,
      unlocked,
      locked: !unlocked,
      visuallyDimmed: !unlocked,
      padlockOverlay: !unlocked,
      lockedClickFeedback: unlocked ? null : 'shake-highlight',
      horizontalIndex: index
    };
  });
}

export function buildEpisodeSelectSnapshot(cards = [], {
  focusIndex = 0
} = {}) {
  const normalizedCards = cards.map((card) => ({
    episode: card.episode,
    title: card.title,
    heroKey: card.heroKey,
    x: card.x,
    y: card.y,
    width: card.width,
    height: card.height,
    heroRegion: { ...card.heroRegion },
    scoreTotalText: card.scoreTotalText,
    starTallyText: card.starTallyText,
    starTallyMatches: /^\d+\/15$/.test(card.starTallyText),
    locked: card.locked,
    visuallyDimmed: card.visuallyDimmed,
    padlockOverlay: card.padlockOverlay,
    lockedClickFeedback: card.lockedClickFeedback
  }));
  const activeIndex = cards.length > 0
    ? ((focusIndex % cards.length) + cards.length) % cards.length
    : 0;

  return {
    type: 'episode-select',
    cardCount: normalizedCards.length,
    cards: normalizedCards,
    chapterCards: normalizedCards,
    leftToRightEpisodes: normalizedCards.map((card) => card.episode),
    horizontalFlow: normalizedCards.every((card, index) => (
      index === 0 || card.x > normalizedCards[index - 1].x
    )),
    allStarTalliesMatch: normalizedCards.every((card) => card.starTallyMatches),
    starTallyRegex: '^\\d+/15$',
    arrow: {
      visible: true,
      enabled: normalizedCards.length > 1,
      direction: 'forward',
      focusIndex: activeIndex,
      targetEpisode: normalizedCards[activeIndex]?.episode ?? null,
      advancesChapters: normalizedCards.length > 1
    }
  };
}

export function buildLevelSelectCards(
  episode = 1,
  save = {},
  unlocks = {},
  layout = LEVEL_SELECT_LAYOUT
) {
  const levelIds = EPISODE_LEVEL_IDS[episode] ?? EPISODE_LEVEL_IDS[1];
  const cleared = getClearedSet(save);

  return levelIds.map((levelId, index) => {
    const unlocked = Boolean(unlocks.levels?.[levelId]);
    const isCleared = cleared.has(levelId);
    const bestScore = Math.max(0, Math.floor(Number(save.bestScore?.[levelId]) || 0));
    const bestStars = Math.max(0, Math.min(3, Math.floor(Number(save.bestStars?.[levelId]) || 0)));

    return {
      episode,
      levelId,
      x: getCardX(index, levelIds.length, layout),
      y: layout.cardY,
      width: layout.cardWidth,
      height: layout.cardHeight,
      bestScore,
      bestScoreText: `Best ${formatScore(bestScore)}`,
      bestStars,
      bestStarsText: `${bestStars}/3`,
      statusText: isCleared ? 'Cleared' : (unlocked ? 'Open' : 'Locked'),
      cleared: isCleared,
      unlocked,
      locked: !unlocked,
      visuallyDimmed: !unlocked,
      padlockOverlay: !unlocked,
      lockedClickFeedback: unlocked ? null : 'shake-highlight',
      canStart: unlocked,
      horizontalIndex: index
    };
  });
}
