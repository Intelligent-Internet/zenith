import { ABILITY_SFX, BIRD_FLIGHT_SFX } from '../constants/audio.js';
import { BIRD_VISUALS } from '../constants/slingshot.js';
import { BIRD_SPRITE_FRAMES } from '../constants/assets.js';
import { CHUCK_SPEED_BURST_MULTIPLIER } from '../constants/birds.js';
import { BOMB_EXPLOSION } from '../constants/materials.js';
import { COLLISION_CATEGORIES } from '../systems/physics.js';

export const MEANINGFUL_COLLISION_SPEED_RATIO = 0.5;
export { BOMB_EXPLOSION };

const BIRD_ABILITY_TYPES = {
  red: 'none',
  blues: 'split',
  chuck: 'speedBurst',
  matilda: 'eggDropAndRedirect',
  bomb: 'explode',
  hal: 'boomerang'
};

const BLUES_SPLIT = {
  audioEvent: ABILITY_SFX.blues,
  childRadius: 12,
  minVerticalVelocityDelta: 3
};

export const CHUCK_SPEED_BURST = {
  audioEvent: ABILITY_SFX.chuck,
  multiplier: CHUCK_SPEED_BURST_MULTIPLIER,
  glassSpeedLossFactor: 0.05
};

export const MATILDA_EGG_DROP = {
  audioEvent: ABILITY_SFX.matilda,
  eggTexture: 'matilda-egg',
  eggRadius: 10,
  spawnYOffset: 38,
  redirectVy: -8,
  blockContactSpeedLossFactor: 0.05
};

export const HAL_BOOMERANG = {
  audioEvent: ABILITY_SFX.hal,
  vxScale: -1.2,
  vyImpulse: -8,
  rotateRadPerSec: 6,
  flightDistanceMultiplier: 1.5,
  stoneDamageRatio: 0.04
};

let nextMatildaEggId = 1;

function finiteNonNegative(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(0, number) : fallback;
}

function gameObjectPosition(gameObject) {
  const position = gameObject?.body?.position;

  return {
    x: position?.x ?? gameObject?.x ?? 0,
    y: position?.y ?? gameObject?.y ?? 0
  };
}

function gameObjectVelocity(gameObject) {
  const velocity = gameObject?.body?.velocity ?? { x: 0, y: 0 };

  return {
    x: velocity.x,
    y: velocity.y,
    speed: Math.hypot(velocity.x, velocity.y)
  };
}

function bodyCollisionCategory(body) {
  return body?.collisionFilter?.category
    ?? body?.parent?.collisionFilter?.category
    ?? body?.gameObject?.body?.collisionFilter?.category
    ?? null;
}

function bodyMatchesGameObject(body, gameObject) {
  if (!body || !gameObject?.body) {
    return false;
  }

  return body === gameObject.body
    || body.parent === gameObject.body
    || (gameObject.body.parent && body === gameObject.body.parent)
    || (body.parent && gameObject.body.parent && body.parent === gameObject.body.parent);
}

function contactKind(contactBody, contactEntity) {
  if (contactEntity?.kind) {
    return contactEntity.kind;
  }

  if (contactBody?.label === 'ground') {
    return 'ground';
  }

  return 'solid';
}

export function isMeaningfulCollision({
  hpLoss = 0,
  preSpeed = 0,
  postSpeed = preSpeed
} = {}) {
  const normalizedHpLoss = finiteNonNegative(hpLoss);
  if (normalizedHpLoss > 0) {
    return true;
  }

  const normalizedPreSpeed = finiteNonNegative(preSpeed);
  const normalizedPostSpeed = finiteNonNegative(postSpeed, normalizedPreSpeed);

  return normalizedPreSpeed > 0
    && normalizedPostSpeed < normalizedPreSpeed * MEANINGFUL_COLLISION_SPEED_RATIO;
}

export class BirdAbilityState {
  constructor({
    hasAbility = true
  } = {}) {
    this.hasAbility = Boolean(hasAbility);
    this.abilityFired = false;
    this.windowOpen = true;
    this.lastCollision = null;
    this.lastFire = null;
  }

  setHasAbility(hasAbility) {
    this.hasAbility = Boolean(hasAbility);
    return this.getState();
  }

  openForLaunch() {
    this.abilityFired = false;
    this.windowOpen = true;
    this.lastCollision = null;
    this.lastFire = null;
    return this.getState();
  }

