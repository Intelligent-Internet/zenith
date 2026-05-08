import Phaser from 'phaser';

import { getEpisodeBackgroundKey } from '../constants/assets.js';
import { END_STATE_SFX, GAMEPLAY_SFX_VOLUME, SLINGSHOT_SFX } from '../constants/audio.js';
import { SLINGSHOT } from '../constants/slingshot.js';
import { THREE_STAR_THRESHOLDS } from '../constants/scoring.js';
import Boulder from '../entities/Boulder.js';
import { GlassBlock, StoneBlock, WoodBlock } from '../entities/Block.js';
import { LargePig, MediumPig, SmallPig } from '../entities/Pig.js';
import Slingshot from '../entities/Slingshot.js';
import TNT from '../entities/TNT.js';
import { registerDebugScene } from '../systems/debug.js';
import {
  createCircleRegion,
  createInputRouter,
  createRectRegion
} from '../systems/inputRouter.js';
import { resolveLevelConfig } from '../systems/levelLoader.js';
import { getPersistence } from '../systems/persistence.js';
import { COLLISION_CATEGORIES, PhysicsSystem } from '../systems/physics.js';
import { setGlobalSoundMute } from '../systems/soundMute.js';
import {
  buildClearResult,
  getClearedCardActions,
  getFailedCardActions,
  resolveLevelOutcome
} from '../systems/winLose.js';
import { resolveHudLayout } from '../utils/mobileHud.js';

export default class Game extends Phaser.Scene {
  constructor() {
    super('Game');
  }

  init(data = {}) {
    this.levelConfig = resolveLevelConfig({ sceneData: data });
    this.levelId = this.levelConfig.id;
  }

  create() {
    this.score = 0;
    this.pigsLeft = 0;
    this.settled = true;
    this.levelEnded = false;
    this.birdsLaunched = 0;
    this.initialBirdCount = this.levelConfig.queue.length;
    this.birdsLeft = this.levelConfig.queue.length;
    this.queue = this.levelConfig.queue.map((entry) => ({ ...entry }));
    this.flyingBird = null;
    this.bird = null;
    this.threeStarThreshold = { ...THREE_STAR_THRESHOLDS };
    this.audioState = {
      lastEvent: null,
      lastAbilityEvent: null,
      muted: false,
      paused: false,
      recentEvents: []
    };
    this.persistence = getPersistence();
    this.save = this.persistence.loadSave();
    this.audioState.muted = this.save.mute;
    this.applySoundMute(this.audioState.muted);
    this.pausedForOverlay = false;
    this.hudRegions = [];
    this.hudLayout = this.createHudLayout();

    this.physicsSystem = new PhysicsSystem(this, {
      width: this.levelConfig.levelWidth,
      height: 720,
      onSettledChange: () => this.evaluateLevelEnd()
    });
    this.configureCamera();
    this.drawLevelBackdrop();
    this.createLevelObjects();
    this.createPauseControls();
    this.createScoreHud();
    this.inputRouter = createInputRouter({
      isPaused: () => this.pausedForOverlay,
      hudRegions: () => this.getHudInputRegions()
    });
    this.slingshot = new Slingshot(this, {
      anchor: this.levelConfig.anchor,
      queue: this.levelConfig.queue,
      levelWidth: this.levelConfig.levelWidth,
      groundY: this.levelConfig.groundY,
      inputRouter: this.inputRouter,
      onPull: () => this.recordAudioEvent(SLINGSHOT_SFX.pull),
      onLaunch: (bird, launch) => this.handleBirdLaunched(bird, launch),
      onResolve: (reason) => this.handleBirdResolved(reason)
    });

    this.refreshDebug();
  }

  drawLevelBackdrop() {
    const { levelWidth, groundY } = this.levelConfig;

    this.add.image(0, 0, getEpisodeBackgroundKey(this.levelConfig.id))
      .setOrigin(0)
      .setDisplaySize(levelWidth, 720)
      .setDepth(-20);
    this.add.rectangle(levelWidth / 2, groundY + 44, levelWidth, 128, 0x2c6b38).setDepth(-15);
    this.add.rectangle(levelWidth / 2, groundY + 92, levelWidth, 96, 0x4b352a).setDepth(-16);
    const ground = this.matter.add.rectangle(levelWidth / 2, groundY + 26, levelWidth, 52, {
      isStatic: true,
      label: 'ground'
    });
    ground.collisionFilter.category = COLLISION_CATEGORIES.GROUND;
  }

