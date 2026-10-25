/* eslint-disable react-refresh/only-export-components */
import React, { createContext, useContext, useEffect, useState, useCallback } from "react";

interface RouterContextType {
  path: string;
  navigate: (to: string) => void;
  redirectAfterLogin: string | null;
  setRedirectAfterLogin: (path: string | null) => void;
}

const RouterContext = createContext<RouterContextType | undefined>(undefined);

export function RouterProvider({
  children,
  initialPath,
}: {
  children: React.ReactNode;
  initialPath?: string;
}) {
  const [path, setPath] = useState<string>(
    initialPath || (typeof window !== "undefined" ? window.location.pathname : "/")
  );
  const [redirectAfterLogin, setRedirectAfterLogin] = useState<string | null>(null);

  const navigate = useCallback((to: string) => {
    if (typeof window !== "undefined") {
      window.history.pushState(null, "", to);
    }
    setPath(to);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const onPopState = () => {
      setPath(window.location.pathname);
    };

    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  return (
    <RouterContext.Provider
      value={{
        path,
        navigate,
        redirectAfterLogin,
        setRedirectAfterLogin,
      }}
    >
      {children}
    </RouterContext.Provider>
  );
}

export function useRouter() {
  const context = useContext(RouterContext);
  if (!context) {
    throw new Error("useRouter must be used within a RouterProvider");
  }
  return context;
}
