import Phaser from 'phaser';

import {
  SLINGSHOT,
  SLINGSHOT_ART,
  BIRD_VISUALS
} from '../constants/slingshot.js';
import {
  clampDragVector,
  computeLaunchVelocity,
  predictTrajectory
} from '../utils/aim.js';
import { PHYSICS_CONFIG } from '../systems/physics.js';
import { INPUT_TARGETS } from '../systems/inputRouter.js';
import { createBird } from './Bird.js';

function pointerId(pointer) {
  return pointer?.id ?? pointer?.pointerId ?? 0;
}

export default class Slingshot {
  constructor(scene, {
    anchor,
    queue,
    levelWidth,
    groundY,
    inputRouter,
    onPull,
    onLaunch,
    onResolve
  }) {
    this.scene = scene;
    this.anchor = { ...anchor };
    this.clampRadius = SLINGSHOT.clampRadius;
    this.levelWidth = levelWidth;
    this.groundY = groundY;
    this.inputRouter = inputRouter;
    this.queue = queue.map((entry, index) => ({
      id: `${entry.type}-${index}`,
      type: entry.type
    }));
    this.onPull = onPull;
    this.onLaunch = onLaunch;
    this.onResolve = onResolve;

    this.activeBird = null;
    this.flyingBird = null;
    this.dragging = false;
    this.activePointerId = null;
    this.dragStartedAt = 0;
    this.dragVector = { x: 0, y: 0, distance: 0, rawDistance: 0 };
    this.lastAimTrail = [];
    this.lastLaunch = null;
    this.flightStartedAt = 0;
    this.outOfWorldAt = null;
    this.restStartedAt = null;
    this.renderedQueue = [];

    this.forkSprite = scene.add.image(this.anchor.x, this.anchor.y, SLINGSHOT_ART.texture)
      .setDisplaySize(SLINGSHOT_ART.width, SLINGSHOT_ART.height)
      .setOrigin(0.5, SLINGSHOT_ART.originY)
      .setDepth(2);
    this.bandGraphics = scene.add.graphics().setDepth(12);
    this.pouch = scene.add.ellipse(this.anchor.x, this.anchor.y, 34, 20, 0xb83b2b)
      .setStrokeStyle(2, 0x6f1d17)
      .setDepth(13);
    this.queueIcons = scene.add.container(0, 0).setDepth(8);
    this.aimDots = Array.from({ length: SLINGSHOT.aimDotCount }, () => (
      scene.add.circle(0, 0, 5, 0xffffff, 0.7)
        .setStrokeStyle(1, 0x234155, 0.45)
        .setDepth(4)
        .setVisible(false)
    ));

    this.renderQueueIcons();
    this.loadNextBird();
    this.installInputHandlers();
  }

  installInputHandlers() {
    this.scene.input.on('pointerdown', this.handlePointerDown, this);
    this.scene.input.on('pointermove', this.handlePointerMove, this);
    this.scene.input.on('pointerup', this.handlePointerUp, this);
    this.scene.input.on('pointerupoutside', this.handlePointerUp, this);
    this.scene.input.on('gameout', this.handlePointerLeave, this);
    this.scene.events.once(Phaser.Scenes.Events.SHUTDOWN, () => this.destroy());
  }

  leftForkTip() {
    return {
      x: this.anchor.x + SLINGSHOT_ART.leftTip.x,
      y: this.anchor.y + SLINGSHOT_ART.leftTip.y
    };
  }

  rightForkTip() {
    return {
      x: this.anchor.x + SLINGSHOT_ART.rightTip.x,
      y: this.anchor.y + SLINGSHOT_ART.rightTip.y
    };
  }

