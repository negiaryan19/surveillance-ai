/** Display helpers shared by several components. Pure functions only. */

/** Zone levels in ascending priority; mirrors `LEVELS` in Backend/src/zones.py. */
export const ZONE_LEVELS = ['SAFE', 'PERIMETER', 'WARNING', 'CRITICAL'];

/** Same boundary the backend uses for the CRITICAL category. */
export const CRITICAL_SCORE = 70;
const WARNING_SCORE = 30;

/** Milliseconds since the epoch for a UTC ISO string, or null when unparseable. */
export function parseTimestamp(iso) {
  const ms = Date.parse(iso ?? '');
  return Number.isNaN(ms) ? null : ms;
}

/** Backend timestamps are UTC ISO-8601; render them in the viewer's own locale and zone. */
export function formatDateTime(iso) {
  const ms = parseTimestamp(iso);
  if (ms === null) return iso || 'Unknown';
  return new Date(ms).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'medium' });
}

export function formatTime(iso) {
  const ms = parseTimestamp(iso);
  if (ms === null) return iso || 'Unknown';
  return new Date(ms).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

/** Hour label for chart axes, e.g. "14:00" (or "2 PM" in 12-hour locales). */
export function formatHour(iso) {
  const ms = parseTimestamp(iso);
  if (ms === null) return '';
  return new Date(ms).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

/** "low" | "warning" | "critical" - drives the colour of threat badges. */
export function threatTone(score) {
  const value = Number(score) || 0;
  if (value >= CRITICAL_SCORE) return 'critical';
  if (value >= WARNING_SCORE) return 'warning';
  return 'low';
}

/** "Person - Aryan Negi" when the incident carries a recognised identity. */
export function incidentTitle(incident) {
  const object = incident?.object_type || 'Unknown object';
  return incident?.identity ? `${object} - ${incident.identity}` : object;
}

/** Camera display name for an id, falling back to the upper-cased id the backend also uses. */
export function cameraName(cameras, id) {
  if (!id) return 'N/A';
  return cameras.find((camera) => camera.id === id)?.name ?? id.toUpperCase();
}

export function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}
