import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Check, CheckCheck, Clock, Copy, Plus, Send, Trash2, X } from "lucide-react";
import { api } from "@/lib/apiClient";
import { useAuthStore } from "@/lib/authStore";
import { cn } from "@/lib/utils";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { useToast } from "@/components/shared/Toast";
import { Button, Card, CardHeader, Empty, ErrorText, Field, InfoNote, PageHeader, Tabs, inputCls } from "@/features/crm/components/ui";
import { fmtDateTime } from "@/features/crm/format";

interface WaConfig {
  configured: boolean;
  enabled: boolean;
  phone_number_id: string;
  waba_id: string;
  graph_version: string;
  access_token_masked: string;
  app_secret_masked: string;
  app_secret_from_env: boolean;
  display_phone: string;
  verified_name: string;
  updated_at: string | null;
  webhook_url: string;
  verify_token: string;
  last_webhook_at: string | null;
  last_webhook_error: { at: string; reason: string } | null;
}

interface WebhookLogEntry { at: string; kind: "verify" | "update"; ok: boolean; status: number; summary: string; ip: string | null; test: boolean }

/** Webhook troubleshooting: refused calls, verify checks and test calls.
 * Normal delivery updates aren't listed — they show on each message. */
function WebhookActivity() {
  const canEdit = useCanEdit();
  const qc = useQueryClient();
  const log = useQuery({
    queryKey: ["whatsapp", "webhook-log"],
    queryFn: () => api.get<{ items: WebhookLogEntry[]; last_webhook_at: string | null }>("/whatsapp/webhook-log"),
  });
  const selftest = useMutation({
    mutationFn: () => api.post<{ ok: boolean; detail: string }>("/whatsapp/webhook-selftest"),
    onSettled: () => qc.invalidateQueries({ queryKey: ["whatsapp", "webhook-log"] }),
  });
  const items = log.data?.items || [];
  const last = log.data?.last_webhook_at;
  return (
    <Card>
      <CardHeader title="Webhook problems & tests"
        subtitle={last ? <>Last call from Meta: <span className="text-emerald-400">{fmtDateTime(last + "Z")} ✓</span> · delivery times show under Sent messages on the Test tab</> : "No call from Meta yet"}
        action={canEdit ? <Button size="sm" onClick={() => selftest.mutate()} loading={selftest.isPending}>Send a test call</Button> : undefined} />
      {selftest.data && (
        <div className={cn("mx-5 mt-3 rounded-xl px-3 py-2 text-xs", selftest.data.ok ? "bg-emerald-500/10 text-emerald-400" : "bg-rose-500/10 text-rose-400")}>
          {selftest.data.detail}{selftest.data.ok && !last ? " Your side works — if Meta's calls still don't arrive, check the subscription and the messages field in Meta." : ""}
        </div>
      )}
      <ErrorText error={selftest.error} />
      {!log.data ? <div className="p-5"><TableSkeleton /></div> : items.length === 0 ? (
        <Empty>No problems recorded. Press "Send a test call" any time to check the webhook.</Empty>
      ) : (
        <div className="divide-y divide-[var(--border-subtle)] mt-2">
          {items.map((e, i) => (
            <div key={i} className="px-5 py-2.5 flex flex-col sm:flex-row sm:items-start gap-1 sm:gap-3 text-xs">
              <span className="w-32 shrink-0 text-[var(--text-muted)] whitespace-nowrap">{fmtDateTime(e.at + "Z")}</span>
              <span className="w-28 shrink-0">
                <span className={cn("inline-block px-1.5 py-0.5 rounded font-semibold",
                  e.test ? "bg-[var(--bg-subtle)] text-[var(--text-secondary)]"
                    : e.ok ? "bg-emerald-500/10 text-emerald-400" : "bg-rose-500/10 text-rose-400")}>
                  {e.test ? "Test call" : e.kind === "verify" ? "Verify" : "From Meta"}
                </span>
              </span>
              <span className={cn("flex-1 min-w-0 break-words", e.ok ? "text-[var(--text-primary)]" : "text-rose-400")}>{e.summary}</span>
              {e.ip && <span className="shrink-0 font-mono text-[var(--text-muted)]">{e.ip}</span>}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

interface WebhookCheck { checked: boolean; subscribed?: boolean; apps?: string[]; reason?: string }

interface Contacts {
  ceo: { user_id: number; name: string; phone: string }[];
  ceo_extra: { name: string; phone: string }[];
  team_leaders: { user_id: number; name: string; phone: string }[];
  telecallers: { user_id: number; name: string; rows: { store_id: number | null; phone: string }[] }[];
  stores: { store_id: number; name: string; phone: string }[];
}

interface Template {
  key: string;
  name: string;
  label: string;
  recipient: string;
  trigger: string;
  params: { name: string; sample: string }[];
  body: string;
  buttons: { type: "quick_reply" | "url" | "flow"; text: string; url?: string; sample?: string; optional?: boolean }[];
  meta: { status: string; language: string; category: string; buttons?: { type: string; text: string; dynamic: boolean }[] }[];
}

interface WaMessage {
  id: number;
  wa_message_id: string | null;
  to: string;
  template: string;
  status: "accepted" | "sent" | "delivered" | "read" | "failed";
  error_code: string | null;
  error: string | null;
  created_at: string | null;
  sent_at: string | null;
  delivered_at: string | null;
  read_at: string | null;
  failed_at: string | null;
  sent_by: string | null;
}

const errMsg = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");

function useCanEdit() {
  return useAuthStore((s) => s.hasPermission("settings", "edit"));
}

function CopyField({ label, value }: { label: string; value: string }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setDone(true);
      setTimeout(() => setDone(false), 1500);
    } catch {
      // Clipboard can be blocked (no HTTPS); the value is selectable anyway.
    }
  };
  return (
    <div>
      <p className="text-[11px] font-medium text-[var(--text-secondary)] mb-1">{label}</p>
      <div className="flex gap-2">
        <code className="flex-1 min-w-0 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] px-3 py-2 text-xs text-[var(--text-primary)] break-all select-all">{value}</code>
        <Button size="sm" onClick={copy} title="Copy">{done ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}</Button>
      </div>
    </div>
  );
}

// ── Tab 1: setup ────────────────────────────────────────────────────

function SetupTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const canEdit = useCanEdit();
  const { data: cfg, isLoading } = useQuery({ queryKey: ["whatsapp", "config"], queryFn: () => api.get<WaConfig>("/whatsapp/config") });
  const [form, setForm] = useState({ access_token: "", phone_number_id: "", waba_id: "", app_secret: "" });
  useEffect(() => {
    if (cfg) setForm((f) => ({ ...f, phone_number_id: cfg.phone_number_id, waba_id: cfg.waba_id }));
  }, [cfg]);

  const save = useMutation({
    mutationFn: () => api.put<WaConfig>("/whatsapp/config", form),
    onSuccess: (data) => {
      qc.setQueryData(["whatsapp", "config"], data);
      qc.invalidateQueries({ queryKey: ["whatsapp", "templates"] });
      setForm((f) => ({ ...f, access_token: "", app_secret: "" }));
      toast.success(`Connected to ${data.verified_name || "WhatsApp"} ${data.display_phone}`);
    },
  });
  const rotate = useMutation({
    mutationFn: () => api.post<WaConfig>("/whatsapp/config/new-verify-token"),
    onSuccess: (data) => {
      qc.setQueryData(["whatsapp", "config"], data);
      toast.success("New verify token made. Paste it into Meta and verify again.");
    },
  });

  const check = useQuery({
    queryKey: ["whatsapp", "webhook-check"],
    queryFn: () => api.get<WebhookCheck>("/whatsapp/webhook-check"),
    enabled: !!cfg?.configured,
  });
  const subscribe = useMutation({
    mutationFn: () => api.post<WebhookCheck>("/whatsapp/webhook-subscribe"),
    onSuccess: (data) => {
      qc.setQueryData(["whatsapp", "webhook-check"], data);
      toast.success("Subscribed. Delivery updates will start coming in for new messages.");
    },
    onError: (e) => toast.error(errMsg(e)),
  });

  const toggle = useMutation({
    mutationFn: (enabled: boolean) => api.put<WaConfig>("/whatsapp/config/enabled", { enabled }),
    onSuccess: (data) => {
      qc.setQueryData(["whatsapp", "config"], data);
      toast.success(data.enabled ? "WhatsApp is on" : "WhatsApp is off — no messages will be sent");
    },
    onError: (e) => toast.error(errMsg(e)),
  });

  if (isLoading || !cfg) return <TableSkeleton />;
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex items-center gap-4 px-5 py-4">
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-[var(--text-primary)]">
              WhatsApp messages are{" "}
              <span className={cfg.enabled ? "text-emerald-400" : "text-rose-400"}>{cfg.enabled ? "ON" : "OFF"}</span>
            </p>
            <p className="text-xs text-[var(--text-muted)] mt-0.5">
              {!cfg.configured ? "Submit the WhatsApp details below to turn it on."
                : cfg.enabled ? "Messages can be sent. Turn off to stop every WhatsApp message at once."
                  : "Nothing is sent, not even test messages. Your details and numbers are kept."}
            </p>
          </div>
          <button type="button" role="switch" aria-checked={cfg.enabled} aria-label="WhatsApp messages on or off"
            disabled={!canEdit || !cfg.configured || toggle.isPending}
            onClick={() => toggle.mutate(!cfg.enabled)}
            className={cn("relative shrink-0 w-12 h-7 rounded-full transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed",
              cfg.enabled ? "bg-emerald-500" : "bg-[var(--border-strong)]")}>
            <span className={cn("absolute top-1 left-1 w-5 h-5 rounded-full shadow transition-transform", cfg.enabled && "translate-x-5")}
              style={{ backgroundColor: "#fff" }} />
          </button>
        </div>
      </Card>
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 items-start">
        <Card>
          <CardHeader title="WhatsApp Cloud API" subtitle="From developers.facebook.com → your app → WhatsApp → API Setup" />
          <div className="px-5 py-4 space-y-3">
            {cfg.configured && (
              <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-400">
                Connected: <b>{cfg.verified_name || "WhatsApp number"}</b> {cfg.display_phone}
                {cfg.updated_at && <span className="text-[var(--text-muted)]"> · saved {fmtDateTime(cfg.updated_at + "Z")}</span>}
              </div>
            )}
            <Field label="Access token" hint={cfg.access_token_masked ? `Saved (${cfg.access_token_masked}). Leave blank to keep it.` : "A permanent System User token is best; temporary tokens stop after 24 hours."}>
              <input type="password" autoComplete="off" className={inputCls} value={form.access_token} onChange={set("access_token")}
                placeholder={cfg.access_token_masked ? "••••••••  (unchanged)" : "EAAG…"} disabled={!canEdit} />
            </Field>
            <Field label="Phone number ID">
              <input className={inputCls} value={form.phone_number_id} onChange={set("phone_number_id")} placeholder="e.g. 106540352242922" disabled={!canEdit} />
            </Field>
            <Field label="WhatsApp Business Account ID (optional)" hint="Lets the Test tab show whether each template is approved.">
              <input className={inputCls} value={form.waba_id} onChange={set("waba_id")} placeholder="e.g. 102290129340398" disabled={!canEdit} />
            </Field>
            <Field label="App secret (for the webhook)"
              hint={cfg.app_secret_masked ? `Saved (${cfg.app_secret_masked}). Leave blank to keep it.`
                : cfg.app_secret_from_env ? "Not set here: the Meta app secret from the server's .env is used."
                  : "App settings → Basic → App secret. Meta signs every webhook call with it."}>
              <input type="password" autoComplete="off" className={inputCls} value={form.app_secret} onChange={set("app_secret")}
                placeholder={cfg.app_secret_masked ? "••••••••  (unchanged)" : ""} disabled={!canEdit} />
            </Field>
            <ErrorText error={save.error} />
            {canEdit && (
              <Button variant="primary" onClick={() => save.mutate()} loading={save.isPending}
                disabled={!form.phone_number_id.trim() || (!cfg.access_token_masked && !form.access_token.trim())}>
                {cfg.configured ? "Save and re-check" : "Submit"}
              </Button>
            )}
          </div>
        </Card>

        <Card>
          <CardHeader title="Webhook" subtitle="So the app knows when a message is sent, delivered, read or failed" />
          {!cfg.configured ? (
            <Empty>Submit the WhatsApp details first. The webhook link and verify token show here after that.</Empty>
          ) : (
            <div className="px-5 py-4 space-y-3">
              <CopyField label="Callback URL" value={cfg.webhook_url} />
              <CopyField label="Verify token" value={cfg.verify_token} />
              <ol className="list-decimal pl-5 space-y-1 text-xs text-[var(--text-secondary)]">
                <li>Meta app → WhatsApp → Configuration → Webhook → Edit.</li>
                <li>Paste the Callback URL and Verify token above, then Verify and save.</li>
                <li>Under Webhook fields, subscribe to <b>messages</b>.</li>
                <li>Make sure the check below says <b>Yes</b>, and the Meta app is <b>Live</b> (not in Development mode).</li>
              </ol>
              {/^https:\/\//.test(cfg.webhook_url) ? null : (
                <InfoNote>This link is not HTTPS, so Meta can't reach it. It works once the app runs on dash.breakprotection.com.</InfoNote>
              )}
              <div className="rounded-xl border border-[var(--border-subtle)] px-3 py-2.5 text-xs space-y-1">
                <p className="font-semibold text-[var(--text-primary)]">WhatsApp account subscribed to the app?</p>
                {!check.data ? <p className="text-[var(--text-muted)]">Checking…</p>
                  : !check.data.checked ? <p className="text-[var(--text-muted)]">{check.data.reason}</p>
                    : check.data.subscribed ? (
                      <p className="text-emerald-400">Yes{check.data.apps?.length ? ` · ${check.data.apps.join(", ")}` : ""}</p>
                    ) : (
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-rose-400 flex-1 min-w-48">No. Meta sends no delivery updates until it is, even when the webhook verified.</p>
                        {canEdit && <Button size="sm" variant="primary" onClick={() => subscribe.mutate()} loading={subscribe.isPending}>Subscribe now</Button>}
                      </div>
                    )}
              </div>
              <p className="text-xs text-[var(--text-muted)]">
                Last webhook call received: {cfg.last_webhook_at ? <span className="text-emerald-400">{fmtDateTime(cfg.last_webhook_at + "Z")}</span> : "none yet"}
              </p>
              {cfg.last_webhook_error && (!cfg.last_webhook_at || cfg.last_webhook_error.at > cfg.last_webhook_at) && (
                <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-400">
                  <b>Last webhook call was refused</b> ({fmtDateTime(cfg.last_webhook_error.at + "Z")}): {cfg.last_webhook_error.reason}
                </div>
              )}
              {canEdit && (
                <Button size="sm" variant="ghost" onClick={() => rotate.mutate()} loading={rotate.isPending}>Make a new verify token</Button>
              )}
            </div>
          )}
        </Card>
      </div>
      {cfg.configured && <WebhookActivity />}
    </div>
  );
}

// ── Tab 2: numbers ──────────────────────────────────────────────────

const numberCls = "w-full sm:w-56 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] px-3 py-2 text-sm text-[var(--text-primary)] tabular-nums placeholder:text-[var(--text-muted)]";
const PHONE_HINT = "e.g. 9876543210 or +91 98765 43210";

function Row({ children }: { children: ReactNode }) {
  return <div className="flex flex-col sm:flex-row sm:items-center gap-2 px-5 py-2.5">{children}</div>;
}

function NumbersTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const canEdit = useCanEdit();
  const { data, isLoading } = useQuery({ queryKey: ["whatsapp", "contacts"], queryFn: () => api.get<Contacts>("/whatsapp/contacts") });
  const [draft, setDraft] = useState<Contacts | null>(null);
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    if (data && !dirty) {
      // Every telecaller gets at least one row to type into.
      setDraft({ ...data, telecallers: data.telecallers.map((t) => ({ ...t, rows: t.rows.length ? t.rows : [{ store_id: null, phone: "" }] })) });
    }
  }, [data, dirty]);

  const save = useMutation({
    mutationFn: (c: Contacts) => api.put<{ saved: number }>("/whatsapp/contacts", {
      ceo: c.ceo.map(({ user_id, phone }) => ({ user_id, phone })),
      ceo_extra: c.ceo_extra,
      team_leaders: c.team_leaders.map(({ user_id, phone }) => ({ user_id, phone })),
      telecallers: c.telecallers.flatMap((t) => t.rows.map((r) => ({ user_id: t.user_id, store_id: r.store_id, phone: r.phone }))),
      stores: c.stores.map(({ store_id, phone }) => ({ store_id, phone })),
    }),
    onSuccess: (res) => {
      setDirty(false);
      qc.invalidateQueries({ queryKey: ["whatsapp", "contacts"] });
      toast.success(`Saved ${res.saved} number${res.saved === 1 ? "" : "s"}`);
    },
  });

  if (isLoading || !draft) return <TableSkeleton />;
  const update = (fn: (c: Contacts) => void) => {
    const next = structuredClone(draft);
    fn(next);
    setDraft(next);
    setDirty(true);
  };
  const phoneInput = (value: string, onChange: (v: string) => void) => (
    <input inputMode="tel" className={numberCls} value={value} placeholder={PHONE_HINT} disabled={!canEdit}
      onChange={(e) => onChange(e.target.value)} />
  );

  return (
    <div className="space-y-4 pb-20">
      <InfoNote>Numbers are saved with the country code (a 10-digit number gets +91). Leave a box empty for no WhatsApp alerts to that person.</InfoNote>

      <Card>
        <CardHeader title="CEO" subtitle="Gets B2 (lead not called within 15 minutes)" />
        <div className="divide-y divide-[var(--border-subtle)]">
          {draft.ceo.map((u, i) => (
            <Row key={u.user_id}>
              <span className="flex-1 text-sm text-[var(--text-primary)]">{u.name}</span>
              {phoneInput(u.phone, (v) => update((c) => { c.ceo[i]!.phone = v; }))}
            </Row>
          ))}
          {draft.ceo_extra.map((r, i) => (
            <Row key={`x${i}`}>
              <input className={cn(inputCls, "sm:flex-1")} value={r.name} placeholder="Name" disabled={!canEdit}
                onChange={(e) => update((c) => { c.ceo_extra[i]!.name = e.target.value; })} />
              {phoneInput(r.phone, (v) => update((c) => { c.ceo_extra[i]!.phone = v; }))}
              {canEdit && <Button size="sm" variant="danger" onClick={() => update((c) => { c.ceo_extra.splice(i, 1); })} title="Remove"><Trash2 size={14} /></Button>}
            </Row>
          ))}
          {draft.ceo.length === 0 && draft.ceo_extra.length === 0 && <Empty>No user has the CEO role. Add a number below.</Empty>}
        </div>
        {canEdit && (
          <div className="px-5 py-3 border-t border-[var(--border-subtle)]">
            <Button size="sm" onClick={() => update((c) => { c.ceo_extra.push({ name: "", phone: "" }); })}><Plus size={14} />Add another number</Button>
          </div>
        )}
      </Card>

      <Card>
        <CardHeader title="Team leaders" subtitle="Get B2 for their stores' leads. New team leaders appear here automatically." />
        {draft.team_leaders.length === 0 ? <Empty>No team leaders yet.</Empty> : (
          <div className="divide-y divide-[var(--border-subtle)]">
            {draft.team_leaders.map((u, i) => (
              <Row key={u.user_id}>
                <span className="flex-1 text-sm text-[var(--text-primary)]">{u.name}</span>
                {phoneInput(u.phone, (v) => update((c) => { c.team_leaders[i]!.phone = v; }))}
              </Row>
            ))}
          </div>
        )}
      </Card>

      <Card>
        <CardHeader title="Telecallers" subtitle="Get B1 (new lead alert). New telecallers appear here automatically; add a row per store they cover." />
        {draft.telecallers.length === 0 ? <Empty>No telecallers yet.</Empty> : (
          <div className="divide-y divide-[var(--border-subtle)]">
            {draft.telecallers.map((t, ti) => (
              <div key={t.user_id} className="py-1.5">
                {t.rows.map((r, ri) => (
                  <Row key={ri}>
                    <span className={cn("sm:w-48 text-sm", ri === 0 ? "text-[var(--text-primary)]" : "text-[var(--text-muted)] hidden sm:block")}>
                      {ri === 0 ? t.name : "↳"}
                    </span>
                    <select className={cn(inputCls, "sm:flex-1")} value={r.store_id ?? ""} disabled={!canEdit}
                      onChange={(e) => update((c) => { c.telecallers[ti]!.rows[ri]!.store_id = e.target.value ? Number(e.target.value) : null; })}>
                      <option value="">Any store</option>
                      {draft.stores.map((s) => <option key={s.store_id} value={s.store_id}>{s.name}</option>)}
                    </select>
                    {phoneInput(r.phone, (v) => update((c) => { c.telecallers[ti]!.rows[ri]!.phone = v; }))}
                    {canEdit && (ri === 0 ? (
                      <Button size="sm" onClick={() => update((c) => { c.telecallers[ti]!.rows.push({ store_id: null, phone: r.phone }); })} title="Add another store" className="sm:w-20">
                        <Plus size={14} />Add
                      </Button>
                    ) : (
                      <Button size="sm" variant="danger" onClick={() => update((c) => { c.telecallers[ti]!.rows.splice(ri, 1); })} title="Remove" className="sm:w-20"><Trash2 size={14} /></Button>
                    ))}
                  </Row>
                ))}
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card>
        <CardHeader title="Stores (branch WhatsApp)" subtitle="Get A2 (new priority booking) and A3 (pick a new slot)" />
        {draft.stores.length === 0 ? <Empty>No stores yet.</Empty> : (
          <div className="divide-y divide-[var(--border-subtle)]">
            {draft.stores.map((s, i) => (
              <Row key={s.store_id}>
                <span className="flex-1 text-sm text-[var(--text-primary)]">{s.name}</span>
                {phoneInput(s.phone, (v) => update((c) => { c.stores[i]!.phone = v; }))}
              </Row>
            ))}
          </div>
        )}
      </Card>

      {canEdit && (
        <div className="sticky bottom-0 -mx-1 px-1 py-3 bg-[var(--bg-primary)] border-t border-[var(--border-subtle)] flex items-center gap-3">
          <Button variant="primary" onClick={() => save.mutate(draft)} loading={save.isPending} disabled={!dirty}>Save numbers</Button>
          {dirty && <Button variant="ghost" onClick={() => setDirty(false)}>Discard changes</Button>}
          <ErrorText error={save.error} />
        </div>
      )}
    </div>
  );
}

// ── Tab 3: test templates ───────────────────────────────────────────

const STATUS_LOOK: Record<WaMessage["status"], { label: string; cls: string; icon: ReactNode }> = {
  accepted: { label: "Accepted", cls: "text-[var(--text-muted)]", icon: <Clock size={13} /> },
  sent: { label: "Sent", cls: "text-[var(--text-secondary)]", icon: <Check size={13} /> },
  delivered: { label: "Delivered", cls: "text-[var(--text-secondary)]", icon: <CheckCheck size={13} /> },
  read: { label: "Read", cls: "text-blue-400", icon: <CheckCheck size={13} /> },
  failed: { label: "Failed", cls: "text-rose-400", icon: <X size={13} /> },
};

/** Does the approved template have our button i? undefined = Meta not checked. */
function onMeta(t: Template, i: number): boolean | undefined {
  const mb = t.meta[0]?.buttons;
  if (!mb) return undefined;
  const ours = t.buttons[i];
  const theirs = mb[i];
  if (!ours || !theirs) return false;
  if (ours.type === "url") return theirs.type === "URL" && theirs.dynamic;
  return theirs.type === (ours.type === "flow" ? "FLOW" : "QUICK_REPLY");
}

function metaChip(t: Template, checked: boolean) {
  if (!checked) return null;
  const s = t.meta[0]?.status;
  const color = s === "APPROVED" ? "text-emerald-400 bg-emerald-500/10" : s ? "text-amber-400 bg-amber-500/10" : "text-rose-400 bg-rose-500/10";
  return <span className={cn("text-[10px] font-semibold px-1.5 py-0.5 rounded", color)}>{s ? s.toLowerCase() : "not on Meta"}</span>;
}

function TestTab() {
  const toast = useToast();
  const canEdit = useCanEdit();
  const qc = useQueryClient();
  const { data: cfg } = useQuery({ queryKey: ["whatsapp", "config"], queryFn: () => api.get<WaConfig>("/whatsapp/config") });
  const { data, isLoading } = useQuery({
    queryKey: ["whatsapp", "templates"],
    queryFn: () => api.get<{ templates: Template[]; meta_checked: boolean; meta_error: string | null }>("/whatsapp/templates"),
  });
  const messages = useQuery({
    queryKey: ["whatsapp", "messages"],
    queryFn: () => api.get<{ items: WaMessage[] }>("/whatsapp/messages?limit=30"),
    // Poll while anything sent recently may still change status.
    refetchInterval: (q) => (q.state.data?.items.some((m) => m.status !== "read" && m.status !== "failed"
      && m.created_at && Date.now() - new Date(m.created_at).getTime() < 10 * 60_000) ? 4000 : false),
  });

  const [selected, setSelected] = useState("");
  const tpl = data?.templates.find((t) => t.name === selected) ?? data?.templates[0];
  const [to, setTo] = useState("");
  const [language, setLanguage] = useState("en");
  const [values, setValues] = useState<Record<string, string>>({});
  const [buttonValues, setButtonValues] = useState<Record<number, string>>({});
  const [include, setInclude] = useState<Set<number>>(new Set());

  useEffect(() => {
    if (!tpl) return;
    setValues(Object.fromEntries(tpl.params.map((p) => [p.name, p.sample])));
    setButtonValues(Object.fromEntries(tpl.buttons.map((b, i) => [i, b.sample || ""])));
    setInclude(new Set(tpl.buttons.map((_, i) => i).filter((i) => onMeta(tpl, i) !== false)));
    if (tpl.meta[0]?.language) setLanguage(tpl.meta[0].language);
  }, [tpl?.name]); // eslint-disable-line react-hooks/exhaustive-deps

  const preview = useMemo(() => (tpl ? tpl.body.replace(/\{\{(\w+)\}\}/g, (_, n) => values[n] || `{{${n}}}`) : ""), [tpl, values]);

  const send = useMutation({
    mutationFn: () => api.post<{ message: WaMessage }>("/whatsapp/test-send", {
      template: tpl!.name, to, language, values, button_values: buttonValues, include_buttons: [...include],
    }),
    onSuccess: () => {
      toast.success("Sent to Meta. Watch the status below.");
      qc.invalidateQueries({ queryKey: ["whatsapp", "messages"] });
    },
    onError: () => qc.invalidateQueries({ queryKey: ["whatsapp", "messages"] }),
  });

  if (isLoading || !data || !tpl) return <TableSkeleton />;

  return (
    <div className="space-y-4">
      {cfg && !cfg.configured && <InfoNote>Finish the Setup tab before sending test messages.</InfoNote>}
      {cfg?.configured && !cfg.enabled && <InfoNote>WhatsApp is turned off. Turn it on in the Setup tab to send test messages.</InfoNote>}
      {data.meta_error && <InfoNote>Could not read template status from Meta: {data.meta_error}</InfoNote>}
      {!data.meta_checked && !data.meta_error && cfg?.configured && (
        <InfoNote>Add the WhatsApp Business Account ID on the Setup tab to see whether each template is approved.</InfoNote>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-4 items-start">
        <Card>
          <CardHeader title="Templates" />
          <div className="divide-y divide-[var(--border-subtle)]">
            {data.templates.map((t) => (
              <button key={t.name} onClick={() => setSelected(t.name)}
                className={cn("w-full text-left px-4 py-2.5 cursor-pointer", t.name === tpl.name ? "bg-blue-500/10" : "hover:bg-[var(--bg-card-hover)]")}>
                <span className="flex items-center gap-2">
                  <span className="text-[11px] font-bold text-blue-400 w-6">{t.key}</span>
                  <span className="text-sm text-[var(--text-primary)] flex-1 min-w-0 truncate">{t.label}</span>
                  {metaChip(t, data.meta_checked)}
                </span>
                <span className="block pl-8 text-[11px] text-[var(--text-muted)] font-mono truncate">{t.name}</span>
              </button>
            ))}
          </div>
        </Card>

        <Card>
          <CardHeader title={`${tpl.key} · ${tpl.label}`} subtitle={`To ${tpl.recipient} · when: ${tpl.trigger}`} />
          <div className="px-5 py-4 grid grid-cols-1 xl:grid-cols-2 gap-5">
            <div className="space-y-3">
              <div className="grid grid-cols-[1fr_90px] gap-2">
                <Field label="Send to (WhatsApp number)">
                  <input inputMode="tel" className={inputCls} value={to} onChange={(e) => setTo(e.target.value)} placeholder={PHONE_HINT} />
                </Field>
                <Field label="Language">
                  <input className={inputCls} value={language} onChange={(e) => setLanguage(e.target.value)} />
                </Field>
              </div>
              <p className="text-[11px] font-bold uppercase tracking-wider text-[var(--text-muted)] pt-1">Dummy values</p>
              {tpl.params.map((p) => (
                <Field key={p.name} label={p.name}>
                  <input className={inputCls} value={values[p.name] ?? ""} onChange={(e) => setValues({ ...values, [p.name]: e.target.value })} />
                </Field>
              ))}
              {tpl.buttons.length > 0 && (
                <>
                  <p className="text-[11px] font-bold uppercase tracking-wider text-[var(--text-muted)] pt-1">Buttons</p>
                  {tpl.buttons.map((b, i) => (
                    <div key={i} className="space-y-1.5">
                      <label className="flex items-center gap-2 text-xs text-[var(--text-secondary)] cursor-pointer">
                        <input type="checkbox" checked={include.has(i)} onChange={(e) => {
                          const next = new Set(include);
                          if (e.target.checked) next.add(i); else next.delete(i);
                          setInclude(next);
                        }} />
                        <b className="text-[var(--text-primary)]">{b.text}</b>
                        <span>({b.type === "url" ? "link" : b.type === "flow" ? "WhatsApp Flow" : "quick reply"}{b.optional ? ", optional" : ""})</span>
                        {onMeta(tpl, i) === false && <span className="text-amber-400">· not on the approved template</span>}
                      </label>
                      {b.type === "url" && include.has(i) && (
                        <Field label={b.url || "Link value"} hint="Fills the {{1}} at the end of the link">
                          <input className={inputCls} value={buttonValues[i] ?? ""} onChange={(e) => setButtonValues({ ...buttonValues, [i]: e.target.value })} />
                        </Field>
                      )}
                    </div>
                  ))}
                  <p className="text-[11px] text-[var(--text-muted)]">
                    {tpl.meta[0]?.buttons ? "Ticked to match the approved template on Meta." : "Untick a button the approved template doesn't have, or Meta refuses the message."}
                  </p>
                </>
              )}
              <ErrorText error={send.error} />
              {canEdit && (
                <Button variant="primary" onClick={() => send.mutate()} loading={send.isPending} disabled={!to.trim() || !cfg?.enabled}>
                  <Send size={14} />Send test message
                </Button>
              )}
            </div>

            <div>
              <p className="text-[11px] font-bold uppercase tracking-wider text-[var(--text-muted)] mb-2">Preview</p>
              <div className="rounded-2xl p-4 bg-[#0b141a]" style={{ backgroundImage: "radial-gradient(rgba(255,255,255,.04) 1px, transparent 1px)", backgroundSize: "14px 14px" }}>
                <div className="max-w-sm rounded-xl rounded-tl-sm bg-[#202c33] px-3 py-2 shadow">
                  <p className="text-[13.5px] leading-snug whitespace-pre-wrap" style={{ color: "#e9edef" }}>{preview}</p>
                  <p className="text-right text-[10px] mt-1" style={{ color: "#8696a0" }}>now</p>
                </div>
                {tpl.buttons.filter((_, i) => include.has(i)).map((b) => (
                  <div key={b.text} className="max-w-sm mt-1 rounded-xl bg-[#202c33] py-2 text-center text-[13.5px] font-medium" style={{ color: "#53bdeb" }}>
                    {b.text}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </Card>
      </div>

      <Card>
        <CardHeader title="Sent messages" subtitle="Accepted = Meta took it. Sent, Delivered and Read times come back from Meta through the webhook." />
        {!messages.data ? <div className="p-5"><TableSkeleton /></div> : messages.data.items.length === 0 ? <Empty>No messages sent yet.</Empty> : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-[var(--text-muted)] border-b border-[var(--border-subtle)]">
                  {["Time", "To", "Template", "Status", "Sent", "Delivered", "Read", "By"].map((h) => <th key={h} className="py-2.5 px-4 text-left font-semibold whitespace-nowrap">{h}</th>)}
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border-subtle)]">
                {messages.data.items.map((m) => {
                  const look = STATUS_LOOK[m.status] ?? STATUS_LOOK.accepted;
                  return (
                    <tr key={m.id} className="align-top">
                      <td className="py-2.5 px-4 whitespace-nowrap text-[var(--text-secondary)]">{fmtDateTime(m.created_at)}</td>
                      <td className="py-2.5 px-4 font-mono text-[var(--text-primary)]">+{m.to}</td>
                      <td className="py-2.5 px-4 font-mono text-[var(--text-secondary)]">{m.template}</td>
                      <td className="py-2.5 px-4">
                        <span className={cn("inline-flex items-center gap-1 font-semibold", look.cls)}>{look.icon}{look.label}</span>
                        {m.failed_at && <p className="text-rose-400 whitespace-nowrap">at {fmtDateTime(m.failed_at)}</p>}
                        {m.error && <p className="text-rose-400 max-w-xs mt-0.5">{m.error_code ? `#${m.error_code} · ` : ""}{m.error}</p>}
                      </td>
                      <td className="py-2.5 px-4 whitespace-nowrap text-[var(--text-secondary)]">{m.sent_at ? fmtDateTime(m.sent_at) : "—"}</td>
                      <td className="py-2.5 px-4 whitespace-nowrap text-[var(--text-secondary)]">{m.delivered_at ? fmtDateTime(m.delivered_at) : "—"}</td>
                      <td className="py-2.5 px-4 whitespace-nowrap text-[var(--text-secondary)]">{m.read_at ? fmtDateTime(m.read_at) : "—"}</td>
                      <td className="py-2.5 px-4 text-[var(--text-secondary)]">{m.sent_by || "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

const TABS = [{ key: "setup", label: "1 · WhatsApp setup" }, { key: "numbers", label: "2 · Numbers" }, { key: "test", label: "3 · Test templates" }];

export default function WhatsAppSettings() {
  // ?tab=numbers opens a tab directly (and survives a reload)
  const [params, setParams] = useSearchParams();
  const tab = TABS.some((t) => t.key === params.get("tab")) ? params.get("tab")! : "setup";
  const setTab = (key: string) => setParams({ tab: key }, { replace: true });
  return (
    <ErrorBoundary>
      <div className="space-y-4">
        <PageHeader title="WhatsApp" subtitle="Connect the WhatsApp Business number, set who gets alerts, and test each template." />
        <Tabs tabs={TABS} value={tab} onChange={setTab} />
        {tab === "setup" && <SetupTab />}
        {tab === "numbers" && <NumbersTab />}
        {tab === "test" && <TestTab />}
      </div>
    </ErrorBoundary>
  );
}
