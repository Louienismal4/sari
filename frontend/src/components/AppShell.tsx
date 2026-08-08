import { useEffect, useState, type ReactNode } from "react";
import type { ViewKey } from "../types";
import { Icon } from "./Icon";
import { Sidebar } from "./Sidebar";

interface AppShellProps {
  activeView: ViewKey;
  onNavigate: (view: ViewKey) => void;
  children: ReactNode;
  pageTitle: string;
  isLoading?: boolean;
  error?: string | null;
  onRetry?: () => void;
}

export function AppShell({ activeView, onNavigate, children, pageTitle, isLoading = false, error, onRetry }: AppShellProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [theme, setTheme] = useState<"system" | "light" | "dark">(() => {
    const savedTheme = localStorage.getItem("sari-theme");
    return savedTheme === "light" || savedTheme === "dark" ? savedTheme : "system";
  });
  const today = new Intl.DateTimeFormat("en-PH", { month: "short", day: "numeric", year: "numeric" }).format(new Date());

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const applyTheme = () => {
      const resolvedTheme = theme === "system" ? (media.matches ? "dark" : "light") : theme;
      document.documentElement.dataset.theme = resolvedTheme;
      document.documentElement.style.colorScheme = resolvedTheme;
    };
    applyTheme();
    localStorage.setItem("sari-theme", theme);
    media.addEventListener("change", applyTheme);
    return () => media.removeEventListener("change", applyTheme);
  }, [theme]);

  const nextTheme = theme === "system" ? "light" : theme === "light" ? "dark" : "system";
  const themeIcon = theme === "system" ? "monitor" : theme === "light" ? "sun" : "moon";

  return (
    <div className="app-shell">
      <Sidebar activeView={activeView} onNavigate={onNavigate} open={menuOpen} onClose={() => setMenuOpen(false)} />
      <main className="main-shell">
        <header className="topbar">
          <button type="button" className="mobile-menu-button icon-button" aria-label="Open navigation" onClick={() => setMenuOpen(true)}><Icon name="menu" size={22} /></button>
          <div className="mobile-brand"><span>Sari-Sari</span></div>
          <div className="topbar-meta">
            <Icon name="calendar" size={18} />
            <span>{today}</span>
            <span className="topbar-divider" />
            <button
              type="button"
              className="icon-button theme-button"
              aria-label={`Theme: ${theme}. Switch to ${nextTheme}.`}
              title={`Theme: ${theme}`}
              onClick={() => setTheme(nextTheme)}
            >
              <Icon name={themeIcon} size={18} />
            </button>
            <span className="avatar" aria-label="Maria"><Icon name="user" size={17} /><span>Maria</span></span>
          </div>
        </header>
        <div className="page-frame">
          <div className="mobile-page-title">{pageTitle}</div>
          {error ? (
            <div className="error-banner" role="alert">
              <span>{error}</span>
              {onRetry ? <button type="button" onClick={onRetry}>Try again</button> : null}
            </div>
          ) : null}
          {isLoading ? <div className="loading-line" aria-label="Loading" /> : null}
          {children}
        </div>
      </main>
    </div>
  );
}
