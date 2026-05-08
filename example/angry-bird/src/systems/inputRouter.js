export const INPUT_TARGETS = Object.freeze({
  blocked: 'blocked',
  hud: 'hud',
  slingshot: 'slingshot',
  ability: 'ability',
  canvas: 'canvas'
});

function valueFrom(source, fallback) {
  return typeof source === 'function' ? source() : (source ?? fallback);
}

export function createRectRegion(id, {
  x,
  y,
  width,
  height
}) {
  return {
    id,
    type: 'rect',
    x,
    y,
    width,
    height
  };
}

export function createCircleRegion(id, {
  x,
  y,
  radius
}) {
  return {
    id,
    type: 'circle',
    x,
    y,
    radius
  };
}

export function pointInRegion(point, region) {
  if (!point || !region) {
    return false;
  }

  if (region.type === 'circle') {
    return Math.hypot(point.x - region.x, point.y - region.y) <= region.radius;
  }

  return (
    point.x >= region.x
    && point.x <= region.x + region.width
    && point.y >= region.y
    && point.y <= region.y + region.height
  );
}

function findRegion(point, regions) {
  return regions.find((region) => pointInRegion(point, region)) ?? null;
}

export function createInputRouter({
  isPaused = () => false,
  hudRegions = []
} = {}) {
  return {
    routePointerDown({
      screenPoint,
      worldPoint,
      slingshot = {},
      ability = {}
    } = {}) {
      if (valueFrom(isPaused, false)) {
        return { target: INPUT_TARGETS.blocked };
      }

      const region = findRegion(screenPoint, valueFrom(hudRegions, []));
      if (region) {
        return {
          target: INPUT_TARGETS.hud,
          regionId: region.id
        };
      }

      if (slingshot.canDrag && slingshot.hit) {
        return {
          target: INPUT_TARGETS.slingshot,
          point: worldPoint
        };
      }

      if (ability.canFire) {
        return {
          target: INPUT_TARGETS.ability,
          point: worldPoint
        };
      }

      return {
        target: INPUT_TARGETS.canvas,
        point: worldPoint
      };
    }
  };
}
