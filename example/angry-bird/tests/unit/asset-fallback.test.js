import { describe, expect, it, vi } from 'vitest';

import {
  installFallbackTexture,
  warnAssetLoadFailure
} from '../../src/systems/assetFallback.js';

function fakeCanvasFactory() {
  return vi.fn((width, height) => ({
    width,
    height,
    getContext: vi.fn(() => ({
      fillRect: vi.fn(),
      strokeRect: vi.fn(),
      beginPath: vi.fn(),
      arc: vi.fn(),
      fill: vi.fn(),
      stroke: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
      closePath: vi.fn(),
      fillText: vi.fn()
    }))
  }));
}

describe('asset fallback texture handling', () => {
  it('installs a same-key spritesheet placeholder using the failed asset frame dimensions', () => {
    const createCanvas = fakeCanvasFactory();
    const textures = {
      exists: vi.fn(() => false),
      addSpriteSheet: vi.fn(() => ({ key: 'bird-red' }))
    };

    const installed = installFallbackTexture({
      textures
    }, {
      type: 'spritesheet',
      key: 'bird-red',
      frameWidth: 96,
      frameHeight: 96,
      frameCount: 5
    }, {
      createCanvas
    });

    expect(installed).toBe(true);
    expect(createCanvas).toHaveBeenCalledWith(480, 96);
    expect(textures.addSpriteSheet).toHaveBeenCalledWith('bird-red', expect.objectContaining({
      width: 480,
      height: 96
    }), {
      frameWidth: 96,
      frameHeight: 96
    });
  });

  it('installs a same-key image placeholder for failed image assets', () => {
    const createCanvas = fakeCanvasFactory();
    const textures = {
      exists: vi.fn(() => false),
      addCanvas: vi.fn(() => ({ key: 'pig-small' }))
    };

    const installed = installFallbackTexture({
      textures
    }, {
      type: 'image',
      key: 'pig-small',
      fallbackWidth: 64,
      fallbackHeight: 64
    }, {
      createCanvas
    });

    expect(installed).toBe(true);
    expect(createCanvas).toHaveBeenCalledWith(64, 64);
    expect(textures.addCanvas).toHaveBeenCalledWith('pig-small', expect.objectContaining({
      width: 64,
      height: 64
    }));
  });

  it('warns once per failed asset key', () => {
    const logger = {
      warn: vi.fn()
    };
    const warnedKeys = new Set();
    const asset = {
      key: 'bird-red',
      url: 'assets/images/bird-red-sheet.png'
    };

    expect(warnAssetLoadFailure(asset, { logger, warnedKeys })).toBe(true);
    expect(warnAssetLoadFailure(asset, { logger, warnedKeys })).toBe(false);
    expect(logger.warn).toHaveBeenCalledTimes(1);
    expect(logger.warn.mock.calls[0][0]).toContain('bird-red');
  });
});
