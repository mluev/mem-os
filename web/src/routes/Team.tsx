import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, KeyRound, ShieldCheck, UserPlus } from "lucide-react";
import { toast } from "sonner";
import { api } from "../api/client";
import type { ApiKey, Me, User } from "../api/types";
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
  Card,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  EmptyState,
  ErrorState,
  Input,
  Loading,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui";
import { relativeTime } from "../lib/format";

/**
 * People and credentials.
 *
 * A person signs in with a password; their agents use API keys. The two are
 * separate on purpose — a key can be revoked without locking anyone out of the
 * dashboard, and a stolen key never yields a password.
 */
export function Team() {
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/v1/auth/me") });
  const people = useQuery({
    queryKey: ["users"],
    queryFn: () => api<{ items: User[] }>("/v1/users"),
  });
  const [inviting, setInviting] = useState(false);
  const isAdmin = me.data?.role === "admin";

  return (
    <>
      <div className="page-header">
        <div>
          <span className="eyebrow">THE TEAM</span>
          <h1>People and keys</h1>
          <p>
            Everyone has their own memory. The team scope holds what you all share.
          </p>
        </div>
        {isAdmin ? (
          <Button onClick={() => setInviting(true)}>
            <UserPlus size={15} /> Add teammate
          </Button>
        ) : null}
      </div>

      <Card>
        {people.isLoading ? (
          <Loading />
        ) : people.error ? (
          <ErrorState error={people.error} retry={() => void people.refetch()} />
        ) : !people.data?.items.length ? (
          <EmptyState title="No one yet" body="Add the first teammate to get started." />
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Person</th>
                <th scope="col">Role</th>
                <th scope="col">Agent key last used</th>
                <th scope="col">Status</th>
                {isAdmin ? <th scope="col">Change</th> : null}
              </tr>
            </thead>
            <tbody>
              {people.data.items.map((person) => (
                <PersonRow
                  key={person.id}
                  person={person}
                  isAdmin={isAdmin}
                  isSelf={person.id === me.data?.id}
                />
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <MyKeys />

      {inviting ? <InviteDialog close={() => setInviting(false)} /> : null}
    </>
  );
}

function PersonRow({
  person,
  isAdmin,
  isSelf,
}: {
  person: User;
  isAdmin: boolean;
  isSelf: boolean;
}) {
  const client = useQueryClient();
  const patch = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api(`/v1/users/${person.id}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: () => {
      toast.success(`Updated ${person.handle}`);
      void client.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (error: unknown) =>
      toast.error(error instanceof Error ? error.message : "Could not update"),
  });
  return (
    <tr>
      <td>
        <span className="list-primary">
          <strong>
            {person.display_name}
            {isSelf ? <Badge className="ml">you</Badge> : null}
          </strong>
          <span>{person.handle}</span>
        </span>
      </td>
      <td>
        {person.role === "admin" ? (
          <Badge>
            <ShieldCheck size={12} /> admin
          </Badge>
        ) : (
          <Badge>member</Badge>
        )}
      </td>
      <td className="numeric">
        {person.key_last_used_at ? relativeTime(person.key_last_used_at) : "never"}
      </td>
      <td>{person.disabled_at ? <Badge>disabled</Badge> : <Badge>active</Badge>}</td>
      {isAdmin ? (
        <td>
          <div className="row-actions">
            <Button
              variant="secondary"
              size="sm"
              disabled={patch.isPending}
              onClick={() => patch.mutate({ role: person.role === "admin" ? "member" : "admin" })}
            >
              Make {person.role === "admin" ? "member" : "admin"}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={patch.isPending}
              onClick={() => patch.mutate({ disabled: !person.disabled_at })}
            >
              {person.disabled_at ? "Re-enable" : "Disable"}
            </Button>
          </div>
        </td>
      ) : null}
    </tr>
  );
}

function InviteDialog({ close }: { close: () => void }) {
  const client = useQueryClient();
  const [handle, setHandle] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("member");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      await api("/v1/users", {
        method: "POST",
        body: JSON.stringify({
          handle: handle.trim(),
          display_name: name.trim() || handle.trim(),
          password,
          role,
        }),
      });
      toast.success(`${handle} can sign in now`, {
        description: "Ask them to change this password on first sign-in.",
      });
      void client.invalidateQueries({ queryKey: ["users"] });
      close();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not add this person");
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && close()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a teammate</DialogTitle>
        </DialogHeader>
        <form className="stack" onSubmit={submit}>
          <label>
            Handle
            <Input
              autoFocus
              value={handle}
              onChange={(event) => setHandle(event.target.value)}
              placeholder="alex"
            />
          </label>
          <label>
            Display name
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Alex Petrov"
            />
          </label>
          <label>
            Role
            <Select value={role} onValueChange={setRole}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="member">Member</SelectItem>
                <SelectItem value="admin">Administrator</SelectItem>
              </SelectContent>
            </Select>
          </label>
          <label>
            First password
            <Input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="at least 12 characters"
            />
          </label>
          {error ? <p className="form-error">{error}</p> : null}
          <div className="row-actions">
            <Button type="submit" disabled={!handle.trim() || password.length < 12}>
              Add
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

function MyKeys() {
  const client = useQueryClient();
  const keys = useQuery({
    queryKey: ["api-keys"],
    queryFn: () => api<{ items: ApiKey[] }>("/v1/api-keys"),
  });
  const [minted, setMinted] = useState<{ name: string; secret: string } | null>(null);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);

  const create = useMutation({
    mutationFn: (name: string) =>
      api<{ name: string; secret: string }>("/v1/api-keys", {
        method: "POST",
        body: JSON.stringify({ name }),
      }),
    onSuccess: (created) => {
      setMinted(created);
      void client.invalidateQueries({ queryKey: ["api-keys"] });
    },
    onError: (error: unknown) =>
      toast.error(error instanceof Error ? error.message : "Could not create a key"),
  });
  const revoke = useMutation({
    mutationFn: (id: string) => api(`/v1/api-keys/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Key revoked");
      void client.invalidateQueries({ queryKey: ["api-keys"] });
    },
  });

  const live = keys.data?.items.filter((key) => !key.revoked_at) ?? [];
  return (
    <>
      <div className="page-header">
        <div>
          <span className="eyebrow">YOUR AGENTS</span>
          <h2>API keys</h2>
          <p>
            One key per machine or agent. Revoking a key never signs you out of this
            dashboard.
          </p>
        </div>
        <Button
          variant="secondary"
          disabled={create.isPending}
          onClick={() => create.mutate(`key ${live.length + 1}`)}
        >
          <KeyRound size={15} /> New key
        </Button>
      </div>
      <Card>
        {keys.isLoading ? (
          <Loading />
        ) : keys.error ? (
          <ErrorState error={keys.error} />
        ) : !live.length ? (
          <EmptyState
            title="No keys yet"
            body="Create one, then run memkit login on the machine that needs it."
          />
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Prefix</th>
                <th scope="col">Created</th>
                <th scope="col">Last used</th>
                <th scope="col" />
              </tr>
            </thead>
            <tbody>
              {live.map((key) => (
                <tr key={key.id}>
                  <td>{key.name}</td>
                  <td className="mono">{key.key_prefix}</td>
                  <td className="numeric">{relativeTime(key.created_at)}</td>
                  <td className="numeric">
                    {key.last_used_at ? relativeTime(key.last_used_at) : "never"}
                  </td>
                  <td>
                    <Button variant="ghost" size="sm" onClick={() => setRevoking(key)}>
                      Revoke
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {minted ? (
        <Dialog open onOpenChange={(open) => !open && setMinted(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Copy this key now</DialogTitle>
            </DialogHeader>
            <p>
              This is the only time it is shown. Only a hash is stored, so it cannot be
              retrieved later.
            </p>
            <pre className="secret">{minted.secret}</pre>
            <div className="row-actions">
              <Button
                onClick={async () => {
                  await navigator.clipboard.writeText(minted.secret);
                  toast.success("Copied");
                }}
              >
                <Copy size={15} /> Copy
              </Button>
              <Button variant="secondary" onClick={() => setMinted(null)}>
                Done
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      ) : null}

      <AlertDialog open={Boolean(revoking)} onOpenChange={(open) => !open && setRevoking(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Revoke “{revoking?.name}”?</AlertDialogTitle>
            <AlertDialogDescription>
              Any agent using this key stops working immediately. Nothing it already
              stored is affected.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep it</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (revoking) revoke.mutate(revoking.id);
                setRevoking(null);
              }}
            >
              Revoke
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
