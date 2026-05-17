import { useEffect, useState } from 'react';

const NAV_ITEMS = [
  { id: 'home', label: 'HOME' },
  { id: 'operations', label: 'OPERATIONS' },
  { id: 'hardware', label: 'INTEL VAULT' },
  { id: 'contact', label: 'GET IN TOUCH' },
];

const STATS = [
  '60 FPS // M4 NEURAL ENGINE',
  'AES-256 // ENCRYPTION',
  '5+ CLASSES // YOLOV8',
  '<2SEC // TELEGRAM ALERT',
];

const CAMERAS = [
  { id: 'CAM_01', label: 'ACTIVE', status: 'active' },
  { id: 'CAM_02', label: 'OFFLINE', status: 'offline' },
  { id: 'CAM_03', label: 'ACTIVE', status: 'active' },
  { id: 'CAM_04', label: 'MOTION', status: 'motion' },
];

const SPECS = [
  ['Model', 'AI-X90 Surveillance Core'],
  ['OS', 'Mil-Spec iOS'],
  ['Connection', 'Encrypted SatLink'],
  ['Processor', 'Apple M4 Neural Engine'],
  ['Detection', 'YOLOv8-M (Real-Time)'],
];

const PARTICLES = Array.from({ length: 40 }, (_, index) => ({
  id: `particle-${index}`,
  left: `${(index * 19) % 100}%`,
  top: `${18 + ((index * 13) % 76)}%`,
  delay: `${(index % 12) * -0.7}s`,
  duration: `${10 + (index % 7)}s`,
  size: `${2 + (index % 3)}px`,
}));

const DETECTIONS = [
  { label: 'PERSON 94%', left: '13%', top: '70%', width: '72px', height: '132px' },
  { label: 'PERSON 91%', left: '24%', top: '73%', width: '86px', height: '118px' },
  { label: 'VEHICLE 87%', left: '43%', top: '68%', width: '128px', height: '78px' },
  { label: 'PERSON 89%', left: '57%', top: '74%', width: '62px', height: '105px' },
  { label: 'VEHICLE 82%', left: '68%', top: '67%', width: '162px', height: '82px' },
  { label: 'PERSON 96%', left: '78%', top: '70%', width: '54px', height: '118px' },
  { label: 'PERSON 78%', left: '60%', top: '63%', width: '42px', height: '78px' },
  { label: 'TARGET 72%', left: '36%', top: '61%', width: '34px', height: '52px' },
  { label: 'PERSON 90%', left: '86%', top: '66%', width: '39px', height: '86px' },
  { label: 'VEHICLE 85%', left: '8%', top: '68%', width: '170px', height: '94px' },
];

function ShieldIcon({ className = '' }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 2.8 20 6v5.8c0 4.6-3.2 8.4-8 9.8-4.8-1.4-8-5.2-8-9.8V6l8-3.2Z" />
      <path d="M12 6.3v11.2" />
      <path d="M8.2 9.5h7.6" />
    </svg>
  );
}

function SimpleIcon({ type, className = '' }) {
  const paths = {
    drone: (
      <>
        <path d="M8 12h8M12 8v8M4.5 7.5l4 4-4 4M19.5 7.5l-4 4 4 4" />
        <circle cx="4.5" cy="7.5" r="2.2" />
        <circle cx="19.5" cy="7.5" r="2.2" />
        <circle cx="4.5" cy="15.5" r="2.2" />
        <circle cx="19.5" cy="15.5" r="2.2" />
      </>
    ),
    monitor: (
      <>
        <rect x="4" y="5" width="16" height="11" rx="1.5" />
        <path d="M9 20h6M12 16v4" />
      </>
    ),
    map: (
      <>
        <path d="m4 6 5-2 6 2 5-2v14l-5 2-6-2-5 2V6Z" />
        <path d="M9 4v14M15 6v14" />
      </>
    ),
    alert: (
      <>
        <path d="M12 3 21 20H3L12 3Z" />
        <path d="M12 9v5M12 17h.01" />
      </>
    ),
    gear: (
      <>
        <circle cx="12" cy="12" r="3.2" />
        <path d="M12 2.8v3M12 18.2v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2.8 12h3M18.2 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" />
      </>
    ),
    chip: (
      <>
        <rect x="7" y="7" width="10" height="10" rx="1.4" />
        <path d="M9 3v4M12 3v4M15 3v4M9 17v4M12 17v4M15 17v4M3 9h4M3 12h4M3 15h4M17 9h4M17 12h4M17 15h4" />
      </>
    ),
    back: <path d="M15 5 8 12l7 7" />,
  };

  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true">
      {paths[type]}
    </svg>
  );
}