  renderQueueIcons() {
    this.queueIcons.removeAll(true);
    this.renderedQueue = [];

    const iconSize = this.queue.length > 5 ? 26 : 30;
    const spacing = iconSize + 8;
    const startX = this.anchor.x - 82;
    const y = Math.min(690, this.anchor.y + 86);

    this.queue.forEach((entry, index) => {
      const visual = BIRD_VISUALS[entry.type] ?? BIRD_VISUALS.red;
      const x = startX + index * spacing;
      const icon = this.scene.add.image(x, y, visual.texture)
        .setDisplaySize(iconSize, iconSize)
        .setDepth(8);
      const slot = this.scene.add.circle(x, y, iconSize / 2 + 4, 0x13293a, 0.38)
        .setStrokeStyle(2, 0xffffff, 0.25)
        .setDepth(7);

      this.queueIcons.add(slot);
      this.queueIcons.add(icon);
      this.renderedQueue.push({
        type: entry.type,
        spriteKey: visual.texture,
        x,
        y
      });
    });
  }

  loadNextBird() {
    if (this.activeBird || this.flyingBird || this.queue.length === 0) {
      return;
    }

    this.activeBird = createBird(this.scene, this.queue[0].type, this.anchor.x, this.anchor.y);
    this.activeBird.setPouchPosition(this.anchor.x, this.anchor.y);
    this.pouch.setPosition(this.anchor.x, this.anchor.y);
  }

  canDrag() {
    return Boolean(this.activeBird && !this.flyingBird && !this.scene.isSlingshotPaused?.());
  }

  pointerWorldPosition(pointer) {
    const camera = this.scene.cameras.main;
    const rawX = Number.isFinite(pointer?.worldX) ? pointer.worldX : pointer.x + camera.scrollX;
    const rawY = Number.isFinite(pointer?.worldY) ? pointer.worldY : pointer.y + camera.scrollY;

    return {
      x: Phaser.Math.Clamp(rawX, 0, this.levelWidth),
      y: Phaser.Math.Clamp(rawY, 0, 720)
    };
  }

  handlePointerDown(pointer) {
    if (this.activePointerId !== null) {
      return;
    }

    const position = this.pointerWorldPosition(pointer);
    const canDrag = this.canDrag();
    const hit = Boolean(canDrag && this.activeBird?.containsPoint(position.x, position.y, 10));
    const route = this.inputRouter?.routePointerDown({
      screenPoint: { x: pointer.x, y: pointer.y },
      worldPoint: position,
      slingshot: { canDrag, hit },
      ability: { canFire: Boolean(this.flyingBird?.canFireAbility?.()) }
    });

    if (route?.target === INPUT_TARGETS.ability) {
      this.handleAbilityTap(position, pointer);
      return;
    }

    if (route && route.target !== INPUT_TARGETS.slingshot) {
      return;
    }

    if (!route && !hit) {
      return;
    }

    this.activePointerId = pointerId(pointer);
    this.dragging = true;
    this.dragStartedAt = this.scene.time.now;
    this.dragVector = { x: 0, y: 0, distance: 0, rawDistance: 0 };
    this.onPull?.();
    this.updateDrag(position);
  }

  handleAbilityTap(point, pointer) {
    if (this.scene.isSlingshotPaused?.()) {
      return null;
    }

    const result = this.flyingBird?.tryFireAbility?.({
      point,
      pointer,
      scene: this.scene,
      slingshot: this
    }) ?? null;
    const abilityEvent = result?.audioEvent ?? result?.result?.audioEvent;

    if (result?.fired && abilityEvent) {
      this.scene.recordAbilityEvent?.(abilityEvent);
    }

    const resolveReason = result?.result?.resolveReason;
    if (result?.fired && resolveReason && this.flyingBird?.exploded) {
      this.resolveFlyingBird(resolveReason);
    }

    this.scene.refreshDebug?.();
    return result;
  }

  handlePointerMove(pointer) {
    if (!this.dragging || pointerId(pointer) !== this.activePointerId) {
      return;
    }

    this.updateDrag(this.pointerWorldPosition(pointer));
  }

  handlePointerUp(pointer) {
    if (!this.dragging || pointerId(pointer) !== this.activePointerId) {
      return;
    }

    if (this.scene.isSlingshotPaused?.()) {
      this.cancelDrag();
      return;
    }

    const isTap = this.dragVector.rawDistance < SLINGSHOT.tapDeadZone;
    const isForwardDrag = this.dragVector.x > SLINGSHOT.forwardDragDeadZone;

    if (isTap || isForwardDrag) {
      this.cancelDrag();
      return;
    }

    this.launchActiveBird();
  }

