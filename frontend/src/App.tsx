import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./lib/auth";
import { AuthPage } from "./pages/AuthPage";
import { RoomsPage } from "./pages/RoomsPage";
import { RoomPage } from "./pages/RoomPage";
import type { ReactNode } from "react";

function RequireAuth({ children }: { children: ReactNode }) {
  const { token } = useAuth();
  return token ? <>{children}</> : <Navigate to="/auth" replace />;
}

export function App() {
  const { token } = useAuth();
  return (
    <Routes>
      <Route
        path="/auth"
        element={token ? <Navigate to="/rooms" replace /> : <AuthPage />}
      />
      <Route
        path="/rooms"
        element={
          <RequireAuth>
            <RoomsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/rooms/:roomId"
        element={
          <RequireAuth>
            <RoomPage />
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to={token ? "/rooms" : "/auth"} replace />} />
    </Routes>
  );
}
