import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { api, getStaffToken, setStaffToken } from "./api";
import type { LoginResponse, ShopInfo, StaffUser } from "./types";

interface AuthValue {
  user: StaffUser | null;
  shop: ShopInfo | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [token, setToken] = useState<string | null>(getStaffToken);

  const me = useQuery({
    queryKey: ["me", token],
    queryFn: () => api<{ user: StaffUser; shop: ShopInfo }>("/api/v1/auth/me"),
    enabled: !!token,
    retry: false,
    staleTime: 5 * 60_000,
  });

  const logout = useCallback(() => {
    setStaffToken(null);
    setToken(null);
    queryClient.clear();
  }, [queryClient]);

  useEffect(() => {
    const onLogout = () => setToken(null);
    window.addEventListener("staff-logout", onLogout);
    return () => window.removeEventListener("staff-logout", onLogout);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const response = await api<LoginResponse>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    setStaffToken(response.access_token);
    setToken(response.access_token);
  }, []);

  const value: AuthValue = {
    user: token ? (me.data?.user ?? null) : null,
    shop: token ? (me.data?.shop ?? null) : null,
    loading: !!token && me.isLoading,
    login,
    logout,
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
