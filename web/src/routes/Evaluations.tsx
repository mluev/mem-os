import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "../api/client";
import type { CursorPage, EvaluationCase } from "../api/types";
import { Badge, Button, Card, ErrorState, Loading } from "../components/ui";

interface Evaluation { id: string; status: string; model: string; total_cases?: number; reviewed_cases?: number }

export function Evaluations() {
  const client = useQueryClient();
  const runs = useQuery({ queryKey: ["evaluations"], queryFn: () => api<CursorPage<Evaluation>>("/v1/evaluations") });
  const [selected, setSelected] = useState("");
  const evaluationId = selected || runs.data?.items[0]?.id || "";
  const cases = useQuery({ queryKey: ["evaluation-cases", evaluationId], enabled: Boolean(evaluationId), queryFn: () => api<CursorPage<EvaluationCase>>(`/v1/evaluations/${evaluationId}/cases`) });
  const review = useMutation({ mutationFn: ({ caseId, ranking, harmful, comparison }: { caseId: string; ranking: string[]; harmful: string[]; comparison: string }) => api(`/v1/evaluations/${evaluationId}/cases/${caseId}/review`, { method: "POST", body: JSON.stringify({ ranking, harmful, notes: "", current_vs_v7: comparison }) }), onSuccess: async () => { toast.success("Human review saved"); await client.invalidateQueries({ queryKey: ["evaluation-cases", evaluationId] }); }, onError: (error) => toast.error(error.message) });
  if (runs.isLoading) return <Loading />;
  if (runs.error || !runs.data) return <ErrorState error={runs.error} />;
  return <><div className="page-header"><div><span className="eyebrow">HUMAN-ONLY JUDGMENT</span><h1>Blinded evaluation</h1><p>Rank all four answers without seeing which memory arm produced them. Harmful answers must be marked explicitly.</p></div>{evaluationId ? <Button onClick={() => api(`/v1/evaluations/${evaluationId}/finalize`, { method: "POST" }).then(() => toast.success("Evaluation finalized")).catch((error: Error) => toast.error(error.message))}>Finalize 32 cases</Button> : null}</div>
    <Card style={{ marginBottom: 16 }}>{!runs.data.items.length ? <p className="quiet-empty">No evaluation has been prepared.</p> : runs.data.items.map((run) => <button className="list-row replay-batch-button" key={run.id} type="button" onClick={() => setSelected(run.id)}><span className="list-primary"><strong>{run.model}</strong><span>{run.id.slice(0, 8)}</span></span><Badge>{run.status}</Badge></button>)}</Card>
    {cases.isLoading ? <Loading /> : cases.data?.items.map((item) => <EvaluationRow key={item.id} item={item} save={(ranking, harmful, comparison) => review.mutate({ caseId: item.id, ranking, harmful, comparison })} />)}
  </>;
}

function EvaluationRow({ item, save }: { item: EvaluationCase; save: (ranking: string[], harmful: string[], comparison: string) => void }) {
  const [ranking, setRanking] = useState<string[]>(item.review?.ranking ?? []);
  const [harmful, setHarmful] = useState<string[]>(item.review?.harmful ?? []);
  const [comparison, setComparison] = useState(item.review?.current_vs_v7 ?? "tie");
  function rank(label: string) { setRanking((current) => current.includes(label) ? current.filter((value) => value !== label) : [...current, label]); }
  return <Card style={{ marginBottom: 16 }}><div className="card-header"><div><h2>{item.case_key}</h2><p>{item.prompt}</p></div>{item.review ? <Badge>reviewed</Badge> : null}</div><div className="evaluation-grid">{(["A", "B", "C", "D"] as const).map((label) => <article key={label} className="evaluation-arm"><strong>{label} {ranking.includes(label) ? `· rank ${ranking.indexOf(label) + 1}` : ""}</strong><p>{item.arms[label]}</p><span className="page-actions"><Button size="sm" variant="secondary" onClick={() => rank(label)}>Add to ranking</Button><Button size="sm" variant={harmful.includes(label) ? "destructive" : "secondary"} onClick={() => setHarmful((current) => current.includes(label) ? current.filter((value) => value !== label) : [...current, label])}>Harmful</Button></span></article>)}</div><div className="card-body"><p className="subtle">Compared directly: reviewed v7 versus current memory</p><span className="page-actions"><Button size="sm" variant={comparison === "v7_win" ? "default" : "secondary"} onClick={() => setComparison("v7_win")}>v7 wins</Button><Button size="sm" variant={comparison === "tie" ? "default" : "secondary"} onClick={() => setComparison("tie")}>Tie</Button><Button size="sm" variant={comparison === "current_win" ? "default" : "secondary"} onClick={() => setComparison("current_win")}>Current wins</Button><Button disabled={ranking.length !== 4} onClick={() => save(ranking, harmful, comparison)}>Save human ranking</Button></span></div></Card>;
}
