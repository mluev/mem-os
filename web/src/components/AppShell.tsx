import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  BookOpen,
  Boxes,
  Brain,
  Command,
  Database,
  Gauge,
  Inbox,
  LogOut,
  Menu,
  MessagesSquare,
  Moon,
  Search,
  ThumbsUp,
  Sun,
  TerminalSquare,
  UsersRound,
  X,
} from "lucide-react";
import { Link, Outlet, useRouter, useRouterState } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, forgetApiKey } from "../api/client";
import type { Me, Stats } from "../api/types";
import {
  Button,
  Command as CommandMenu,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  Dialog,
  DialogContent,
  Input,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "./ui";

const NAV = [
  { to: "/", label: "Overview", icon: Gauge },
  { to: "/review", label: "Needs attention", icon: Inbox },
  { to: "/memories", label: "Memories", icon: Brain },
  { to: "/search", label: "Search", icon: Search },
  { to: "/entities", label: "Entities", icon: Boxes },
  { to: "/team", label: "Team", icon: UsersRound },
  { to: "/sessions", label: "Sessions", icon: MessagesSquare },
  { to: "/feedback", label: "Feedback", icon: ThumbsUp },
  { to: "/judge-runs", label: "Judge runs", icon: BookOpen },
  { to: "/ops", label: "Operations", icon: TerminalSquare },
] as const;

interface Health { qdrant: { available: boolean; memories: number | null; raw: number | null }; outbox: { pending: number } }

export function AuthGate({ children }: { children: React.ReactNode }) {
  const client = useQueryClient();
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api<Me>("/v1/auth/me"),
    retry: false,
    staleTime: 60_000,
  });
  const [signedOut, setSignedOut] = useState(false);
  useEffect(() => {
    const locked = () => {
      setSignedOut(true);
      // Cached memories and in-flight reads belong to the old identity.
      // Cancelling first also prevents late responses from repopulating them.
      void client.cancelQueries();
      client.clear();
    };
    window.addEventListener("memkit:unauthorized", locked);
    return () => window.removeEventListener("memkit:unauthorized", locked);
  }, [client]);
  if (me.isLoading) return <main className="key-gate" aria-busy="true" />;
  if (me.data && !signedOut) return children;
  return <SignIn onSignedIn={() => { setSignedOut(false); void me.refetch(); }} />;
}

function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const [handle, setHandle] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ handle: handle.trim(), password }),
      });
      setPassword("");
      onSignedIn();
    } catch (reason) {
      // The service answers identically for a wrong password and an unknown
      // handle, so this message must not be more specific than that.
      setError(reason instanceof Error ? reason.message : "Could not sign in");
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="key-gate">
      <form className="key-card" onSubmit={submit}>
        <div className="brand-mark"><Database size={20} /></div>
        <div>
          <span className="eyebrow">MEM OS</span>
          <h1>Sign in</h1>
          <p>Your memory, and the memory your team shares.</p>
        </div>
        <label>
          Handle
          <Input
            autoFocus
            autoComplete="username"
            value={handle}
            onChange={(event) => setHandle(event.target.value)}
            placeholder="you"
          />
        </label>
        <label>
          Password
          <Input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        {error ? <p className="form-error">{error}</p> : null}
        <Button type="submit" disabled={busy || !handle.trim() || !password}>
          {busy ? "Signing in…" : "Open dashboard"}
        </Button>
      </form>
    </main>
  );
}

