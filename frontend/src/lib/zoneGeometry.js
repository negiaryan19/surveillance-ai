/**
 * Pure geometry for the zone editor. Rectangles are `{x1, y1, x2, y2}` normalised to 0..1
 * of the frame, matching the backend's `rect: [x1, y1, x2, y2]` (x1 < x2, y1 < y2).
 */
import { clamp } from './format.js';

/** Smallest zone the editor will create or shrink to (2% of the frame on each axis). */
export const MIN_SIZE = 0.02;
export const MAX_ZONES = 12;
export const ZONE_ID_PATTERN = /^[A-Za-z0-9_-]{1,32}$/;

/** Fresh client-side id the backend will keep (it accepts ids matching ZONE_ID_PATTERN). */
export function newZoneId() {
  return `z${Date.now().toString(36)}${Math.floor(Math.random() * 46656).toString(36)}`;
}

export function rectFromArray(rect) {
  const [x1, y1, x2, y2] = Array.isArray(rect) ? rect.map(Number) : [0, 0, 0, 0];
  return { x1, y1, x2, y2 };
}

export function rectToArray({ x1, y1, x2, y2 }) {
  return [x1, y1, x2, y2].map((value) => Number(value.toFixed(4)));
}

/** Order the corners and keep the rectangle inside the frame; enforce the minimum size. */
export function normaliseRect({ x1, y1, x2, y2 }) {
  let left = clamp(Math.min(x1, x2), 0, 1);
  let right = clamp(Math.max(x1, x2), 0, 1);
  let top = clamp(Math.min(y1, y2), 0, 1);
  let bottom = clamp(Math.max(y1, y2), 0, 1);
  if (right - left < MIN_SIZE) {
    right = Math.min(1, left + MIN_SIZE);
    left = right - MIN_SIZE;
  }
  if (bottom - top < MIN_SIZE) {
    bottom = Math.min(1, top + MIN_SIZE);
    top = bottom - MIN_SIZE;
  }
  return { x1: left, y1: top, x2: right, y2: bottom };
}

export function isBigEnough({ x1, y1, x2, y2 }) {
  return Math.abs(x2 - x1) >= MIN_SIZE && Math.abs(y2 - y1) >= MIN_SIZE;
}

/** Translate by (dx, dy), stopping at the frame edge without changing the size. */
export function moveRect(rect, dx, dy) {
  const width = rect.x2 - rect.x1;
  const height = rect.y2 - rect.y1;
  const x1 = clamp(rect.x1 + dx, 0, 1 - width);
  const y1 = clamp(rect.y1 + dy, 0, 1 - height);
  return { x1, y1, x2: x1 + width, y2: y1 + height };
}

/**
 * Drag one handle by (dx, dy). `handle` is a compass direction: "n", "s", "e", "w", "ne", ...
 * The opposite edge stays put; the dragged edge cannot cross it.
 */
export function resizeRect(rect, handle, dx, dy) {
  const next = { ...rect };
  if (handle.includes('w')) next.x1 = clamp(rect.x1 + dx, 0, rect.x2 - MIN_SIZE);
  if (handle.includes('e')) next.x2 = clamp(rect.x2 + dx, rect.x1 + MIN_SIZE, 1);
  if (handle.includes('n')) next.y1 = clamp(rect.y1 + dy, 0, rect.y2 - MIN_SIZE);
  if (handle.includes('s')) next.y2 = clamp(rect.y2 + dy, rect.y1 + MIN_SIZE, 1);
  return next;
}

/** Zone as sent to `PUT /api/zones/<camera_id>`. */
export function zoneToPayload(zone) {
  return { id: zone.id, name: zone.name.trim(), level: zone.level, rect: rectToArray(zone.rect) };
}

/** Zone as received from `GET /api/zones`, with the rect unpacked for editing. */
export function zoneFromPayload(raw, index) {
  const id = ZONE_ID_PATTERN.test(String(raw.id ?? '')) ? String(raw.id) : newZoneId();
  return {
    id,
    name: String(raw.name ?? `Zone ${index + 1}`),
    level: String(raw.level ?? 'WARNING'),
    rect: normaliseRect(rectFromArray(raw.rect)),
  };
}

/** True when the two lists would serialise identically (used for the "unsaved changes" state). */
export function sameZones(a, b) {
  if (a.length !== b.length) return false;
  return a.every((zone, index) => JSON.stringify(zoneToPayload(zone)) === JSON.stringify(zoneToPayload(b[index])));
}
