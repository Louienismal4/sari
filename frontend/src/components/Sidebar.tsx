import type { ViewKey } from "../types";
import { Icon, type IconName } from "./Icon";

interface SidebarProps {
  activeView: ViewKey;
  onNavigate: (view: ViewKey) => void;
  open: boolean;
  onClose: () => void;
}

const navItems: Array<{ key: ViewKey; label: string; icon: IconName }> = [
  { key: "overview", label: "Overview", icon: "home" },
  { key: "items", label: "Items", icon: "box" },
  { key: "stock", label: "Stock", icon: "stock" },
  { key: "receipts", label: "Receipts", icon: "receipt" },
];

export function Sidebar({ activeView, onNavigate, open, onClose }: SidebarProps) {
  return (
    <>
      <aside className={`sidebar ${open ? "sidebar-open" : ""}`}>
        <div className="brand-lockup">
          <span>Sari-Sari</span>
          <button type="button" className="icon-button sidebar-close" aria-label="Close navigation" onClick={onClose}>
            <Icon name="close" size={19} />
          </button>
        </div>
        <nav aria-label="Main navigation">
          {navItems.map((item) => (
            <button
              className={`nav-item ${activeView === item.key ? "nav-item-active" : ""}`}
              key={item.key}
              type="button"
              onClick={() => { onNavigate(item.key); onClose(); }}
            >
              <Icon name={item.icon} size={21} />
              <span>{item.label}</span>
            </button>
          ))}
        </nav>
        <div className="store-switcher">
          <span className="field-label">Store</span>
          <button type="button" className="store-button">
            <span className="store-button-label"><Icon name="store" size={18} />Maria’s Store</span>
            <span className="store-caret">⌄</span>
          </button>
        </div>
      </aside>
      {open ? <button type="button" className="sidebar-scrim" aria-label="Close navigation" onClick={onClose} /> : null}
    </>
  );
}
