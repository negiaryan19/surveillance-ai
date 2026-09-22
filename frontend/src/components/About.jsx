import { backendLabel } from '../api/client.js';
import PanelHeader from './PanelHeader.jsx';

function InfoBlock({ title, children }) {
  return (
    <article className="info-block">
      <h4>{title}</h4>
      <p>{children}</p>
    </article>
  );
}

function ModuleRow({ label, value }) {
  return (
    <div className="kv-row">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

/** Project abstract plus a read-out of what the running backend reports about itself. */
export default function About({ health, modules, cameras }) {
  const knownFaceCount = modules?.knownFaces?.count ?? 0;
  const emotion = modules?.emotion;

  return (
    <>
      <section className="panel project-info">
        <PanelHeader title="Project Abstract" subtitle="Submission-ready summary" />
        <div className="abstract-grid">
          <InfoBlock title="Objective">
            Detect suspicious activity through AI-enabled camera monitoring and show alerts on a web dashboard.
          </InfoBlock>
          <InfoBlock title="Features">
            Live feeds, YOLO threat logs, emotion signals, editable security zones, {knownFaceCount} known face
            profile{knownFaceCount === 1 ? '' : 's'}, incident clips and reports.
          </InfoBlock>
          <InfoBlock title="Technologies">
            React, Vite, Flask, OpenCV, YOLOv8, SQLite, facial landmarks, Python, and CSS.
          </InfoBlock>
          <InfoBlock title="Outcome">
            A working full-stack surveillance prototype with a frontend connected to the backend APIs.
          </InfoBlock>
        </div>
      </section>

      <section className="panel">
        <PanelHeader title="System" subtitle={`Backend at ${backendLabel()}`} />
        <dl className="kv-list">
          <ModuleRow label="Version" value={health?.version ?? 'Unknown'} />
          <ModuleRow label="Authentication" value={health?.auth_required ? 'API token required' : 'Open (loopback only)'} />
          <ModuleRow label="Cameras" value={cameras.length ? cameras.map((camera) => camera.name).join(', ') : 'None reported'} />
          <ModuleRow label="Emotion engine" value={emotion ? `${emotion.engine} (${emotion.status})` : 'Unknown'} />
          <ModuleRow label="Telegram alerts" value={modules?.telegram?.configured ? 'Configured' : 'Not configured'} />
          <ModuleRow label="Clip recorder" value={modules?.recorder?.enabled ? 'Enabled' : 'Unknown'} />
        </dl>
      </section>

      <section className="panel">
        <PanelHeader title="Known Limitations" subtitle="Read before relying on an alert" />
        <ul className="plain-list">
          <li>Weapon detection is the COCO &quot;knife&quot; class on a nano model; expect misses and false alarms.</li>
          <li>Emotion labels come from a facial-landmark heuristic and are experimental.</li>
          <li>Faces smaller than roughly 40 px in the frame cannot be recognised.</li>
          <li>Blink liveness does not stop a replayed video of an authorised person.</li>
          <li>Snapshots, clips and enrolled faces are stored unencrypted on the server; tell people they are recorded.</li>
        </ul>
      </section>
    </>
  );
}
