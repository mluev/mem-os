import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { KeyGate } from "./components/AppShell";
import { Toaster } from "./components/ui";
import { router } from "./router";
import "./styles/globals.css";

const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error) => {
      if ("status" in error && error.status === 401) {
        window.dispatchEvent(new Event("memkit:unauthorized"));
      }
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      retry: (count, error) => !("status" in error && error.status === 401) && count < 2,
      refetchOnWindowFocus: false,
    },
  },
});

const root = document.getElementById("root");
if (!root) throw new Error("Missing root element");
createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <KeyGate>
        <RouterProvider router={router} />
      </KeyGate>
      <Toaster richColors position="bottom-right" />
    </QueryClientProvider>
  </StrictMode>,
);
