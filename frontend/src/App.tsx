import { Navigate, Route, Routes } from 'react-router-dom';
import type { ReactElement } from 'react';
import BottomNav from './components/BottomNav';
import NavBar from './components/NavBar';
import AccountPage from './pages/AccountPage';
import FeedPage from './pages/FeedPage';
import HoldingsPage from './pages/HoldingsPage';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import { useAuth } from './lib/auth';

function RequireAuth({ children }: { children: ReactElement }) {
  const { token } = useAuth();
  if (!token) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  return (
    <div className="min-h-screen bg-page pb-14 font-sans text-ink md:pb-0">
      <NavBar />
      <Routes>
        <Route path="/" element={<FeedPage />} />
        <Route
          path="/holdings"
          element={
            <RequireAuth>
              <HoldingsPage />
            </RequireAuth>
          }
        />
        <Route
          path="/account"
          element={
            <RequireAuth>
              <AccountPage />
            </RequireAuth>
          }
        />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
      </Routes>
      <BottomNav />
    </div>
  );
}
