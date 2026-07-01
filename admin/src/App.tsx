import { Navigate, Route, Routes } from "react-router-dom";

import { Shell } from "./components/Shell";
import { AuthProvider, useAuth } from "./lib/auth";
import { Adstat } from "./pages/Adstat";
import { Analytics } from "./pages/Analytics";
import { Audit } from "./pages/Audit";
import { Broadcasts } from "./pages/Broadcasts";
import { Buys } from "./pages/Buys";
import { BuyPlan } from "./pages/BuyPlan";
import { Channels } from "./pages/Channels";
import { Cities } from "./pages/Cities";
import { Danger } from "./pages/Danger";
import { Dashboard } from "./pages/Dashboard";
import { DataOps } from "./pages/DataOps";
import { Dedup } from "./pages/Dedup";
import { Events } from "./pages/Events";
import { Flows } from "./pages/Flows";
import { Funnel } from "./pages/Funnel";
import { Health } from "./pages/Health";
import { Settings } from "./pages/Settings";
import { Sources } from "./pages/Sources";
import { System } from "./pages/System";
import { Users } from "./pages/Users";
import { Venues } from "./pages/Venues";
import { Login } from "./pages/Login";
import { Moderation } from "./pages/Moderation";

function Gate() {
  const { user, ready } = useAuth();
  if (!ready) return <div className="state">…</div>;
  if (!user) return <Login />;

  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Dashboard />} />
        <Route path="moderation" element={<Moderation />} />
        <Route path="health" element={<Health />} />
        <Route path="ops/flows" element={<Flows />} />
        <Route path="channels" element={<Channels />} />
        <Route path="sources" element={<Sources />} />
        <Route path="broadcasts" element={<Broadcasts />} />
        <Route path="events" element={<Events />} />
        <Route path="analytics" element={<Analytics />} />
        <Route path="funnel" element={<Funnel />} />
        <Route path="venues" element={<Venues />} />
        <Route path="dedup" element={<Dedup />} />
        <Route path="settings" element={<Settings />} />
        <Route path="users" element={<Users />} />
        <Route path="cities" element={<Cities />} />
        <Route path="audit" element={<Audit />} />
        <Route path="adstat" element={<Adstat />} />
        <Route path="buy-plan" element={<BuyPlan />} />
        <Route path="buys" element={<Buys />} />
        <Route path="ops/data" element={<DataOps />} />
        <Route path="ops/danger" element={<Danger />} />
        <Route path="ops/system" element={<System />} />
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
