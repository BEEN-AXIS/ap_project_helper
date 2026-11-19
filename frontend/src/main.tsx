import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import { refreshSession } from "./net/api";
import { useAuth } from "./state/auth";
import { applyDocumentSettings, useSettings } from "./state/settings";
import "./styles.css";

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 10_000, retry: 1, refetchOnWindowFocus: false } } });

function Boot() {
  useEffect(() => {
    applyDocumentSettings(useSettings.getState().s);
    void refreshSession().finally(() => {
      const p = useAuth.getState().profile;
      if (p?.settings) useSettings.getState().hydrate(p.settings as never);
      useAuth.getState().markReady();
    });
  }, []);
  return <App />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <Boot />
    </QueryClientProvider>
  </StrictMode>,
);
