import { Navigate, Route, Routes } from 'react-router-dom';
import type { ReactElement } from 'react';
import BottomNav from './components/BottomNav';
import NavBar from './components/NavBar';
import TranslationProgressBanner from './components/TranslationProgressBanner';
import AlertChartsPage from './pages/AlertChartsPage';
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
      <TranslationProgressBanner />
      <NavBar />
      <Routes>
        <Route path="/" element={<FeedPage />} />
        <Route path="/alerts/:id/charts" element={<AlertChartsPage />} />
        <Route
          path="/holdings"
          element={
            <RequireAuth>
              <HoldingsPage />
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
