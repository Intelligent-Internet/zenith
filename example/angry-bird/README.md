# Angry Birds Web Game

A browser clone of the classic slingshot-physics game, built with Phaser 3.90 + Matter.js + Vite. Six birds, three episodes, 15 levels, original art and audio.

## Quickstart

```bash
npm install
npm run dev      # http://127.0.0.1:4100
```

| Command | What it does |
| --- | --- |
| `npm run dev` | Vite dev server on port 4100. `ANGRY_BIRD_DEV=1` exposes `window.__GAME__` for debug. |
| `npm run build` | Production build to `dist/`. |
| `npm run preview` | Preview the prod build on port 4101. |
| `npm test` | Vitest suite (44 files, 179 tests). |
| `npm run lint` | ESLint flat config across the repo. |

The dev server auto-sets `ANGRY_BIRD_DEV=1`; the prod preview does not. URL params `?level=<id>` jump straight into a level (dev only) and `?roster=1` opens the debug roster screen.

## Stack

- **Phaser 3.90** with bundled Matter.js for physics
- **Vite 6** dev/build (envPrefix: `VITE_`, `ANGRY_BIRD_`)
- **Vanilla JavaScript** (ES modules, 2-space indent, explicit `.js` extensions)
- **Vitest 1.x** for unit tests
- **ESLint** flat config — zero warnings policy

## Game content

### Birds

| Type | Ability (tap after launch) |
| --- | --- |
| Red | none |
| Blues | splits into three |
| Chuck | speed burst |
| Matilda | drops an explosive egg |
| Bomb | timed explosion |
| Hal | boomerang return |

Material affinities (e.g., Chuck vs glass, Bomb vs stone, Matilda vs wood) are tabulated in `src/constants/birds.js`.

### Levels

15 levels across 3 episodes, declared as JSON in `src/data/levels/<episode>-<level>.json`. The unlock graph is computed from `save.cleared` (no flat unlock list), so a wiped or partial save resolves correctly.

### Materials

Wood, glass, and stone blocks plus TNT. HP, score values, and break-particle keys live in `src/constants/materials.js`. Scoring thresholds for 1/2/3 stars per level are in `src/constants/scoring.js`.

### Audio

All SFX are original or CC0 sources. Autoplay is blocked until first user gesture; audio resumes via `src/systems/audioUnlock.js`.

## Project layout

```
src/
├── main.js                 Phaser.Game config + scene list
├── scenes/                 Boot, Preloader, Menu, EpisodeSelect, LevelSelect,
│                           Game, PauseOverlay, ClearedCard, FailedCard, ...
├── entities/               Bird, Pig, Block, TNT, Slingshot, Boulder
├── systems/                physics, scoring, progression, persistence,
│                           audio*, debug, inputRouter, bootRoute, winLose
├── data/levels/*.json      15 level definitions
├── constants/              birds, materials, scoring tables
└── utils/                  aim, dhash, math (pure helpers)
public/assets/{images,audio}    original sprites + SFX
tests/{unit,strategies,fixtures,e2e}
scripts/                    check_*.sh integrity gates + run_strategy.js
```

## Persistence

Save key: `angry-bird-save-v1` in `localStorage`.

```json
{
  "schemaVersion": 1,
  "cleared": ["1-01", "1-02"],
  "bestScore": { "1-01": 33000 },
  "bestStars": { "1-01": 3 },
  "mute": false
}
```

## Dev hooks

When the dev server runs with `ANGRY_BIRD_DEV=1`, `window.__GAME__` exposes:

- `__GAME__.scene` — current scene (`levelId`, `bird`, `slingshot`, `pigsLeft`, `score`, `endCard`, ...)
- `__GAME__.save` — current save snapshot
- `__GAME__.audio.recentEvents` — ring buffer of recent SFX keys (validator hook)
- `__GAME__.debug.*` — layout/state inspectors (e.g. `episodeSelectDOM()`)

No god-mode helpers (no `killAllPigs()`); the slingshot must be driven through the public input surface.

## Strategy runner

Every level ships a deterministic strategy at `tests/strategies/<level>.json` that proves clearability through the public surface. Replay one or all:

```bash
node scripts/run_strategy.js 1-01                          # one level
for l in 1-01 1-02 ... 3-05; do node scripts/run_strategy.js "$l"; done
```

The runner uses `agent-browser` (Playwright) under the hood and asserts the cleared end-card state plus `pigsLeft === 0`. It seeds `localStorage` *before* navigating to `?level=<id>` so the boot route is parsed exactly once.


## License & usage

**This project is for research and educational purposes only. It is not for distribution, public hosting, or any commercial use.**

"Angry Birds" and all related characters, names, marks, and creative elements are trademarks and copyrighted works of Rovio Entertainment Corporation. This repository is an unofficial, non-commercial reimplementation. Any use of this codebase that touches the Angry Birds brand — including the bird/pig character names, silhouettes, or game design — must comply with Rovio's intellectual-property terms. We claim no affiliation with or endorsement by Rovio.

Concretely:

- Do **not** publish, host, or distribute builds of this game to end users.
- Do **not** sell, sublicense, or monetize this code or any derivative.
- The original sprites and audio under `public/assets/` were generated/synthesized for this project; they are research artifacts and inherit the same research-only restriction — they do not grant rights to the underlying Angry Birds IP.

If you fork this for your own research, retain this section verbatim and keep the originality gates in CI. For any use beyond research or education, you must obtain the appropriate license from Rovio Entertainment Corporation.
