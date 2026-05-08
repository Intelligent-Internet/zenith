import { TNT_EXPLOSION } from '../constants/materials.js';

let nextTntId = 1;

export default class TNT {
  constructor(scene, x, y, {
    width = TNT_EXPLOSION.width,
    height = TNT_EXPLOSION.height,
    isStatic = true
  } = {}) {
    this.id = `tnt-${nextTntId}`;
    nextTntId += 1;
    this.kind = 'tnt';
    this.scene = scene;
    this.maxHp = TNT_EXPLOSION.hp;
    this.hp = TNT_EXPLOSION.hp;
    this.width = width;
    this.height = height;
    this.triggered = false;
    this.detonated = false;
    this.destroyed = false;
    this.lastPosition = { x, y };

    this.gameObject = scene.matter.add.image(x, y, TNT_EXPLOSION.texture)
      .setDisplaySize(width, height)
      .setRectangle(width, height)
      .setDepth(5)
      .setFriction(0.7)
      .setFrictionAir(0.002)
      .setBounce(0.1)
      .setDensity(0.001)
      .setStatic(isStatic);

    this.gameObject.setData('physicsEntity', this);
    this.gameObject.setData('entityKind', this.kind);
    this.gameObject.setData('hp', this.hp);
    scene.physicsSystem?.registerTnt(this);
  }

  get x() {
    return this.getPosition().x;
  }

  get y() {
    return this.getPosition().y;
  }

  get body() {
    return this.gameObject.body;
  }

  getPosition() {
    const position = this.gameObject?.body?.position;
    if (position) {
      this.lastPosition = { x: position.x, y: position.y };
    }

    return this.lastPosition;
  }

  takeDamage(damage, source = {}) {
    if (this.destroyed || this.detonated) {
      return this.getDebugState();
    }

    if (damage > 0) {
      this.scene.physicsSystem?.triggerTnt(this, {
        reason: source.reason ?? 'damage',
        source
      });
    }

    return this.getDebugState();
  }

  trigger(options = {}) {
    return this.scene.physicsSystem?.triggerTnt(this, options);
  }

  markTriggered({
    reason = 'triggered',
    triggeredAtMs = 0,
    scheduledDetonationAtMs = triggeredAtMs,
    sourceId = null
  } = {}) {
    if (this.triggered) {
      return;
    }

    this.triggered = true;
    this.triggerReason = reason;
    this.triggeredAtMs = triggeredAtMs;
    this.scheduledDetonationAtMs = scheduledDetonationAtMs;
    this.sourceId = sourceId;
  }

  markDetonated(timeMs = 0) {
    if (this.detonated) {
      return;
    }

    this.detonated = true;
    this.detonatedAtMs = timeMs;
    this.hp = 0;
    this.destroy('detonated');
  }

  destroy(reason = 'destroyed') {
    if (this.destroyed) {
      return;
    }

    this.destroyed = true;
    this.destroyReason = reason;
    this.scene.physicsSystem?.onTntDestroyed(this, reason);
    this.gameObject.destroy();
  }

  getDebugState() {
    return {
      id: this.id,
      kind: this.kind,
      hp: this.hp,
      maxHp: this.maxHp,
      x: this.x,
      y: this.y,
      width: this.width,
      height: this.height,
      triggered: this.triggered,
      detonated: this.detonated,
      destroyed: this.destroyed,
      triggerReason: this.triggerReason ?? null,
      triggeredAtMs: this.triggeredAtMs ?? null,
      scheduledDetonationAtMs: this.scheduledDetonationAtMs ?? null,
      detonatedAtMs: this.detonatedAtMs ?? null,
      sourceId: this.sourceId ?? null
    };
  }
}
