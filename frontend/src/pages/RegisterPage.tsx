import { Link, useNavigate } from 'react-router-dom';
import RegisterForm from '../components/RegisterForm';

export default function RegisterPage() {
  const navigate = useNavigate();
  return (
    <div className="mx-auto mt-16 w-full max-w-sm px-4">
      <h1 className="mb-6 font-display text-2xl font-bold text-ink">Create account</h1>
      <RegisterForm onSuccess={() => navigate('/')} />
      <p className="mt-4 text-xs uppercase tracking-widest text-muted">
        Already registered?{' '}
        <Link to="/login" className="text-ink underline">
          Log in
        </Link>
      </p>
    </div>
  );
}