  configureCamera() {
    const camera = this.cameras.main;

    camera.setBounds(0, 0, this.levelConfig.levelWidth, 720);
    camera.setZoom(1);
    camera.scrollX = 0;
    camera.scrollY = 0;
    this.cameraState = {
      mode: this.levelConfig.cameraWide ? 'recentered' : 'fixed',
      following: false,
      target: this.levelConfig.cameraWide ? 'slingshot' : 'level',
      center: this.levelConfig.cameraWide
        ? { x: this.levelConfig.anchor.x, y: 360 }
        : { x: 640, y: 360 },
      lastFollowStartedAt: null,
      lastRecenteredAt: this.time?.now ?? null
    };
  }

  isWideCameraLevel() {
    return Boolean(this.levelConfig?.cameraWide);
  }

  followLaunchedBird(bird) {
    if (!this.isWideCameraLevel() || !bird) {
      return false;
    }

    const camera = this.cameras?.main;
    if (!camera || typeof camera.startFollow !== 'function') {
      return false;
    }

    camera.startFollow(bird, true, 0.08, 0.08);
    this.cameraState = {
      ...(this.cameraState ?? {}),
      mode: 'follow',
      following: true,
      target: 'bird',
      lastFollowStartedAt: this.time?.now ?? null
    };
    return true;
  }

  recenterCameraOnSlingshot() {
    if (!this.isWideCameraLevel()) {
      this.cameraState = {
        ...(this.cameraState ?? {}),
        mode: 'fixed',
        following: false,
        target: 'level'
      };
      return false;
    }

    const camera = this.cameras?.main;
    if (!camera) {
      return false;
    }

    const center = {
      x: this.levelConfig.anchor.x,
      y: 360
    };

    camera.stopFollow?.();
    if (typeof camera.centerOn === 'function') {
      camera.centerOn(center.x, center.y);
    } else {
      const viewportWidth = camera.width ?? 1280;
      camera.scrollX = Math.max(0, Math.min(
        center.x - viewportWidth / 2,
        this.levelConfig.levelWidth - viewportWidth
      ));
      camera.scrollY = 0;
    }

    this.cameraState = {
      ...(this.cameraState ?? {}),
      mode: 'recentered',
      following: false,
      target: 'slingshot',
      center,
      lastRecenteredAt: this.time?.now ?? null
    };
    return true;
  }

  createLevelObjects() {
    const blockClasses = {
      glass: GlassBlock,
      stone: StoneBlock,
      wood: WoodBlock
    };
    const pigClasses = {
      large: LargePig,
      medium: MediumPig,
      small: SmallPig
    };

    this.platforms = (this.levelConfig.platforms ?? []).map((platform) => this.createPlatform(platform));
    this.mounds = this.levelConfig.mounds.map((mound) => this.createMound(mound));
    this.blocks = this.levelConfig.blocks.map((block) => {
      const BlockClass = blockClasses[block.material];
      return new BlockClass(this, block.x, block.y, {
        width: block.width,
        height: block.height,
        angle: block.angle,
        isStatic: block.isStatic
      });
    });
    this.pigs = this.levelConfig.pigs.map((pig) => {
      const PigClass = pigClasses[pig.tier];
      return new PigClass(this, pig.x, pig.y, {
        isStatic: pig.isStatic
      });
    });
    this.boulders = this.levelConfig.boulders.map((boulder) => new Boulder(this, boulder.x, boulder.y, {
      radius: boulder.radius,
      hp: boulder.hp,
      isStatic: boulder.isStatic
    }));
    this.tntCrates = this.levelConfig.tntCrates.map((crate) => new TNT(this, crate.x, crate.y, {
      width: crate.width,
      height: crate.height,
      isStatic: crate.isStatic
    }));
  }

