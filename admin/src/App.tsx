import { Navigate, Route, Routes } from "react-router-dom";

import { Shell } from "./components/Shell";
import { AuthProvider, useAuth } from "./lib/auth";
import { ALL_ITEMS } from "./lib/nav";
import { Dashboard } from "./pages/Dashboard";
import { Health } from "./pages/Health";
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