  canFire() {
    return this.hasAbility && this.windowOpen && !this.abilityFired;
  }

  getNoFireReason() {
    if (!this.hasAbility) {
      return 'no-ability';
    }

    if (this.abilityFired) {
      return 'already-fired';
    }

    if (!this.windowOpen) {
      return 'window-closed';
    }

    return 'not-ready';
  }

  tryFire(callback) {
    if (!this.canFire()) {
      return {
        fired: false,
        reason: this.getNoFireReason(),
        state: this.getState()
      };
    }

    const result = callback?.() ?? null;
    this.abilityFired = true;
    this.lastFire = { result };

    return {
      fired: true,
      result,
      state: this.getState()
    };
  }

  recordCollision(collision = {}) {
    const normalizedCollision = {
      hpLoss: finiteNonNegative(collision.hpLoss),
      preSpeed: finiteNonNegative(collision.preSpeed),
      postSpeed: finiteNonNegative(collision.postSpeed, finiteNonNegative(collision.preSpeed)),
      impact: finiteNonNegative(collision.impact)
    };
    const meaningful = isMeaningfulCollision(normalizedCollision);

    this.lastCollision = {
      ...normalizedCollision,
      meaningful
    };

    if (meaningful) {
      this.windowOpen = false;
    }

    return {
      meaningful,
      state: this.getState()
    };
  }

  getState() {
    return {
      hasAbility: this.hasAbility,
      abilityFired: this.abilityFired,
      windowOpen: this.windowOpen,
      lastCollision: this.lastCollision,
      lastFire: this.lastFire
    };
  }
}

export class MatildaEgg {
  constructor(scene, parentBird, {
    x,
    y,
    radius = MATILDA_EGG_DROP.eggRadius
  }) {
    this.id = `matilda-egg-${nextMatildaEggId}`;
    nextMatildaEggId += 1;
    this.kind = 'matildaEgg';
    this.scene = scene;
    this.parentBird = parentBird;
    this.radius = radius;
    this.exploded = false;
    this.lastPosition = { x, y };
    this.lastExplosion = null;

    this.gameObject = scene.matter.add.image(x, y, MATILDA_EGG_DROP.eggTexture)
      .setCircle(radius)
      .setDisplaySize(radius * 2, radius * 2)
      .setDepth(9)
      .setFriction(0.6)
      .setFrictionAir(0)
      .setBounce(0.1)
      .setDensity(0.003)
      .setIgnoreGravity(false)
      .setStatic(false);

    this.gameObject.setData('physicsEntity', this);
    this.gameObject.setData('entityKind', this.kind);
    this.gameObject.setData('collisionRadius', radius);
    this.gameObject.setVelocity(0, 0);
    scene.physicsSystem?.registerMatildaEgg?.(this);
  }

  get x() {
    return this.getPosition().x;
  }

  get y() {
    return this.getPosition().y;
  }

  get body() {
    return this.gameObject?.body;
  }

  getPosition() {
    const position = this.gameObject?.body?.position;
    if (position) {
      this.lastPosition = { x: position.x, y: position.y };
    }

    return this.lastPosition;
  }

  getVelocity() {
    return gameObjectVelocity(this.gameObject);
  }

  isExcludedContact({ contactBody, contactEntity } = {}) {
    if (contactEntity === this.parentBird || contactEntity?.kind === 'slingshot') {
      return true;
    }

    if (bodyMatchesGameObject(contactBody, this.parentBird?.gameObject)) {
      return true;
    }

    return bodyCollisionCategory(contactBody) === COLLISION_CATEGORIES.SLINGSHOT;
  }

  explode({
    contactBody = null,
    contactEntity = null,
    reason = 'contact'
  } = {}) {
    const resolvedContactKind = contactKind(contactBody, contactEntity);

    if (this.exploded) {
      return this.getDebugState({
        exploded: false,
        reason: 'already-exploded',
        contactKind: resolvedContactKind
      });
    }

    if (this.isExcludedContact({ contactBody, contactEntity })) {
      return this.getDebugState({
        exploded: false,
        reason: 'excluded-contact',
        contactKind: resolvedContactKind
      });
    }

    this.exploded = true;
    this.lastExplosion = {
      x: this.x,
      y: this.y,
      reason,
      contactKind: resolvedContactKind,
      contactMaterial: contactEntity?.material ?? null,
      t: this.scene?.time?.now ?? null
    };

    this.scene.physicsSystem?.onMatildaEggExploded?.(this, {
      contactBody,
      contactEntity,
      reason
    });
    this.gameObject?.destroy?.();

    return this.getDebugState({
      exploded: true,
      reason,
      contactKind: resolvedContactKind
    });
  }

