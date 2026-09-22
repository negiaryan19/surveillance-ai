import { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, FileDown, Info, ListOrdered, MapPinned, Users } from 'lucide-react';
import { backendLabel, clearToken, mediaUrl } from './api/client.js';
import { useBackend } from './hooks/useBackend.js';
import { useEventStream } from './hooks/useEventStream.js';
import { useIncidents } from './hooks/useIncidents.js';
import { usePageVisible } from './hooks/usePageVisible.js';
import { useStats } from './hooks/useStats.js';
import { CRITICAL_SCORE, incidentTitle } from './lib/format.js';
import { tabDomIds } from './lib/tabIds.js';
import About from './components/About.jsx';
import AlertControls from './components/AlertControls.jsx';
import CameraFeed from './components/CameraFeed.jsx';
import FacesPanel from './components/FacesPanel.jsx';
import IncidentDrawer from './components/IncidentDrawer.jsx';
import IncidentFilters from './components/IncidentFilters.jsx';
import IncidentTable from './components/IncidentTable.jsx';
import LoginGate from './components/LoginGate.jsx';
import MetricCards from './components/MetricCards.jsx';
import PanelHeader from './components/PanelHeader.jsx';
import StatsChart from './components/StatsChart.jsx';
import Tabs from './components/Tabs.jsx';
import Toasts from './components/Toasts.jsx';
import Topbar from './components/Topbar.jsx';
import ZoneEditor from './components/ZoneEditor.jsx';

const TABS = [
  { id: 'dashboard', label: 'Dashboard', icon: Activity },
  { id: 'incidents', label: 'Incidents', icon: ListOrdered },
  { id: 'zones', label: 'Zones', icon: MapPinned },
  { id: 'faces', label: 'Faces', icon: Users },
  { id: 'about', label: 'About', icon: Info },
];
const TAB_IDS = new Set(TABS.map((tab) => tab.id));
const START_COMMAND = 'cd Backend && source venv/bin/activate && python web/app.py';

function tabFromHash() {
  const match = /(?:^#|[#&])tab=([a-z]+)/.exec(window.location.hash);
  return match && TAB_IDS.has(match[1]) ? match[1] : 'dashboard';
}

/** Tab selection lives in `#tab=<id>` so views are linkable and survive a reload. */
function useHashTab() {
  const [tab, setTab] = useState(tabFromHash);
  useEffect(() => {
    const sync = () => setTab(tabFromHash());
    window.addEventListener('hashchange', sync);
    return () => window.removeEventListener('hashchange', sync);
  }, []);
  const select = useCallback((id) => {
    if (window.location.hash !== `#tab=${id}`) window.location.hash = `tab=${id}`;
    setTab(id);
  }, []);
  return [tab, select];
}

function useToasts() {
  const [toasts, setToasts] = useState([]);
  const dismiss = useCallback((id) => setToasts((current) => current.filter((toast) => toast.id !== id)), []);
  const push = useCallback((toast) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    setToasts((current) => [...current.slice(-4), { id, ...toast }]);
  }, []);
  return { toasts, push, dismiss };
}

function TabPanel({ id, active, children }) {
  const ids = tabDomIds(id);
  return (
    <div id={ids.panel} role="tabpanel" aria-labelledby={ids.tab} hidden={!active} className="tabpanel">
      {active && children}
    </div>
  );
}

