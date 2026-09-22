/** Title bar shared by every panel; `children` holds optional right-aligned actions. */
export default function PanelHeader({ title, subtitle, children }) {
  return (
    <div className="panel-header">
      <div>
        <h3>{title}</h3>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {children && <div className="panel-actions">{children}</div>}
    </div>
  );
}
