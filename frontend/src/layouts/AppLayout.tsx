import { Outlet, useLocation } from "react-router-dom";
import { useState, useEffect } from "react";
import Sidebar from "../components/Sidebar";
import RightPanel from "../components/RightPanel";

export default function AppLayout() {
  const location = useLocation();
  const isTaskView = /\/(reproduce|search|paper-only|experiments|polish)\/task\/\d+/.test(location.pathname);
  const [panelOpen, setPanelOpen] = useState(false);

  useEffect(() => {
    setPanelOpen(isTaskView);
  }, [isTaskView]);

  return (
    <div className="h-screen w-screen flex font-sans text-slate-800">
      <Sidebar />
      <main className="flex-1 flex flex-col relative h-full bg-[#F8F9FA]">
        {/* Toggle button for right panel */}
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

      {/* Right panel with slide transition */}
      <div
        className={`shrink-0 transition-all duration-300 ease-in-out overflow-hidden ${
          panelOpen ? "w-[280px]" : "w-0"
        }`}
      >
        <div className="w-[280px] h-full">
          <RightPanel />
        </div>
      </div>
    </div>
  );
}
