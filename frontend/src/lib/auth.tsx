import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { login as apiLogin, register as apiRegister } from './api';

interface AuthState {
  token: string | null;
  email: string | null;
}

interface AuthContextValue extends AuthState {
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const TOKEN_KEY = 'newsflo.token';
const EMAIL_KEY = 'newsflo.email';

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(() => ({
    token: localStorage.getItem(TOKEN_KEY),
    email: localStorage.getItem(EMAIL_KEY),
  }));

  const persist = useCallback((token: string, email: string) => {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(EMAIL_KEY, email);
    setState({ token, email });
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await apiLogin(email, password);
      persist(res.access_token, email);
    },
    [persist],
  );

  const register = useCallback(
    async (email: string, password: string) => {
      const res = await apiRegister(email, password);
      persist(res.access_token, email);
    },
    [persist],
  );

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(EMAIL_KEY);
    setState({ token: null, email: null });
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ ...state, login, register, logout }),
    [state, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (ctx === null) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return ctx;
}