  handlePointerLeave() {
    if (this.dragging) {
      this.cancelDrag();
    }
  }

  updateDrag(position) {
    if (!this.activeBird) {
      return;
    }

    const clamped = clampDragVector({
      x: position.x - this.anchor.x,
      y: position.y - this.anchor.y
    }, this.clampRadius);

    this.dragVector = clamped;
    const birdX = this.anchor.x + clamped.x;
    const birdY = this.anchor.y + clamped.y;

    this.activeBird.setPouchPosition(birdX, birdY);
    this.pouch.setPosition(birdX, birdY);
    this.drawBands(birdX, birdY);
    this.updateAimTrail(birdX, birdY);
  }

  drawBands(birdX, birdY) {
    const left = this.leftForkTip();
    const right = this.rightForkTip();

    this.bandGraphics.clear();
    [0x6f1d17, 0xd64a38].forEach((color, index) => {
      this.bandGraphics.lineStyle(index === 0 ? 8 : 4, color, 1);
      this.bandGraphics.beginPath();
      this.bandGraphics.moveTo(left.x, left.y);
      this.bandGraphics.lineTo(birdX, birdY);
      this.bandGraphics.moveTo(right.x, right.y);
      this.bandGraphics.lineTo(birdX, birdY);
      this.bandGraphics.strokePath();
    });
  }

  updateAimTrail(originX, originY) {
    const velocity = computeLaunchVelocity(this.dragVector, {
      clampRadius: this.clampRadius,
      power: SLINGSHOT.launchPower
    });
    const dots = predictTrajectory({
      origin: { x: originX, y: originY },
      velocity,
      gravityPerSecond: SLINGSHOT.trajectoryGravityPerSecond,
      sampleCount: SLINGSHOT.aimDotCount,
      sampleStep: SLINGSHOT.aimSampleStep,
      velocityScale: SLINGSHOT.trajectoryVelocityScale
    });

    this.lastAimTrail = dots;
    dots.forEach((dot, index) => {
      this.aimDots[index]
        .setPosition(dot.x, dot.y)
        .setAlpha(Math.max(0.18, 0.75 - index * 0.035))
        .setVisible(true);
    });
  }

  hideAimTrail() {
    this.aimDots.forEach((dot) => dot.setVisible(false));
  }

  cancelDrag() {
    if (this.activeBird) {
      this.activeBird.setPouchPosition(this.anchor.x, this.anchor.y);
      this.pouch.setPosition(this.anchor.x, this.anchor.y);
    }

    this.dragging = false;
    this.activePointerId = null;
    this.dragVector = { x: 0, y: 0, distance: 0, rawDistance: 0 };
    this.lastAimTrail = [];
    this.bandGraphics.clear();
    this.hideAimTrail();
  }

  launchActiveBird() {
    if (!this.activeBird) {
      this.cancelDrag();
      return;
    }

    const velocity = computeLaunchVelocity(this.dragVector, {
      clampRadius: this.clampRadius,
      power: SLINGSHOT.launchPower
    });
    const origin = { x: this.activeBird.x, y: this.activeBird.y };
    const launched = this.activeBird;

    this.queue.shift();
    this.activeBird = null;
    this.flyingBird = launched;
    this.flightStartedAt = this.scene.time.now;
    this.outOfWorldAt = null;
    this.restStartedAt = null;
    this.lastLaunch = {
      type: launched.type,
      origin,
      drag: { ...velocity.drag },
      velocity: { x: velocity.x, y: velocity.y, speed: velocity.speed },
      predicted: this.lastAimTrail.map((dot) => ({ ...dot }))
    };

    this.dragging = false;
    this.activePointerId = null;
    this.hideAimTrail();
    this.bandGraphics.clear();
    this.pouch.setPosition(this.anchor.x, this.anchor.y);
    this.renderQueueIcons();
    const launchResult = launched.launch(velocity);
    const actualVelocity = launchResult?.velocity ?? launched.getVelocity?.() ?? velocity;
    this.lastLaunch.velocity = {
      x: actualVelocity.x,
      y: actualVelocity.y,
      speed: actualVelocity.speed ?? Math.hypot(actualVelocity.x ?? 0, actualVelocity.y ?? 0)
    };
    if (launchResult?.flightDistanceMultiplier) {
      this.lastLaunch.flightDistanceMultiplier = launchResult.flightDistanceMultiplier;
    }
    this.onLaunch?.(launched, this.lastLaunch);
  }