  createPlatform({ x, y, width, height }) {
    const halfWidth = width / 2;
    const topY = y - height;
    const graphics = this.add.graphics()
      .setDepth(1);

    graphics.fillStyle(0x503728, 1);
    graphics.fillRect(x - halfWidth, topY, width, height);
    graphics.fillStyle(0x6f3f2b, 0.6);
    [
      { x: x - halfWidth + width * 0.18, y: topY + height * 0.28, width: 36, height: 8 },
      { x: x - halfWidth + width * 0.58, y: topY + height * 0.48, width: 44, height: 10 },
      { x: x - halfWidth + width * 0.34, y: topY + height * 0.72, width: 28, height: 7 }
    ].forEach((mark) => graphics.fillRect(mark.x, mark.y, mark.width, mark.height));
    graphics.fillStyle(0x4d9d36, 1);
    graphics.fillRect(x - halfWidth, topY - 8, width, 12);
    graphics.lineStyle(4, 0x2c6c2d, 1);
    graphics.beginPath();
    graphics.moveTo(x - halfWidth, topY - 1);
    graphics.lineTo(x + halfWidth, topY - 1);
    graphics.strokePath();

    const body = this.matter.add.rectangle(x, topY + height / 2, width, height, {
      isStatic: true,
      label: 'raised-platform'
    });
    body.collisionFilter.category = COLLISION_CATEGORIES.GROUND;

    return {
      x,
      y,
      width,
      height,
      body,
      graphics
    };
  }

  createMound({ x, y, width, height }) {
    const halfWidth = width / 2;
    const topY = y - height;
    const graphics = this.add.graphics()
      .setDepth(1);

    graphics.fillStyle(0x503728, 1);
    graphics.fillTriangle(x - halfWidth, y, x, topY, x + halfWidth, y);
    graphics.lineStyle(8, 0x3c7f37, 1);
    graphics.beginPath();
    graphics.moveTo(x - halfWidth, y - 4);
    graphics.lineTo(x, topY);
    graphics.lineTo(x + halfWidth, y - 4);
    graphics.strokePath();

    const slopeAngle = Math.atan2(height, halfWidth);
    const slopeLength = Math.hypot(halfWidth, height);
    const leftSlope = this.matter.add.rectangle(
      x - halfWidth / 2,
      y - height / 2,
      slopeLength,
      18,
      { isStatic: true, label: 'mound-left-slope', angle: -slopeAngle }
    );
    const rightSlope = this.matter.add.rectangle(
      x + halfWidth / 2,
      y - height / 2,
      slopeLength,
      18,
      { isStatic: true, label: 'mound-right-slope', angle: slopeAngle }
    );
    const topCap = this.matter.add.rectangle(x, topY + 8, 84, 16, {
      isStatic: true,
      label: 'mound-top-cap'
    });
    const core = this.matter.add.rectangle(x, y - height / 3, width * 0.45, height * 0.75, {
      isStatic: true,
      label: 'mound-core'
    });

    [leftSlope, rightSlope, topCap, core].forEach((body) => {
      body.collisionFilter.category = COLLISION_CATEGORIES.GROUND;
    });

    return {
      x,
      y,
      width,
      height,
      bodies: [leftSlope, rightSlope, topCap, core],
      graphics
    };
  }

