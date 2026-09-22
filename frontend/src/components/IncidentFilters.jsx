import { RotateCcw } from 'lucide-react';
import { DEFAULT_FILTERS } from '../hooks/useIncidents.js';
import { ZONE_LEVELS } from '../lib/format.js';

const THREAT_OPTIONS = [
  { value: '', label: 'Any threat' },
  { value: '30', label: '30+ (warning)' },
  { value: '50', label: '50+' },
  { value: '70', label: '70+ (critical)' },
  { value: '90', label: '90+' },
];

function isDefault(filters) {
  return Object.keys(DEFAULT_FILTERS).every((key) => filters[key] === DEFAULT_FILTERS[key]);
}

/**
 * One filter row above the table it scopes. Camera options come from /api/cameras so the
 * values are exactly the ids the backend filters on.
 */
export default function IncidentFilters({ filters, onChange, cameras }) {
  const update = (patch) => onChange({ ...filters, ...patch });

  return (
    <form className="filters" aria-label="Incident filters" onSubmit={(event) => event.preventDefault()}>
      <div className="field">
        <label htmlFor="filter-threat">Min threat</label>
        <select id="filter-threat" value={filters.minThreat} onChange={(event) => update({ minThreat: event.target.value })}>
          {THREAT_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="filter-zone">Zone</label>
        <select id="filter-zone" value={filters.zone} onChange={(event) => update({ zone: event.target.value })}>
          <option value="">Any zone</option>
          {ZONE_LEVELS.map((level) => (
            <option key={level} value={level}>
              {level}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="filter-camera">Camera</label>
        <select id="filter-camera" value={filters.camera} onChange={(event) => update({ camera: event.target.value })}>
          <option value="">Any camera</option>
          {cameras.map((camera) => (
            <option key={camera.id} value={camera.id}>
              {camera.name}
            </option>
          ))}
        </select>
      </div>
      <label className="checkbox-field" htmlFor="filter-unack">
        <input
          id="filter-unack"
          type="checkbox"
          checked={filters.unacknowledged}
          onChange={(event) => update({ unacknowledged: event.target.checked })}
        />
        Unacknowledged only
      </label>
      <button type="button" className="btn ghost" onClick={() => onChange(DEFAULT_FILTERS)} disabled={isDefault(filters)}>
        <RotateCcw size={16} aria-hidden="true" />
        Clear
      </button>
    </form>
  );
}