  destroy(reason = 'destroyed') {
    if (this.exploded) {
      return;
    }

    this.exploded = true;
    this.lastExplosion = {
      x: this.x,
      y: this.y,
      reason,
      contactKind: 'cleanup',
      contactMaterial: null,
      t: this.scene?.time?.now ?? null
    };
    this.gameObject?.destroy?.();
  }

  getDebugState(extra = {}) {
    return {
      id: this.id,
      kind: this.kind,
      x: this.x,
      y: this.y,
      radius: this.radius,
      exploded: this.exploded,
      velocity: this.getVelocity(),
      lastExplosion: this.lastExplosion,
      ...extra
    };
  }
}

export default class Bird {
  constructor(scene, type, x, y, {
    abilityType = BIRD_ABILITY_TYPES[type] ?? 'none'
  } = {}) {
    const visual = BIRD_VISUALS[type] ?? BIRD_VISUALS.red;

    this.scene = scene;
    this.kind = 'bird';
    this.type = type;
    this.abilityType = abilityType;
    this.visual = visual;
    this.radius = visual.radius;
    this.launched = false;
    this.gameObjects = [];
    this.abilityState = new BirdAbilityState({
      hasAbility: this.hasAbility()
    });
    this.syncAbilityState();

    this.gameObject = this.createPhysicsBody({
      x,
      y,
      radius: visual.radius,
      staticBody: true,
      ignoreGravity: true,
      role: 'parent'
    });
    this.gameObjects = [this.gameObject];
    this.updateAbilityData();
  }

  createPhysicsBody({
    x,
    y,
    radius,
    staticBody,
    ignoreGravity,
    role
  }) {
    const gameObject = this.scene.matter.add.image(x, y, this.visual.texture, BIRD_SPRITE_FRAMES.idleCry)
      .setCircle(radius)
      .setDisplaySize(radius * 2, radius * 2)
      .setDepth(10)
      .setFriction(0.8)
      .setFrictionAir(0)
      .setBounce(0.35)
      .setDensity(0.004)
      .setIgnoreGravity(ignoreGravity)
      .setStatic(staticBody);

    gameObject.setData('birdType', this.type);
    gameObject.setData('physicsEntity', this);
    gameObject.setData('entityKind', this.kind);
    gameObject.setData('collisionRadius', radius);
    gameObject.setData('birdBodyRole', role);
    this.setVisualFrame('idleCry', gameObject);
    this.updateAbilityDataFor(gameObject);
    this.scene.physicsSystem?.registerBird(this, gameObject);

    return gameObject;
  }

  setVisualFrame(frameKey, target = null) {
    const frame = BIRD_SPRITE_FRAMES[frameKey];
    if (!Number.isInteger(frame)) {
      return;
    }

    const gameObjects = target ? [target] : this.getPhysicsBodies();
    gameObjects.forEach((gameObject) => {
      gameObject?.setFrame?.(frame);
      gameObject?.setData?.('visualFrame', frameKey);
      gameObject?.setData?.('visualFrameIndex', frame);
    });
    this.visualFrame = frameKey;
  }

  getPhysicsBodies() {
    return this.gameObjects.length > 0 ? this.gameObjects : [this.gameObject].filter(Boolean);
  }

  replacePhysicsBodies(gameObjects) {
    this.gameObjects = gameObjects;
    this.gameObject = gameObjects[0] ?? null;
    this.updateAbilityData();
  }

  get x() {
    return gameObjectPosition(this.gameObject).x;
  }

  get y() {
    return gameObjectPosition(this.gameObject).y;
  }

  get body() {
    return this.gameObject?.body;
  }

  hasAbility() {
    return this.abilityType !== 'none';
  }

  syncAbilityState() {
    const state = this.abilityState.getState();

    this.abilityFired = state.abilityFired;
    this.windowOpen = state.windowOpen;
    this.lastAbilityCollision = state.lastCollision;
    this.lastAbilityFire = state.lastFire;
    this.updateAbilityData();

    return state;
  }

