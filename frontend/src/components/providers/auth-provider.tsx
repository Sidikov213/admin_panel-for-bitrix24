"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect } from "react";
import { ApiError, api } from "@/lib/api";
import type { User } from "@/types/api";

interface AuthContextValue {
  user: User | undefined;
  isLoading: boolean;
  isAuthenticated: boolean;
  logout: () => Promise<void>;
  refetch: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();

  const { data: user, isLoading, error, refetch } = useQuery({
    queryKey: ["auth", "me"],
    queryFn: () => api.me(),
    retry: false,
  });

  useEffect(() => {
    if (isLoading) return;
    const isLogin = pathname === "/login";
    if (error instanceof ApiError && error.status === 401 && !isLogin) {
      router.replace("/login");
    }
  }, [error, isLoading, pathname, router]);

  const logout = async () => {
    await api.logout();
    queryClient.setQueryData(["auth", "me"], undefined);
    queryClient.clear();
    router.replace("/login");
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        logout,
        refetch: () => {
          void refetch();
        },
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
