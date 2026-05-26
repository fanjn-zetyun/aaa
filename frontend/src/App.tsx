import { Routes, Route, Navigate } from "react-router-dom";
import { getToken } from "./lib/api";
import AppLayout from "./layouts/AppLayout";
import LoginPage from "./pages/LoginPage";
import ReproducePage from "./pages/ReproducePage";
import SearchPage from "./pages/SearchPage";
import PaperOnlyPage from "./pages/PaperOnlyPage";
import ExperimentsPage from "./pages/ExperimentsPage";
import AutoResearchPage from "./pages/AutoResearchPage";
import AutoResearchMockRunPage from "./pages/AutoResearchMockRunPage";
import PolishPage from "./pages/PolishPage";
import ChatPage from "./pages/ChatPage";
import ZeroCodeBoardDemoPage from "./pages/ZeroCodeBoardDemoPage";
import ModelSettingsPage from "./pages/ModelSettingsPage";

function PrivateRoute({ children }: { children: React.ReactNode }) {
  return getToken() ? <>{children}</> : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <PrivateRoute>
            <AppLayout />
          </PrivateRoute>
        }
      >
        <Route index element={<Navigate to="/reproduce" replace />} />
        <Route path="/reproduce" element={<ReproducePage />} />
        <Route path="/reproduce/task/:taskId" element={<ChatPage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/search/task/:taskId" element={<ChatPage />} />
        <Route path="/paper-only" element={<PaperOnlyPage />} />
        <Route path="/paper-only/demo/zero-code-board" element={<ZeroCodeBoardDemoPage />} />
        <Route path="/paper-only/task/:taskId" element={<ChatPage />} />
        <Route path="/experiments" element={<ExperimentsPage />} />
        <Route path="/experiments/task/:taskId" element={<ChatPage />} />
        <Route path="/auto-research" element={<AutoResearchPage />} />
        <Route path="/auto-research/demo/mock-run" element={<AutoResearchMockRunPage />} />
        <Route path="/auto-research/task/:taskId" element={<ChatPage />} />
        <Route path="/polish" element={<PolishPage />} />
        <Route path="/polish/task/:taskId" element={<ChatPage />} />
        <Route path="/model-settings" element={<ModelSettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/reproduce" replace />} />
    </Routes>
  );
}