  updateAbilityData() {
    this.getPhysicsBodies().forEach((gameObject) => this.updateAbilityDataFor(gameObject));
  }

  updateAbilityDataFor(gameObject) {
    gameObject?.setData?.('abilityFired', this.abilityFired);
    gameObject?.setData?.('abilityWindowOpen', this.windowOpen);
    gameObject?.setData?.('abilityType', this.abilityType);
    if (this.visualFrame) {
      gameObject?.setData?.('visualFrame', this.visualFrame);
      gameObject?.setData?.('visualFrameIndex', BIRD_SPRITE_FRAMES[this.visualFrame]);
    }
  }

  resetAbilityState() {
    this.abilityState.openForLaunch();
    return this.syncAbilityState();
  }

  setPouchPosition(x, y) {
    this.gameObject.setStatic(true);
    this.gameObject.setIgnoreGravity(true);
    this.gameObject.setPosition(x, y);
    this.gameObject.setVelocity(0, 0);
    this.gameObject.setAngularVelocity(0);
  }

  resolveLaunchVelocity(velocity = {}) {
    const x = Number.isFinite(velocity.x) ? velocity.x : 0;
    const y = Number.isFinite(velocity.y) ? velocity.y : 0;

    return {
      ...velocity,
      x,
      y,
      speed: Math.hypot(x, y)
    };
  }

  launch(velocity = {}) {
    const launchVelocity = this.resolveLaunchVelocity(velocity);

    this.launched = true;
    this.resetAbilityState();
    this.gameObject.setStatic(false);
    this.gameObject.setIgnoreGravity(false);
    this.gameObject.setVelocity(launchVelocity.x, launchVelocity.y);
    this.gameObject.setAngularVelocity(launchVelocity.x * 0.012);
    this.setVisualFrame('fly');

    return {
      type: this.type,
      inputVelocity: {
        x: Number.isFinite(velocity.x) ? velocity.x : 0,
        y: Number.isFinite(velocity.y) ? velocity.y : 0,
        speed: Number.isFinite(velocity.speed) ? velocity.speed : Math.hypot(velocity.x ?? 0, velocity.y ?? 0)
      },
      velocity: this.getVelocity()
    };
  }

  containsPoint(x, y, padding = 0) {
    return Math.hypot(this.x - x, this.y - y) <= this.radius + padding;
  }

  getVelocity() {
    return gameObjectVelocity(this.gameObject);
  }

  capSpeed(maxSpeed) {
    const velocity = this.getVelocity();
    const cappedSpeed = finiteNonNegative(maxSpeed);

    if (!this.gameObject || velocity.speed <= cappedSpeed) {
      return {
        changed: false,
        maxSpeed: cappedSpeed,
        preVelocity: velocity,
        postVelocity: velocity
      };
    }

    if (velocity.speed === 0 || cappedSpeed === 0) {
      this.gameObject.setVelocity(0, 0);
    } else {
      const scale = cappedSpeed / velocity.speed;
      this.gameObject.setVelocity(velocity.x * scale, velocity.y * scale);
    }

    return {
      changed: true,
      maxSpeed: cappedSpeed,
      preVelocity: velocity,
      postVelocity: this.getVelocity()
    };
  }

  getFlightAudioEvent() {
    return BIRD_FLIGHT_SFX[this.type] ?? null;
  }

  canFireAbility() {
    return this.launched && this.abilityState.canFire();
  }

  tryFireAbility(context = {}) {
    if (!this.launched) {
      return {
        fired: false,
        reason: 'not-launched',
        state: this.syncAbilityState()
      };
    }

    if (this.abilityState.canFire()) {
      this.setVisualFrame('abilityPre');
    }

    const result = this.abilityState.tryFire(() => this.performAbility(context));
    this.syncAbilityState();
    if (result.fired) {
      this.setVisualFrame('abilityPost');
    }

    return result;
  }

  performAbility() {
    return {
      type: this.type,
      abilityType: this.abilityType,
      stubbed: true
    };
  }

  recordCollision(collision = {}) {
    const result = this.abilityState.recordCollision(collision);

    this.syncAbilityState();
    if (result.meaningful) {
      this.setVisualFrame('hit');
    }

    return result;
  }

