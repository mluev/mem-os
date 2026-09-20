import { createRootRoute, createRoute, createRouter, lazyRouteComponent, Link } from "@tanstack/react-router";
import { z } from "zod";
import { AppShell } from "./components/AppShell";
import { EmptyState } from "./components/ui";

const root = createRootRoute({ component: AppShell });

// `memory` lives on every route: the detail drawer is opened by search param
// so a link to one fact works from the listing, the review queue, an entity
// page or a session transcript without each screen inventing its own state.
const withDrawer = { memory: z.string().optional() };

const overview = createRoute({ getParentRoute: () => root, path: "/", validateSearch: (v) => z.object({ ...withDrawer, days: z.coerce.number().optional() }).parse(v), component: lazyRouteComponent(() => import("./routes/Overview"), "Overview") });
const memories = createRoute({
  getParentRoute: () => root,
  path: "/memories",
  validateSearch: (value) =>
    z
      .object({
        ...withDrawer,
        q: z.string().optional(),
        kind: z.string().optional(),
        scope: z.string().optional(),
        subject: z.string().optional(),
        source_role: z.string().optional(),
        status: z.string().optional(),
        review_status: z.string().optional(),
        tag: z.string().optional(),
        sort: z.string().optional(),
        order: z.string().optional(),
        offset: z.coerce.number().optional(),
        limit: z.coerce.number().optional(),
      })
      .parse(value),
  component: lazyRouteComponent(() => import("./routes/Memories"), "Memories"),
});
const review = createRoute({ getParentRoute: () => root, path: "/review", validateSearch: (v) => z.object({ ...withDrawer, kind: z.string().optional() }).parse(v), component: lazyRouteComponent(() => import("./routes/Review"), "Review") });
const entities = createRoute({ getParentRoute: () => root, path: "/entities", validateSearch: (v) => z.object(withDrawer).parse(v), component: lazyRouteComponent(() => import("./routes/Entities"), "Entities") });
const entity = createRoute({ getParentRoute: () => root, path: "/entities/$slug", validateSearch: (v) => z.object({ ...withDrawer, tab: z.string().optional() }).parse(v), component: lazyRouteComponent(() => import("./routes/Entities"), "EntityDetail") });
const team = createRoute({ getParentRoute: () => root, path: "/team", component: lazyRouteComponent(() => import("./routes/Team"), "Team") });
const search = createRoute({ getParentRoute: () => root, path: "/search", validateSearch: (v) => z.object(withDrawer).parse(v), component: lazyRouteComponent(() => import("./routes/SearchPlayground"), "SearchPlayground") });
const runs = createRoute({ getParentRoute: () => root, path: "/judge-runs", component: lazyRouteComponent(() => import("./routes/JudgeRuns"), "JudgeRuns") });
const run = createRoute({ getParentRoute: () => root, path: "/judge-runs/$runId", component: lazyRouteComponent(() => import("./routes/JudgeRuns"), "JudgeRunDetail") });
const sessions = createRoute({ getParentRoute: () => root, path: "/sessions", component: lazyRouteComponent(() => import("./routes/Sessions"), "Sessions") });
const session = createRoute({ getParentRoute: () => root, path: "/sessions/$sessionId", validateSearch: (v) => z.object(withDrawer).parse(v), component: lazyRouteComponent(() => import("./routes/Sessions"), "SessionDetail") });
const ops = createRoute({ getParentRoute: () => root, path: "/ops", component: lazyRouteComponent(() => import("./routes/Ops"), "Ops") });
const feedback = createRoute({ getParentRoute: () => root, path: "/feedback", component: lazyRouteComponent(() => import("./routes/Feedback"), "Feedback") });
const missing = createRoute({ getParentRoute: () => root, path: "$", component: () => <EmptyState title="Screen not found" body="This route does not exist." action={<Link className="button button-secondary" to="/">Overview</Link>} /> });

const routeTree = root.addChildren([overview, memories, review, entities, entity, team, search, feedback, runs, run, sessions, session, ops, missing]);
export const router = createRouter({ routeTree, basepath: "/ui", defaultPreload: "intent", scrollRestoration: true });
declare module "@tanstack/react-router" { interface Register { router: typeof router } }
