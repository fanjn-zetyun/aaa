import { Outlet, useLocation } from "react-router-dom";
import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import Sidebar from "../components/Sidebar";
import RightPanel from "../components/RightPanel";

type ResizeTarget = "sidebar" | "rightPanel";

const SIDEBAR_STORAGE_KEY = "lobster.sidebarPercent.v4";
const RIGHT_PANEL_STORAGE_KEY = "lobster.rightPanelPercent.v4";
const DEFAULT_SIDE_PERCENT = 25;
const RESIZE_HANDLE_WIDTH = 8;
const SIDEBAR_MIN_WIDTH = 240;
const RIGHT_PANEL_MIN_WIDTH = 240;
const MAIN_MIN_WIDTH = 480;
const RESIZE_STEP_PERCENT = 1;

export default function AppLayout() {
  const location = useLocation();
  const isTaskView = /\/(reproduce|search|paper-only|experiments|auto-research|polish)\/task\/\d+/.test(location.pathname);
  const [panelOpen, setPanelOpen] = useState(false);
  const [resizing, setResizing] = useState<ResizeTarget | null>(null);
  const [sidebarPercent, setSidebarPercent] = useState(() =>
    readStoredPercent(SIDEBAR_STORAGE_KEY, DEFAULT_SIDE_PERCENT)
  );
  const [rightPanelPercent, setRightPanelPercent] = useState(() =>
    readStoredPercent(RIGHT_PANEL_STORAGE_KEY, DEFAULT_SIDE_PERCENT)
  );
  const sidebarPercentRef = useRef(sidebarPercent);
  const rightPanelPercentRef = useRef(rightPanelPercent);
  const rightPanelVisible = isTaskView && panelOpen;

  useEffect(() => {
    setPanelOpen(isTaskView);
  }, [isTaskView]);

  useEffect(() => {
    sidebarPercentRef.current = sidebarPercent;
  }, [sidebarPercent]);

  useEffect(() => {
    rightPanelPercentRef.current = rightPanelPercent;
  }, [rightPanelPercent]);

  useEffect(() => {
    storePercent(SIDEBAR_STORAGE_KEY, sidebarPercent);
  }, [sidebarPercent]);

  useEffect(() => {
    storePercent(RIGHT_PANEL_STORAGE_KEY, rightPanelPercent);
  }, [rightPanelPercent]);

  useEffect(() => {
    function keepPercentsInBounds() {
      const nextSidebarPercent = clamp(
        sidebarPercentRef.current,
        getSidebarMinPercent(),
        getSidebarMaxPercent(rightPanelPercentRef.current)
      );
      const nextRightPanelPercent = clamp(
        rightPanelPercentRef.current,
        getRightPanelMinPercent(),
        getRightPanelMaxPercent(nextSidebarPercent)
      );
      sidebarPercentRef.current = nextSidebarPercent;
      rightPanelPercentRef.current = nextRightPanelPercent;
      setSidebarPercent(nextSidebarPercent);
      setRightPanelPercent(nextRightPanelPercent);
    }

    keepPercentsInBounds();
    window.addEventListener("resize", keepPercentsInBounds);
    return () => window.removeEventListener("resize", keepPercentsInBounds);
  }, []);

  useEffect(() => {
    if (!resizing) return;

    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    function handlePointerMove(event: PointerEvent) {
      if (resizing === "sidebar") {
        setSidebarPercent(
          clamp(pointerXToPercent(event.clientX), getSidebarMinPercent(), getSidebarMaxPercent(rightPanelPercent))
        );
      } else {
        setRightPanelPercent(
          clamp(pointerXToRightPercent(event.clientX), getRightPanelMinPercent(), getRightPanelMaxPercent(sidebarPercent))
        );
      }
    }

    function stopResize() {
      setResizing(null);
    }

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", stopResize);
    window.addEventListener("pointercancel", stopResize);

    return () => {
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", stopResize);
      window.removeEventListener("pointercancel", stopResize);
    };
  }, [resizing, rightPanelPercent, sidebarPercent]);

  function startResize(target: ResizeTarget, event: ReactPointerEvent<HTMLDivElement>) {
    event.preventDefault();
    setResizing(target);
  }

  function handleResizeKeyDown(target: ResizeTarget, event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const direction = event.key === "ArrowRight" ? 1 : -1;
    const step = event.shiftKey ? RESIZE_STEP_PERCENT * 2 : RESIZE_STEP_PERCENT;

    if (target === "sidebar") {
      setSidebarPercent((percent) =>
        clamp(percent + direction * step, getSidebarMinPercent(), getSidebarMaxPercent(rightPanelPercent))
      );
    } else {
      setRightPanelPercent((percent) =>
        clamp(percent - direction * step, getRightPanelMinPercent(), getRightPanelMaxPercent(sidebarPercent))
      );
    }
  }

  return (
    <div className="h-screen w-screen flex overflow-hidden font-sans text-slate-800">
      <div
        className={`h-full min-w-0 shrink-0 overflow-hidden ${
          resizing ? "" : "transition-[flex-basis] duration-300 ease-in-out"
        }`}
        style={{ flexBasis: `${sidebarPercent}%` }}
      >
        <Sidebar />
      </div>

      <ResizeHandle
        active={resizing === "sidebar"}
        ariaLabel="调整左侧栏宽度"
        onPointerDown={(event) => startResize("sidebar", event)}
        onKeyDown={(event) => handleResizeKeyDown("sidebar", event)}
      />

      <main className="min-w-0 flex-1 flex flex-col relative h-full bg-[#F8F9FA]">
        {isTaskView && (
          <button
            onClick={() => setPanelOpen(!panelOpen)}
            className="absolute top-4 right-4 z-20 w-8 h-8 flex items-center justify-center rounded-lg bg-white border border-slate-200 text-slate-400 hover:text-slate-600 hover:border-slate-300 transition-colors shadow-sm"
            title={panelOpen ? "隐藏面板" : "显示面板"}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              {panelOpen ? (
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M13 5l7 7-7 7M5 5l7 7-7 7" />
              ) : (
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M11 19l-7-7 7-7M19 19l-7-7 7-7" />
              )}
            </svg>
          </button>
        )}
        <Outlet />
      </main>

      {rightPanelVisible && (
        <ResizeHandle
          active={resizing === "rightPanel"}
          ariaLabel="调整右侧栏宽度"
          onPointerDown={(event) => startResize("rightPanel", event)}
          onKeyDown={(event) => handleResizeKeyDown("rightPanel", event)}
        />
      )}

      <div
        className={`h-full min-w-0 shrink-0 overflow-hidden ${
          resizing ? "" : "transition-[flex-basis] duration-300 ease-in-out"
        }`}
        style={{ flexBasis: rightPanelVisible ? `${rightPanelPercent}%` : "0%" }}
      >
        <RightPanel />
      </div>
    </div>
  );
}