  getDebugState(extra = {}) {
    const velocity = this.getVelocity();
    const bodies = this.getBodyDebugStates();

    return {
      type: this.type,
      x: this.x,
      y: this.y,
      radius: this.radius,
      bodyCount: bodies.length,
      bodies,
      launched: this.launched,
      abilityFired: this.abilityFired,
      windowOpen: this.windowOpen,
      abilityType: this.abilityType,
      canFireAbility: this.canFireAbility(),
      lastAbilityCollision: this.lastAbilityCollision,
      lastAbilityFire: this.lastAbilityFire,
      velocity,
      canDrag: false,
      ...extra
    };
  }

  destroy() {
    const uniqueBodies = new Set(this.getPhysicsBodies());

    uniqueBodies.forEach((gameObject) => gameObject?.destroy?.());
    this.gameObjects = [];
    this.gameObject = null;
  }

  getBodyDebugStates() {
    return this.getPhysicsBodies().map((gameObject) => {
      const position = gameObjectPosition(gameObject);

      return {
        role: gameObject.getData?.('birdBodyRole') ?? 'body',
        x: position.x,
        y: position.y,
        radius: gameObject.getData?.('collisionRadius') ?? this.radius,
        visualFrame: gameObject.getData?.('visualFrame') ?? this.visualFrame ?? 'idleCry',
        visualFrameIndex: gameObject.getData?.('visualFrameIndex') ?? BIRD_SPRITE_FRAMES[this.visualFrame] ?? BIRD_SPRITE_FRAMES.idleCry,
        velocity: gameObjectVelocity(gameObject)
      };
    });
  }
}

export class RedBird extends Bird {
  constructor(scene, x, y) {
    super(scene, 'red', x, y, { abilityType: 'none' });
  }

  performAbility() {
    return {
      type: this.type,
      abilityType: this.abilityType,
      stubbed: true
    };
  }
}

export class BluesBird extends Bird {
  constructor(scene, x, y) {
    super(scene, 'blues', x, y, { abilityType: BIRD_ABILITY_TYPES.blues });
  }

  performAbility() {
    const parentBody = this.gameObject;
    const parentPosition = { x: this.x, y: this.y };
    const parentVelocity = this.getVelocity();
    const splitDelta = Math.max(
      BLUES_SPLIT.minVerticalVelocityDelta,
      parentVelocity.speed * 0.22
    );
    const childSpecs = [
      { role: 'straight', velocity: { x: parentVelocity.x, y: parentVelocity.y } },
      { role: 'up', velocity: { x: parentVelocity.x, y: parentVelocity.y - splitDelta } },
      { role: 'down', velocity: { x: parentVelocity.x, y: parentVelocity.y + splitDelta } }
    ];
    const children = childSpecs.map((spec, index) => {
      const child = this.createPhysicsBody({
        x: parentPosition.x,
        y: parentPosition.y,
        radius: BLUES_SPLIT.childRadius,
        staticBody: false,
        ignoreGravity: false,
        role: spec.role
      });

      child.setPosition(parentPosition.x, parentPosition.y);
      child.setVelocity(spec.velocity.x, spec.velocity.y);
      child.setAngularVelocity((index - 1) * 0.08 + spec.velocity.x * 0.012);

      return child;
    });

    parentBody?.destroy?.();
    this.replacePhysicsBodies(children);
    this.setVisualFrame('abilityPost');

    return {
      type: this.type,
      abilityType: this.abilityType,
      audioEvent: BLUES_SPLIT.audioEvent,
      bodyCount: children.length,
      parentPosition,
      parentRadius: this.radius,
      bodies: this.getBodyDebugStates()
    };
  }
}

export class ChuckBird extends Bird {
  constructor(scene, x, y) {
    super(scene, 'chuck', x, y, { abilityType: BIRD_ABILITY_TYPES.chuck });
  }

  performAbility() {
    const preVelocity = this.getVelocity();
    const postVelocity = {
      x: preVelocity.x * CHUCK_SPEED_BURST.multiplier,
      y: preVelocity.y * CHUCK_SPEED_BURST.multiplier
    };

    this.gameObject?.setVelocity?.(postVelocity.x, postVelocity.y);
    this.gameObject?.setAngularVelocity?.(postVelocity.x * 0.012);

    return {
      type: this.type,
      abilityType: this.abilityType,
      audioEvent: CHUCK_SPEED_BURST.audioEvent,
      multiplier: CHUCK_SPEED_BURST.multiplier,
      preVelocity,
      postVelocity: this.getVelocity()
    };
  }

