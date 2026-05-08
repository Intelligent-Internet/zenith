const BASE_GAME_WIDTH = 1280;
const BASE_GAME_HEIGHT = 720;
const MIN_READABLE_DISPLAY_SCALE = 0.58;
const MAX_HUD_SCALE = 1.85;

function finitePositive(value, fallback) {
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function resolveDisplayScale({
  gameWidth,
  gameHeight,
  displayWidth,
  displayHeight
}) {
  const widthScale = displayWidth / gameWidth;
  const heightScale = displayHeight / gameHeight;
  return finitePositive(Math.min(widthScale, heightScale), 1);
}

export function resolveHudLayout({
  gameWidth = BASE_GAME_WIDTH,
  gameHeight = BASE_GAME_HEIGHT,
  displayWidth = gameWidth,
  displayHeight = gameHeight
} = {}) {
  const safeGameWidth = finitePositive(gameWidth, BASE_GAME_WIDTH);
  const safeGameHeight = finitePositive(gameHeight, BASE_GAME_HEIGHT);
  const safeDisplayWidth = finitePositive(displayWidth, safeGameWidth);
  const safeDisplayHeight = finitePositive(displayHeight, safeGameHeight);
  const displayScale = resolveDisplayScale({
    gameWidth: safeGameWidth,
    gameHeight: safeGameHeight,
    displayWidth: safeDisplayWidth,
    displayHeight: safeDisplayHeight
  });
  const hudScale = clamp(MIN_READABLE_DISPLAY_SCALE / displayScale, 1, MAX_HUD_SCALE);

  const pauseRadius = 28 * hudScale;
  const pauseX = Math.max(48, pauseRadius + 12 * hudScale);
  const pauseY = Math.max(48, pauseRadius + 12 * hudScale);
  const levelX = pauseX + 44 * hudScale;
  const scoreX = safeGameWidth - 48;
  const scoreY = Math.max(36, 12 * hudScale + 12 * hudScale);
  const birdsY = scoreY + 32 * hudScale;

  return {
    displayScale,
    hudScale,
    pause: {
      x: pauseX,
      y: pauseY,
      radius: pauseRadius,
      hitRadius: pauseRadius + 6 * hudScale,
      fontSize: 22 * hudScale,
      levelX,
      levelFontSize: 24 * hudScale,
      levelRegion: {
        x: levelX - 8 * hudScale,
        y: pauseY - 26 * hudScale,
        width: 112 * hudScale,
        height: 52 * hudScale
      }
    },
    score: {
      x: scoreX,
      y: scoreY,
      fontSize: 24 * hudScale,
      region: {
        x: safeGameWidth - 250 * hudScale,
        y: Math.max(0, scoreY - 24 * hudScale),
        width: 238 * hudScale,
        height: 44 * hudScale
      }
    },
    birds: {
      x: scoreX,
      y: birdsY,
      fontSize: 20 * hudScale,
      region: {
        x: safeGameWidth - 230 * hudScale,
        y: birdsY - 22 * hudScale,
        width: 218 * hudScale,
        height: 42 * hudScale
      }
    }
  };
}
