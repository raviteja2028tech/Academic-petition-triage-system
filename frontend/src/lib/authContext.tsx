import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, getStoredToken, setStoredToken } from "./api";
import type { AuthUser, UserRole } from "./types";

interface AuthContextType {
  user: AuthUser | null;
  token: string | null;
  role: UserRole | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (userId: string, pass: string, expectedRole?: UserRole) => Promise<AuthUser>;
  studentLogin: (userId: string, pass: string) => Promise<AuthUser>;
  examinerLogin: (userId: string, pass: string) => Promise<AuthUser>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const USER_STORAGE_KEY = "academic_triage_user_profile";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(getStoredToken());
  const [user, setUserState] = useState<AuthUser | null>(() => {
    try {
      const saved = localStorage.getItem(USER_STORAGE_KEY);
      return saved ? (JSON.parse(saved) as AuthUser) : null;
    } catch {
      return null;
    }
  });
  const [isLoading, setIsLoading] = useState<boolean>(true);

  // Validate session on initial load
  useEffect(() => {
    let active = true;
    const currentToken = getStoredToken();
    if (!currentToken) {
      setIsLoading(false);
      return;
    }

    api.me()
      .then((profile) => {
        if (!active) return;
        setUserState(profile);
        localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(profile));
      })
      .catch(() => {
        if (!active) return;
        setStoredToken(null);
        setTokenState(null);
        setUserState(null);
        localStorage.removeItem(USER_STORAGE_KEY);
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  const handleAuthSuccess = (accessToken: string, authUser: AuthUser) => {
    setStoredToken(accessToken);
    setTokenState(accessToken);
    setUserState(authUser);
    localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(authUser));
  };

  const login = async (userId: string, pass: string, expectedRole?: UserRole): Promise<AuthUser> => {
    const res = await api.login({ user_id: userId, password: pass, role: expectedRole });
    handleAuthSuccess(res.access_token, res.user);
    return res.user;
  };

  const studentLogin = async (userId: string, pass: string): Promise<AuthUser> => {
    const res = await api.studentLogin({ user_id: userId, password: pass });
    handleAuthSuccess(res.access_token, res.user);
    return res.user;
  };

  const examinerLogin = async (userId: string, pass: string): Promise<AuthUser> => {
    const res = await api.examinerLogin({ user_id: userId, password: pass });
    handleAuthSuccess(res.access_token, res.user);
    return res.user;
  };

  const logout = async (): Promise<void> => {
    try {
      await api.logout();
    } catch {
      // Ignore network errors on logout
    } finally {
      setStoredToken(null);
      setTokenState(null);
      setUserState(null);
      localStorage.removeItem(USER_STORAGE_KEY);
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        role: user?.role ?? null,
        isAuthenticated: !!token && !!user,
        isLoading,
        login,
        studentLogin,
        examinerLogin,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    return {
      user: null,
      token: null,
      role: null,
      isAuthenticated: false,
      isLoading: false,
      login: async () => ({ user_id: "", role: "student", name: "" }),
      studentLogin: async () => ({ user_id: "", role: "student", name: "" }),
      examinerLogin: async () => ({ user_id: "", role: "examiner", name: "" }),
      logout: async () => {},
    };
  }
  return context;
}
