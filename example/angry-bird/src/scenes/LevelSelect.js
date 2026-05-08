import Phaser from 'phaser';

import {
  EPISODE_HERO_TITLES,
  getEpisodeBackgroundKey,
  getEpisodeHeroKey
} from '../constants/assets.js';
import { registerDebugScene } from '../systems/debug.js';
import { loadLevelConfig } from '../systems/levelLoader.js';
import { getPersistence } from '../systems/persistence.js';
import { computeUnlocks } from '../systems/progression.js';
import { buildLevelSelectCards } from '../systems/selectScreenModels.js';

export default class LevelSelect extends Phaser.Scene {
  constructor() {
    super('LevelSelect');
  }

  init(data = {}) {
    this.episode = data.episode ?? 1;
  }

  create() {
    this.persistence = getPersistence();
    this.save = this.persistence.loadSave();
    this.unlocks = computeUnlocks(this.save);
    this.levelCards = buildLevelSelectCards(this.episode, this.save, this.unlocks);

    this.drawBackdrop();
    this.renderHeader();
    this.renderBackButton();
    this.renderLevelCards();
    this.input.off('pointerdown', this.handlePointerDown, this);
    this.input.on('pointerdown', this.handlePointerDown, this);
    this.refreshDebug();
  }

  drawBackdrop() {
    this.add.image(0, 0, getEpisodeBackgroundKey(`${this.episode}-01`))
      .setOrigin(0)
      .setDisplaySize(1280, 720)
      .setDepth(-30);
    this.add.rectangle(640, 360, 1280, 720, 0x0f513d, 0.14).setDepth(-29);
    this.add.rectangle(640, 684, 1280, 88, 0x2f7d32, 0.88).setDepth(-28);
  }

  renderHeader() {
    this.add.image(390, 168, getEpisodeHeroKey(this.episode))
      .setDisplaySize(142, 142)
      .setDepth(4);
    this.add.text(640, 102, EPISODE_HERO_TITLES[this.episode] ?? `Episode ${this.episode}`, {
      fontFamily: 'Arial, sans-serif',
      fontSize: '48px',
      fontStyle: 'bold',
      color: '#ffffff',
      stroke: '#173b32',
      strokeThickness: 7
    }).setOrigin(0.5).setDepth(5);
    this.add.text(640, 158, 'Choose a level', {
      fontFamily: 'Arial, sans-serif',
      fontSize: '25px',
      fontStyle: 'bold',
      color: '#f6f0d0',
      stroke: '#173b32',
      strokeThickness: 4
    }).setOrigin(0.5).setDepth(5);
  }

  renderBackButton() {
    const button = this.add.circle(80, 638, 40, 0xf8d24a, 1)
      .setStrokeStyle(4, 0xffffff)
      .setInteractive({ useHandCursor: true })
      .setDepth(20);
    const arrow = this.add.text(78, 635, '<', {
      fontFamily: 'Arial, sans-serif',
      fontSize: '48px',
      fontStyle: 'bold',
      color: '#1f2933'
    }).setOrigin(0.5).setDepth(21);

    button.on('pointerdown', () => this.scene.start('EpisodeSelect'));
    arrow.setInteractive({ useHandCursor: true });
    arrow.on('pointerdown', () => this.scene.start('EpisodeSelect'));
  }

  renderLevelCards() {
    this.cardLayer?.destroy(true);
    this.cardLayer = this.add.container(0, 0);
    this.lockedCardFeedbacks = [];

    this.levelCards.forEach((card) => {
      this.drawLevelCard(card);
    });
  }

  drawLevelCard(card) {
    const container = this.add.container(card.x, card.y).setDepth(8);
    const body = this.add.graphics();
    const left = -card.width / 2;
    const top = -card.height / 2;
    const fill = card.locked ? 0x51606c : (card.cleared ? 0xf8d24a : 0xf6f0d0);

    body.fillStyle(fill, 1);
    body.lineStyle(4, 0x0d2433, 1);
    body.fillRoundedRect(left, top, card.width, card.height, 8);
    body.strokeRoundedRect(left, top, card.width, card.height, 8);

    const levelLabel = this.add.text(0, -48, card.levelId, {
      fontFamily: 'Arial, sans-serif',
      fontSize: '32px',
      fontStyle: 'bold',
      color: '#1f2933'
    }).setOrigin(0.5);
    const score = this.add.text(0, -4, card.bestScoreText, {
      fontFamily: 'Arial, sans-serif',
      fontSize: '17px',
      fontStyle: 'bold',
      color: '#1f2933'
    }).setOrigin(0.5);
    const stars = this.add.text(0, 27, card.bestStarsText, {
      fontFamily: 'Arial, sans-serif',
      fontSize: '21px',
      fontStyle: 'bold',
      color: '#1f2933'
    }).setOrigin(0.5);
    const status = this.add.text(0, 62, card.statusText, {
      fontFamily: 'Arial, sans-serif',
      fontSize: '18px',
      fontStyle: 'bold',
      color: card.cleared ? '#2f7d32' : (card.unlocked ? '#1f2933' : '#7f1d1d')
    }).setOrigin(0.5);

    container.add([body, levelLabel, score, stars, status]);
    container.setData('restingX', card.x);

    let lockFeedback = null;

    if (card.locked) {
      lockFeedback = this.addLockedOverlay(container, card);
      container.setAlpha(0.72);
    }

    this.cardLayer.add(container);

    if (card.canStart) {
      const hitArea = this.add.rectangle(card.x, card.y, card.width, card.height, 0xffffff, 0.001)
        .setInteractive({ useHandCursor: true })
        .setDepth(30);
      hitArea.on('pointerdown', () => {
        this.scene.start('Game', {
          level: card.levelId,
          levelConfig: loadLevelConfig(card.levelId)
        });
      });
      this.cardLayer.add(hitArea);
    } else {
      this.addLockedHitArea(card, container, lockFeedback);
    }
  }

