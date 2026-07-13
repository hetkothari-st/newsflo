import { Link, useNavigate } from 'react-router-dom';
import LoginForm from '../components/LoginForm';

export default function LoginPage() {
  const navigate = useNavigate();
  return (
    <div className="mx-auto mt-16 w-full max-w-sm px-4">
      <h1 className="mb-6 font-display text-3xl font-bold text-ink">Log in</h1>
      <LoginForm onSuccess={() => navigate('/')} />
      <p className="mt-4 text-xs uppercase tracking-widest text-muted">
        No account?{' '}
        <Link to="/register" className="text-ink underline">
          Register
        </Link>
      </p>
    </div>
  );
}
