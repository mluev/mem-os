import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { ArrowLeft, Boxes, Plus, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "../api/client";
import type { Entities as EntityList, Users, EntityCreated, Entity, EntityKind, Me, MemorySummary, EntityProfile } from "../api/types";
import {
  Badge,
  Button,
  Card,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  EmptyState,
  ErrorState,
  Importance,
  Input,
  Loading,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  TypeBadge,
} from "../components/ui";
import { relativeTime } from "../lib/format";

const CREATABLE: EntityKind[] = ["project", "product", "company", "person", "custom"];

/**
 * The things memory can belong to or be about.
 *
 * A teammate appears here as well as a project: a fact about a person needs
 * somewhere to attach, and that somewhere is an entity like any other.
 */
export function Entities() {
  const list = useQuery({
    queryKey: ["entities"],
    queryFn: () => api<EntityList>("/v1/entities"),
  });
  const [creating, setCreating] = useState(false);
  const groups: Array<[string, EntityKind[]]> = [
    ["Shared spaces", ["team"]],
    ["Projects and products", ["project", "product", "company", "custom"]],
    ["People", ["user", "person"]],
  ];

  return (
    <>
      <div className="page-header">
        <div>
          <span className="eyebrow">SCOPES AND SUBJECTS</span>
          <h1>Entities</h1>
          <p>
            Each one holds its own memory, and can be the subject of a fact recorded
            elsewhere.
          </p>
        </div>
        <Button onClick={() => setCreating(true)}>
          <Plus size={15} /> New entity
        </Button>
      </div>

      {list.isLoading ? (
        <Loading />
      ) : list.error ? (
        <ErrorState error={list.error} retry={() => void list.refetch()} />
      ) : !list.data?.items.length ? (
        <EmptyState title="Nothing yet" body="Create a project to give it a memory of its own." />
      ) : (
        groups.map(([heading, kinds]) => {
          const items = list.data.items.filter((entity) => kinds.includes(entity.kind));
          if (!items.length) return null;
          return (
            <Card key={heading}>
              <span className="nav-label">{heading}</span>
              {items.map((entity) => (
                <Link
                  className="list-row"
                  key={entity.id}
                  to="/entities/$slug"
                  params={{ slug: entity.slug }}
                >
                  <span className="list-primary">
                    <strong>{entity.name}</strong>
                    <span>
                      {entity.aliases.length
                        ? `also ${entity.aliases.slice(0, 4).join(", ")}`
                        : entity.slug}
                    </span>
                  </span>
                  <TypeBadge type={entity.kind} />
                  {entity.writable ? null : <Badge>read-only</Badge>}
                </Link>
              ))}
            </Card>
          );
        })
      )}

      {creating ? <CreateDialog close={() => setCreating(false)} /> : null}
    </>
  );
}

function CreateDialog({ close }: { close: () => void }) {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<EntityKind>("project");
  const [aliases, setAliases] = useState("");
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      const created = await api<EntityCreated>("/v1/entities", {
        method: "POST",
        body: JSON.stringify({
          kind,
          name: name.trim(),
          aliases: aliases
            .split(",")
            .map((alias) => alias.trim())
            .filter(Boolean),
        }),
      });
      toast.success(`${name} created`, { description: `Scope ${created.slug}` });
      void client.invalidateQueries({ queryKey: ["entities"] });
      close();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create this entity");
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && close()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New entity</DialogTitle>
        </DialogHeader>
        <form className="stack" onSubmit={submit}>
          <label>
            Name
            <Input
              autoFocus
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Mem OS"
            />
          </label>
          <label>
            Kind
            <Select value={kind} onValueChange={(value) => setKind(value as EntityKind)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CREATABLE.map((option) => (
                  <SelectItem key={option} value={option}>
                    {option}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
          <label>
            Other names it goes by
            <Input
              value={aliases}
              onChange={(event) => setAliases(event.target.value)}
              placeholder="memkit, mem-os"
            />
            <small>
              Comma separated. These are how a name in conversation finds this entity, so
              include what people actually say.
            </small>
          </label>
          {error ? <p className="form-error">{error}</p> : null}
          <div className="row-actions">
            <Button type="submit" disabled={!name.trim()}>
              Create
            </Button>
            <Button type="button" variant="secondary" onClick={close}>
              Cancel
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function EntityDetail() {
  const { slug } = useParams({ strict: false }) as { slug: string };
  const search = useSearch({ strict: false }) as { tab?: string };
  const navigate = useNavigate();
  const profile = useQuery({
    queryKey: ["entity", slug],
    queryFn: () => api<EntityProfile>(`/v1/entities/${encodeURIComponent(slug)}/profile`),
  });

  if (profile.isLoading) return <Loading />;
  if (profile.error || !profile.data) return <ErrorState error={profile.error} />;
  const { entity, about, in_scope: inScope } = profile.data;

  return (
    <>
      <div className="page-header">
        <div>
          <Link to="/entities" className="eyebrow">
            <ArrowLeft size={11} /> ENTITIES
          </Link>
          <h1>{entity.name}</h1>
          <p>
            {entity.description || `${entity.kind} · ${entity.slug}`}
          </p>
        </div>
        <TypeBadge type={entity.kind} />
      </div>

      <Tabs
        value={search.tab ?? "memory"}
        onValueChange={(tab) => void navigate({ to: ".", search: (old) => ({ ...old, tab }) })}
      >
        <TabsList>
          <TabsTrigger value="memory">Memory</TabsTrigger>
          <TabsTrigger value="about">About it ({about.length})</TabsTrigger>
          <TabsTrigger value="names">Names</TabsTrigger>
          {entity.kind !== "user" ? <TabsTrigger value="members">Members</TabsTrigger> : null}
        </TabsList>

        <TabsContent value="memory">
          <Card>
            {!inScope.length ? (
              <EmptyState
                title="Nothing in this space yet"
                body={
                  entity.kind === "user"
                    ? "This person's private memory is not visible here."
                    : "Facts recorded while working in this scope will appear here."
                }
              />
            ) : (
              inScope.map((memory) => <MemoryLine key={memory.id} memory={memory} />)
            )}
          </Card>
        </TabsContent>

        <TabsContent value="about">
          <Card>
            <span className="nav-label">
              What the team has recorded about {entity.name}
            </span>
            {!about.length ? (
              <EmptyState title="Nothing recorded" body="No facts name this entity as their subject." />
            ) : (
              about.map((memory) => <MemoryLine key={memory.id} memory={memory} />)
            )}
          </Card>
        </TabsContent>

        <TabsContent value="names">
          <Aliases entity={entity} onChanged={() => void profile.refetch()} />
        </TabsContent>

        {entity.kind !== "user" ? (
          <TabsContent value="members">
            <Members entity={entity} onChanged={() => void profile.refetch()} />
          </TabsContent>
        ) : null}
      </Tabs>
    </>
  );
}

/** One fact, linking into the drawer by search param so any screen can open it. */
function MemoryLine({ memory }: { memory: MemorySummary }) {
  return (
    <Link className="list-row" to="." search={(old) => ({ ...old, memory: memory.id })}>
      <span className="list-primary">
        <strong>{memory.text}</strong>
        <span>
          {memory.kind}
          {memory.author ? ` · ${memory.author}` : ""} · {relativeTime(memory.updated_at)}
        </span>
      </span>
      {memory.review_status === "pending" ? <Badge>unconfirmed</Badge> : null}
      <Importance value={memory.importance} />
    </Link>
  );
}

function Aliases({ entity, onChanged }: { entity: Entity; onChanged: () => void }) {
  const [alias, setAlias] = useState("");
  const add = useMutation({
    mutationFn: (value: string) =>
      api(`/v1/entities/${encodeURIComponent(entity.slug)}/aliases`, {
        method: "POST",
        body: JSON.stringify({ alias: value }),
      }),
    onSuccess: () => {
      setAlias("");
      onChanged();
    },
    onError: (error: unknown) =>
      toast.error(error instanceof Error ? error.message : "Could not add that name"),
  });
  const remove = useMutation({
    mutationFn: (value: string) =>
      api(
        `/v1/entities/${encodeURIComponent(entity.slug)}/aliases/${encodeURIComponent(value)}`,
        { method: "DELETE" },
      ),
    onSuccess: onChanged,
  });

  return (
    <Card>
      <span className="nav-label">Names this entity answers to</span>
      <p>
        An alias is how a name spoken in conversation reaches this entity. It has to be
        unique across the whole team, because two entities answering to one name means a
        fact cannot be routed to either.
      </p>
      <div className="chip-row">
        {entity.aliases.map((value) => (
          <span className="chip" key={value}>
            {value}
            {entity.writable ? (
              <button
                type="button"
                aria-label={`Remove ${value}`}
                onClick={() => remove.mutate(value)}
              >
                <X size={12} />
              </button>
            ) : null}
          </span>
        ))}
        {!entity.aliases.length ? <span className="muted">none</span> : null}
      </div>
      {entity.writable ? (
        <form
          className="row-actions"
          onSubmit={(event) => {
            event.preventDefault();
            if (alias.trim()) add.mutate(alias.trim());
          }}
        >
          <Input
            value={alias}
            onChange={(event) => setAlias(event.target.value)}
            placeholder="Саша"
          />
          <Button type="submit" disabled={!alias.trim() || add.isPending}>
            Add name
          </Button>
        </form>
      ) : null}
    </Card>
  );
}

function Members({ entity, onChanged }: { entity: Entity; onChanged: () => void }) {
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/v1/auth/me") });
  const people = useQuery({
    queryKey: ["users"],
    queryFn: () => api<Users>("/v1/users"),
  });
  const [handle, setHandle] = useState("");
  const [role, setRole] = useState("member");
  const members = entity.members ?? [];
  const mine = members.find((member) => member.user_id === me.data?.id);
  const mayManage = mine?.role === "owner" || me.data?.role === "admin";

  const put = useMutation({
    mutationFn: ({ userId, memberRole }: { userId: string; memberRole: string }) =>
      api(`/v1/entities/${encodeURIComponent(entity.slug)}/members/${userId}`, {
        method: "PUT",
        body: JSON.stringify({ role: memberRole }),
      }),
    onSuccess: () => {
      setHandle("");
      onChanged();
    },
    onError: (error: unknown) =>
      toast.error(error instanceof Error ? error.message : "Could not change membership"),
  });
  const remove = useMutation({
    mutationFn: (userId: string) =>
      api(`/v1/entities/${encodeURIComponent(entity.slug)}/members/${userId}`, {
        method: "DELETE",
      }),
    onSuccess: onChanged,
  });

  const candidates = (people.data?.items ?? []).filter(
    (person) => !members.some((member) => member.user_id === person.id),
  );

  return (
    <Card>
      <span className="nav-label">Who can read and write this space</span>
      {!members.length ? (
        <EmptyState title="No members" body="Add someone to give them access." />
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Person</th>
              <th scope="col">Role</th>
              {mayManage ? <th scope="col" /> : null}
            </tr>
          </thead>
          <tbody>
            {members.map((member) => (
              <tr key={member.user_id}>
                <td>
                  <span className="list-primary">
                    <strong>{member.display_name}</strong>
                    <span>{member.handle}</span>
                  </span>
                </td>
                <td>
                  <Badge>{member.role}</Badge>
                  {member.role === "viewer" ? (
                    <small className="muted"> can read, cannot write</small>
                  ) : null}
                </td>
                {mayManage ? (
                  <td>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => remove.mutate(member.user_id)}
                    >
                      Remove
                    </Button>
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {mayManage && candidates.length ? (
        <form
          className="row-actions"
          onSubmit={(event) => {
            event.preventDefault();
            if (handle) put.mutate({ userId: handle, memberRole: role });
          }}
        >
          <Select value={handle} onValueChange={setHandle}>
            <SelectTrigger>
              <SelectValue placeholder="Add someone" />
            </SelectTrigger>
            <SelectContent>
              {candidates.map((person) => (
                <SelectItem key={person.id} value={person.id}>
                  {person.display_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={role} onValueChange={setRole}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="member">Member</SelectItem>
              <SelectItem value="viewer">Viewer</SelectItem>
              <SelectItem value="owner">Owner</SelectItem>
            </SelectContent>
          </Select>
          <Button type="submit" disabled={!handle || put.isPending}>
            <Boxes size={15} /> Add
          </Button>
        </form>
      ) : null}
    </Card>
  );
}
