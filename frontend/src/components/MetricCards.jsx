function MetricCard({ label, value, hint, tone }) {
  return (
    <article className={tone ? `metric-card ${tone}` : 'metric-card'}>
      <span>{label}</span>
      <strong>{value}</strong>
      {hint && <small>{hint}</small>}
    </article>
  );
}

function statValue(stats, key) {
  return stats ? String(stats[key] ?? 0) : '-';
}

/**
 * Headline numbers for the Dashboard. Each figure is a stat tile rather than a chart:
 * a single current value reads fastest as a number.
 */
export default function MetricCards({ stats, cameras, modules }) {
  const online = cameras.filter((camera) => camera.online).length;
  const tracks = cameras.reduce((sum, camera) => sum + camera.tracks, 0);
  const hours = stats?.hours ?? 24;
  const critical = stats?.critical ?? 0;
  const unacknowledged = stats?.unacknowledged ?? 0;

  return (
    <section className="metrics-grid" aria-label="System metrics">
      <MetricCard
        label="Cameras online"
        value={`${online}/${cameras.length}`}
        hint={`${tracks} tracked object${tracks === 1 ? '' : 's'}`}
        tone={cameras.length > 0 && online < cameras.length ? 'warn' : ''}
      />
      <MetricCard label={`Incidents (${hours} h)`} value={statValue(stats, 'total')} />
      <MetricCard label={`Critical (${hours} h)`} value={statValue(stats, 'critical')} tone={critical > 0 ? 'danger' : ''} />
      <MetricCard
        label="Unacknowledged"
        value={statValue(stats, 'unacknowledged')}
        tone={unacknowledged > 0 ? 'warn' : ''}
      />
      <MetricCard
        label="Known faces"
        value={modules ? String(modules.knownFaces?.count ?? 0) : '-'}
        hint={modules?.telegram?.configured ? 'Telegram alerts on' : 'Telegram not configured'}
      />
    </section>
  );
}
