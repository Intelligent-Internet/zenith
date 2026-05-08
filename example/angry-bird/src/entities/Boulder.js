import { BOULDER } from '../constants/materials.js';
import { applyDamageToHp } from '../systems/physics.js';

let nextBoulderId = 1;

export default class Boulder {
  constructor(scene, x, y, {
    radius = BOULDER.radius,
    hp = BOULDER.hp,
    isStatic = false
  } = {}) {
    this.id = `boulder-${nextBoulderId}`;
    nextBoulderId += 1;
    this.kind = 'boulder';
    this.scene = scene;
    this.material = BOULDER.material;
    this.maxHp = hp;
    this.hp = hp;
    this.radius = radius;
    this.score = BOULDER.score;
    this.destroyed = false;
    this.lastPosition = { x, y };

    this.gameObject = scene.matter.add.image(x, y, BOULDER.texture)
      .setDisplaySize(radius * 2, radius * 2)
      .setCircle(radius)
      .setDepth(5)
      .setFriction(BOULDER.friction)
      .setFrictionAir(BOULDER.frictionAir)
      .setBounce(BOULDER.restitution)
      .setDensity(BOULDER.density)
      .setStatic(isStatic);

    this.gameObject.setData('physicsEntity', this);
    this.gameObject.setData('entityKind', this.kind);
    this.gameObject.setData('material', this.material);
    this.gameObject.setData('hp', this.hp);
    scene.physicsSystem?.registerBoulder(this);
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
    if (this.destroyed) {
      return this.getDebugState();
    }

    const result = applyDamageToHp(this.hp, damage);
    this.hp = result.remainingHp;
    this.lastDamage = {
      amount: Math.max(0, damage),
      source,
      remainingHp: this.hp
    };
    this.gameObject.setData('hp', this.hp);

    if (result.destroyed) {
      this.destroy('damage');
    }

    return this.getDebugState();
  }

  destroy(reason = 'destroyed') {
    if (this.destroyed) {
      return;
    }

    this.destroyed = true;
    this.scene.physicsSystem?.onBlockDestroyed(this, reason);
    this.gameObject.destroy();
  }

  getDebugState() {
    return {
      id: this.id,
      kind: this.kind,
      material: this.material,
      hp: this.hp,
      maxHp: this.maxHp,
      x: this.x,
      y: this.y,
      radius: this.radius,
      destroyed: this.destroyed,
      lastDamage: this.lastDamage ?? null
    };
  }
}
