import { Check } from 'lucide-react';
import { cameraName, formatDateTime, incidentTitle } from '../lib/format.js';
import { ThreatBadge, ZoneBadge } from './Badges.jsx';

/**
 * Incident list. On narrow screens the table collapses into stacked cards (CSS uses each
 * cell's `data-label`), so it stays readable at 360 px without horizontal scrolling.
 * The first cell holds a real <button>, which is what makes every row keyboard reachable.
 *
 * @param {{incidents: object[], cameras: object[], onSelect: (incident: object) => void,
 *          loading?: boolean, compact?: boolean, emptyHint?: string}} props
 */
export default function IncidentTable({ incidents, cameras, onSelect, loading = false, compact = false, emptyHint }) {
  if (incidents.length === 0) {
    return (
      <div className="empty-state">
        <strong>{loading ? 'Loading incidents...' : 'No incidents'}</strong>
        {!loading && <span>{emptyHint ?? 'Incidents appear here when the backend records a detection.'}</span>}
      </div>
    );
  }

  return (
    <div className={loading ? 'table-wrap refreshing' : 'table-wrap'}>
      <table className={compact ? 'incident-table compact' : 'incident-table'}>
        <caption className="sr-only">Incidents, newest first</caption>
        <thead>
          <tr>
            <th scope="col">Incident</th>
            <th scope="col">Time</th>
            {!compact && <th scope="col">Camera</th>}
            <th scope="col">Zone</th>
            <th scope="col">Threat</th>
            {!compact && <th scope="col">Status</th>}
          </tr>
        </thead>
        <tbody>
          {incidents.map((incident) => (
            <tr key={incident.id} className={incident.acknowledged ? 'acknowledged' : ''} onClick={() => onSelect(incident)}>
              <td data-label="Incident">
                <button
                  type="button"
                  className="link-button"
                  onClick={(event) => {
                    event.stopPropagation();
                    onSelect(incident);
                  }}
                  aria-label={`Open incident ${incident.id}: ${incidentTitle(incident)}`}
                >
                  {incidentTitle(incident)}
                </button>
              </td>
              <td data-label="Time">
                <time dateTime={incident.timestamp}>{formatDateTime(incident.timestamp)}</time>
              </td>
              {!compact && <td data-label="Camera">{cameraName(cameras, incident.camera)}</td>}
              <td data-label="Zone">
                <ZoneBadge level={incident.zone_level} />
              </td>
              <td data-label="Threat">
                <ThreatBadge score={incident.threat_score} category={incident.category} />
              </td>
              {!compact && (
                <td data-label="Status">
                  {incident.acknowledged ? (
                    <span className="ack-state done">
                      <Check size={14} aria-hidden="true" />
                      Acknowledged
                    </span>
                  ) : (
                    <span className="ack-state">Open</span>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
