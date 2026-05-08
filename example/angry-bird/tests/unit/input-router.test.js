import { describe, expect, it } from 'vitest';

import {
  INPUT_TARGETS,
  createInputRouter,
  createRectRegion
} from '../../src/systems/inputRouter.js';

describe('input router priority', () => {
  const hudRegion = createRectRegion('pause-button', {
    x: 20,
    y: 20,
    width: 120,
    height: 72
  });

  it('blocks all gameplay input while paused', () => {
    const router = createInputRouter({
      isPaused: () => true,
      hudRegions: [hudRegion]
    });

    expect(router.routePointerDown({
      screenPoint: { x: 240, y: 560 },
      worldPoint: { x: 240, y: 560 },
      slingshot: { canDrag: true, hit: true },
      ability: { canFire: true }
    }).target).toBe(INPUT_TARGETS.blocked);
  });

  it('routes HUD regions before slingshot or ability handlers', () => {
    const router = createInputRouter({
      isPaused: () => false,
      hudRegions: [hudRegion]
    });

    expect(router.routePointerDown({
      screenPoint: { x: 48, y: 48 },
      worldPoint: { x: 220, y: 560 },
      slingshot: { canDrag: true, hit: true },
      ability: { canFire: true }
    })).toMatchObject({
      target: INPUT_TARGETS.hud,
      regionId: 'pause-button'
    });
  });

  it('routes a slingshot hit before a canvas ability tap', () => {
    const router = createInputRouter({
      isPaused: () => false,
      hudRegions: [hudRegion]
    });

    expect(router.routePointerDown({
      screenPoint: { x: 220, y: 560 },
      worldPoint: { x: 220, y: 560 },
      slingshot: { canDrag: true, hit: true },
      ability: { canFire: true }
    }).target).toBe(INPUT_TARGETS.slingshot);
  });

  it('routes unblocked canvas taps to ability when a flight can use it', () => {
    const router = createInputRouter({
      isPaused: () => false,
      hudRegions: [hudRegion]
    });

    expect(router.routePointerDown({
      screenPoint: { x: 840, y: 420 },
      worldPoint: { x: 840, y: 420 },
      slingshot: { canDrag: false, hit: false },
      ability: { canFire: true }
    }).target).toBe(INPUT_TARGETS.ability);
  });
});