export function AppShell() {
  const path = useRouterState({ select: (state) => state.location.pathname });
  const [sidebar, setSidebar] = useState(false);
  const [palette, setPalette] = useState(false);
  const [theme, setTheme] = useState(
    () => localStorage.getItem("memkit.theme") === "light" ? "light" : "dark",
  );
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/v1/auth/me"), staleTime: 60_000 });
  const health = useQuery({
    queryKey: ["health"],
    queryFn: () => api<Health>("/v1/admin/health"),
    refetchInterval: 15_000,
    retry: false,
  });
  // The badge is the whole point of a review queue: work nobody can see does
  // not get done.
  const pending = useQuery({
    queryKey: ["stats", "review", "badge"],
    queryFn: () => api<Stats<{ pending: number }>>("/v1/admin/stats/review?days=1"),
    refetchInterval: 30_000,
    retry: false,
  });
  const waiting = pending.data?.totals.pending ?? 0;
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("memkit.theme", theme);
  }, [theme]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPalette((value) => !value);
      }
      if (event.key === "Escape") setPalette(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const title = useMemo(
    () => NAV.find((item) => item.to === path)?.label ?? "memkit",
    [path],
  );
  const nextTheme = theme === "dark" ? "light" : "dark";
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <aside className={sidebar ? "sidebar sidebar-open" : "sidebar"}>
        <div className="brand">
          <span className="brand-mark"><Database size={17} /></span>
          <div><strong>memkit</strong><small>Memory OS</small></div>
        </div>
        <span className="nav-label">Workspace</span>
        <nav>
          {NAV.map(({ to, label, icon: Icon }) => (
            <Link
              key={to}
              to={to}
              className={path === to || (to !== "/" && path.startsWith(to)) ? "nav-link active" : "nav-link"}
              onClick={() => setSidebar(false)}
            >
              <Icon size={17} strokeWidth={1.8} />
              {label}
              {to === "/review" && waiting > 0 ? <span className="nav-badge">{waiting}</span> : null}
            </Link>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="service-status">
            <span className={health.data ? "health-dot ok" : "health-dot bad"} />
            <div>
              <strong>{health.data?.qdrant.available ? "Service healthy" : "Needs attention"}</strong>
              <small>{health.data ? `${health.data.qdrant.memories ?? "—"} memories · ${health.data.outbox.pending} queued` : "Checking…"}</small>
            </div>
          </div>
          {me.data ? (
            <div className="identity">
              <div>
                <strong>{me.data.display_name}</strong>
                <small>{me.data.handle} · {me.data.role}</small>
              </div>
              <Button
                variant="ghost"
                size="sm"
                aria-label="Sign out"
                onClick={async () => {
                  try {
                    await api("/v1/auth/logout", { method: "POST" });
                  } finally {
                    forgetApiKey();
                  }
                }}
              >
                <LogOut size={13} /> Sign out
              </Button>
            </div>
          ) : null}
        </div>
      </aside>
      {sidebar ? <button type="button" className="sidebar-scrim" aria-label="Close navigation backdrop" onClick={() => setSidebar(false)} /> : null}
      <Button
        variant="ghost"
        size="icon"
        className={sidebar ? "mobile-menu is-open" : "mobile-menu"}
        aria-label={sidebar ? "Close navigation" : "Open navigation"}
        onClick={() => setSidebar((value) => !value)}
      >
        <span className="mobile-menu-icon mobile-menu-open"><Menu size={17} strokeWidth={1.8} /></span>
        <span className="mobile-menu-icon mobile-menu-close"><X size={18} strokeWidth={1.8} /></span>
      </Button>
      <div className="content-shell">
        <header className="topbar">
          <div className="topbar-title">
            <span className="topbar-mark"><Database size={17} /></span>
            <span>{title}</span>
          </div>
          <div className="topbar-actions">
            <Button variant="secondary" className="command-button" onClick={() => setPalette(true)}>
              <Command size={19} /> Jump or search <kbd>⌘K</kbd>
            </Button>
            <TooltipProvider delayDuration={250}>
              <Tooltip>
                <TooltipTrigger asChild><Button variant="secondary" size="icon" className="icon-button" aria-label={`Use ${nextTheme} theme`} onClick={() => setTheme(nextTheme)}>{theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}</Button></TooltipTrigger>
                <TooltipContent>Use {nextTheme} theme</TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
        </header>
        {(health.data?.outbox.pending ?? 0) > 0 ? (
          <div className="health-banner">
            <span><strong>Index updates are queued.</strong> Nothing is lost — the database has them; only search is behind.</span>
            <Link to="/ops">Open maintenance →</Link>
          </div>
        ) : null}
        <main className="page" id="main-content"><Outlet /></main>
      </div>
      {palette ? <CommandPalette close={() => setPalette(false)} /> : null}
    </div>
  );
}

function CommandPalette({ close }: { close: () => void }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const items = NAV.filter((item) => item.label.toLowerCase().includes(query.toLowerCase()));
  return (
    <Dialog open onOpenChange={(open) => { if (!open) close(); }}>
      <DialogContent className="command-palette" hideClose>
        <CommandMenu>
          <CommandInput autoFocus value={query} onValueChange={setQuery} placeholder="Go to a screen…" />
          <CommandList>
            <CommandEmpty>No matching screen.</CommandEmpty>
            <CommandGroup heading="Navigate">
          {items.map(({ to, label, icon: Icon }) => (
                <CommandItem key={to} value={label} onSelect={() => { void router.navigate({ to }); close(); }}><Icon size={17} />{label}<span>↵</span></CommandItem>
          ))}
            </CommandGroup>
          </CommandList>
        </CommandMenu>
      </DialogContent>
    </Dialog>
  );
}
