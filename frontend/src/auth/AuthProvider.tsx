/* eslint-disable react-refresh/only-export-components */
import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import { apiFetch, setAccessToken, setOnUnauthenticated } from "../api/client";
import type { components } from "../api/schema";

export type UserResponse = components["schemas"]["UserResponse"];
export type TokenResponse = components["schemas"]["TokenResponse"];
export type LoginRequest = components["schemas"]["UserLoginRequest"];
export type SignupRequest = components["schemas"]["UserSignupRequest"];

interface AuthContextType {
  user: UserResponse | null;
  accessToken: string | null;
  isLoading: boolean;
  login: (credentials: LoginRequest) => Promise<void>;
  signup: (data: SignupRequest) => Promise<void>;
  logout: () => Promise<void>;
  refreshAuth: () => Promise<boolean>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserResponse | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const applyAuth = useCallback((tokenResponse: TokenResponse | null) => {
    if (tokenResponse) {
      setAccessToken(tokenResponse.access_token);
      setToken(tokenResponse.access_token);
      setUser(tokenResponse.user);
    } else {
      setAccessToken(null);
      setToken(null);
      setUser(null);
    }
  }, []);

  const refreshAuth = useCallback(async (): Promise<boolean> => {
    try {
      const data = await apiFetch<TokenResponse>("/v1/auth/refresh", {
        method: "POST",
        headers: {
          "X-FlowForge-CSRF": "1",
        },
      });
      applyAuth(data);
      return true;
    } catch {
      applyAuth(null);
      return false;
    }
  }, [applyAuth]);

  useEffect(() => {
    setOnUnauthenticated(() => {
      applyAuth(null);
    });

    let isMounted = true;
    refreshAuth().finally(() => {
      if (isMounted) {
        setIsLoading(false);
      }
    });

    return () => {
      isMounted = false;
      setOnUnauthenticated(null);
    };
  }, [applyAuth, refreshAuth]);

  const login = async (credentials: LoginRequest) => {
    const data = await apiFetch<TokenResponse>("/v1/auth/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(credentials),
    });
    applyAuth(data);
  };

  const signup = async (req: SignupRequest) => {
    const data = await apiFetch<TokenResponse>("/v1/auth/signup", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(req),
    });
    applyAuth(data);
  };

  const logout = async () => {
    try {
      await apiFetch<void>("/v1/auth/logout", {
        method: "POST",
        headers: {
          "X-FlowForge-CSRF": "1",
        },
      });
    } finally {
      applyAuth(null);
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        accessToken: token,
        isLoading,
        login,
        signup,
        logout,
        refreshAuth,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
