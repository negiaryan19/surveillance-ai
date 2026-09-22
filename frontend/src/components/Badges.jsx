import { threatTone } from '../lib/format.js';

/** Threat score with its category word, so severity never depends on colour alone. */
export function ThreatBadge({ score, category }) {
  const tone = threatTone(score);
  return (
    <span className={`threat-badge ${tone}`}>
      {Number(score) || 0}
      <small>{category || tone.toUpperCase()}</small>
    </span>
  );
}

/** Zone level chip, coloured like the zone overlay the backend draws on the video. */
export function ZoneBadge({ level }) {
  const value = level || 'SAFE';
  return <span className={`zone-badge zone-${value.toLowerCase()}`}>{value}</span>;
}
