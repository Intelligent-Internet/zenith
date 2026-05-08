const DEFAULT_FALLBACK_SIZE = 96;

function finitePositive(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : fallback;
}

function createBrowserCanvas(width, height) {
  if (typeof document === 'undefined') {
    return null;
  }

  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  return canvas;
}

function fallbackLabel(asset) {
  return String(asset?.key ?? 'asset')
    .replace(/^bird-/, '')
    .replace(/^block-/, '')
    .replace(/^pig-/, '')
    .slice(0, 10)
    .toUpperCase();
}

function drawFallbackFrame(context, asset, x, width, height, frameIndex) {
  const inset = Math.max(6, Math.round(Math.min(width, height) * 0.08));
  const label = fallbackLabel(asset);
  const stripeColor = frameIndex % 2 === 0 ? '#ff3b8a' : '#ffca3a';

  context.fillStyle = '#243040';
  context.fillRect(x, 0, width, height);
  context.fillStyle = stripeColor;
  context.fillRect(x + inset, inset, width - inset * 2, height - inset * 2);
  context.strokeStyle = '#ffffff';
  context.lineWidth = Math.max(3, Math.round(inset / 2));
  context.strokeRect(x + inset, inset, width - inset * 2, height - inset * 2);

  context.beginPath();
  context.moveTo(x + inset, inset);
  context.lineTo(x + width - inset, height - inset);
  context.moveTo(x + width - inset, inset);
  context.lineTo(x + inset, height - inset);
  context.stroke();

  context.fillStyle = '#1f2933';
  context.fillRect(x + inset * 1.5, height * 0.58, width - inset * 3, height * 0.22);
  context.fillStyle = '#ffffff';
  context.font = `${Math.max(10, Math.round(height * 0.13))}px Arial, sans-serif`;
  context.textAlign = 'center';
  context.textBaseline = 'middle';
  context.fillText('MISSING', x + width / 2, height * 0.42);
  context.fillText(label, x + width / 2, height * 0.69);
}

function createFallbackCanvas(asset, {
  createCanvas = createBrowserCanvas
} = {}) {
  const frameWidth = finitePositive(asset?.frameWidth ?? asset?.fallbackWidth, DEFAULT_FALLBACK_SIZE);
  const frameHeight = finitePositive(asset?.frameHeight ?? asset?.fallbackHeight, DEFAULT_FALLBACK_SIZE);
  const frameCount = asset?.type === 'spritesheet'
    ? Math.max(1, Math.floor(finitePositive(asset?.frameCount, 1)))
    : 1;
  const canvas = createCanvas(frameWidth * frameCount, frameHeight);
  const context = canvas?.getContext?.('2d');

  if (!canvas || !context) {
    return null;
  }

  for (let frame = 0; frame < frameCount; frame += 1) {
    drawFallbackFrame(context, asset, frame * frameWidth, frameWidth, frameHeight, frame);
  }

  return {
    canvas,
    frameWidth,
    frameHeight
  };
}

export function installFallbackTexture(scene, asset, options = {}) {
  const textures = scene?.textures;

  if (!textures || !asset?.key || !['image', 'spritesheet'].includes(asset.type)) {
    return false;
  }

  if (textures.exists?.(asset.key)) {
    return false;
  }

  const fallback = createFallbackCanvas(asset, options);

  if (!fallback) {
    return false;
  }

  if (asset.type === 'spritesheet') {
    return Boolean(textures.addSpriteSheet?.(asset.key, fallback.canvas, {
      frameWidth: fallback.frameWidth,
      frameHeight: fallback.frameHeight
    }));
  }

  return Boolean(textures.addCanvas?.(asset.key, fallback.canvas));
}

export function warnAssetLoadFailure(asset, {
  logger = console,
  warnedKeys = new Set()
} = {}) {
  if (!asset?.key || warnedKeys.has(asset.key)) {
    return false;
  }

  warnedKeys.add(asset.key);
  logger?.warn?.(`[Preloader] Non-critical asset failed to load; using fallback placeholder for ${asset.key} (${asset.url ?? 'unknown url'})`);
  return true;
}