  applyGlassBreakSpeedLoss({ preSpeed = this.getVelocity().speed } = {}) {
    const preCollisionSpeed = finiteNonNegative(preSpeed);
    const cappedSpeed = preCollisionSpeed * CHUCK_SPEED_BURST.glassSpeedLossFactor;
    const result = this.capSpeed(cappedSpeed);

    return {
      material: 'glass',
      factor: CHUCK_SPEED_BURST.glassSpeedLossFactor,
      preCollisionSpeed,
      ...result
    };
  }
}

export class MatildaBird extends Bird {
  constructor(scene, x, y) {
    super(scene, 'matilda', x, y, { abilityType: BIRD_ABILITY_TYPES.matilda });
    this.activeEgg = null;
  }

  performAbility() {
    const position = { x: this.x, y: this.y };
    const preVelocity = this.getVelocity();
    const egg = new MatildaEgg(this.scene, this, {
      x: position.x,
      y: position.y + MATILDA_EGG_DROP.spawnYOffset
    });

    this.activeEgg = egg;
    this.gameObject?.setVelocity?.(preVelocity.x, MATILDA_EGG_DROP.redirectVy);
    this.gameObject?.setAngularVelocity?.(preVelocity.x * 0.012);

    return {
      type: this.type,
      abilityType: this.abilityType,
      audioEvent: MATILDA_EGG_DROP.audioEvent,
      redirectVy: MATILDA_EGG_DROP.redirectVy,
      preVelocity,
      postVelocity: this.getVelocity(),
      egg: egg.getDebugState()
    };
  }

  applyBlockContactSpeedLoss({ preSpeed = this.getVelocity().speed } = {}) {
    const preCollisionSpeed = finiteNonNegative(preSpeed);
    const cappedSpeed = preCollisionSpeed * MATILDA_EGG_DROP.blockContactSpeedLossFactor;
    const result = this.capSpeed(cappedSpeed);

    return {
      material: 'block',
      factor: MATILDA_EGG_DROP.blockContactSpeedLossFactor,
      preCollisionSpeed,
      ...result
    };
  }

  getDebugState(extra = {}) {
    return super.getDebugState({
      activeEgg: this.activeEgg?.getDebugState() ?? null,
      ...extra
    });
  }
}

export class BombBird extends Bird {
  constructor(scene, x, y) {
    super(scene, 'bomb', x, y, { abilityType: BIRD_ABILITY_TYPES.bomb });
    this.exploded = false;
    this.autoExplosionArmedAt = null;
    this.autoExplosionDueAt = null;
    this.lastExplosion = null;
  }

  launch(velocity) {
    this.exploded = false;
    this.autoExplosionArmedAt = null;
    this.autoExplosionDueAt = null;
    this.lastExplosion = null;
    super.launch(velocity);
  }

  canFireAbility() {
    if (!this.launched || this.exploded) {
      return false;
    }

    return super.canFireAbility() || this.isAutoExplosionPending();
  }

  tryFireAbility(context = {}) {
    if (!this.launched) {
      return {
        fired: false,
        reason: 'not-launched',
        state: this.syncAbilityState()
      };
    }

    if (this.exploded) {
      return {
        fired: false,
        reason: 'already-exploded',
        state: this.syncAbilityState()
      };
    }

    if (this.isAutoExplosionPending() && !this.abilityState.canFire()) {
      return this.forceExplosion({
        ...context,
        reason: context.reason ?? 'tap-during-auto-timer'
      });
    }

    return super.tryFireAbility({
      ...context,
      reason: context.reason ?? 'tap'
    });
  }

  performAbility(context = {}) {
    return this.explode({
      ...context,
      reason: context.reason ?? 'tap'
    });
  }

  forceExplosion(context = {}) {
    const result = this.explode(context);

    if (result.exploded) {
      this.abilityState.abilityFired = true;
      this.abilityState.lastFire = { result };
      this.setVisualFrame('abilityPost');
    }

    this.syncAbilityState();

    return {
      fired: result.exploded,
      reason: result.exploded ? undefined : result.reason,
      result,
      state: this.syncAbilityState()
    };
  }