  addLockedOverlay(container, card) {
    const overlay = this.add.rectangle(0, 0, card.width - 10, card.height - 10, 0x000000, 0.26);
    const lock = this.add.graphics();

    lock.lineStyle(5, 0xf8d24a, 0.98);
    lock.beginPath();
    lock.arc(0, -2, 20, Math.PI, 0, false);
    lock.strokePath();
    lock.fillStyle(0xf8d24a, 0.98);
    lock.fillRoundedRect(-23, -2, 46, 36, 6);
    lock.fillStyle(0x1f2933, 1);
    lock.fillCircle(0, 12, 4);
    lock.fillRect(-2, 14, 4, 10);
    const feedback = this.add.graphics().setVisible(false);

    feedback.fillStyle(0xf8d24a, 0.3);
    feedback.fillRoundedRect(
      -card.width / 2 + 5,
      -card.height / 2 + 5,
      card.width - 10,
      card.height - 10,
      8
    );
    feedback.lineStyle(6, 0xf8d24a, 1);
    feedback.strokeRoundedRect(
      -card.width / 2 + 5,
      -card.height / 2 + 5,
      card.width - 10,
      card.height - 10,
      8
    );

    container.add([overlay, lock, feedback]);
    return feedback;
  }

  addLockedHitArea(card, container, feedback) {
    this.lockedCardFeedbacks.push({ card, container, feedback });

    const triggerFeedback = () => {
      this.playLockedFeedback(container, feedback);
    };

    container.setSize(card.width, card.height);
    container.setInteractive(
      new Phaser.Geom.Rectangle(-card.width / 2, -card.height / 2, card.width, card.height),
      Phaser.Geom.Rectangle.Contains
    );
    container.on('pointerdown', triggerFeedback);
    container.on('pointerup', triggerFeedback);

    const hitArea = this.add.rectangle(card.x, card.y, card.width, card.height, 0xffffff, 0.001)
      .setInteractive({ useHandCursor: true })
      .setDepth(30);

    hitArea.on('pointerdown', triggerFeedback);
    hitArea.on('pointerup', triggerFeedback);
    this.cardLayer.add(hitArea);
  }

  handlePointerDown(pointer) {
    const hit = this.lockedCardFeedbacks.find(({ card }) => (
      pointer.x >= card.x - card.width / 2
        && pointer.x <= card.x + card.width / 2
        && pointer.y >= card.y - card.height / 2
        && pointer.y <= card.y + card.height / 2
    ));

    if (hit) {
      this.playLockedFeedback(hit.container, hit.feedback);
    }
  }

  playLockedFeedback(container, feedback) {
    const restingX = container.getData('restingX') ?? container.x;
    const previousShake = container.getData('lockShakeTween');

    previousShake?.stop();
    container.setX(restingX);

    if (feedback) {
      this.tweens.killTweensOf(feedback);
      feedback.setVisible(true).setAlpha(1);
      this.tweens.add({
        targets: feedback,
        alpha: 0.18,
        duration: 900,
        ease: 'Quad.easeOut',
        onComplete: () => {
          feedback.setVisible(false).setAlpha(1);
        }
      });
    }

    const shake = this.tweens.addCounter({
      from: 0,
      to: 1,
      duration: 330,
      ease: 'Sine.easeInOut',
      onUpdate: (tween) => {
        container.setX(restingX + Math.sin(tween.getValue() * Math.PI * 8) * 9);
      },
      onComplete: () => {
        container.setX(restingX);
        container.setData('lockShakeTween', null);
      }
    });
    container.setData('lockShakeTween', shake);
  }

  refreshDebug() {
    registerDebugScene(this, {
      save: this.save,
      mute: this.save?.mute ?? false,
      scene: {
        levelSelect: {
          episode: this.episode,
          cards: this.levelCards
        }
      }
    });
  }
}
