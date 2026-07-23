import { Navigate, Route, Routes } from 'react-router-dom';
import { useState, type ReactElement } from 'react';
import BottomNav from './components/BottomNav';
import CalendarModal from './components/CalendarModal';
import NavBar from './components/NavBar';
import TranslationProgressBanner from './components/TranslationProgressBanner';
import AccountPage from './pages/AccountPage';
import AlertChartsPage from './pages/AlertChartsPage';
import AlertCompanyAnalysisPage from './pages/AlertCompanyAnalysisPage';
import CompanyPage from './pages/CompanyPage';
import FeedPage from './pages/FeedPage';
import FeedV2Page from './pages/FeedV2Page';
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
  const [calendarOpen, setCalendarOpen] = useState(false);
  return (
    <div className="min-h-screen bg-page pb-14 font-sans text-ink md:pb-0">
      <TranslationProgressBanner />
      <NavBar onOpenCalendar={() => setCalendarOpen(true)} />
      <Routes>
        <Route path="/" element={<FeedPage />} />
        <Route path="/feed-v2" element={<FeedV2Page />} />
        <Route path="/company/:id" element={<CompanyPage />} />
        <Route path="/alerts/:id/charts" element={<AlertChartsPage />} />
        <Route path="/alerts/:id/company/:companyId" element={<AlertCompanyAnalysisPage />} />
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
      <BottomNav onOpenCalendar={() => setCalendarOpen(true)} />
      <CalendarModal open={calendarOpen} onClose={() => setCalendarOpen(false)} />
    </div>
  );
}
