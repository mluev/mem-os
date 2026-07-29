import type { HTMLAttributes, ReactNode } from "react";
import { LoaderCircle } from "lucide-react";
import { cn } from "../../lib/utils";
import { Button } from "./button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "./tooltip";

export function Badge({ className, ...props }: HTMLAttributes<HTMLSpanElement>) { return <span className={cn("badge", className)} {...props} />; }
export function Card({ className, ...props }: HTMLAttributes<HTMLElement>) { return <section className={cn("card", className)} {...props} />; }
export function EmptyState({ title, body, action }: { title: string; body: string; action?: ReactNode }) { return <div className="empty-state"><div className="empty-mark" aria-hidden="true" /><h3>{title}</h3><p>{body}</p>{action}</div>; }
export function Loading({ label = "Loading" }: { label?: string }) { return <div className="loading"><LoaderCircle size={17} className="spin" /><span>{label}</span></div>; }
export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) { return <div className="error-state" role="alert"><strong>Couldn’t load this view</strong><span>{error instanceof Error ? error.message : "Unknown error"}</span>{retry ? <Button variant="secondary" size="sm" onClick={retry}>Retry</Button> : null}</div>; }
export function TypeBadge({ type }: { type: string }) { return <Badge className={`type-badge type-${type}`}><span className="badge-dot" />{type}</Badge>; }
export function Importance({ value }: { value: number }) { return <TooltipProvider delayDuration={250}><Tooltip><TooltipTrigger asChild><div className="importance"><span className="importance-track"><span style={{ width: `${Math.round(value * 100)}%` }} /></span><span>{value.toFixed(2)}</span></div></TooltipTrigger><TooltipContent>Importance {value.toFixed(2)}</TooltipContent></Tooltip></TooltipProvider>; }
