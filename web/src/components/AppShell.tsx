import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  BookOpen,
  Brain,
  Command,
  Database,
  Gauge,
  KeyRound,
  Menu,
  Moon,
  Search,
  ThumbsUp,
  Sun,
  TerminalSquare,
  UsersRound,
  X,
} from "lucide-react";
import { Link, Outlet, useRouter, useRouterState } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { api, forgetApiKey, getApiKey, rememberApiKey } from "../api/client";
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
  { to: "/memories", label: "Memories", icon: Brain },
  { to: "/search", label: "Search", icon: Search },
  { to: "/feedback", label: "Feedback", icon: ThumbsUp },
  { to: "/judge-runs", label: "Judge runs", icon: BookOpen },
  { to: "/sessions", label: "Sessions", icon: UsersRound },
  { to: "/ops", label: "Operations", icon: TerminalSquare },
] as const;

interface Health { qdrant: { available: boolean; memories: number | null; raw: number | null }; outbox: { pending: number } }

export function KeyGate({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(import.meta.env.DEV || Boolean(getApiKey()));
  useEffect(() => {
    const locked = () => setReady(false);
    const unlocked = () => setReady(true);
    window.addEventListener("memkit:unauthorized", locked);
    window.addEventListener("memkit:key-changed", unlocked);
    return () => {
      window.removeEventListener("memkit:unauthorized", locked);
      window.removeEventListener("memkit:key-changed", unlocked);
    };
  }, []);
  if (ready) return children;
  return <KeyDialog onReady={() => setReady(true)} />;
}

function KeyDialog({ onReady }: { onReady: () => void }) {
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    rememberApiKey(key);
    try {
      await api("/v1/memories?limit=1");
      onReady();
    } catch (reason) {
      forgetApiKey();
      setError(reason instanceof Error ? reason.message : "Invalid key");
    }
  }
  return (
    <main className="key-gate">
      <form className="key-card" onSubmit={submit}>
        <div className="brand-mark"><Database size={20} /></div>
        <div>
          <span className="eyebrow">LOCAL ADMIN</span>
          <h1>Unlock memkit</h1>
          <p>The key stays in this browser tab and is sent only to Mem OS.</p>
        </div>
        <label>
          API key
          <span className="input-with-icon">
            <KeyRound size={15} />
            <Input
              type="password"
              autoFocus
              value={key}
              onChange={(event) => setKey(event.target.value)}
              placeholder="X-API-Key"
            />
          </span>
        </label>
        {error ? <p className="form-error">{error}</p> : null}
        <Button type="submit" disabled={!key.trim()}>Open dashboard</Button>
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
  const health = useQuery({
    queryKey: ["health"],
    queryFn: () => api<Health>("/v1/admin/health"),
    refetchInterval: 15_000,
  });
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
          <Button variant="ghost" size="sm" className="key-forget" onClick={forgetApiKey}><KeyRound size={13} /> API key</Button>
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
            <span><strong>Index updates are queued.</strong> SQLite is safe; inspect delivery in Operations.</span>
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
