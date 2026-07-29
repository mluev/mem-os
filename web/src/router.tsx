import {
  createRootRoute,
  createRoute,
  createRouter,
  lazyRouteComponent,
  Link,
} from "@tanstack/react-router";
import { z } from "zod";
import { AppShell } from "./components/AppShell";
import { EmptyState } from "./components/ui";

const rootRoute = createRootRoute({ component: AppShell });
const indexRoute = createRoute({ getParentRoute: () => rootRoute, path: "/", component: lazyRouteComponent(() => import("./routes/Overview"), "Overview") });

const memorySearch = z.object({
  q: z.string().optional(),
  type: z.string().optional(),
  status: z.string().optional(),
  scope: z.string().optional(),
  sort: z.string().optional(),
  order: z.enum(["asc", "desc"]).optional(),
  page: z.coerce.number().int().positive().optional(),
  sel: z.string().optional(),
  never_retrieved: z.coerce.boolean().optional(),
  expired_validity: z.coerce.boolean().optional(),
  min_importance: z.coerce.number().optional(),
  max_importance: z.coerce.number().optional(),
});
const memoriesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/memories",
  validateSearch: (search) => memorySearch.parse(search),
  component: lazyRouteComponent(() => import("./routes/Memories"), "Memories"),
});
const searchRoute = createRoute({ getParentRoute: () => rootRoute, path: "/search", component: lazyRouteComponent(() => import("./routes/SearchPlayground"), "SearchPlayground") });
const judgeRunsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/judge-runs", component: lazyRouteComponent(() => import("./routes/JudgeRuns"), "JudgeRuns") });
const judgeRunDetailRoute = createRoute({ getParentRoute: () => rootRoute, path: "/judge-runs/$runId", component: lazyRouteComponent(() => import("./routes/JudgeRuns"), "JudgeRunDetail") });
const sessionsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/sessions", component: lazyRouteComponent(() => import("./routes/Sessions"), "Sessions") });
const sessionDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/sessions/$sessionId",
  validateSearch: (search) => z.object({ highlight: z.coerce.number().int().optional() }).parse(search),
  component: lazyRouteComponent(() => import("./routes/Sessions"), "SessionDetail"),
});
const opsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/ops", component: lazyRouteComponent(() => import("./routes/Ops"), "Ops") });
const tasksRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/tasks",
  validateSearch: (search) => z.object({
    project: z.string().optional(),
    archived: z.coerce.boolean().optional(),
    sel: z.string().optional(),
  }).parse(search),
  component: lazyRouteComponent(() => import("./routes/Tasks"), "Tasks"),
});
const notFoundRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "$",
  component: () => <EmptyState title="This screen does not exist" body="The API still returns JSON 404s; only the /ui application uses this fallback." action={<Link className="button button-secondary" to="/">Back to overview</Link>} />,
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  memoriesRoute,
  searchRoute,
  judgeRunsRoute,
  judgeRunDetailRoute,
  sessionsRoute,
  sessionDetailRoute,
  opsRoute,
  tasksRoute,
  notFoundRoute,
]);

export const router = createRouter({
  routeTree,
  basepath: "/ui",
  defaultPreload: "intent",
  scrollRestoration: true,
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
