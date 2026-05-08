import Phaser from 'phaser';

import { BIRD_SPRITE_FRAMES } from '../constants/assets.js';
import { registerDebugScene } from '../systems/debug.js';
import { getPersistence } from '../systems/persistence.js';
import { setGlobalSoundMute } from '../systems/soundMute.js';

export default class Menu extends Phaser.Scene {
  constructor() {
    super('Menu');
  }

  create() {
    if (typeof document !== 'undefined') {
      document.title = 'Angry Birds Web Game';
    }

    this.persistence = getPersistence();
    this.save = this.persistence.loadSave();
    this.audioState = {
      lastEvent: null,
      lastAbilityEvent: null,
      muted: this.save.mute,
      recentEvents: []
    };
    this.applySoundMute(this.audioState.muted);

    this.add.rectangle(640, 360, 1280, 720, 0x7ec8e3);
    this.add.rectangle(640, 672, 1280, 96, 0x2f7d32);
    this.add.sprite(382, 374, 'bird-red', BIRD_SPRITE_FRAMES.idleCry)
      .setDisplaySize(96, 96);
    this.add.text(640, 278, 'Angry Birds', {
      fontFamily: 'Arial, sans-serif',
      fontSize: '64px',
      color: '#ffffff'
    }).setOrigin(0.5);

    const playButton = this.add.rectangle(640, 392, 220, 72, 0xf8d24a)
      .setStrokeStyle(4, 0x1f2933)
      .setInteractive({ useHandCursor: true });
    this.add.text(640, 392, 'Play', {
      fontFamily: 'Arial, sans-serif',
      fontSize: '34px',
      fontStyle: 'bold',
      color: '#1f2a32'
    }).setOrigin(0.5);

    this.muteButton = this.add.rectangle(640, 482, 220, 56, 0xf6f0d0)
      .setStrokeStyle(4, 0x1f2933)
      .setInteractive({ useHandCursor: true });
    this.muteText = this.add.text(640, 482, '', {
      fontFamily: 'Arial, sans-serif',
      fontSize: '22px',
      fontStyle: 'bold',
      color: '#1f2a32'
    }).setOrigin(0.5);
    this.refreshMuteText();

    playButton.on('pointerdown', () => {
      this.scene.start('EpisodeSelect');
    });
    this.muteButton.on('pointerdown', () => this.toggleMute());

    this.refreshDebug();
  }

  applySoundMute(muted) {
    setGlobalSoundMute(this.sound, muted);
  }

  toggleMute() {
    const muted = !this.audioState.muted;
    this.save = this.persistence.setMute(muted);
    this.audioState.muted = this.save.mute;
    this.applySoundMute(this.audioState.muted);
    this.refreshMuteText();
    this.refreshDebug();
  }

  refreshMuteText() {
    this.muteText?.setText(`Mute: ${this.audioState?.muted ? 'On' : 'Off'}`);
  }

  refreshDebug() {
    registerDebugScene(this, {
      save: this.save,
      audio: this.audioState,
      mute: this.audioState?.muted ?? false
    });
  }
}