  recordCollision(collision = {}) {
    const result = super.recordCollision(collision);

    this.armAutoExplosion(collision);

    return result;
  }

  armAutoExplosion(collision = {}) {
    if (
      this.exploded
      || this.abilityFired
      || this.autoExplosionDueAt !== null
      || !this.isSolidAutoExplosionContact(collision)
    ) {
      return null;
    }

    const now = Number.isFinite(collision.timeMs)
      ? collision.timeMs
      : this.scene?.time?.now ?? 0;

    this.autoExplosionArmedAt = now;
    this.autoExplosionDueAt = now + BOMB_EXPLOSION.autoDelayMs;

    return {
      armedAt: this.autoExplosionArmedAt,
      dueAt: this.autoExplosionDueAt,
      delayMs: BOMB_EXPLOSION.autoDelayMs,
      contactKind: collision.contactKind ?? null,
      contactMaterial: collision.contactMaterial ?? null
    };
  }

  isSolidAutoExplosionContact({ contactKind } = {}) {
    return ['block', 'pig', 'ground', 'solid'].includes(contactKind);
  }

  isAutoExplosionPending() {
    return this.autoExplosionDueAt !== null && !this.exploded;
  }

  updateFlight(timeOrContext = this.scene?.time?.now ?? 0) {
    const timeMs = typeof timeOrContext === 'number'
      ? timeOrContext
      : timeOrContext.time ?? timeOrContext.timeMs ?? this.scene?.time?.now ?? 0;

    if (this.exploded) {
      return {
        exploded: false,
        reason: 'already-exploded'
      };
    }

    if (this.autoExplosionDueAt === null) {
      return {
        exploded: false,
        reason: 'auto-not-armed'
      };
    }

    if (timeMs < this.autoExplosionDueAt) {
      return {
        exploded: false,
        reason: 'auto-pending',
        dueAt: this.autoExplosionDueAt
      };
    }

    return this.forceExplosion({
      reason: 'auto',
      timeMs
    }).result;
  }

  explode({
    reason = 'tap',
    timeMs = this.scene?.time?.now ?? null
  } = {}) {
    if (this.exploded) {
      return {
        type: this.type,
        abilityType: this.abilityType,
        audioEvent: BOMB_EXPLOSION.audioEvent,
        exploded: false,
        reason: 'already-exploded',
        lastExplosion: this.lastExplosion
      };
    }

    const x = this.x;
    const y = this.y;
    const resolvedTimeMs = timeMs ?? this.scene?.time?.now ?? null;
    const elapsedSinceArmedMs = this.autoExplosionArmedAt === null || resolvedTimeMs === null
      ? null
      : resolvedTimeMs - this.autoExplosionArmedAt;
    const delayMs = this.autoExplosionArmedAt === null || this.autoExplosionDueAt === null
      ? null
      : this.autoExplosionDueAt - this.autoExplosionArmedAt;

    this.exploded = true;
    this.lastExplosion = {
      type: this.type,
      abilityType: this.abilityType,
      audioEvent: BOMB_EXPLOSION.audioEvent,
      exploded: true,
      reason,
      resolveReason: reason === 'auto' ? 'bomb-auto-explosion' : 'bomb-tap-explosion',
      x,
      y,
      t: resolvedTimeMs,
      armedAt: this.autoExplosionArmedAt,
      dueAt: this.autoExplosionDueAt,
      delayMs,
      elapsedSinceArmedMs
    };

    this.scene?.physicsSystem?.onBombExploded?.(this, this.lastExplosion);
    this.gameObject?.destroy?.();

    return this.lastExplosion;
  }

  applyWoodBreakSpeedLoss({ preSpeed = this.getVelocity().speed } = {}) {
    const preCollisionSpeed = finiteNonNegative(preSpeed);
    const cappedSpeed = preCollisionSpeed * BOMB_EXPLOSION.woodSpeedLossFactor;
    const result = this.capSpeed(cappedSpeed);

    return {
      material: 'wood',
      factor: BOMB_EXPLOSION.woodSpeedLossFactor,
      preCollisionSpeed,
      ...result
    };
  }

  getDebugState(extra = {}) {
    return super.getDebugState({
      exploded: this.exploded,
      autoExplosionArmedAt: this.autoExplosionArmedAt,
      autoExplosionDueAt: this.autoExplosionDueAt,
      lastExplosion: this.lastExplosion,
      ...extra
    });
  }
}