  createPauseControls() {
    const { pause } = this.hudLayout;
    const pauseButton = this.add.circle(pause.x, pause.y, pause.radius, 0xf8d24a)
      .setStrokeStyle(4, 0x1f2933)
      .setDepth(50)
      .setScrollFactor(0)
      .setInteractive({ useHandCursor: true });
    this.add.text(pause.x, pause.y, 'II', {
      fontFamily: 'Arial, sans-serif',
      fontSize: `${pause.fontSize}px`,
      fontStyle: 'bold',
      color: '#1f2933'
    }).setOrigin(0.5).setDepth(51).setScrollFactor(0);

    this.add.text(pause.levelX, pause.y, this.levelConfig.id, {
      fontFamily: 'Arial, sans-serif',
      fontSize: `${pause.levelFontSize}px`,
      fontStyle: 'bold',
      color: '#ffffff'
    }).setOrigin(0, 0.5).setDepth(51).setScrollFactor(0);

    this.hudRegions.push(
      createCircleRegion('pause-button', { x: pause.x, y: pause.y, radius: pause.hitRadius }),
      createRectRegion('level-id', pause.levelRegion)
    );

    pauseButton.on('pointerdown', (_pointer, _localX, _localY, event) => {
      event?.stopPropagation();
      this.openPause();
    });
    this.escHandler = () => this.openPause();
    this.input.keyboard?.on('keydown-ESC', this.escHandler);
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => {
      this.input.keyboard?.off('keydown-ESC', this.escHandler);
    });
  }

  createScoreHud() {
    const { score, birds } = this.hudLayout;

    this.scoreText = this.add.text(score.x, score.y, 'SCORE: 0', {
      fontFamily: 'Arial, sans-serif',
      fontSize: `${score.fontSize}px`,
      fontStyle: 'bold',
      color: '#ffffff',
      stroke: '#1f2933',
      strokeThickness: 4
    }).setOrigin(1, 0.5).setDepth(20).setScrollFactor(0);
    this.birdsText = this.add.text(birds.x, birds.y, `BIRDS: ${this.birdsLeft}`, {
      fontFamily: 'Arial, sans-serif',
      fontSize: `${birds.fontSize}px`,
      fontStyle: 'bold',
      color: '#ffffff',
      stroke: '#1f2933',
      strokeThickness: 4
    }).setOrigin(1, 0.5).setDepth(20).setScrollFactor(0);
    this.hudRegions.push(
      createRectRegion('score', score.region),
      createRectRegion('birds-remaining', birds.region)
    );
  }

  createHudLayout() {
    const gameSize = this.scale?.gameSize ?? {};
    const displaySize = this.scale?.displaySize ?? {};
    const canvasBounds = this.game?.canvas?.getBoundingClientRect?.() ?? {};

    return resolveHudLayout({
      gameWidth: gameSize.width,
      gameHeight: gameSize.height,
      displayWidth: displaySize.width ?? canvasBounds.width,
      displayHeight: displaySize.height ?? canvasBounds.height
    });
  }

  updateScoreHud() {
    this.scoreText?.setText(`SCORE: ${this.score.toLocaleString('en-US')}`);
  }

  updateBirdsHud() {
    this.birdsText?.setText(`BIRDS: ${this.birdsLeft}`);
  }

  getHudInputRegions() {
    return this.hudRegions;
  }

  openPause() {
    if (this.pausedForOverlay || this.levelEnded) {
      return;
    }

    this.pausedForOverlay = true;
    this.slingshot?.cancelDrag();
    this.matter.world.pause();
    this.suspendActiveAudio();
    this.scene.launch('PauseOverlay', {
      levelId: this.levelConfig.id
    });
    this.scene.pause();
    this.refreshDebug();
  }

  preparePauseOverlayExit({ resumeAudio = false } = {}) {
    if (!this.pausedForOverlay) {
      return;
    }

    this.pausedForOverlay = false;
    this.matter.world.resume();
    if (resumeAudio) {
      this.resumeActiveAudio();
    } else {
      this.stopActiveAudio();
    }
    this.refreshDebug();
  }

  resumeFromPauseOverlay() {
    this.preparePauseOverlayExit({ resumeAudio: true });
    this.scene.resume('Game');
    this.scene.stop('PauseOverlay');
    this.refreshDebug();
  }

  isSlingshotPaused() {
    return this.pausedForOverlay;
  }

  handleBirdLaunched(bird, launch) {
    this.birdsLaunched += 1;
    this.flyingBird = bird.getDebugState({ canDrag: false });
    this.followLaunchedBird?.(bird);
    this.recordAudioEvent(SLINGSHOT_SFX.release);
    const flightAudioEvent = bird.getFlightAudioEvent?.();
    if (flightAudioEvent) {
      this.recordAudioEvent(flightAudioEvent);
    }
    this.lastLaunch = launch;
    this.physicsSystem?.markLaunched(this.time.now);
    this.refreshDebug();
  }

  handleBirdResolved(reason) {
    this.lastResolveReason = reason;
    this.recenterCameraOnSlingshot?.();
    this.evaluateLevelEnd();
    this.refreshDebug();
  }

  handlePigDefeated({ reason, pigsLeft }) {
    this.pigsLeft = pigsLeft;
    this.lastPigDefeatReason = reason;

    if (pigsLeft > 0 || this.levelEnded) {
      this.refreshDebug();
      return;
    }

    this.refreshDebug();
  }

  addScore(points) {
    this.score = Math.max(0, Math.floor(this.score + (Number(points) || 0)));
    this.updateScoreHud();
    this.refreshDebug();
  }

  recordLevelClear({
    score = this.score,
    stars
  } = {}) {
    this.save = this.persistence.recordLevelClear({
      levelId: this.levelConfig.id,
      score,
      stars
    });
    this.refreshDebug();
    return this.save;
  }

  applySoundMute(muted) {
    setGlobalSoundMute(this.sound, muted);
  }

  suspendActiveAudio() {
    if (typeof this.sound?.pauseAll === 'function') {
      this.sound.pauseAll();
      this.audioState.paused = true;
      return true;
    }

    const sounds = Array.isArray(this.sound?.sounds) ? this.sound.sounds : [];
    const pausedAny = sounds.reduce((didPause, sound) => {
      if (typeof sound?.pause === 'function' && sound.isPlaying !== false) {
        sound.pause();
        return true;
      }

      return didPause;
    }, false);

    this.audioState.paused = pausedAny;
    return pausedAny;
  }

  resumeActiveAudio() {
    if (typeof this.sound?.resumeAll === 'function') {
      this.sound.resumeAll();
      this.audioState.paused = false;
      return true;
    }

    const sounds = Array.isArray(this.sound?.sounds) ? this.sound.sounds : [];
    const resumedAny = sounds.reduce((didResume, sound) => {
      if (typeof sound?.resume === 'function' && sound.isPaused !== false) {
        sound.resume();
        return true;
      }

      return didResume;
    }, false);

    this.audioState.paused = false;
    return resumedAny;
  }

  stopActiveAudio() {
    if (typeof this.sound?.stopAll === 'function') {
      this.sound.stopAll();
      this.audioState.paused = false;
      return true;
    }

    const sounds = Array.isArray(this.sound?.sounds) ? this.sound.sounds : [];
    const stoppedAny = sounds.reduce((didStop, sound) => {
      if (typeof sound?.stop === 'function') {
        sound.stop();
        return true;
      }

      return didStop;
    }, false);

    this.audioState.paused = false;
    return stoppedAny;
  }

  setMute(muted) {
    const nextMuted = Boolean(muted);

    this.audioState.muted = nextMuted;
    this.save = this.persistence.setMute(nextMuted);
    this.applySoundMute(nextMuted);
    this.events.emit('mute-changed', nextMuted);
    this.refreshDebug();
    return this.save;
  }

  recordAudioEvent(eventName) {
    if (!eventName) {
      return;
    }

    this.audioState.lastEvent = eventName;
    this.audioState.recentEvents = [
      ...this.audioState.recentEvents,
      { key: eventName, t: this.time.now }
    ].slice(-64);
    this.playAudioEvent?.(eventName);
  }

  playAudioEvent(eventName) {
    const hasLoadedAudio = this.cache?.audio?.exists?.(eventName) ?? false;

    if (!hasLoadedAudio || typeof this.sound?.play !== 'function') {
      return false;
    }

    try {
      this.sound.play(eventName, { volume: GAMEPLAY_SFX_VOLUME });
      return true;
    } catch {
      return false;
    }
  }

  recordAbilityEvent(eventName) {
    this.audioState.lastAbilityEvent = eventName;
    this.recordAudioEvent(eventName);
  }

  update(time) {
    this.slingshot?.update(time);
    this.physicsSystem?.update(time);
    this.evaluateLevelEnd();
    this.refreshDebug();
  }

  getRemainingBirdCount() {
    return this.slingshot?.getQueueDebug().length ?? this.birdsLeft ?? 0;
  }

  evaluateLevelEnd() {
    if (this.levelEnded) {
      return null;
    }

    this.pigsLeft = this.physicsSystem?.pigs?.filter((pig) => !pig.defeated).length ?? this.pigsLeft;
    const birdsLeft = this.getRemainingBirdCount();
    const outcome = resolveLevelOutcome({
      settled: this.settled,
      pigsLeft: this.pigsLeft,
      birdsLeft
    });

    if (outcome === 'cleared') {
      this.showClearedCard(birdsLeft);
    } else if (outcome === 'failed') {
      this.showFailedCard();
    }

    return outcome;
  }

  showClearedCard(unusedBirdCount) {
    this.levelEnded = true;
    const result = buildClearResult({
      levelId: this.levelConfig.id,
      baseScore: this.score,
      unusedBirdCount,
      save: this.save
    });
    const persistedSave = this.persistence.replaceSave(result.save);

    this.score = result.finalScore;
    this.save = persistedSave;
    result.save = persistedSave;
    this.updateScoreHud();
    this.recordAudioEvent(END_STATE_SFX.cleared);
    this.refreshDebug();
    this.pauseForEndCard();
    this.scene.launch('ClearedCard', {
      ...result,
      actions: getClearedCardActions({
        levelId: this.levelConfig.id,
        save: this.save
      }),
      birdsLaunched: this.birdsLaunched,
      initialBirdCount: this.initialBirdCount
    });
    this.scene.pause();
  }

  showFailedCard() {
    this.levelEnded = true;
    this.recordAudioEvent(END_STATE_SFX.failed);
    this.refreshDebug();
    this.pauseForEndCard();
    this.scene.launch('FailedCard', {
      levelId: this.levelConfig.id,
      score: this.score,
      save: this.save,
      pigsLeft: this.pigsLeft,
      actions: getFailedCardActions(this.levelConfig.id)
    });
    this.scene.pause();
  }

  pauseForEndCard() {
    this.slingshot?.cancelDrag();
    this.input.enabled = false;
    this.matter.world.pause();
  }

  refreshDebug() {
    const slingshotDebug = this.slingshot?.getDebugState() ?? {
      anchor: this.levelConfig?.anchor ?? { x: 0, y: 0 },
      clampRadius: SLINGSHOT.clampRadius
    };

    this.queue = this.slingshot?.getQueueDebug() ?? this.queue ?? [];
    this.bird = this.slingshot?.getBirdDebugState() ?? null;
    this.flyingBird = this.slingshot?.getFlyingBirdDebugState() ?? null;
    this.birdsLeft = this.queue.length;
    this.updateBirdsHud();
    const physicsDebug = this.physicsSystem?.getDebugState() ?? {
      blocks: [],
      pigs: [],
      settled: null
    };

    const mainCamera = this.cameras?.main;

    registerDebugScene(this, {
      scene: {
        score: this.score,
        birdsLeft: this.birdsLeft,
        pigsLeft: this.pigsLeft,
        settled: this.settled,
        queue: this.queue,
        flyingBird: this.flyingBird,
        threeStarThreshold: this.threeStarThreshold,
        bird: this.bird,
        slingshot: slingshotDebug,
        aimTrail: this.slingshot?.getAimTrailDebug() ?? [],
        renderedQueue: slingshotDebug.renderedQueue ?? [],
        paused: this.pausedForOverlay,
        levelId: this.levelConfig.id,
        tntCrates: this.tntCrates?.map((crate) => crate.getDebugState?.() ?? crate) ?? [],
        boulders: this.boulders?.map((boulder) => boulder.getDebugState?.() ?? boulder) ?? [],
        mounds: this.levelConfig.mounds ?? [],
        platforms: this.levelConfig.platforms ?? [],
        cameraWide: this.levelConfig.cameraWide,
        slingshotElevated: this.levelConfig.slingshotElevated,
        ground: { y: this.levelConfig.groundY },
        cameras: {
          main: {
            bounds: {
              width: this.levelConfig.levelWidth,
              height: 720
            },
            scrollX: mainCamera?.scrollX ?? 0,
            scrollY: mainCamera?.scrollY ?? 0,
            mode: this.cameraState?.mode ?? 'fixed',
            following: this.cameraState?.following ?? false,
            target: this.cameraState?.target ?? null,
            center: this.cameraState?.center ?? null,
            lastFollowStartedAt: this.cameraState?.lastFollowStartedAt ?? null,
            lastRecenteredAt: this.cameraState?.lastRecenteredAt ?? null
          }
        },
        lastResolveReason: this.lastResolveReason ?? null,
        lastSettleReason: this.lastSettleReason ?? null,
        lastPigDefeatReason: this.lastPigDefeatReason ?? null,
        lastMatildaEggExplosion: this.lastMatildaEggExplosion ?? null,
        lastMatildaBlockContact: this.lastMatildaBlockContact ?? null,
        lastBombExplosion: this.lastBombExplosion ?? null,
        lastTntExplosion: this.lastTntExplosion ?? null,
        lastBombWoodContact: this.lastBombWoodContact ?? null,
        blocks: physicsDebug.blocks,
        pigs: physicsDebug.pigs,
        tntDebug: physicsDebug.tntCrates ?? [],
        boulderDebug: physicsDebug.boulders ?? [],
        eggs: physicsDebug.eggs ?? [],
        physics: physicsDebug
      },
      slingshot: slingshotDebug,
      save: this.save,
      audio: this.audioState
    });
  }
}