function FixedNav({ activePage, setPage }) {
  return (
    <header className="site-nav">
      <button className="brand-mark" type="button" onClick={() => setPage('home')}>
        <ShieldIcon className="brand-icon" />
        <span>PROJECT CHANAKYA</span>
      </button>
      <nav aria-label="Primary navigation">
        {NAV_ITEMS.map((item) => (
          <button
            className={activePage === item.id ? 'nav-link active' : 'nav-link'}
            key={item.id}
            type="button"
            onClick={() => setPage(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>
    </header>
  );
}

function App() {
  const [page, setPage] = useState('home');
  const [time, setTime] = useState('23:45');

  useEffect(() => {
    const updateClock = () => {
      const now = new Date();
      setTime(now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false }));
    };

    updateClock();
    const timer = window.setInterval(updateClock, 1000);
    return () => window.clearInterval(timer);
  }, []);

  const visiblePage = page === 'contact' ? 'home' : page;

  return (
    <main className={`app-shell page-${visiblePage}`}>
      <FixedNav activePage={page} setPage={setPage} />
      {visiblePage === 'home' && <HeroLanding setPage={setPage} />}
      {visiblePage === 'operations' && <OperationsCommandCenter time={time} setPage={setPage} />}
      {visiblePage === 'hardware' && <HardwareStatus setPage={setPage} />}
    </main>
  );
}

function HeroLanding({ setPage }) {
  return (
    <section className="hero-screen" aria-label="Project Chanakya landing page">
      <div className="hero-stage" aria-hidden="true">
        <div className="storm-glow" />
        <div className="hero-scan-cone" />
        <div className="scan-beam beam-one" />
        <div className="scan-beam beam-two" />
        <div className="scan-beam beam-three" />
        <div className="scan-beam beam-four" />
        <div className="particle-field">
          {PARTICLES.map((particle) => (
            <i
              key={particle.id}
              style={{
                '--left': particle.left,
                '--top': particle.top,
                '--delay': particle.delay,
                '--duration': particle.duration,
                '--size': particle.size,
              }}
            />
          ))}
        </div>
        <HeroDrone />
        <svg className="mountain-layer rear" viewBox="0 0 1440 460" preserveAspectRatio="none">
          <path d="M0 254 92 186 185 226 294 136 390 213 517 94 661 214 782 122 917 206 1044 102 1169 199 1288 125 1440 214v246H0Z" />
        </svg>
        <svg className="mountain-layer front" viewBox="0 0 1440 390" preserveAspectRatio="none">
          <path d="M0 218 76 130 141 184 231 116 315 178 402 86 517 190 630 134 709 204 831 96 942 192 1018 128 1135 216 1236 116 1328 180 1440 105v285H0Z" />
        </svg>
        <div className="rock-field" />
        <div className="detection-field">
          {DETECTIONS.map((box, index) => (
            <span
              className="detection-box"
              key={`${box.label}-${index}`}
              style={{
                '--left': box.left,
                '--top': box.top,
                '--width': box.width,
                '--height': box.height,
                '--delay': `${index * -0.9}s`,
              }}
            >
              <b>{box.label}</b>
            </span>
          ))}
        </div>
      </div>
      <div className="hero-copy">
        <p className="eyebrow">AUTONOMOUS BORDER INTELLIGENCE</p>
        <h1>
          AUTONOMOUS SURVEILLANCE.
          <span>AI ACCELERATED.</span>
        </h1>
        <p>
          Project Chanakya fuses aerial detection, neural threat assessment, encrypted incident
          reporting, and live command telemetry into one hardened surveillance interface.
        </p>
        <div className="hero-actions">
          <button type="button" className="cta primary" onClick={() => setPage('operations')}>
            LAUNCH COMMAND HUB
          </button>
          <button type="button" className="cta secondary" onClick={() => setPage('hardware')}>
            INTEL VAULT
          </button>
        </div>
      </div>
      <div className="scroll-cue">
        <span>SCROLL</span>
        <i />
      </div>
      <div className="stats-strip">
        {STATS.map((stat) => (
          <span key={stat}>{stat}</span>
        ))}
      </div>
    </section>
  );
}

function HeroDrone() {
  const rotors = [
    [44, 44],
    [88, 22],
    [176, 22],
    [220, 44],
    [72, 96],
    [192, 96],
  ];

  return (
    <svg className="hero-drone" viewBox="0 0 264 132" role="img" aria-label="Military hexacopter drone">
      <defs>
        <radialGradient id="droneGlow" cx="50%" cy="50%" r="60%">
          <stop offset="0%" stopColor="#00ff88" stopOpacity="0.95" />
          <stop offset="100%" stopColor="#00ff88" stopOpacity="0" />
        </radialGradient>
      </defs>
      <g className="rotor-lines">
        <path d="M88 62 44 44M93 50 88 22M171 50l5-28M176 62l44-18M96 72 72 96M168 72l24 24" />
      </g>
      {rotors.map(([cx, cy]) => (
        <g className="rotor" key={`${cx}-${cy}`} transform={`translate(${cx} ${cy})`}>
          <ellipse cx="0" cy="0" rx="29" ry="5" />
          <circle cx="0" cy="0" r="6" />
        </g>
      ))}
      <path className="drone-body" d="M91 56c12-20 70-20 82 0l17 38H74l17-38Z" />
      <path className="drone-cockpit" d="M112 54c10-9 30-9 40 0l7 18h-54l7-18Z" />
      <path className="landing-gear" d="M92 90 70 122M172 90l22 32M82 119h-23M182 119h23" />
      <circle className="scanner-core" cx="132" cy="91" r="15" />
      <circle cx="132" cy="91" r="24" fill="url(#droneGlow)" />
    </svg>
  );
}

function OperationsCommandCenter({ time, setPage }) {
  return (
    <section className="ops-screen" aria-label="Operations Command Center">
      <div className="ops-topbar">
        <strong>{time}</strong>
        <div>
          <h2>DEFENSE COMMAND CENTER</h2>
          <p>Border Security Operations - Night Shift</p>
        </div>
        <span>SIG 4G&nbsp;&nbsp;BAT 85</span>
      </div>
      <div className="monitor-array">
        <MonitorTerrain />
        <MonitorHeatmap />
        <MonitorGrid />
      </div>
      <div className="command-desk">
        <div className="keyboard-line" />
        <div className="force-watermark">
          <ShieldIcon />
          <span>INDIAN BORDER DEFENSE FORCE</span>
        </div>
      </div>
      <button className="deploy-button" type="button">
        DEPLOY RESPONSE
      </button>
      <OpsTabs setPage={setPage} />
    </section>
  );
}

function MonitorTerrain() {
  return (
    <article className="monitor-card monitor-terrain" aria-label="Aerial terrain monitor">
      <div className="monitor-title">
        <span>AERIAL TERRAIN VIEW</span>
        <SimpleIcon type="drone" />
      </div>
      <svg className="terrain-map" viewBox="0 0 520 360" preserveAspectRatio="none" aria-hidden="true">
        <rect width="520" height="360" />
        {Array.from({ length: 48 }, (_, index) => (
          <rect
            key={index}
            x={(index * 47) % 520}
            y={(index * 31) % 360}
            width={28 + (index % 5) * 18}
            height={8 + (index % 4) * 7}
            opacity={0.08 + (index % 6) * 0.025}
            transform={`rotate(${(index % 7) * 9}, ${(index * 47) % 520}, ${(index * 31) % 360})`}
          />
        ))}
        <path d="M-40 300C70 250 98 105 190 126c92 20 91 114 179 107 90-8 114-127 206-142" />
        <path d="M-10 210C60 186 86 80 177 85c91 6 109 91 188 82 82-9 96-104 187-105" />
      </svg>
      <div className="terrain-box vehicle-box">
        <b>TARGET DETECTED: VEHICLE</b>
      </div>
      <div className="terrain-box coordinate-box">
        <b>COORDINATES: 32°N 76°E</b>
      </div>
      <div className="terrain-box threat-box">
        <b>THREAT LEVEL: MODERATE</b>
      </div>
      <i className="thermal-spot spot-a" />
      <i className="thermal-spot spot-b" />
      <i className="thermal-spot spot-c" />
      <div className="monitor-scanline" />
    </article>
  );
}

function MonitorHeatmap() {
  return (
    <article className="monitor-card monitor-heatmap" aria-label="Heatmap and drone monitor">
      <div className="monitor-title">
        <span>HEATMAP + DRONE VIEW</span>
        <span>ACTIVE // DRONE_3</span>
      </div>
      <div className="heat-grid" />
      <div className="heat-blob primary" />
      <div className="heat-blob secondary" />
      <svg className="map-lines" viewBox="0 0 560 380" preserveAspectRatio="none" aria-hidden="true">
        <path d="M0 238C80 202 92 126 171 118c105-10 138 102 229 76 96-28 113-147 223-152 80-3 111 50 157 69" />
        <path d="M32 314C118 268 121 192 209 190c92-1 125 78 213 55 89-24 120-102 210-90" />
        <path d="M94 0v380M208 0v380M322 0v380M436 0v380M0 82h560M0 190h560M0 302h560" />
      </svg>
      <svg className="center-drone" viewBox="0 0 180 90" aria-hidden="true">
        <path d="M62 43 28 30M68 35 58 14M118 35l10-21M118 43l34-13M75 48h30l15 24H60l15-24Z" />
        <ellipse cx="26" cy="29" rx="20" ry="4" />
        <ellipse cx="58" cy="14" rx="18" ry="4" />
        <ellipse cx="128" cy="14" rx="18" ry="4" />
        <ellipse cx="154" cy="29" rx="20" ry="4" />
      </svg>
      <div className="face-card">
        <div className="face-placeholder" />
        <div>
          <b>FACIAL RECOGNITION: MATCH FOUND</b>
          <span>IDENTITY: UNKNOWN SUBJECT</span>
          <span>THREAT: HIGH</span>
          <span>LAST SEEN: SECTOR 20</span>
        </div>
      </div>
      <div className="monitor-scanline" />
    </article>
  );
}

function MonitorGrid() {
  return (
    <article className="monitor-card monitor-grid" aria-label="Multi-camera grid monitor">
      {CAMERAS.map((camera) => (
        <div className={`camera-tile ${camera.status}`} key={camera.id}>
          <i />
          <div className="camera-horizon" />
          <div className="camera-target" />
          <span>{camera.id} {camera.label}</span>
        </div>
      ))}
      <div className="monitor-scanline" />
    </article>
  );
}

function OpsTabs({ setPage }) {
  const tabs = [
    ['DRONE CONTROL', 'drone', 'operations'],
    ['LIVE FEEDS', 'monitor', 'operations'],
    ['OPERATIONS', 'map', 'operations'],
    ['ALERTS', 'alert', 'operations'],
    ['SETTINGS', 'gear', 'hardware'],
  ];

  return (
    <nav className="ops-tabs" aria-label="Operations tabs">
      {tabs.map(([label, icon, target], index) => (
        <button className={index === 2 ? 'active' : ''} type="button" key={label} onClick={() => setPage(target)}>
          <SimpleIcon type={icon} />
          <span>{label}</span>
        </button>
      ))}
    </nav>
  );
}

function HardwareStatus({ setPage }) {
  return (
    <section className="hardware-screen" aria-label="Hardware Status">
      <div className="hardware-device">
        <header className="hardware-header">
          <button type="button" onClick={() => setPage('operations')}>
            <SimpleIcon type="back" />
            Back
          </button>
          <h2>AI Surveillance Hardware Detail</h2>
        </header>
        <div className="pcb-hero" />
        <section className="hardware-panel">
          <h3>HARDWARE STATUS</h3>
          <p className="active-link">ACTIVE - SECURE LINK ESTABLISHED</p>
          <h4>SPECIFICATIONS</h4>
          <dl>
            {SPECS.map(([label, value]) => (
              <div key={label}>
                <dt>{label}:</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
        </section>
        <HardwareTabs setPage={setPage} />
      </div>
    </section>
  );
}

function HardwareTabs({ setPage }) {
  const tabs = [
    ['MAP', 'map', 'home'],
    ['DRONES', 'drone', 'operations'],
    ['HARDWARE', 'chip', 'hardware'],
    ['SETTINGS', 'gear', 'hardware'],
  ];

  return (
    <nav className="hardware-tabs" aria-label="Hardware tabs">
      {tabs.map(([label, icon, target]) => (
        <button className={label === 'HARDWARE' ? 'active' : ''} type="button" key={label} onClick={() => setPage(target)}>
          <SimpleIcon type={icon} />
          <span>{label}</span>
        </button>
      ))}
    </nav>
  );
}

export default App;