export class HalBird extends Bird {
  constructor(scene, x, y) {
    super(scene, 'hal', x, y, { abilityType: BIRD_ABILITY_TYPES.hal });
    this.rotationRad = 0;
    this.lastRotationUpdateAt = null;
    this.lastBoomerang = null;
  }

  resolveLaunchVelocity(velocity = {}) {
    const baseVelocity = super.resolveLaunchVelocity(velocity);
    const x = baseVelocity.x * HAL_BOOMERANG.flightDistanceMultiplier;
    const y = baseVelocity.y;

    return {
      ...baseVelocity,
      x,
      y,
      speed: Math.hypot(x, y)
    };
  }

  launch(velocity) {
    this.rotationRad = 0;
    this.lastRotationUpdateAt = this.scene?.time?.now ?? 0;
    this.lastBoomerang = null;
    const result = super.launch(velocity);

    this.applyAirborneRotation();

    return {
      ...result,
      flightDistanceMultiplier: HAL_BOOMERANG.flightDistanceMultiplier,
      rotateRadPerSec: HAL_BOOMERANG.rotateRadPerSec
    };
  }

  applyAirborneRotation() {
    this.gameObject?.setAngularVelocity?.(HAL_BOOMERANG.rotateRadPerSec / 60);
  }

  resolveUpdateTime(timeOrContext) {
    if (typeof timeOrContext === 'number' && Number.isFinite(timeOrContext)) {
      return timeOrContext;
    }

    const contextTime = timeOrContext?.time ?? timeOrContext?.timeMs;
    if (Number.isFinite(contextTime)) {
      return contextTime;
    }

    return this.scene?.time?.now ?? this.lastRotationUpdateAt ?? 0;
  }

  updateFlight(timeOrContext = this.scene?.time?.now ?? 0) {
    if (!this.launched) {
      return {
        rotated: false,
        reason: 'not-launched'
      };
    }

    this.applyAirborneRotation();
    const timeMs = this.resolveUpdateTime(timeOrContext);
    const previousTimeMs = this.lastRotationUpdateAt ?? timeMs;
    const deltaMs = Math.max(0, timeMs - previousTimeMs);
    const deltaRad = HAL_BOOMERANG.rotateRadPerSec * (deltaMs / 1000);

    this.rotationRad += deltaRad;
    this.lastRotationUpdateAt = timeMs;

    if (typeof this.gameObject?.setRotation === 'function') {
      this.gameObject.setRotation(this.rotationRad);
    } else if (this.gameObject) {
      this.gameObject.rotation = this.rotationRad;
    }

    return {
      rotated: true,
      rotationRad: this.rotationRad,
      deltaRad,
      rotateRadPerSec: HAL_BOOMERANG.rotateRadPerSec
    };
  }

  performAbility() {
    const preVelocity = this.getVelocity();
    const postVelocity = {
      x: preVelocity.x * HAL_BOOMERANG.vxScale,
      y: preVelocity.y + HAL_BOOMERANG.vyImpulse
    };

    this.gameObject?.setVelocity?.(postVelocity.x, postVelocity.y);
    this.applyAirborneRotation();
    this.lastBoomerang = {
      type: this.type,
      abilityType: this.abilityType,
      audioEvent: HAL_BOOMERANG.audioEvent,
      vxScale: HAL_BOOMERANG.vxScale,
      vyImpulse: HAL_BOOMERANG.vyImpulse,
      preVelocity,
      postVelocity: this.getVelocity()
    };

    return this.lastBoomerang;
  }

  getDebugState(extra = {}) {
    return super.getDebugState({
      rotationRad: this.rotationRad,
      rotateRadPerSec: HAL_BOOMERANG.rotateRadPerSec,
      lastBoomerang: this.lastBoomerang,
      ...extra
    });
  }
}

export const BIRD_CLASSES = {
  red: RedBird,
  blues: BluesBird,
  chuck: ChuckBird,
  matilda: MatildaBird,
  bomb: BombBird,
  hal: HalBird
};

export function createBird(scene, type, x, y) {
  const BirdClass = BIRD_CLASSES[type] ?? RedBird;
  return new BirdClass(scene, x, y);
}
