import "./index.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, StrictMode, Suspense, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";

import { AdminLayout, PublicLayout } from "./components/Layout";
import { AuthProvider } from "./lib/auth";
import { I18nProvider } from "./lib/i18n";
import ChatPage from "./pages/Chat";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import NotFound from "./pages/NotFound";
import { Spinner } from "./components/ui";

// Admin pages (and their charts) load only when an admin opens them.
const Dashboard = lazy(() => import("./pages/admin/Dashboard"));
const Conversations = lazy(() => import("./pages/admin/Conversations"));
const ConversationDetail = lazy(() => import("./pages/admin/ConversationDetail"));
const Knowledge = lazy(() => import("./pages/admin/Knowledge"));
const Evaluations = lazy(() => import("./pages/admin/Evaluations"));

const page = (node: ReactNode) => <Suspense fallback={<Spinner />}>{node}</Suspense>;

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 15_000 } },
});

const router = createBrowserRouter([
  {
    element: <PublicLayout />,
    children: [
      { path: "/", element: <Landing /> },
      { path: "/chat", element: <ChatPage /> },
      { path: "/login", element: <Login /> },
    ],
  },
  {
    path: "/admin",
    element: <AdminLayout />,
    children: [
      { index: true, element: page(<Dashboard />) },
      { path: "conversations", element: page(<Conversations />) },
      { path: "conversations/:id", element: page(<ConversationDetail />) },
      { path: "knowledge", element: page(<Knowledge />) },
      { path: "evaluations", element: page(<Evaluations />) },
    ],
  },
  { path: "*", element: <NotFound /> },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <AuthProvider>
          <RouterProvider router={router} />
        </AuthProvider>
      </I18nProvider>
    </QueryClientProvider>
  </StrictMode>,
);
