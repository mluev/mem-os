import { useEffect, useMemo, useState } from "react";
import { DragDropProvider, DragOverlay, useDroppable, type DragEndEvent } from "@dnd-kit/react";
import { useSortable } from "@dnd-kit/react/sortable";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import {
  Archive,
  CalendarClock,
  CheckCircle2,
  Circle,
  CircleDashed,
  Copy,
  MoreHorizontal,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { api, ApiError, queryString } from "../api/client";
import type {
  JudgeOp,
  Memory,
  Message,
  TaskBoard,
  TaskBoardItem,
  TaskWorkflowStatus,
} from "../api/types";
import { guessLang, relativeTime, shortId } from "../lib/format";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Badge,
  Button,
  DatePicker,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  EmptyState,
  ErrorState,
  Importance,
  Input,
  Label,
  Loading,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Sheet,
  SheetContent,
  Slider,
  Switch,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
} from "../components/ui";

const PROJECT_UNKNOWN = "__unknown__";

const STATUS_META: Array<{
  id: TaskWorkflowStatus;
  label: string;
  description: string;
  icon: typeof Circle;
}> = [
  { id: "unknown", label: "Unknown", description: "Needs triage", icon: CircleDashed },
  { id: "todo", label: "To do", description: "Ready to start", icon: Circle },
  { id: "doing", label: "Doing", description: "In progress", icon: CalendarClock },
  { id: "done", label: "Done", description: "Completed work", icon: CheckCircle2 },
];

type TaskSearch = {
  project?: string;
  archived?: boolean;
  sel?: string;
};

type DialogState =
  | { mode: "create"; status: TaskWorkflowStatus; seed?: TaskBoardItem }
  | { mode: "edit"; task: TaskBoardItem }
  | null;

interface Provenance {
  memory: Memory;
  task_board: {
    workflow_status: TaskWorkflowStatus;
    project_key: string | null;
    version: number;
    updated_at: string;
  } | null;
  messages: Message[];
  judge_run: { id: number; model: string; created_at: string } | null;
  judge_ops: JudgeOp[];
}

export function matchesProject(task: TaskBoardItem, project?: string): boolean {
  if (!project) return true;
  if (project === PROJECT_UNKNOWN) return task.project_key === null;
  return task.project_key === project;
}

export function placeTask(
  items: TaskBoardItem[],
  task: TaskBoardItem,
  status: TaskWorkflowStatus,
  targetId: string | null,
): TaskBoardItem[] {
  const moved = { ...task, workflow_status: status };
  const next = items.filter((item) => item.id !== task.id);
  if (targetId) {
    const targetIndex = next.findIndex((item) => item.id === targetId);
    if (targetIndex >= 0) {
      next.splice(targetIndex, 0, moved);
      return next;
    }
  }
  const firstInColumn = next.findIndex((item) => item.workflow_status === status);
  next.splice(firstInColumn >= 0 ? firstInColumn : next.length, 0, moved);
  return next;
}

export function neighbors(
  items: TaskBoardItem[],
  taskId: string,
  status: TaskWorkflowStatus,
  project?: string,
): { before_id: string | null; after_id: string | null } {
  const column = items.filter(
    (item) => item.workflow_status === status && matchesProject(item, project),
  );
  const index = column.findIndex((item) => item.id === taskId);
  return {
    before_id: index > 0 ? column[index - 1]?.id ?? null : null,
    after_id: index >= 0 && index < column.length - 1 ? column[index + 1]?.id ?? null : null,
  };
}

