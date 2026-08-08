import type { SVGProps } from "react";

export type IconName =
  | "basket"
  | "home"
  | "box"
  | "stock"
  | "receipt"
  | "plus"
  | "receive"
  | "scan"
  | "search"
  | "filter"
  | "chevron"
  | "close"
  | "edit"
  | "menu"
  | "archive"
  | "calendar"
  | "camera"
  | "upload"
  | "refresh"
  | "alert"
  | "check"
  | "arrow-up"
  | "arrow-down"
  | "clipboard"
  | "sun"
  | "moon"
  | "monitor"
  | "user"
  | "store";

interface IconProps extends SVGProps<SVGSVGElement> {
  name: IconName;
  size?: number;
}

export function Icon({ name, size = 20, ...props }: IconProps) {
  const common = { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.65, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, ...props };
  switch (name) {
    case "basket":
      return <svg {...common}><path d="M4 9h16l-1.1 10.2a2 2 0 0 1-2 1.8H7.1a2 2 0 0 1-2-1.8L4 9Z" /><path d="M2.5 9h19" /><path d="m8 9 2-5h4l2 5" /><path d="M8 13h8M9 16h6" /></svg>;
    case "home":
      return <svg {...common}><path d="m3 10 9-7 9 7" /><path d="M5 9v11h14V9" /><path d="M9 20v-6h6v6" /></svg>;
    case "box":
      return <svg {...common}><path d="m4 7 8-4 8 4-8 4-8-4Z" /><path d="M4 7v10l8 4 8-4V7M12 11v10" /></svg>;
    case "stock":
      return <svg {...common}><rect x="5" y="3" width="14" height="18" rx="1.5" /><path d="M8 7h8M8 11h8M8 15h5" /><path d="m15 18 1.5 1.5L19 17" /></svg>;
    case "receipt":
      return <svg {...common}><path d="M6 3h12v18l-2-1.4-2 1.4-2-1.4-2 1.4-2-1.4-2 1.4V3Z" /><path d="M9 7h6M9 11h6M9 15h4" /></svg>;
    case "plus":
      return <svg {...common}><path d="M12 5v14M5 12h14" /></svg>;
    case "receive":
      return <svg {...common}><path d="M12 3v12" /><path d="m7 10 5 5 5-5" /><path d="M5 20h14" /></svg>;
    case "scan":
      return <svg {...common}><path d="M5 4H3v4M19 4h2v4M5 20H3v-4M19 20h2v-4" /><path d="M7 8v8M10 7v10M14 7v10M17 8v8" /></svg>;
    case "search":
      return <svg {...common}><circle cx="10.8" cy="10.8" r="6.8" /><path d="m16 16 4.2 4.2" /></svg>;
    case "filter":
      return <svg {...common}><path d="M4 6h16M7 12h10M10 18h4" /></svg>;
    case "chevron":
      return <svg {...common}><path d="m9 6 6 6-6 6" /></svg>;
    case "close":
      return <svg {...common}><path d="m6 6 12 12M18 6 6 18" /></svg>;
    case "edit":
      return <svg {...common}><path d="m4 16.5-.8 3.3 3.3-.8L18 7.5 15.5 5 4 16.5Z" /><path d="m14 6.5 2.5 2.5" /></svg>;
    case "menu":
      return <svg {...common}><path d="M4 7h16M4 12h16M4 17h16" /></svg>;
    case "archive":
      return <svg {...common}><path d="M4 7h16v13H4zM3 4h18v3H3zM9 12h6" /></svg>;
    case "calendar":
      return <svg {...common}><rect x="4" y="5" width="16" height="15" rx="1.5" /><path d="M8 3v4M16 3v4M4 9h16" /></svg>;
    case "camera":
      return <svg {...common}><path d="M4 8h3l1.5-2h7L17 8h3v11H4V8Z" /><circle cx="12" cy="13.5" r="3.2" /></svg>;
    case "upload":
      return <svg {...common}><path d="M12 16V4M7 9l5-5 5 5" /><path d="M4 20h16" /></svg>;
    case "refresh":
      return <svg {...common}><path d="M20 7v5h-5" /><path d="M4 17v-5h5" /><path d="M6.5 9a6.5 6.5 0 0 1 11.2-2L20 9M4 15l2.3 2a6.5 6.5 0 0 0 11.2-2" /></svg>;
    case "alert":
      return <svg {...common}><path d="M12 3 2.8 20h18.4L12 3Z" /><path d="M12 9v5M12 17.5h.01" /></svg>;
    case "check":
      return <svg {...common}><path d="m5 12 4.5 4.5L19 7" /></svg>;
    case "arrow-up":
      return <svg {...common}><path d="M12 19V5M6 11l6-6 6 6" /></svg>;
    case "arrow-down":
      return <svg {...common}><path d="M12 5v14M18 13l-6 6-6-6" /></svg>;
    case "clipboard":
      return <svg {...common}><rect x="5" y="4" width="14" height="17" rx="1.5" /><path d="M9 4V2h6v2M8 9h8M8 13h8M8 17h5" /></svg>;
    case "sun":
      return <svg {...common}><circle cx="12" cy="12" r="3.6" /><path d="M12 2v2.2M12 19.8V22M4.93 4.93l1.56 1.56M17.51 17.51l1.56 1.56M2 12h2.2M19.8 12H22M4.93 19.07l1.56-1.56M17.51 6.49l1.56-1.56" /></svg>;
    case "moon":
      return <svg {...common}><path d="M20.2 15.2A8.5 8.5 0 0 1 8.8 3.8 8.5 8.5 0 1 0 20.2 15.2Z" /></svg>;
    case "monitor":
      return <svg {...common}><rect x="3" y="4" width="18" height="13" rx="1.5" /><path d="M8 21h8M12 17v4" /></svg>;
    case "user":
      return <svg {...common}><circle cx="12" cy="8" r="3.5" /><path d="M5 21a7 7 0 0 1 14 0" /></svg>;
    case "store":
      return <svg {...common}><path d="M4 9v11h16V9M3 9l2-5h14l2 5" /><path d="M3 9a3 3 0 0 0 5 2 3 3 0 0 0 4 0 3 3 0 0 0 4 0 3 3 0 0 0 5-2M8 20v-5h4v5" /></svg>;
  }
}