function ResizeHandle({
  active,
  ariaLabel,
  onPointerDown,
  onKeyDown,
}: {
  active: boolean;
  ariaLabel: string;
  onPointerDown: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onKeyDown: (event: ReactKeyboardEvent<HTMLDivElement>) => void;
}) {
  return (
    <div
      role="separator"
      aria-label={ariaLabel}
      aria-orientation="vertical"
      tabIndex={0}
      onPointerDown={onPointerDown}
      onKeyDown={onKeyDown}
      className={`group relative z-30 h-full shrink-0 cursor-col-resize select-none outline-none transition-colors ${
        active ? "bg-blue-50" : "bg-transparent hover:bg-blue-50/60 focus:bg-blue-50/60"
      }`}
      style={{ width: RESIZE_HANDLE_WIDTH }}
    >
      <div
        className={`absolute left-1/2 top-0 h-full w-px -translate-x-1/2 transition-colors ${
          active ? "bg-blue-400" : "bg-slate-200 group-hover:bg-blue-300 group-focus:bg-blue-300"
        }`}
      />
      <div
        className={`absolute left-1/2 top-1/2 h-12 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full transition-opacity ${
          active ? "bg-blue-400 opacity-100" : "bg-slate-300 opacity-0 group-hover:opacity-100 group-focus:opacity-100"
        }`}
      />
    </div>
  );
}

function readStoredPercent(key: string, fallback: number) {
  if (typeof window === "undefined") return fallback;
  const value = Number(window.localStorage.getItem(key));
  if (!Number.isFinite(value)) return fallback;
  return clamp(value, getMinSidePercent(), getMaxSidePercent());
}

function storePercent(key: string, value: number) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(key, value.toFixed(2));
}

function pointerXToPercent(clientX: number) {
  if (typeof window === "undefined" || window.innerWidth <= 0) return DEFAULT_SIDE_PERCENT;
  return (clientX / window.innerWidth) * 100;
}

function pointerXToRightPercent(clientX: number) {
  if (typeof window === "undefined" || window.innerWidth <= 0) return DEFAULT_SIDE_PERCENT;
  return ((window.innerWidth - clientX) / window.innerWidth) * 100;
}

function getSidebarMinPercent() {
  return getMinSidePercent(SIDEBAR_MIN_WIDTH);
}

function getRightPanelMinPercent() {
  return getMinSidePercent(RIGHT_PANEL_MIN_WIDTH);
}

function getMinSidePercent(minWidth = SIDEBAR_MIN_WIDTH) {
  if (typeof window === "undefined" || window.innerWidth <= 0) return 12;
  return (minWidth / window.innerWidth) * 100;
}

function getSidebarMaxPercent(rightPanelPercent: number) {
  return Math.max(getSidebarMinPercent(), getMaxSidePercent() - rightPanelPercent);
}

function getRightPanelMaxPercent(sidebarPercent: number) {
  return Math.max(getRightPanelMinPercent(), getMaxSidePercent() - sidebarPercent);
}

function getMaxSidePercent() {
  if (typeof window === "undefined" || window.innerWidth <= 0) return 70;
  const available = window.innerWidth - MAIN_MIN_WIDTH - RESIZE_HANDLE_WIDTH * 2;
  return Math.max(getMinSidePercent() * 2, (available / window.innerWidth) * 100);
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}