export function Tasks() {
  const search = useSearch({ strict: false }) as TaskSearch;
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [items, setItems] = useState<TaskBoardItem[]>([]);
  const [dialog, setDialog] = useState<DialogState>(null);
  const [deleteTask, setDeleteTask] = useState<TaskBoardItem | null>(null);

  const board = useQuery({
    queryKey: ["task-board", Boolean(search.archived)],
    queryFn: () =>
      api<TaskBoard>(
        `/v1/admin/tasks/board${queryString({ include_archived: search.archived })}`,
      ),
  });
  useEffect(() => {
    if (board.data) setItems(board.data.items);
  }, [board.data]);

  const filtered = useMemo(
    () => items.filter((task) => matchesProject(task, search.project)),
    [items, search.project],
  );
  const grouped = useMemo(() => {
    const result = new Map<TaskWorkflowStatus, TaskBoardItem[]>(
      STATUS_META.map((status) => [status.id, []]),
    );
    for (const item of filtered) result.get(item.workflow_status)?.push(item);
    return result;
  }, [filtered]);
  const taskById = useMemo(
    () => new Map(items.map((task) => [task.id, task])),
    [items],
  );
  const selectedTask = search.sel ? taskById.get(search.sel) : undefined;

  const updateSearch = (patch: Partial<TaskSearch>) =>
    navigate({
      to: "/tasks",
      search: (old: TaskSearch) => ({ ...old, ...patch }),
    });

  async function saveMove(
    task: TaskBoardItem,
    status: TaskWorkflowStatus,
    targetId: string | null,
    withUndo = true,
  ) {
    if (task.status !== "active") return;
    const snapshot = items;
    const previousStatus = task.workflow_status;
    const previousNeighbors = neighbors(snapshot, task.id, previousStatus, search.project);
    const optimistic = placeTask(snapshot, task, status, targetId);
    const nextNeighbors = neighbors(optimistic, task.id, status, search.project);
    setItems(optimistic);
    try {
      const response = await api<{ task: TaskBoardItem }>(
        `/v1/admin/tasks/${task.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            workflow_status: status,
            ...nextNeighbors,
            expected_board_version: task.board_version,
          }),
        },
      );
      setItems((current) =>
        current.map((item) => (item.id === task.id ? response.task : item)),
      );
      void queryClient.invalidateQueries({ queryKey: ["task-board"] });
      toast.success(`Moved to ${STATUS_META.find((item) => item.id === status)?.label}`, {
        action: withUndo
          ? {
              label: "Undo",
              onClick: () => {
                const current = taskById.get(task.id);
                const version = response.task.board_version;
                if (!current) return;
                setItems((value) =>
                  placeTask(value, response.task, previousStatus, previousNeighbors.after_id),
                );
                void api(`/v1/admin/tasks/${task.id}`, {
                  method: "PATCH",
                  body: JSON.stringify({
                    workflow_status: previousStatus,
                    ...previousNeighbors,
                    expected_board_version: version,
                  }),
                })
                  .then(() => queryClient.invalidateQueries({ queryKey: ["task-board"] }))
                  .catch(() => {
                    toast.error("Undo failed; the board has changed");
                    void board.refetch();
                  });
              },
            }
          : undefined,
      });
    } catch (error) {
      setItems(snapshot);
      if (error instanceof ApiError && error.status === 409) {
        toast.error("This task changed elsewhere. The board was refreshed.");
        await board.refetch();
      } else {
        toast.error(error instanceof Error ? error.message : "Could not move task");
      }
    }
  }

  function handleDragEnd(event: DragEndEvent) {
    if (event.canceled) return;
    const source = event.operation.source;
    const target = event.operation.target;
    if (!source || !target) return;
    const task = taskById.get(String(source.id));
    const status = target.data.workflowStatus as TaskWorkflowStatus | undefined;
    if (!task || !status) return;
    const targetId = target.data.kind === "task" ? String(target.id) : null;
    if (task.workflow_status === status && targetId === task.id) return;
    void saveMove(task, status, targetId);
  }

  async function archive(task: TaskBoardItem) {
    try {
      await api(`/v1/memories/${task.id}`, { method: "DELETE" });
      await queryClient.invalidateQueries({ queryKey: ["task-board"] });
      toast.success("Task archived", {
        action: {
          label: "Undo",
          onClick: () => {
            void api(`/v1/memories/${task.id}`, {
              method: "PATCH",
              body: JSON.stringify({ status: "active" }),
            }).then(() => queryClient.invalidateQueries({ queryKey: ["task-board"] }));
          },
        },
      });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not archive task");
    }
  }

  async function restore(task: TaskBoardItem) {
    try {
      await api(`/v1/memories/${task.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "active" }),
      });
      toast.success("Task restored");
      await queryClient.invalidateQueries({ queryKey: ["task-board"] });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not restore task");
    }
  }

  async function hardDelete(task: TaskBoardItem) {
    try {
      await api(`/v1/memories/${task.id}?hard=true`, { method: "DELETE" });
      toast.success("Task permanently deleted");
      setDeleteTask(null);
      void updateSearch({ sel: search.sel === task.id ? undefined : search.sel });
      await queryClient.invalidateQueries({ queryKey: ["task-board"] });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not delete task");
    }
  }

  return (
    <>
      <div className="page-header task-page-header">
        <div>
          <span className="eyebrow">TASK MEMORY</span>
          <h1>Project task board</h1>
          <p>Organize extracted and manual tasks without changing their memory freshness.</p>
        </div>
        <div className="page-actions">
          <Button variant="secondary" onClick={() => void board.refetch()}>
            <RefreshCw size={14} /> Refresh
          </Button>
          <Button onClick={() => setDialog({ mode: "create", status: "todo" })}>
            <Plus size={14} /> Add task
          </Button>
        </div>
      </div>

      <div className="task-toolbar">
        <label className="task-project-filter">
          <Search size={14} />
          <Select
            value={search.project ?? "all"}
            onValueChange={(value) =>
              void updateSearch({ project: value === "all" ? undefined : value })
            }
          >
            <SelectTrigger aria-label="Filter tasks by project">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All projects</SelectItem>
              {(board.data?.projects ?? []).map((project) => (
                <SelectItem key={project.key ?? PROJECT_UNKNOWN} value={project.key ?? PROJECT_UNKNOWN}>
                  {project.label} · {project.count}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        <Label className="task-archive-toggle">
          <Switch
            checked={Boolean(search.archived)}
            onCheckedChange={(checked) => void updateSearch({ archived: checked || undefined })}
          />
          Include archived
        </Label>
        <span className="task-total mono">
          {filtered.length.toLocaleString()} {filtered.length === 1 ? "task" : "tasks"}
        </span>
      </div>

      {board.isLoading ? (
        <Loading label="Loading task board…" />
      ) : board.error ? (
        <ErrorState error={board.error} retry={() => void board.refetch()} />
      ) : (
        <DragDropProvider onDragEnd={handleDragEnd}>
          <div className="kanban-board" aria-label="Task Kanban board">
            {STATUS_META.map((status) => (
              <TaskColumn
                key={status.id}
                status={status}
                tasks={grouped.get(status.id) ?? []}
                onAdd={() => setDialog({ mode: "create", status: status.id })}
                onOpen={(task) => void updateSearch({ sel: task.id })}
                onEdit={(task) => setDialog({ mode: "edit", task })}
                onDuplicate={(task) => setDialog({ mode: "create", status: task.workflow_status, seed: task })}
                onMove={(task, next) => void saveMove(task, next, null)}
                onProject={(project) =>
                  void updateSearch({ project: project ?? PROJECT_UNKNOWN })
                }
                onArchive={(task) => void archive(task)}
                onRestore={(task) => void restore(task)}
                onDelete={setDeleteTask}
              />
            ))}
          </div>
          <DragOverlay className="task-drag-overlay" dropAnimation={{ duration: 160, easing: "cubic-bezier(.2,.8,.2,1)" }}>
            {(source) => {
              const task = taskById.get(String(source.id));
              return task ? <TaskCardPreview task={task} /> : null;
            }}
          </DragOverlay>
        </DragDropProvider>
      )}

      {dialog ? (
        <TaskDialog
          state={dialog}
          projects={(board.data?.projects ?? []).map((project) => project.key).filter((key): key is string => Boolean(key))}
          selectedProject={
            search.project && search.project !== PROJECT_UNKNOWN ? search.project : null
          }
          close={() => setDialog(null)}
          saved={async () => {
            setDialog(null);
            await queryClient.invalidateQueries({ queryKey: ["task-board"] });
          }}
        />
      ) : null}
      {selectedTask ? (
        <TaskSheet
          task={selectedTask}
          close={() => void updateSearch({ sel: undefined })}
          edit={() => setDialog({ mode: "edit", task: selectedTask })}
          archive={() => void archive(selectedTask)}
          restore={() => void restore(selectedTask)}
          remove={() => setDeleteTask(selectedTask)}
        />
      ) : null}
      {deleteTask ? (
        <DeleteTaskDialog
          task={deleteTask}
          close={() => setDeleteTask(null)}
          confirm={() => void hardDelete(deleteTask)}
        />
      ) : null}
    </>
  );
}

function TaskColumn({
  status,
  tasks,
  onAdd,
  onOpen,
  onEdit,
  onDuplicate,
  onMove,
  onProject,
  onArchive,
  onRestore,
  onDelete,
}: {
  status: (typeof STATUS_META)[number];
  tasks: TaskBoardItem[];
  onAdd: () => void;
  onOpen: (task: TaskBoardItem) => void;
  onEdit: (task: TaskBoardItem) => void;
  onDuplicate: (task: TaskBoardItem) => void;
  onMove: (task: TaskBoardItem, status: TaskWorkflowStatus) => void;
  onProject: (project: string | null) => void;
  onArchive: (task: TaskBoardItem) => void;
  onRestore: (task: TaskBoardItem) => void;
  onDelete: (task: TaskBoardItem) => void;
}) {
  const { ref, isDropTarget } = useDroppable({
    id: `column-${status.id}`,
    type: "task-column",
    accept: ["task", "task-column"],
    data: { kind: "column", workflowStatus: status.id },
  });
  const Icon = status.icon;
  return (
    <section
      ref={ref}
      className={`kanban-column status-${status.id}${isDropTarget ? " is-drop-target" : ""}`}
      aria-labelledby={`task-column-${status.id}`}
    >
      <header className="kanban-column-head">
        <span className="kanban-status-icon"><Icon size={15} /></span>
        <div>
          <h2 id={`task-column-${status.id}`}>{status.label}</h2>
          <p>{status.description}</p>
        </div>
        <span className="kanban-count">{tasks.length}</span>
        <Button variant="ghost" size="icon" onClick={onAdd} aria-label={`Add task to ${status.label}`}>
          <Plus size={15} />
        </Button>
      </header>
      <div className="kanban-list">
        {tasks.map((task, index) => (
          <TaskCard
            key={task.id}
            task={task}
            index={index}
            onOpen={() => onOpen(task)}
            onEdit={() => onEdit(task)}
            onDuplicate={() => onDuplicate(task)}
            onMove={(next) => onMove(task, next)}
            onProject={() => onProject(task.project_key)}
            onArchive={() => onArchive(task)}
            onRestore={() => onRestore(task)}
            onDelete={() => onDelete(task)}
          />
        ))}
        {!tasks.length ? (
          <button type="button" className="kanban-empty-drop" onClick={onAdd}>
            <Plus size={14} />
            Drop here or add a task
          </button>
        ) : null}
      </div>
    </section>
  );
}

function TaskCard({
  task,
  index,
  onOpen,
  onEdit,
  onDuplicate,
  onMove,
  onProject,
  onArchive,
  onRestore,
  onDelete,
}: {
  task: TaskBoardItem;
  index: number;
  onOpen: () => void;
  onEdit: () => void;
  onDuplicate: () => void;
  onMove: (status: TaskWorkflowStatus) => void;
  onProject: () => void;
  onArchive: () => void;
  onRestore: () => void;
  onDelete: () => void;
}) {
  const archived = task.status !== "active";
  const { ref, isDragging, isDropTarget } = useSortable({
    id: task.id,
    index,
    group: task.workflow_status,
    type: "task",
    accept: ["task"],
    disabled: archived,
    data: { kind: "task", workflowStatus: task.workflow_status },
    transition: { duration: 160, easing: "cubic-bezier(.2,.8,.2,1)", idle: true },
  });
  const due = task.valid_until ? new Date(task.valid_until) : null;
  const overdue = due && due.getTime() < Date.now() && task.workflow_status !== "done";
  return (
    <article
      ref={ref}
      className={`task-card${archived ? " is-archived" : ""}${isDragging ? " is-dragging" : ""}${isDropTarget ? " is-drop-target" : ""}`}
      onClick={onOpen}
      aria-label={`${task.text}. Drag to move, or press Enter or Space and use arrow keys.`}
    >
      <div className="task-card-top">
        <p lang={guessLang(task.text)}>{task.text}</p>
      </div>
      <div className="task-card-meta">
        <button
          type="button"
          className="task-project-chip"
          onPointerDown={(event) => event.stopPropagation()}
          onClick={(event) => { event.stopPropagation(); onProject(); }}
        >
          {task.project_key ?? "Unknown project"}
        </button>
        {due ? (
          <span className={overdue ? "task-due is-overdue" : "task-due"}>
            <CalendarClock size={12} />
            {due.toLocaleDateString(undefined, { month: "short", day: "numeric" })}
          </span>
        ) : null}
        {archived ? <Badge>{task.status}</Badge> : null}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="task-card-menu"
              aria-label={`Actions for ${task.text}`}
              onPointerDown={(event) => event.stopPropagation()}
              onClick={(event) => event.stopPropagation()}
            >
              <MoreHorizontal size={14} />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" onClick={(event) => event.stopPropagation()}>
            <DropdownMenuLabel>Task actions</DropdownMenuLabel>
            {!archived ? (
              <>
                <DropdownMenuItem onSelect={onEdit}><Pencil size={14} /> Edit</DropdownMenuItem>
                <DropdownMenuItem onSelect={onDuplicate}><Copy size={14} /> Duplicate</DropdownMenuItem>
                <DropdownMenuSeparator />
                {STATUS_META.filter((status) => status.id !== task.workflow_status).map((status) => (
                  <DropdownMenuItem key={status.id} onSelect={() => onMove(status.id)}>
                    Move to {status.label}
                  </DropdownMenuItem>
                ))}
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={onArchive}><Archive size={14} /> Archive</DropdownMenuItem>
              </>
            ) : (
              <DropdownMenuItem onSelect={onRestore}><RotateCcw size={14} /> Restore</DropdownMenuItem>
            )}
            <DropdownMenuItem className="low-confidence" onSelect={onDelete}>
              <Trash2 size={14} /> Delete permanently
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </article>
  );
}

function TaskCardPreview({ task }: { task: TaskBoardItem }) {
  return (
    <div className="task-card task-card-preview">
      <div className="task-card-top">
        <p>{task.text}</p>
      </div>
      <div className="task-card-meta">
        <span className="task-project-chip">{task.project_key ?? "Unknown project"}</span>
      </div>
    </div>
  );
}

function TaskDialog({
  state,
  projects,
  selectedProject,
  close,
  saved,
}: {
  state: Exclude<DialogState, null>;
  projects: string[];
  selectedProject: string | null;
  close: () => void;
  saved: () => Promise<void>;
}) {
  const editing = state.mode === "edit" ? state.task : null;
  const seed = state.mode === "create" ? state.seed : undefined;
  const [text, setText] = useState(editing?.text ?? seed?.text ?? "");
  const [status, setStatus] = useState<TaskWorkflowStatus>(
    editing?.workflow_status ?? (state.mode === "create" ? state.status : "unknown"),
  );
  const [project, setProject] = useState(
    editing?.project_key ?? seed?.project_key ?? selectedProject ?? "",
  );
  const [importance, setImportance] = useState(editing?.importance ?? seed?.importance ?? 0.6);
  const [validUntil, setValidUntil] = useState(editing?.valid_until ?? seed?.valid_until ?? "");
  const [pending, setPending] = useState(false);

  async function submit() {
    setPending(true);
    try {
      if (editing) {
        const body: Record<string, unknown> = {
          expected_board_version: editing.board_version,
        };
        let changesMemory = false;
        if (text.trim() !== editing.text) { body.text = text.trim(); changesMemory = true; }
        if ((project.trim() || null) !== editing.project_key) {
          body.project_key = project.trim() || null;
          changesMemory = true;
        }
        if (importance !== editing.importance) { body.importance = importance; changesMemory = true; }
        if ((validUntil || null) !== editing.valid_until) { body.valid_until = validUntil || null; changesMemory = true; }
        if (status !== editing.workflow_status) body.workflow_status = status;
        if (changesMemory) body.expected_memory_updated_at = editing.updated_at;
        if (Object.keys(body).length > 1) {
          await api(`/v1/admin/tasks/${editing.id}`, {
            method: "PATCH",
            body: JSON.stringify(body),
          });
        }
        toast.success("Task saved");
      } else {
        await api("/v1/admin/tasks", {
          method: "POST",
          body: JSON.stringify({
            text: text.trim(),
            workflow_status: status,
            project_key: project.trim() || null,
            importance,
            valid_until: validUntil || null,
          }),
        });
        toast.success(seed ? "Task duplicated" : "Task created");
      }
      await saved();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not save task");
    } finally {
      setPending(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open) close(); }}>
      <DialogContent className="task-dialog">
        <DialogHeader>
          <DialogTitle>{editing ? "Edit task" : seed ? "Duplicate task" : "Add task"}</DialogTitle>
          <DialogDescription>
            Task content remains a memory; workflow and ordering stay on the board.
          </DialogDescription>
        </DialogHeader>
        <div className="form-grid">
          <Label className="field field-full">
            <span>Task</span>
            <Textarea autoFocus maxLength={200} value={text} onChange={(event) => setText(event.target.value)} />
            <small className="task-character-count mono">{text.length}/200</small>
          </Label>
          <div className="field">
            <Label>Status</Label>
            <Select value={status} onValueChange={(value) => setStatus(value as TaskWorkflowStatus)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {STATUS_META.map((item) => <SelectItem key={item.id} value={item.id}>{item.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <Label className="field">
            <span>Project</span>
            <Input list="task-project-options" value={project} onChange={(event) => setProject(event.target.value)} placeholder="Unknown project" />
            <datalist id="task-project-options">
              {projects.map((item) => <option key={item} value={item} />)}
            </datalist>
          </Label>
          <div className="field">
            <span className="field-inline-value"><Label>Importance</Label><b className="mono">{importance.toFixed(2)}</b></span>
            <Slider min={0} max={1} step={0.05} value={[importance]} onValueChange={([value]) => setImportance(value ?? importance)} />
          </div>
          <div className="field">
            <Label>Valid until</Label>
            <DatePicker value={validUntil} onChange={setValidUntil} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="secondary" onClick={close}>Cancel</Button>
          <Button disabled={!text.trim() || pending} onClick={() => void submit()}>
            {pending ? "Saving…" : editing ? "Save changes" : seed ? "Duplicate task" : "Add task"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function TaskSheet({
  task,
  close,
  edit,
  archive,
  restore,
  remove,
}: {
  task: TaskBoardItem;
  close: () => void;
  edit: () => void;
  archive: () => void;
  restore: () => void;
  remove: () => void;
}) {
  const data = useQuery({
    queryKey: ["task-provenance", task.id],
    queryFn: () => api<Provenance>(`/v1/memories/${task.id}/sources`),
  });
  const matching = data.data?.judge_ops.find((operation) => operation.matches_this_memory);
  return (
    <Sheet open onOpenChange={(open) => { if (!open) close(); }}>
      <SheetContent className="sheet">
        <div className="sheet-head task-sheet-head">
          <div className="sheet-head-row">
            <div>
              <span className="eyebrow">TASK {shortId(task.id)}</span>
              <h2>{task.text}</h2>
            </div>
            {task.status === "active" ? <Button variant="secondary" size="sm" onClick={edit}><Pencil size={13} /> Edit</Button> : null}
          </div>
        </div>
        <div className="sheet-body">
          <Tabs defaultValue="details">
            <TabsList>
              <TabsTrigger value="details">Details</TabsTrigger>
              <TabsTrigger value="provenance">Provenance</TabsTrigger>
              <TabsTrigger value="danger">Actions</TabsTrigger>
            </TabsList>
            <TabsContent value="details" className="task-sheet-panel">
              <dl className="metadata-grid task-metadata-grid">
                <div><dt>Workflow</dt><dd><Badge>{STATUS_META.find((item) => item.id === task.workflow_status)?.label}</Badge></dd></div>
                <div><dt>Project</dt><dd>{task.project_key ?? "Unknown project"}</dd></div>
                <div><dt>Lifecycle</dt><dd><Badge>{task.status}</Badge></dd></div>
                <div><dt>Importance</dt><dd><Importance value={task.importance} /></dd></div>
                <div><dt>Created</dt><dd>{new Date(task.created_at).toLocaleString()}</dd></div>
                <div><dt>Board updated</dt><dd>{relativeTime(task.board_updated_at)}</dd></div>
                <div><dt>Valid until</dt><dd>{task.valid_until ? new Date(task.valid_until).toLocaleString() : "No expiry"}</dd></div>
                <div><dt>Memory ID</dt><dd className="mono">{task.id}</dd></div>
              </dl>
            </TabsContent>
            <TabsContent value="provenance" className="task-sheet-panel">
              {data.isLoading ? <Loading /> : data.error ? <ErrorState error={data.error} retry={() => void data.refetch()} /> : task.extraction_version === "manual" ? (
                <EmptyState title="Added by hand" body="This task has no judge run or source conversation." />
              ) : (
                <>
                  <div className="provenance-reason">
                    <strong>WHY THE JUDGE STORED THIS</strong>
                    <p>{matching?.reason || "No reason was recorded."}</p>
                  </div>
                  <div className="message-list">
                    {(data.data?.messages ?? []).map((message) => (
                      <a key={message.id} className="message" href={`/ui/sessions/${message.session_id}?highlight=${message.id}`}>
                        <span className="message-role">{message.role}<br />#{message.id}</span>
                        <span className="message-content">{message.content}</span>
                      </a>
                    ))}
                  </div>
                </>
              )}
            </TabsContent>
            <TabsContent value="danger" className="task-sheet-panel">
              <div className="danger-zone">
                <h3>{task.status === "active" ? "Archive or delete task" : "Restore or delete task"}</h3>
                <p>Archive is reversible. Permanent deletion keeps source messages and judge audit records.</p>
                <div className="page-actions">
                  {task.status === "active" ? (
                    <Button variant="secondary" onClick={archive}><Archive size={13} /> Archive</Button>
                  ) : (
                    <Button variant="secondary" onClick={restore}><RotateCcw size={13} /> Restore</Button>
                  )}
                  <Button variant="destructive" onClick={remove}><Trash2 size={13} /> Delete permanently</Button>
                </div>
              </div>
            </TabsContent>
          </Tabs>
        </div>
      </SheetContent>
    </Sheet>
  );
}

function DeleteTaskDialog({
  task,
  close,
  confirm,
}: {
  task: TaskBoardItem;
  close: () => void;
  confirm: () => void;
}) {
  return (
    <AlertDialog open onOpenChange={(open) => { if (!open) close(); }}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete this task permanently?</AlertDialogTitle>
          <AlertDialogDescription>“{task.text}” cannot be recovered after deletion.</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction asChild><Button variant="destructive" onClick={confirm}>Delete permanently</Button></AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
