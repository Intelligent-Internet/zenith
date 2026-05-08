import { describe, expect, it } from 'vitest';

import { resolveHudLayout } from '../../src/utils/mobileHud.js';

describe('mobile HUD layout', () => {
  it('keeps portrait mobile HUD controls readable after FIT scaling', () => {
    const layout = resolveHudLayout({
      gameWidth: 1280,
      gameHeight: 720,
      displayWidth: 390,
      displayHeight: 844
    });

    expect(layout.displayScale).toBeCloseTo(390 / 1280, 4);
    expect(layout.hudScale).toBeGreaterThan(1.5);
    expect(layout.pause.radius * layout.displayScale * 2).toBeGreaterThanOrEqual(30);
    expect(layout.score.fontSize * layout.displayScale).toBeGreaterThanOrEqual(13);
    expect(layout.birds.fontSize * layout.displayScale).toBeGreaterThanOrEqual(11);
  });

  it('keeps desktop HUD at the authored scale', () => {
    const layout = resolveHudLayout({
      gameWidth: 1280,
      gameHeight: 720,
      displayWidth: 1280,
      displayHeight: 720
    });

    expect(layout.hudScale).toBe(1);
    expect(layout.pause.x).toBe(48);
    expect(layout.score.x).toBe(1232);
  });
});