export default function App() {
  const [tab, selectTab] = useHashTab();
  const pageVisible = usePageVisible();
  const { toasts, push: pushToast, dismiss } = useToasts();
  const notifyError = useCallback((message) => pushToast({ tone: 'warning', title: 'Something went wrong', message }), [pushToast]);

  // The event stream should only run while the backend is online, but the backend hook
  // needs the stream's `subscribe`. Mirroring the status into state (adjusted during
  // render, the React-sanctioned pattern) breaks that cycle with a single extra render.
  const [backendStatus, setBackendStatus] = useState('checking');
  const stream = useEventStream(backendStatus === 'online');
  const backend = useBackend(stream.subscribe);
  if (backend.status !== backendStatus) setBackendStatus(backend.status);

  const online = backend.status === 'online';
  const live = stream.connected;
  const stats = useStats({ subscribe: stream.subscribe, enabled: online });
  const incidents = useIncidents({ subscribe: stream.subscribe, live, pageSize: 25 });
  const latest = useIncidents({ subscribe: stream.subscribe, live, pageSize: 8 });
  const [selectedIncident, setSelectedIncident] = useState(null);

  // Toast every new critical incident, with a shortcut into the drawer.
  useEffect(
    () =>
      stream.subscribe((type, payload) => {
        if (type !== 'incident' || Number(payload?.threat_score) < CRITICAL_SCORE) return;
        pushToast({
          tone: 'critical',
          title: incidentTitle(payload),
          message: `${payload.zone_level} zone · ${payload.threat_score}%`,
          action: { label: 'Open incident', onClick: () => setSelectedIncident(payload) },
        });
      }),
    [stream, pushToast],
  );

  const signOut = useCallback(() => {
    clearToken();
    backend.refresh();
  }, [backend]);

  const cameras = backend.cameras;
  const showFeeds = tab === 'dashboard' && pageVisible && online;
  const reportUrl = useMemo(() => mediaUrl('/api/report.pdf'), []);

  if (backend.status === 'unauthorized') {
    return (
      <main className="app">
        <Topbar status={backend.status} live={false} canSignOut={false} />
        <LoginGate onAuthenticated={backend.refresh} />
      </main>
    );
  }

  return (
    <main className="app">
      <Topbar status={backend.status} live={live} canSignOut={Boolean(backend.health?.auth_required)} onSignOut={signOut} />

      {backend.status === 'offline' && (
        <section className="alert-box" role="alert">
          <strong>Backend connection failed.</strong>
          <span>{backend.error || `Nothing is answering at ${backendLabel()}.`}</span>
          <small>Start it with: <code>{START_COMMAND}</code></small>
        </section>
      )}
      {online && backend.error && (
        <section className="alert-box" role="status">
          <strong>Backend reported a problem.</strong>
          <span>{backend.error}</span>
        </section>
      )}

      <nav className="tabbar">
        <Tabs tabs={TABS} active={tab} onChange={selectTab} />
        <a className="btn ghost" href={reportUrl} download>
          <FileDown size={16} aria-hidden="true" />
          Report (PDF)
        </a>
      </nav>

      <TabPanel id="dashboard" active={tab === 'dashboard'}>
        <MetricCards stats={stats.stats} cameras={cameras} modules={backend.modules} />
        <section className="dashboard-grid">
          <div className="panel feeds-panel">
            <PanelHeader title="Live cameras" subtitle={showFeeds ? 'Streaming while this tab is visible' : 'Streams paused'}>
              <AlertControls paused={backend.alertsPaused} onChange={backend.setAlertsPaused} onError={notifyError} />
            </PanelHeader>
            {cameras.length === 0 ? (
              <div className="empty-state">
                <strong>No cameras configured</strong>
                <span>Set CHANAKYA_CAMERAS on the backend, or wait for it to come online.</span>
              </div>
            ) : (
              <div className="feed-grid">
                {cameras.map((camera) => (
                  <CameraFeed key={camera.id} camera={camera} active={showFeeds} />
                ))}
              </div>
            )}
          </div>
          <div className="panel logs-panel">
            <PanelHeader title="Latest incidents" subtitle={live ? 'Updating live' : 'Refreshing every 10 s'}>
              <button type="button" className="link-button" onClick={() => selectTab('incidents')}>View all</button>
            </PanelHeader>
            <IncidentTable incidents={latest.items} cameras={cameras} onSelect={setSelectedIncident} loading={latest.loading} compact />
          </div>
        </section>
        <section className="panel">
          <PanelHeader title="Incidents per hour" subtitle="Last 24 hours" />
          <StatsChart stats={stats.stats} loading={stats.loading} />
        </section>
      </TabPanel>

      <TabPanel id="incidents" active={tab === 'incidents'}>
        <section className="panel">
          <PanelHeader title="Incidents" subtitle={`${incidents.total} matching`}>
            <IncidentFilters filters={incidents.filters} onChange={incidents.setFilters} cameras={cameras} />
          </PanelHeader>
          {incidents.error && <p className="form-error" role="alert">{incidents.error}</p>}
          <IncidentTable incidents={incidents.items} cameras={cameras} onSelect={setSelectedIncident} loading={incidents.loading} />
          <Pager page={incidents.page} pageSize={incidents.pageSize} total={incidents.total} onPage={incidents.setPage} />
        </section>
      </TabPanel>

      <TabPanel id="zones" active={tab === 'zones'}>
        <ZoneEditor cameras={cameras} subscribe={stream.subscribe} onError={notifyError} />
      </TabPanel>

      <TabPanel id="faces" active={tab === 'faces'}>
        <FacesPanel subscribe={stream.subscribe} onError={notifyError} />
      </TabPanel>

      <TabPanel id="about" active={tab === 'about'}>
        <About health={backend.health} modules={backend.modules} cameras={cameras} />
      </TabPanel>

      {selectedIncident && (
        <IncidentDrawer
          incident={selectedIncident}
          cameras={cameras}
          subscribe={stream.subscribe}
          emit={stream.emit}
          onClose={() => setSelectedIncident(null)}
          onError={notifyError}
        />
      )}
      <Toasts toasts={toasts} onDismiss={dismiss} />
    </main>
  );
}

function Pager({ page, pageSize, total, onPage }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (pages <= 1) return null;
  return (
    <nav className="pager" aria-label="Incident pages">
      <button type="button" className="btn ghost" disabled={page === 0} onClick={() => onPage(page - 1)}>Previous</button>
      <span>Page {page + 1} of {pages}</span>
      <button type="button" className="btn ghost" disabled={page >= pages - 1} onClick={() => onPage(page + 1)}>Next</button>
    </nav>
  );
}
