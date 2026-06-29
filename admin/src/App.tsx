import { Navigate, Route, Routes } from "react-router-dom";

import { Shell } from "./components/Shell";
import { AuthProvider, useAuth } from "./lib/auth";
import { ALL_ITEMS } from "./lib/nav";
import { Analytics } from "./pages/Analytics";
import { Broadcasts } from "./pages/Broadcasts";
import { Channels } from "./pages/Channels";
import { Dashboard } from "./pages/Dashboard";
import { Dedup } from "./pages/Dedup";
import { Events } from "./pages/Events";
import { Flows } from "./pages/Flows";
import { Health } from "./pages/Health";
import { Settings } from "./pages/Settings";
import { Sources } from "./pages/Sources";
import { Venues } from "./pages/Venues";
import { Login } from "./pages/Login";
import { Placeholder } from "./pages/Placeholder";

function Gate() {
  const { user, ready } = useAuth();
  if (!ready) return <div className="state">…</div>;
  if (!user) return <Login />;

  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Dashboard />} />
        <Route path="health" element={<Health />} />
        <Route path="ops/flows" element={<Flows />} />
        <Route path="channels" element={<Channels />} />
        <Route path="sources" element={<Sources />} />
        <Route path="broadcasts" element={<Broadcasts />} />
        <Route path="events" element={<Events />} />
        <Route path="analytics" element={<Analytics />} />
        <Route path="venues" element={<Venues />} />
        <Route path="dedup" element={<Dedup />} />
        <Route path="settings" element={<Settings />} />
        {ALL_ITEMS.filter((i) => i.phase).map((i) => (
          <Route key={i.to} path={i.to.replace(/^\//, "")} element={<Placeholder />} />
        ))}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

export function App() {
  return (
    <AuthProvider>
      <Gate />
    </AuthProvider>
  );
}
