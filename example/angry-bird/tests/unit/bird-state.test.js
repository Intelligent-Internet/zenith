import { describe, expect, it, vi } from 'vitest';

import {
  INPUT_TARGETS,
  createInputRouter,
  createRectRegion
} from '../../src/systems/inputRouter.js';
import {
  BirdAbilityState,
  RedBird,
  BluesBird,
  ChuckBird,
  MatildaBird,
  BombBird,
  HalBird,
  createBird,
  isMeaningfulCollision
} from '../../src/entities/Bird.js';

function makeChainableGameObject() {
  const body = {
    velocity: { x: 0, y: 0 },
    position: { x: 0, y: 0 }
  };
  const gameObject = {
    body,
    x: 0,
    y: 0,
    setCircle: vi.fn(() => gameObject),
    setDisplaySize: vi.fn(() => gameObject),
    setDepth: vi.fn(() => gameObject),
    setFriction: vi.fn(() => gameObject),
    setFrictionAir: vi.fn(() => gameObject),
    setBounce: vi.fn(() => gameObject),
    setDensity: vi.fn(() => gameObject),
    setIgnoreGravity: vi.fn(() => gameObject),
    setStatic: vi.fn(() => gameObject),
    setData: vi.fn(() => gameObject),
    setPosition: vi.fn((x, y) => {
      gameObject.x = x;
      gameObject.y = y;
      body.position = { x, y };
      return gameObject;
    }),
    setVelocity: vi.fn((x, y) => {
      body.velocity = { x, y };
      return gameObject;
    }),
    setAngularVelocity: vi.fn(() => gameObject),
    destroy: vi.fn()
  };

  return gameObject;
}

function makeScene() {
  const gameObject = makeChainableGameObject();

  return {
    gameObject,
    matter: {
      add: {
        image: vi.fn(() => gameObject)
      }
    },
    physicsSystem: {
      registerBird: vi.fn()
    }
  };
}

describe('bird meaningful-collision rule', () => {
  it('keeps the ability window open for a graze with no HP loss and retained speed', () => {
    expect(isMeaningfulCollision({
      hpLoss: 0,
      preSpeed: 10,
      postSpeed: 5
    })).toBe(false);
  });

  it('closes the ability window when any HP is lost', () => {
    expect(isMeaningfulCollision({
      hpLoss: 0.1,
      preSpeed: 10,
      postSpeed: 9
    })).toBe(true);
  });

  it('closes the ability window when post-impact speed drops below half', () => {
    expect(isMeaningfulCollision({
      hpLoss: 0,
      preSpeed: 10,
      postSpeed: 4.99
    })).toBe(true);
  });
});

describe('bird ability state machine', () => {
  it('fires an ability once per launch window', () => {
    const state = new BirdAbilityState();

    state.openForLaunch();

    expect(state.tryFire().fired).toBe(true);
    expect(state.tryFire().fired).toBe(false);
    expect(state.getState()).toMatchObject({
      abilityFired: true,
      windowOpen: true
    });
  });

  it('does not close on a graze and still allows the first ability tap', () => {
    const state = new BirdAbilityState();

    state.openForLaunch();
    const collision = state.recordCollision({
      hpLoss: 0,
      preSpeed: 12,
      postSpeed: 8
    });

    expect(collision.meaningful).toBe(false);
    expect(state.getState().windowOpen).toBe(true);
    expect(state.tryFire().fired).toBe(true);
  });

  it('closes on meaningful collision and ignores later ability taps', () => {
    const state = new BirdAbilityState();

    state.openForLaunch();
    const collision = state.recordCollision({
      hpLoss: 3,
      preSpeed: 12,
      postSpeed: 11
    });

    expect(collision.meaningful).toBe(true);
    expect(state.getState().windowOpen).toBe(false);
    expect(state.tryFire().fired).toBe(false);
  });

  it('resets fired and closed state on the next launch or retry-created bird', () => {
    const state = new BirdAbilityState();

    state.openForLaunch();
    state.tryFire();
    state.recordCollision({ hpLoss: 1, preSpeed: 9, postSpeed: 9 });

    state.openForLaunch();

    expect(state.getState()).toMatchObject({
      abilityFired: false,
      windowOpen: true
    });
    expect(state.tryFire().fired).toBe(true);
  });
});

describe('bird base class and stubs', () => {
  it('creates per-type subclasses through the factory', () => {
    const scene = makeScene();

    expect(createBird(scene, 'red', 0, 0)).toBeInstanceOf(RedBird);
    expect(createBird(scene, 'blues', 0, 0)).toBeInstanceOf(BluesBird);
    expect(createBird(scene, 'chuck', 0, 0)).toBeInstanceOf(ChuckBird);
    expect(createBird(scene, 'matilda', 0, 0)).toBeInstanceOf(MatildaBird);
    expect(createBird(scene, 'bomb', 0, 0)).toBeInstanceOf(BombBird);
    expect(createBird(scene, 'hal', 0, 0)).toBeInstanceOf(HalBird);
  });

  it('launch resets ability state and tap attempts are single-fire', () => {
    const bird = createBird(makeScene(), 'chuck', 10, 20);

    bird.launch({ x: 3, y: -2 });
    expect(bird.getDebugState()).toMatchObject({
      abilityFired: false,
      windowOpen: true
    });

    expect(bird.tryFireAbility().fired).toBe(true);
    expect(bird.tryFireAbility().fired).toBe(false);

    bird.recordCollision({ hpLoss: 1, preSpeed: 8, postSpeed: 8 });
    bird.launch({ x: 4, y: -1 });

    expect(bird.tryFireAbility().fired).toBe(true);
  });

  it('red is a silent no-ability stub', () => {
    const bird = createBird(makeScene(), 'red', 10, 20);

    bird.launch({ x: 3, y: -2 });

    expect(bird.tryFireAbility().fired).toBe(false);
    expect(bird.getDebugState()).toMatchObject({
      abilityFired: false,
      windowOpen: true
    });
  });
});

describe('ability tap routing', () => {
  const hudRegion = createRectRegion('pause-button', {
    x: 20,
    y: 20,
    width: 120,
    height: 72
  });

  it('routes only unblocked non-HUD canvas taps to an active ability window', () => {
    const router = createInputRouter({
      isPaused: () => false,
      hudRegions: [hudRegion]
    });

    expect(router.routePointerDown({
      screenPoint: { x: 48, y: 48 },
      worldPoint: { x: 48, y: 48 },
      slingshot: { canDrag: false, hit: false },
      ability: { canFire: true }
    }).target).toBe(INPUT_TARGETS.hud);

    expect(router.routePointerDown({
      screenPoint: { x: 840, y: 420 },
      worldPoint: { x: 840, y: 420 },
      slingshot: { canDrag: false, hit: false },
      ability: { canFire: true }
    }).target).toBe(INPUT_TARGETS.ability);
  });

  it('blocks ability taps while paused', () => {
    const router = createInputRouter({
      isPaused: () => true,
      hudRegions: [hudRegion]
    });

    expect(router.routePointerDown({
      screenPoint: { x: 840, y: 420 },
      worldPoint: { x: 840, y: 420 },
      slingshot: { canDrag: false, hit: false },
      ability: { canFire: true }
    }).target).toBe(INPUT_TARGETS.blocked);
  });
});
