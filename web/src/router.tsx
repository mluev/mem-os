import { createRootRoute, createRoute, createRouter, lazyRouteComponent, Link } from "@tanstack/react-router";
import { z } from "zod";
import { AppShell } from "./components/AppShell";
import { EmptyState } from "./components/ui";

const root = createRootRoute({ component: AppShell });
const overview = createRoute({ getParentRoute: () => root, path: "/", component: lazyRouteComponent(() => import("./routes/Overview"), "Overview") });
const memories = createRoute({
  getParentRoute: () => root,
  path: "/memories",
  validateSearch: (value) => z.object({ kind: z.string().optional(), cursor: z.string().optional() }).parse(value),
  component: lazyRouteComponent(() => import("./routes/Memories"), "Memories"),
});
const search = createRoute({ getParentRoute: () => root, path: "/search", component: lazyRouteComponent(() => import("./routes/SearchPlayground"), "SearchPlayground") });
const runs = createRoute({ getParentRoute: () => root, path: "/judge-runs", component: lazyRouteComponent(() => import("./routes/JudgeRuns"), "JudgeRuns") });
const run = createRoute({ getParentRoute: () => root, path: "/judge-runs/$runId", component: lazyRouteComponent(() => import("./routes/JudgeRuns"), "JudgeRunDetail") });
const sessions = createRoute({ getParentRoute: () => root, path: "/sessions", component: lazyRouteComponent(() => import("./routes/Sessions"), "Sessions") });
const session = createRoute({ getParentRoute: () => root, path: "/sessions/$sessionId", component: lazyRouteComponent(() => import("./routes/Sessions"), "SessionDetail") });
const ops = createRoute({ getParentRoute: () => root, path: "/ops", component: lazyRouteComponent(() => import("./routes/Ops"), "Ops") });
const feedback = createRoute({ getParentRoute: () => root, path: "/feedback", component: lazyRouteComponent(() => import("./routes/Feedback"), "Feedback") });
const missing = createRoute({ getParentRoute: () => root, path: "$", component: () => <EmptyState title="Screen not found" body="This route does not exist." action={<Link className="button button-secondary" to="/">Overview</Link>} /> });

const routeTree = root.addChildren([overview, memories, search, feedback, runs, run, sessions, session, ops, missing]);
export const router = createRouter({ routeTree, basepath: "/ui", defaultPreload: "intent", scrollRestoration: true });
declare module "@tanstack/react-router" { interface Register { router: typeof router } }
