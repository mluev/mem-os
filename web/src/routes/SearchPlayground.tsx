import { useMemo, useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { Braces, ChevronDown, Copy, Play, SlidersHorizontal } from "lucide-react";
import { toast } from "sonner";
import { api } from "../api/client";
import { MEMORY_TYPES, TAU } from "../lib/constants";
import {
  Button,
  Card,
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
  Input,
  Label,
  Slider,
  Switch,
  Textarea,
  TypeBadge,
  EmptyState,
} from "../components/ui";

interface Hit {
  id: string;
  text: string;
  type: string;
  scope: string;
  scope_key: string | null;
  score: number;
  similarity: number;
  importance: number;
  recency: number;
  scope_boost: number;
  age_days: number;
}
interface Preview {
  memories: Hit[];
  raw: unknown[];
  used_tokens: number;
  took_ms: number;
  feedback_recorded: false;
  weights: Record<string, number>;
  tau: Record<string, number>;
  dedup_cosine: number;
  embed_ms: number;
  dropped_scope: unknown[];
  dropped_dedup: unknown[];
  dropped_budget: unknown[];
}

export function SearchPlayground() {
  const [query, setQuery] = useState("");
  const [project, setProject] = useState("");
  const [task, setTask] = useState("");
  const [budget, setBudget] = useState(800);
  const [limit, setLimit] = useState(30);
  const [includeRaw, setIncludeRaw] = useState(false);
  const [types, setTypes] = useState<Set<string>>(new Set());
  const preview = useMutation({
    mutationFn: () => api<Preview>("/v1/admin/search-preview", {
      method: "POST",
      body: JSON.stringify({
        query,
        project: project || null,
        task_key: task || null,
        types: types.size ? [...types] : null,
        budget_tokens: budget,
        limit,
        include_raw: includeRaw,
      }),
    }),
    onError: (error) => toast.error(error.message),
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (query.trim()) preview.mutate();
  }
  return (
    <>
      <div className="page-header">
        <div>
          <span className="eyebrow">RANKING DEBUGGER</span>
          <h1>Search playground</h1>
          <p>Production ranking without retrieval feedback. Running this screen never changes retrieval counts.</p>
        </div>
      </div>
      <div className="search-layout">
        <Card className="search-form">
          <div className="card-header"><div><h2>Query context</h2><p>Project and task remove foreign facts before ranking.</p></div></div>
          <form className="form-stack" onSubmit={submit}>
            <Label className="field"><span>Query</span><Textarea autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="What does the user prefer for package managers?" /></Label>
            <Label className="field"><span>Project</span><Input value={project} onChange={(event) => setProject(event.target.value)} placeholder="memkit" /></Label>
            <Label className="field"><span>Task</span><Input value={task} onChange={(event) => setTask(event.target.value)} placeholder="optional task key" /></Label>
            <div className="field"><Label>Types</Label><div className="page-actions" style={{ flexWrap: "wrap" }}>{MEMORY_TYPES.map((type) => <Button type="button" size="sm" variant={types.has(type) ? "default" : "outline"} key={type} className={types.has(type) ? `type-${type}` : ""} onClick={() => setTypes((current) => { const next = new Set(current); next.has(type) ? next.delete(type) : next.add(type); return next; })}>{type}</Button>)}</div></div>
            <div className="field"><span className="field-inline-value"><Label>Token budget</Label><b className="mono">{budget}</b></span><Slider min={100} max={1600} step={50} value={[budget]} onValueChange={([value]) => setBudget(value ?? 800)} /></div>
            <Label className="field"><span>Result limit</span><Input type="number" min="1" max="200" value={limit} onChange={(event) => setLimit(Number(event.target.value))} /></Label>
            <Label className="setting-row">
              <span><strong>Include raw user turns</strong><small>Search immutable source messages alongside memories.</small></span>
              <Switch checked={includeRaw} onCheckedChange={setIncludeRaw} />
            </Label>
            <Button type="submit" disabled={!query.trim() || preview.isPending}><Play size={13} /> {preview.isPending ? "Ranking…" : "Run preview"}</Button>
          </form>
        </Card>
        <div>
          {!preview.data && !preview.isPending ? <Card><EmptyState title="Run a query to inspect ranking" body="The result will show each score term, recency curve, token budget, and every dedup or budget discard." /></Card> : null}
          {preview.isPending ? <Card><div className="loading">Embedding and ranking locally…</div></Card> : null}
          {preview.data ? <Results data={preview.data} /> : null}
        </div>
      </div>
    </>
  );
}

function Results({ data }: { data: Preview }) {
  const [weightsOpen, setWeightsOpen] = useState(false);
  const [weights, setWeights] = useState(data.weights);
  const reranked = useMemo(
    () => [...data.memories].map((hit) => ({
      ...hit,
      labScore:
        (weights.similarity ?? 0) * hit.similarity +
        (weights.importance ?? 0) * hit.importance +
        (weights.recency ?? 0) * hit.recency +
        (weights.scope ?? 0) * hit.scope_boost,
    })).sort((a, b) => b.labScore - a.labScore),
    [data.memories, weights],
  );
  const sum = Object.values(weights).reduce((total, value) => total + value, 0);
  return <>
    <Card>
      <div className="card-header"><div><h2>{data.memories.length} chosen memories</h2><p>{data.took_ms.toFixed(1)} ms total · {data.embed_ms.toFixed(1)} ms embed · feedback recorded: no</p></div><span className="mono">{data.used_tokens} / 800 tokens</span></div>
      <div className="distribution" style={{ margin: 0, borderRadius: 0, height: 5 }}><span style={{ width: `${Math.min(100, data.used_tokens / 10)}%`, background: data.used_tokens >= 600 && data.used_tokens <= 1000 ? "var(--green)" : "var(--amber)" }} /></div>
      {data.memories.map((hit) => <ScoreResult key={hit.id} hit={hit} weights={data.weights} />)}
    </Card>
    <Collapsible open={weightsOpen} onOpenChange={setWeightsOpen} asChild>
    <Card style={{ marginTop: 14 }}>
      <CollapsibleTrigger asChild><Button variant="ghost" className="card-header collapsible-card-trigger">
        <div><h2><SlidersHorizontal size={13} style={{ display: "inline", marginRight: 7 }} />Weight lab</h2><p>Hypothesis only — confirm with <span className="mono">uv run memkit eval</span> before changing code.</p></div><ChevronDown size={15} />
      </Button></CollapsibleTrigger>
      <CollapsibleContent><div className="card-body">
        <div className="form-grid">
          {Object.entries(weights).map(([name, value]) => <div className="field" key={name}><span className="field-inline-value"><Label>{name}</Label><b className="mono">{value.toFixed(2)}</b></span><Slider min={0} max={1} step={.05} value={[value]} onValueChange={([next]) => setWeights((current) => ({ ...current, [name]: next ?? value }))} /></div>)}
        </div>
        <p className={Math.abs(sum - 1) < .001 ? "subtle mono" : "low-confidence mono"}>weight sum = {sum.toFixed(2)}</p>
        <div className="message-list">{reranked.slice(0, 8).map((hit, index) => <div className="message" key={hit.id}><span className="message-role">#{index + 1}<br />{hit.labScore.toFixed(4)}</span><span className="message-content">{hit.text}</span></div>)}</div>
        <Button variant="secondary" size="sm" onClick={() => { void navigator.clipboard.writeText(Object.entries(weights).map(([key, value]) => `W_${key.toUpperCase()} = ${value.toFixed(2)}`).join("\n")); toast.success("Weights copied"); }}><Copy size={12} /> Copy constants</Button>
      </div></CollapsibleContent>
    </Card>
    </Collapsible>
    <div className="dropped-grid">
      <DropCard label="Scope filtered" count={data.dropped_scope.length} />
      <DropCard label="Deduplicated" count={data.dropped_dedup.length} />
      <DropCard label="Over budget" count={data.dropped_budget.length} />
    </div>
  </>;
}

function ScoreResult({ hit, weights }: { hit: Hit; weights: Record<string, number> }) {
  const [open, setOpen] = useState(false);
  const sim = (weights.similarity ?? .55) * hit.similarity;
  const imp = (weights.importance ?? .2) * hit.importance;
  const rec = (weights.recency ?? .15) * hit.recency;
  const scope = (weights.scope ?? .1) * hit.scope_boost;
  const max = Math.max(hit.score, .0001);
  return <div className="score-row">
    <Button variant="ghost" className="score-head score-trigger" onClick={() => setOpen((value) => !value)}>
      <div><TypeBadge type={hit.type} /><p>{hit.text}</p></div><span className="score">{hit.score.toFixed(4)}</span>
    </Button>
    <div className="score-bar" aria-label="Score composition"><span style={{ width: `${sim / max * 100}%` }} /><span style={{ width: `${imp / max * 100}%` }} /><span style={{ width: `${rec / max * 100}%` }} /><span style={{ width: `${scope / max * 100}%` }} /></div>
    <div className="score-parts"><span>similarity {sim.toFixed(3)}</span><span>importance {imp.toFixed(3)}</span><span>recency {rec.toFixed(3)}</span><span>scope {scope.toFixed(3)}</span></div>
    {open ? <div className="formula-grid">
      <div>0.55 × {hit.similarity.toFixed(4)} = {sim.toFixed(4)}</div>
      <div>0.20 × {hit.importance.toFixed(3)} = {imp.toFixed(4)}</div>
      <div>0.15 × {hit.recency.toFixed(4)} = {rec.toFixed(4)}</div>
      <div>0.10 × {hit.scope_boost.toFixed(1)} = {scope.toFixed(4)}</div>
      <div>Σ = {(sim + imp + rec + scope).toFixed(4)}</div>
      <div>age {hit.age_days} days · τ {TAU[hit.type] ?? 180} days</div>
      <DecaySparkline age={hit.age_days} tau={TAU[hit.type] ?? 180} />
    </div> : null}
  </div>;
}

function DecaySparkline({ age, tau }: { age: number; tau: number }) {
  const maxAge = Math.max(tau * 3, age, 1);
  const points = Array.from({ length: 31 }, (_, index) => {
    const x = index * 2;
    const a = index / 30 * maxAge;
    const y = 18 - Math.exp(-a / tau) * 16;
    return `${x},${y.toFixed(2)}`;
  }).join(" ");
  const dotX = Math.min(60, age / maxAge * 60);
  const dotY = 18 - Math.exp(-age / tau) * 16;
  return <svg width="60" height="20" viewBox="0 0 60 20" role="img" aria-label="Recency decay curve"><polyline points={points} fill="none" stroke="currentColor" strokeWidth="1" /><circle cx={dotX} cy={dotY} r="2" fill="var(--amber)" /></svg>;
}

function DropCard({ label, count }: { label: string; count: number }) {
  return <div className="dropped-card"><strong><Braces size={12} style={{ display: "inline", marginRight: 5 }} />{label}</strong><span>{count} candidates</span></div>;
}