  update(time) {
    if (this.dragging && this.scene.isSlingshotPaused?.()) {
      this.cancelDrag();
      return;
    }

    if (!this.flyingBird) {
      return;
    }

    const flightUpdate = this.flyingBird.updateFlight?.(time);
    if (flightUpdate?.exploded && flightUpdate.resolveReason) {
      this.resolveFlyingBird(flightUpdate.resolveReason);
      return;
    }

    const position = { x: this.flyingBird.x, y: this.flyingBird.y };
    const velocity = this.flyingBird.getVelocity();
    const speedPxPerSecond = velocity.speed * 60;
    const offWorld = position.x < 0 || position.x > this.levelWidth || position.y < 0 || position.y > 720;

    if (offWorld) {
      this.outOfWorldAt ??= time;
      if (time - this.outOfWorldAt >= PHYSICS_CONFIG.birdOffWorldCleanupMs) {
        this.resolveFlyingBird('off-world');
      }
      return;
    }

    this.outOfWorldAt = null;

    if (
      time - this.flightStartedAt >= SLINGSHOT.minSettleFlightMs
      && !this.flyingBird.abilityFired
      && (speedPxPerSecond < PHYSICS_CONFIG.stuckSpeedPxPerSecond || velocity.speed < SLINGSHOT.settleSpeed)
    ) {
      this.restStartedAt ??= time;
      if (time - this.restStartedAt >= PHYSICS_CONFIG.stuckBirdRestMs) {
        this.resolveFlyingBird('stuck-bird-recovery');
      }
      return;
    }

    this.restStartedAt = null;

    if (time - this.flightStartedAt >= PHYSICS_CONFIG.settleTimeoutMs) {
      this.resolveFlyingBird('timeout');
    }
  }

  resolveFlyingBird(reason) {
    const resolved = this.flyingBird;
    this.flyingBird = null;
    this.flightStartedAt = 0;
    this.outOfWorldAt = null;
    this.restStartedAt = null;

    resolved?.destroy();
    this.onResolve?.(reason);
    this.loadNextBird();
  }

  getQueueDebug() {
    return this.queue.map((entry) => ({
      type: entry.type,
      spriteKey: (BIRD_VISUALS[entry.type] ?? BIRD_VISUALS.red).texture
    }));
  }

  getBirdDebugState() {
    return this.activeBird?.getDebugState({ canDrag: this.canDrag() }) ?? null;
  }

  getFlyingBirdDebugState() {
    return this.flyingBird?.getDebugState({ canDrag: false }) ?? null;
  }

  getAimTrailDebug() {
    return this.lastAimTrail.map((dot) => ({ ...dot }));
  }

  getDebugState() {
    return {
      anchor: { ...this.anchor },
      clampRadius: this.clampRadius,
      dragging: this.dragging,
      activePointerId: this.activePointerId,
      canDrag: this.canDrag(),
      queue: this.getQueueDebug(),
      renderedQueue: this.renderedQueue.map((entry) => ({ ...entry })),
      lastAimTrail: this.getAimTrailDebug(),
      lastLaunch: this.lastLaunch
    };
  }

  destroy() {
    this.scene.input.off('pointerdown', this.handlePointerDown, this);
    this.scene.input.off('pointermove', this.handlePointerMove, this);
    this.scene.input.off('pointerup', this.handlePointerUp, this);
    this.scene.input.off('pointerupoutside', this.handlePointerUp, this);
    this.scene.input.off('gameout', this.handlePointerLeave, this);
    this.activeBird?.destroy();
    this.flyingBird?.destroy();
    this.queueIcons.destroy();
    this.forkSprite.destroy();
    this.bandGraphics.destroy();
    this.pouch.destroy();
    this.aimDots.forEach((dot) => dot.destroy());
  }
}
