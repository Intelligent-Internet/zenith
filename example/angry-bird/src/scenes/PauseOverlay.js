import Phaser from 'phaser';

import { registerDebugScene } from '../systems/debug.js';
import { getEpisodeForLevel } from '../systems/winLose.js';
import { createButton } from './endCardHelpers.js';

export default class PauseOverlay extends Phaser.Scene {
  constructor() {
    super('PauseOverlay');
  }

  init(data = {}) {
    this.levelId = data.levelId ?? '1-01';
  }

  create() {
    this.add.zone(640, 360, 1280, 720)
      .setOrigin(0.5)
      .setInteractive();
    this.add.rectangle(640, 360, 1280, 720, 0x0f1720, 0.62);
    this.add.rectangle(640, 356, 420, 360, 0xf6f0d0, 0.98)
      .setStrokeStyle(5, 0x1f2933);
    this.add.text(640, 208, 'PAUSED', {
      fontFamily: 'Arial, sans-serif',
      fontSize: '44px',
      fontStyle: 'bold',
      color: '#1f2933'
    }).setOrigin(0.5);

    createButton(this, {
      x: 640,
      y: 286,
      label: 'Resume',
      width: 240,
      onClick: () => this.resumeGame()
    });
    createButton(this, {
      x: 640,
      y: 358,
      label: 'Retry',
      width: 240,
      onClick: () => this.retryLevel()
    });
    createButton(this, {
      x: 640,
      y: 430,
      label: 'Level Select',
      width: 240,
      onClick: () => this.openLevelSelect()
    });

    this.muteText = this.add.text(640, 502, '', {
      fontFamily: 'Arial, sans-serif',
      fontSize: '22px',
      fontStyle: 'bold',
      color: '#1f2933'
    }).setOrigin(0.5);
    createButton(this, {
      x: 640,
      y: 502,
      label: '',
      width: 240,
      onClick: () => this.toggleMute()
    });
    this.muteText.setDepth(2);
    this.refreshMuteText();

    this.escHandler = () => this.resumeGame();
    this.input.keyboard?.on('keydown-ESC', this.escHandler);
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => {
      this.input.keyboard?.off('keydown-ESC', this.escHandler);
    });
    this.refreshDebug();
  }

  getGameScene() {
    return this.scene.get('Game');
  }

  resumeGame() {
    this.getGameScene()?.resumeFromPauseOverlay();
  }

  navigateWithUrl(params) {
    if (typeof window === 'undefined') {
      return false;
    }

    const nextUrl = new window.URL(window.location.href);
    nextUrl.search = '';
    Object.entries(params).forEach(([key, value]) => {
      nextUrl.searchParams.set(key, value);
    });
    window.location.assign(nextUrl.toString());
    return true;
  }

  retryLevel() {
    const levelId = this.levelId;
    this.getGameScene()?.preparePauseOverlayExit();
    if (this.navigateWithUrl({ level: levelId })) {
      return;
    }

    this.scene.stop('Game');
    this.scene.start('Game', { level: levelId });
  }

  openLevelSelect() {
    const episode = getEpisodeForLevel(this.levelId);
    this.getGameScene()?.preparePauseOverlayExit();
    if (this.navigateWithUrl({ scene: 'LevelSelect', episode })) {
      return;
    }

    this.scene.stop('Game');
    this.scene.start('LevelSelect', { episode });
  }

  toggleMute() {
    const gameScene = this.getGameScene();
    if (!gameScene) {
      return;
    }

    const muted = !gameScene.audioState.muted;
    gameScene.setMute(muted);
    this.refreshMuteText();
    this.refreshDebug();
  }

  refreshMuteText() {
    const muted = Boolean(this.getGameScene()?.audioState?.muted);
    this.muteText?.setText(`Mute: ${muted ? 'On' : 'Off'}`);
  }

  update() {
    this.refreshDebug();
  }

  refreshDebug() {
    const gameScene = this.getGameScene();
    const slingshotDebug = gameScene?.slingshot?.getDebugState();

    registerDebugScene(this, {
      scene: {
        score: gameScene?.score ?? 0,
        birdsLeft: gameScene?.getRemainingBirdCount?.() ?? 0,
        pigsLeft: gameScene?.pigsLeft ?? 0,
        settled: gameScene?.settled ?? true,
        queue: gameScene?.queue ?? [],
        flyingBird: gameScene?.slingshot?.getFlyingBirdDebugState?.() ?? null,
        bird: gameScene?.slingshot?.getBirdDebugState?.() ?? null,
        slingshot: slingshotDebug,
        paused: true,
        threeStarThreshold: gameScene?.threeStarThreshold ?? {}
      },
      slingshot: slingshotDebug,
      save: gameScene?.save,
      audio: gameScene?.audioState,
      mute: gameScene?.audioState?.muted ?? false
    });
  }
}
