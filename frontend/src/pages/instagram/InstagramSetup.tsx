import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { useState, useEffect } from "react";
import {
  Settings, Camera, Bot, Key, Save, AlertCircle, CheckCircle, XCircle,
  Plus, Trash2, Power, PowerOff, X, Check, GripVertical, ChevronDown, ChevronUp,
  MessageSquare, Shield, Brain, Link as LinkIcon, MapPin,
} from "lucide-react";
import type { IGAccount, AIProvider, IGBotSettings, IGForm, IGFormField } from "./types";

type Tab = "accounts" | "ai" | "bot" | "forms";

const TABS: { key: Tab; label: string; icon: any }[] = [
  { key: "accounts", label: "Accounts", icon: Camera },
  { key: "ai", label: "AI Providers", icon: Brain },
  { key: "bot", label: "Bot Settings", icon: Bot },
  { key: "forms", label: "Forms", icon: MessageSquare },
];

const providerInfo: Record<string, { name: string; color: string; models: string[] }> = {
  claude: { name: "Claude (Anthropic)", color: "orange", models: ["claude-sonnet-4-6", "claude-sonnet-4-5", "claude-haiku-4-5-20251001"] },
  openai: { name: "ChatGPT (OpenAI)", color: "green", models: ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"] },
};

const fieldTypeOptions = [
  { value: "text", label: "Text" },
  { value: "phone", label: "Phone" },
  { value: "email", label: "Email" },
  { value: "number", label: "Number" },
  { value: "select", label: "Dropdown" },
  { value: "date", label: "Date" },
];

const emptyField = (): IGFormField => ({
  id: 0, field_key: "", label: "", field_type: "text", required: true,
  options: [], placeholder: "", phase: 1, sort_order: 0, ai_extract_hint: "",
});

export default function InstagramSetup() {
  const [tab, setTab] = useState<Tab>("accounts");

  return (
    <ErrorBoundary>
      <div className="space-y-6">
        <div>
          <h2 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
            <Settings className="text-blue-400" size={22} />
            Instagram Setup
          </h2>
          <p className="text-xs text-[var(--text-muted)] mt-0.5">
            Configure accounts, AI providers, bot behavior, and lead capture forms
          </p>
        </div>

        {/* Tab Bar */}
        <div className="flex gap-1 p-1 rounded-xl bg-[var(--bg-card)] border border-[var(--border-subtle)]">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-lg text-xs font-semibold transition-all flex-1 justify-center ${
                tab === t.key
                  ? "bg-blue-500/20 text-blue-400 border border-blue-500/30"
                  : "text-[var(--text-muted)] hover:text-white hover:bg-white/5"
              }`}
            >
              <t.icon size={14} />
              {t.label}
            </button>
          ))}
        </div>

        {tab === "accounts" && <AccountsTab />}
        {tab === "ai" && <AITab />}
        {tab === "bot" && <BotSettingsTab />}
        {tab === "forms" && <FormsTab />}
      </div>
    </ErrorBoundary>
  );
}

// Store address + optional Google Maps link, editable inline under the
// Instagram account it's linked to — so the bot (and staff) have a real
// location to give a customer, which previously existed nowhere in the
// system (Store only ever had a short region code like "AUH").
function StoreLocationEditor({ store }: { store: any }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [address, setAddress] = useState(store.address || "");
  const [mapsLink, setMapsLink] = useState(store.maps_link || "");

  useEffect(() => {
    setAddress(store.address || "");
    setMapsLink(store.maps_link || "");
  }, [store.id, store.address, store.maps_link]);

  const saveMutation = useMutation({
    mutationFn: () => api.put(`/stores/${store.id}`, { address, maps_link: mapsLink }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["stores-list"] });
      setEditing(false);
    },
  });

  return (
    <div className="mt-3 pt-3 border-t border-[var(--border-subtle)]">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
          <MapPin size={13} className="text-blue-400" />
          <span className="font-semibold text-[var(--text-secondary)]">{store.name}</span>
          {store.region && <span>· {store.region}</span>}
        </div>
        {!editing && (
          <button onClick={() => setEditing(true)} className="text-[10px] font-semibold text-blue-400 hover:text-blue-300">
            {store.address ? "Edit location" : "Add location"}
          </button>
        )}
      </div>

      {editing ? (
        <div className="mt-2 space-y-2">
          <textarea
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            rows={2}
            placeholder="Full store address, e.g. Shop 12, MG Road, Kochi, Kerala 682016"
            className="w-full px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white resize-none"
          />
          <input
            value={mapsLink}
            onChange={(e) => setMapsLink(e.target.value)}
            placeholder="Google Maps link (optional) — e.g. https://maps.app.goo.gl/..."
            className="w-full px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white"
          />
          <div className="flex gap-2">
            <button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-500 text-white text-[11px] font-semibold hover:bg-blue-600 disabled:opacity-50">
              <Check size={12} /> Save
            </button>
            <button onClick={() => { setEditing(false); setAddress(store.address || ""); setMapsLink(store.maps_link || ""); }} className="px-3 py-1.5 rounded-lg bg-white/5 text-[var(--text-muted)] text-[11px] font-semibold hover:bg-white/10">
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <p className="mt-1 text-[11px] text-[var(--text-muted)]">
          {store.address || <span className="italic">No location set — the bot can't give this store's address yet.</span>}
          {store.maps_link && (
            <a href={store.maps_link} target="_blank" rel="noreferrer" className="ml-2 text-blue-400 hover:underline">Map link</a>
          )}
        </p>
      )}
    </div>
  );
}

// ── Accounts Tab ──────────────────────────────────────────────────
function AccountsTab() {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState({ ig_user_id: "", page_id: "", page_name: "", access_token: "", store_id: "" });

  const { data: accounts, isLoading } = useQuery({
    queryKey: ["ig-accounts"],
    queryFn: () => api.get<IGAccount[]>("/instagram/accounts"),
  });

  // Every account's linked store, so the bot has a real address to give a
  // customer instead of no location data anywhere in the system.
  const { data: stores } = useQuery({
    queryKey: ["stores-list"],
    queryFn: () => api.get<any[]>("/stores/"),
  });
  const storeById = new Map((stores || []).map((s: any) => [s.id, s]));

  const createMutation = useMutation({
    mutationFn: (data: any) => api.post("/instagram/accounts", data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["ig-accounts"] }); setShowForm(false); resetForm(); },
  });

  const updateMutation = useMutation({
    mutationFn: (data: any) => api.put(`/instagram/accounts/${editingId}`, data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["ig-accounts"] }); setEditingId(null); resetForm(); },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.del(`/instagram/accounts/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ig-accounts"] }),
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, is_active }: { id: number; is_active: boolean }) => api.put(`/instagram/accounts/${id}`, { is_active }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ig-accounts"] }),
  });

  const resetForm = () => { setForm({ ig_user_id: "", page_id: "", page_name: "", access_token: "", store_id: "" }); };

  const startEdit = (a: IGAccount) => {
    setEditingId(a.id);
    setForm({ ig_user_id: a.ig_user_id, page_id: a.page_id, page_name: a.page_name, access_token: "", store_id: a.store_id?.toString() || "" });
    setShowForm(true);
  };

  const handleSubmit = () => {
    const data: any = { ...form, store_id: form.store_id ? Number(form.store_id) : null };
    if (editingId) {
      const update: any = { page_name: form.page_name, store_id: data.store_id };
      if (form.access_token) update.access_token = form.access_token;
      updateMutation.mutate(update);
    } else {
      createMutation.mutate(data);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-[var(--text-muted)]">Connect Instagram Business accounts for the bot</p>
        <button
          onClick={() => { resetForm(); setEditingId(null); setShowForm(true); }}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-500/20 text-blue-400 border border-blue-500/30 text-xs font-semibold hover:bg-blue-500/30 transition-colors"
        >
          <Plus size={14} /> Add Account
        </button>
      </div>

      {showForm && (
        <div className="rounded-2xl border border-blue-500/30 bg-[var(--bg-card)] p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-white">{editingId ? "Edit Account" : "Connect Account"}</h3>
            <button onClick={() => { setShowForm(false); setEditingId(null); }} className="p-1 rounded hover:bg-white/5"><X size={16} className="text-[var(--text-muted)]" /></button>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-semibold text-[var(--text-muted)] mb-1 block">Instagram User ID</label>
              <input value={form.ig_user_id} onChange={(e) => setForm({ ...form, ig_user_id: e.target.value })} disabled={!!editingId} className="w-full px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-sm text-white disabled:opacity-50" placeholder="e.g. 17841400123456789" />
            </div>
            <div>
              <label className="text-xs font-semibold text-[var(--text-muted)] mb-1 block">Page ID</label>
              <input value={form.page_id} onChange={(e) => setForm({ ...form, page_id: e.target.value })} disabled={!!editingId} className="w-full px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-sm text-white disabled:opacity-50" placeholder="e.g. 1234567890" />
            </div>
            <div>
              <label className="text-xs font-semibold text-[var(--text-muted)] mb-1 block">Page Name</label>
              <input value={form.page_name} onChange={(e) => setForm({ ...form, page_name: e.target.value })} className="w-full px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-sm text-white" placeholder="e.g. BreakProtection Official" />
            </div>
            <div>
              <label className="text-xs font-semibold text-[var(--text-muted)] mb-1 block">Access Token</label>
              <input type="password" value={form.access_token} onChange={(e) => setForm({ ...form, access_token: e.target.value })} className="w-full px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-sm text-white font-mono" placeholder={editingId ? "Leave blank to keep current" : "Paste long-lived token"} />
            </div>
            <div>
              <label className="text-xs font-semibold text-[var(--text-muted)] mb-1 block">Linked Store</label>
              <select value={form.store_id} onChange={(e) => setForm({ ...form, store_id: e.target.value })} className="w-full px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-sm text-white">
                <option value="">None</option>
                {(stores || []).map((s: any) => (
                  <option key={s.id} value={s.id}>{s.name}{s.region ? ` (${s.region})` : ""}</option>
                ))}
              </select>
            </div>
          </div>
          <div className="flex gap-2">
            <button onClick={handleSubmit} disabled={(!form.ig_user_id || !form.page_id || !form.access_token) && !editingId} className="flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-500 text-white text-xs font-semibold hover:bg-blue-600 transition-colors disabled:opacity-50">
              <Check size={14} /> {editingId ? "Update" : "Connect"}
            </button>
            <button onClick={() => { setShowForm(false); setEditingId(null); }} className="px-4 py-2 rounded-lg bg-white/5 text-[var(--text-muted)] text-xs font-semibold hover:bg-white/10">Cancel</button>
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="space-y-3">{[1, 2].map((i) => <div key={i} className="h-20 rounded-xl bg-[var(--bg-card)] animate-pulse" />)}</div>
      ) : accounts && accounts.length > 0 ? (
        <div className="space-y-3">
          {accounts.map((a) => (
            <div key={a.id} className={`p-4 rounded-xl border ${a.is_active ? "bg-[var(--bg-card)] border-[var(--border-subtle)]" : "bg-[var(--bg-card)] border-[var(--border-subtle)] opacity-60"}`}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center"><Camera size={18} className="text-white" /></div>
                  <div>
                    <p className="text-sm font-semibold text-white">{a.page_name || a.ig_user_id}</p>
                    <p className="text-[10px] text-[var(--text-muted)]">IG: {a.ig_user_id} | Page: {a.page_id}</p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={() => toggleMutation.mutate({ id: a.id, is_active: !a.is_active })} className="p-1.5 rounded-lg hover:bg-white/5">
                    {a.is_active ? <Power size={14} className="text-emerald-400" /> : <PowerOff size={14} className="text-[var(--text-muted)]" />}
                  </button>
                  <button onClick={() => startEdit(a)} className="p-1.5 rounded-lg hover:bg-white/5"><LinkIcon size={14} className="text-blue-400" /></button>
                  <button onClick={() => deleteMutation.mutate(a.id)} className="p-1.5 rounded-lg hover:bg-white/5"><Trash2 size={14} className="text-rose-400" /></button>
                </div>
              </div>
              {a.store_id && storeById.get(a.store_id) && (
                <StoreLocationEditor store={storeById.get(a.store_id)} />
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="rounded-2xl border border-dashed border-[var(--border-subtle)] bg-[var(--bg-card)] p-10 text-center">
          <Camera size={40} className="mx-auto text-blue-400 mb-3 opacity-30" />
          <p className="text-sm font-semibold text-white">No Accounts Connected</p>
          <p className="text-xs text-[var(--text-muted)] mt-1">Connect an Instagram Business account to start</p>
        </div>
      )}
    </div>
  );
}

// ── AI Providers Tab ──────────────────────────────────────────────
function AITab() {
  const queryClient = useQueryClient();
  const [apiKeys, setApiKeys] = useState<Record<number, string>>({});

  const { data: providers, isLoading } = useQuery({
    queryKey: ["ai-providers"],
    queryFn: () => api.get<AIProvider[]>("/instagram/ai-providers"),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, api_key, model_name }: { id: number; api_key?: string; model_name?: string }) =>
      api.put(`/instagram/ai-providers/${id}`, { api_key, model_name }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ai-providers"] }),
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, is_active }: { id: number; is_active: boolean }) =>
      api.post(`/instagram/ai-providers/${id}/toggle`, { is_active }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ai-providers"] }),
  });

  const handleSaveKey = (id: number) => {
    const key = apiKeys[id];
    if (key) { updateMutation.mutate({ id, api_key: key }); setApiKeys((prev) => ({ ...prev, [id]: "" })); }
  };

  return (
    <div className="space-y-4">
      <p className="text-xs text-[var(--text-muted)]">Configure AI for the Instagram bot. Only one provider can be active at a time.</p>

      {isLoading ? (
        <div className="space-y-4">{[1, 2].map((i) => <div key={i} className="h-48 rounded-2xl bg-[var(--bg-card)] animate-pulse" />)}</div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {providers?.map((provider) => {
            const info = providerInfo[provider.provider] || { name: provider.provider, models: [] };
            const isConfigured = provider.api_key_encrypted && provider.api_key_encrypted !== "NOT_CONFIGURED";
            return (
              <div key={provider.id} className={`rounded-2xl border p-5 space-y-4 transition-all ${provider.is_active ? "border-emerald-500/40 bg-emerald-500/5" : "border-[var(--border-subtle)] bg-[var(--bg-card)]"}`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className={`w-10 h-10 rounded-xl flex items-center justify-center text-lg ${provider.is_active ? "bg-emerald-500/20 border border-emerald-500/30" : "bg-white/5 border border-[var(--border-subtle)]"}`}>
                      {provider.provider === "claude" ? "\u{1F9E0}" : "\u{1F916}"}
                    </div>
                    <div>
                      <h3 className="text-sm font-bold text-white">{info.name}</h3>
                      <p className="text-[10px] text-[var(--text-muted)]">{provider.is_active ? "Active" : "Inactive"}{isConfigured ? " \u00b7 Key configured" : ""}</p>
                    </div>
                  </div>
                  <button onClick={() => toggleMutation.mutate({ id: provider.id, is_active: !provider.is_active })} className={`relative w-12 h-6 rounded-full transition-colors ${provider.is_active ? "bg-emerald-500" : "bg-white/10"}`}>
                    <div className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-transform ${provider.is_active ? "left-[26px]" : "left-0.5"}`} />
                  </button>
                </div>

                <div>
                  <label className="text-xs font-semibold text-[var(--text-muted)] mb-1 block">Model</label>
                  <select value={provider.model_name} onChange={(e) => updateMutation.mutate({ id: provider.id, model_name: e.target.value })} className="w-full px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-sm text-white">
                    {info.models.map((m) => <option key={m} value={m}>{m}</option>)}
                  </select>
                </div>

                <div>
                  <label className="text-xs font-semibold text-[var(--text-muted)] mb-1 block">API Key</label>
                  <div className="flex gap-2">
                    <input type="password" value={apiKeys[provider.id] || ""} onChange={(e) => setApiKeys((prev) => ({ ...prev, [provider.id]: e.target.value }))} className="flex-1 px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-sm text-white font-mono" placeholder={isConfigured ? "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" : "Enter API key..."} />
                    {apiKeys[provider.id] && (
                      <button onClick={() => handleSaveKey(provider.id)} disabled={updateMutation.isPending} className="px-3 py-2 rounded-lg bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/30">
                        <Save size={14} />
                      </button>
                    )}
                  </div>
                </div>

                {provider.is_active && (
                  <div className="flex items-center gap-2 p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                    <CheckCircle size={14} className="text-emerald-400" />
                    <span className="text-xs text-emerald-300 font-medium">Active - Bot uses this provider</span>
                  </div>
                )}
                {!isConfigured && !provider.is_active && (
                  <div className="flex items-center gap-2 p-2 rounded-lg bg-amber-500/10 border border-amber-500/20">
                    <AlertCircle size={14} className="text-amber-400" />
                    <span className="text-xs text-amber-300 font-medium">Not configured - Add an API key</span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5">
        <h3 className="text-sm font-bold text-white mb-2 flex items-center gap-2"><AlertCircle size={14} className="text-blue-400" /> How it works</h3>
        <ul className="text-xs text-[var(--text-muted)] space-y-1.5 ml-5 list-disc">
          <li>Only <strong className="text-white">one provider</strong> can be active at a time</li>
          <li>Activating one <strong className="text-white">automatically deactivates</strong> the other</li>
          <li>API keys are encrypted at rest in the database</li>
          <li>Credits/tokens are tracked per conversation in the analytics dashboard</li>
        </ul>
      </div>
    </div>
  );
}

// ── Bot Settings Tab ──────────────────────────────────────────────
function BotSettingsTab() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    dm_auto_reply_enabled: false, comment_auto_reply_enabled: false,
    comment_moderation_enabled: false, lead_qualification_enabled: false,
    ai_system_prompt: "", welcome_message: "", after_hours_message: "",
  });

  const { data: accounts } = useQuery({ queryKey: ["ig-accounts"], queryFn: () => api.get<IGAccount[]>("/instagram/accounts") });
  const accountId = accounts?.[0]?.id;

  const { data: settings, isLoading } = useQuery({
    queryKey: ["ig-bot-settings", accountId],
    queryFn: () => api.get<IGBotSettings>(`/instagram/settings?ig_account_id=${accountId}`),
    enabled: !!accountId,
  });

  useEffect(() => {
    if (settings) {
      setForm({
        dm_auto_reply_enabled: settings.dm_auto_reply_enabled,
        comment_auto_reply_enabled: settings.comment_auto_reply_enabled,
        comment_moderation_enabled: settings.comment_moderation_enabled,
        lead_qualification_enabled: settings.lead_qualification_enabled,
        ai_system_prompt: settings.ai_system_prompt,
        welcome_message: settings.welcome_message,
        after_hours_message: settings.after_hours_message,
      });
    }
  }, [settings]);

  const updateMutation = useMutation({
    mutationFn: (data: any) => api.put(`/instagram/settings?ig_account_id=${accountId}`, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ig-bot-settings"] }),
  });

  const handleSave = () => updateMutation.mutate(form);

  const Toggle = ({ label, desc, checked, onChange }: { label: string; desc: string; checked: boolean; onChange: () => void }) => (
    <div className="flex items-center justify-between p-3 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)]">
      <div>
        <p className="text-sm font-semibold text-white">{label}</p>
        <p className="text-[10px] text-[var(--text-muted)]">{desc}</p>
      </div>
      <button onClick={onChange} className={`relative w-12 h-6 rounded-full transition-colors ${checked ? "bg-emerald-500" : "bg-white/10"}`}>
        <div className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-transform ${checked ? "left-[26px]" : "left-0.5"}`} />
      </button>
    </div>
  );

  return (
    <div className="space-y-4">
      <p className="text-xs text-[var(--text-muted)]">Configure the AI prompt and how the bot behaves in DMs and comments</p>

      {!accountId && (
        <div className="flex items-center gap-3 p-3 rounded-xl bg-amber-500/10 border border-amber-500/20">
          <AlertCircle size={16} className="text-amber-400 flex-shrink-0" />
          <p className="text-xs text-amber-300">Connect an Instagram account in the <strong>Accounts</strong> tab to enable bot features. You can configure the prompt below in the meantime.</p>
        </div>
      )}

      {isLoading ? (
        <div className="space-y-3">{[1, 2, 3, 4].map((i) => <div key={i} className="h-16 rounded-xl bg-[var(--bg-card)] animate-pulse" />)}</div>
      ) : (
        <>
          {/* AI System Prompt — always visible */}
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 space-y-4">
            <div className="flex items-center gap-2">
              <Brain size={16} className="text-purple-400" />
              <h3 className="text-sm font-bold text-white">AI System Prompt</h3>
            </div>
            <p className="text-[10px] text-[var(--text-muted)]">This prompt defines the AI's personality and behavior when replying to Instagram DMs and comments.</p>
            <textarea
              value={form.ai_system_prompt}
              onChange={(e) => setForm({ ...form, ai_system_prompt: e.target.value })}
              rows={8}
              className="w-full px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-sm text-white resize-none font-mono leading-relaxed"
              placeholder={"You are a helpful assistant for BreakProtection, a mobile phone retailer in India.\n\nYou help customers with:\n- Product inquiries and pricing\n- Store visit bookings\n- Complaints and feedback\n- General questions\n\nBe polite, professional, and concise. Always respond in the customer's language."}
            />
          </div>

          {/* Welcome + After Hours Messages — always visible */}
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 space-y-4">
            <div className="flex items-center gap-2">
              <MessageSquare size={16} className="text-blue-400" />
              <h3 className="text-sm font-bold text-white">Messages</h3>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="text-xs font-semibold text-[var(--text-muted)] mb-1 block">Welcome Message</label>
                <input
                  value={form.welcome_message}
                  onChange={(e) => setForm({ ...form, welcome_message: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-sm text-white"
                  placeholder="Hi! Welcome to BreakProtection. How can I help you today?"
                />
                <p className="text-[10px] text-[var(--text-muted)] mt-1">Sent when a user first messages the bot</p>
              </div>
              <div>
                <label className="text-xs font-semibold text-[var(--text-muted)] mb-1 block">After Hours Message</label>
                <input
                  value={form.after_hours_message}
                  onChange={(e) => setForm({ ...form, after_hours_message: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-sm text-white"
                  placeholder="Thanks for reaching out! Our team is currently offline..."
                />
                <p className="text-[10px] text-[var(--text-muted)] mt-1">Sent outside business hours</p>
              </div>
            </div>
          </div>

          {/* Bot Feature Toggles — only when account connected */}
          {accountId && (
            <div className="space-y-3">
              <p className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider">Bot Features</p>
              <Toggle label="DM Auto-Reply" desc="Automatically reply to incoming Instagram DMs using AI" checked={form.dm_auto_reply_enabled} onChange={() => { const v = !form.dm_auto_reply_enabled; setForm({ ...form, dm_auto_reply_enabled: v }); updateMutation.mutate({ dm_auto_reply_enabled: v }); }} />
              <Toggle label="Comment Auto-Reply" desc="Automatically reply to comments on your posts" checked={form.comment_auto_reply_enabled} onChange={() => { const v = !form.comment_auto_reply_enabled; setForm({ ...form, comment_auto_reply_enabled: v }); updateMutation.mutate({ comment_auto_reply_enabled: v }); }} />
              <Toggle label="Comment Moderation" desc="Hide comments matching flagged keywords" checked={form.comment_moderation_enabled} onChange={() => { const v = !form.comment_moderation_enabled; setForm({ ...form, comment_moderation_enabled: v }); updateMutation.mutate({ comment_moderation_enabled: v }); }} />
              <Toggle label="Lead Qualification" desc="AI detects purchase intent and creates leads automatically" checked={form.lead_qualification_enabled} onChange={() => { const v = !form.lead_qualification_enabled; setForm({ ...form, lead_qualification_enabled: v }); updateMutation.mutate({ lead_qualification_enabled: v }); }} />
            </div>
          )}

          <button onClick={handleSave} disabled={updateMutation.isPending || !accountId} className="flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-500 text-white text-xs font-semibold hover:bg-blue-600 transition-colors disabled:opacity-50">
            <Save size={14} /> Save Settings
          </button>
          {!accountId && <p className="text-[10px] text-[var(--text-muted)]">Connect an account in the Accounts tab to save these settings</p>}
        </>
      )}
    </div>
  );
}

// ── Forms Tab ─────────────────────────────────────────────────────
function FormsTab() {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [editingForm, setEditingForm] = useState<IGForm | null>(null);
  const [expandedForm, setExpandedForm] = useState<number | null>(null);
  const [form, setForm] = useState({ name: "", display_name: "", description: "", form_type: "simple", ai_prompt_hint: "", success_message: "Thank you! Your submission has been received." });
  const [fields, setFields] = useState<IGFormField[]>([emptyField()]);

  const { data: forms, isLoading } = useQuery({ queryKey: ["ig-forms"], queryFn: () => api.get<IGForm[]>("/instagram/forms") });

  const createMutation = useMutation({
    mutationFn: (data: any) => api.post("/instagram/forms", data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["ig-forms"] }); setShowForm(false); resetForm(); },
  });

  const updateMutation = useMutation({
    mutationFn: (data: any) => api.put(`/instagram/forms/${editingForm?.id}`, data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["ig-forms"] }); setEditingForm(null); resetForm(); },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.del(`/instagram/forms/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ig-forms"] }),
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, is_active }: { id: number; is_active: boolean }) => api.put(`/instagram/forms/${id}`, { is_active }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ig-forms"] }),
  });

  const resetForm = () => {
    setForm({ name: "", display_name: "", description: "", form_type: "simple", ai_prompt_hint: "", success_message: "Thank you! Your submission has been received." });
    setFields([emptyField()]);
  };

  const startEdit = (f: IGForm) => {
    setEditingForm(f);
    setForm({ name: f.name, display_name: f.display_name, description: f.description, form_type: f.form_type, ai_prompt_hint: f.ai_prompt_hint, success_message: f.success_message });
    setFields(f.fields.length > 0 ? [...f.fields] : [emptyField()]);
    setShowForm(true);
  };

  const addField = () => setFields([...fields, { ...emptyField(), sort_order: fields.length }]);
  const removeField = (i: number) => { if (fields.length > 1) setFields(fields.filter((_, idx) => idx !== i)); };
  const updateField = (i: number, key: keyof IGFormField, value: any) => {
    const updated = [...fields];
    updated[i] = { ...updated[i], [key]: value };
    if (key === "label" && !updated[i].field_key) updated[i].field_key = value.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
    setFields(updated);
  };

  const handleSubmit = () => {
    const data = { ...form, fields: fields.filter((f) => f.field_key && f.label) };
    if (editingForm) { updateMutation.mutate(data); } else { createMutation.mutate(data); }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-[var(--text-muted)]">Create forms for lead capture via Instagram DMs</p>
        <button onClick={() => { resetForm(); setEditingForm(null); setShowForm(true); }} className="flex items-center gap-2 px-4 py-2 rounded-lg bg-purple-500/20 text-purple-400 border border-purple-500/30 text-xs font-semibold hover:bg-purple-500/30 transition-colors">
          <Plus size={14} /> Add Form
        </button>
      </div>

      {showForm && (
        <div className="rounded-2xl border border-purple-500/30 bg-[var(--bg-card)] p-5 space-y-5">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-white">{editingForm ? "Edit Form" : "New Form"}</h3>
            <button onClick={() => { setShowForm(false); setEditingForm(null); }} className="p-1 rounded hover:bg-white/5"><X size={16} className="text-[var(--text-muted)]" /></button>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div><label className="text-xs font-semibold text-[var(--text-muted)] mb-1 block">Internal Name</label><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="w-full px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-sm text-white" placeholder="e.g. complaint" /></div>
            <div><label className="text-xs font-semibold text-[var(--text-muted)] mb-1 block">Display Name</label><input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} className="w-full px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-sm text-white" placeholder="e.g. Complaint Form" /></div>
            <div><label className="text-xs font-semibold text-[var(--text-muted)] mb-1 block">Form Type</label>
              <select value={form.form_type} onChange={(e) => setForm({ ...form, form_type: e.target.value })} className="w-full px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-sm text-white">
                <option value="simple">Simple (Phase 1 only)</option>
                <option value="two_phase">Two-Phase (DM + Web)</option>
              </select>
            </div>
            <div><label className="text-xs font-semibold text-[var(--text-muted)] mb-1 block">AI Prompt Hint</label><input value={form.ai_prompt_hint} onChange={(e) => setForm({ ...form, ai_prompt_hint: e.target.value })} className="w-full px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-sm text-white" placeholder="When should AI trigger this form?" /></div>
          </div>
          <div><label className="text-xs font-semibold text-[var(--text-muted)] mb-1 block">Description</label><input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="w-full px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-sm text-white" /></div>
          <div><label className="text-xs font-semibold text-[var(--text-muted)] mb-1 block">Success Message</label><input value={form.success_message} onChange={(e) => setForm({ ...form, success_message: e.target.value })} className="w-full px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-sm text-white" /></div>

          <div className="space-y-3">
            <div className="flex items-center justify-between"><label className="text-xs font-semibold text-[var(--text-muted)]">Form Fields</label><button onClick={addField} className="text-[10px] font-semibold text-purple-400 hover:text-purple-300">+ Add Field</button></div>
            {fields.map((field, i) => (
              <div key={i} className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] p-3 space-y-3">
                <div className="flex items-center gap-2">
                  <GripVertical size={14} className="text-[var(--text-muted)]" />
                  <input value={field.label} onChange={(e) => updateField(i, "label", e.target.value)} className="flex-1 px-2 py-1 rounded bg-transparent border-b border-[var(--border-subtle)] text-sm text-white focus:outline-none focus:border-purple-500" placeholder="Field label" />
                  <select value={field.field_type} onChange={(e) => updateField(i, "field_type", e.target.value)} className="px-2 py-1 rounded bg-[var(--bg-card)] border border-[var(--border-subtle)] text-xs text-white">{fieldTypeOptions.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}</select>
                  <select value={field.phase} onChange={(e) => updateField(i, "phase", parseInt(e.target.value))} className="px-2 py-1 rounded bg-[var(--bg-card)] border border-[var(--border-subtle)] text-xs text-white"><option value={1}>Phase 1 (DM)</option><option value={2}>Phase 2 (Web)</option></select>
                  <label className="flex items-center gap-1 text-xs text-[var(--text-muted)]"><input type="checkbox" checked={field.required} onChange={(e) => updateField(i, "required", e.target.checked)} className="accent-purple-500" />Req</label>
                  <button onClick={() => removeField(i)} className="p-1 rounded hover:bg-white/5"><Trash2 size={12} className="text-rose-400" /></button>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <input value={field.placeholder} onChange={(e) => updateField(i, "placeholder", e.target.value)} className="px-2 py-1 rounded bg-transparent border border-[var(--border-subtle)] text-xs text-white" placeholder="Placeholder" />
                  <input value={field.ai_extract_hint} onChange={(e) => updateField(i, "ai_extract_hint", e.target.value)} className="px-2 py-1 rounded bg-transparent border border-[var(--border-subtle)] text-xs text-white" placeholder="AI extract hint" />
                </div>
                {field.field_type === "select" && (
                  <div><label className="text-[10px] text-[var(--text-muted)] mb-1 block">Options (one per line: value|label)</label>
                    <textarea rows={2} value={field.options.map((o) => `${o.value}|${o.label}`).join("\n")} onChange={(e) => { const opts = e.target.value.split("\n").filter(Boolean).map((l) => { const [v, lb] = l.split("|"); return { value: v?.trim() || "", label: lb?.trim() || v?.trim() || "" }; }); updateField(i, "options", opts); }} className="w-full px-2 py-1 rounded bg-transparent border border-[var(--border-subtle)] text-xs text-white resize-none font-mono" />
                  </div>
                )}
              </div>
            ))}
          </div>

          <div className="flex gap-2">
            <button onClick={handleSubmit} disabled={!form.name || !form.display_name || createMutation.isPending || updateMutation.isPending} className="flex items-center gap-2 px-4 py-2 rounded-lg bg-purple-500 text-white text-xs font-semibold hover:bg-purple-600 transition-colors disabled:opacity-50"><Check size={14} />{editingForm ? "Update" : "Create"}</button>
            <button onClick={() => { setShowForm(false); setEditingForm(null); }} className="px-4 py-2 rounded-lg bg-white/5 text-[var(--text-muted)] text-xs font-semibold hover:bg-white/10">Cancel</button>
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="space-y-3">{[1, 2, 3].map((i) => <div key={i} className="h-20 rounded-xl bg-[var(--bg-card)] animate-pulse" />)}</div>
      ) : forms && forms.length > 0 ? (
        <div className="space-y-3">
          {forms.map((f) => (
            <div key={f.id} className={`rounded-xl border ${f.is_active ? "bg-[var(--bg-card)] border-[var(--border-subtle)]" : "bg-[var(--bg-card)] border-[var(--border-subtle)] opacity-60"}`}>
              <div className="p-4 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className={`w-2 h-2 rounded-full ${f.is_active ? "bg-emerald-400" : "bg-[var(--text-muted)]"}`} />
                  <div>
                    <p className="text-sm font-semibold text-white">{f.display_name}</p>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-[10px] px-2 py-0.5 rounded bg-purple-500/10 text-purple-300">{f.form_type === "two_phase" ? "Two-Phase" : "Simple"}</span>
                      <span className="text-[10px] px-2 py-0.5 rounded bg-blue-500/10 text-blue-300">{f.fields.length} fields</span>
                      <span className="text-[10px] text-[var(--text-muted)]">{f.submission_count} submissions</span>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={() => setExpandedForm(expandedForm === f.id ? null : f.id)} className="p-1.5 rounded-lg hover:bg-white/5">{expandedForm === f.id ? <ChevronUp size={14} className="text-[var(--text-muted)]" /> : <ChevronDown size={14} className="text-[var(--text-muted)]" />}</button>
                  <button onClick={() => toggleMutation.mutate({ id: f.id, is_active: !f.is_active })} className="p-1.5 rounded-lg hover:bg-white/5">{f.is_active ? <Power size={14} className="text-emerald-400" /> : <PowerOff size={14} className="text-[var(--text-muted)]" />}</button>
                  <button onClick={() => startEdit(f)} className="p-1.5 rounded-lg hover:bg-white/5"><MessageSquare size={14} className="text-blue-400" /></button>
                  <button onClick={() => deleteMutation.mutate(f.id)} className="p-1.5 rounded-lg hover:bg-white/5"><Trash2 size={14} className="text-rose-400" /></button>
                </div>
              </div>
              {expandedForm === f.id && f.fields.length > 0 && (
                <div className="px-4 pb-4 border-t border-[var(--border-subtle)] pt-3">
                  <div className="space-y-1.5">
                    {f.fields.map((field) => (
                      <div key={field.field_key} className="flex items-center gap-3 text-xs">
                        <span className="text-white font-medium w-32 truncate">{field.label}</span>
                        <span className="text-[var(--text-muted)] px-1.5 py-0.5 rounded bg-white/5">{field.field_type}</span>
                        <span className={`px-1.5 py-0.5 rounded ${field.phase === 1 ? "bg-blue-500/10 text-blue-300" : "bg-amber-500/10 text-amber-300"}`}>Phase {field.phase}</span>
                        {field.required && <span className="text-red-400 text-[10px]">Required</span>}
                      </div>
                    ))}
                  </div>
                  <p className="text-[10px] text-[var(--text-muted)] mt-2 italic">{f.ai_prompt_hint}</p>
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="rounded-2xl border border-dashed border-[var(--border-subtle)] bg-[var(--bg-card)] p-10 text-center">
          <MessageSquare size={40} className="mx-auto text-purple-400 mb-3 opacity-30" />
          <p className="text-sm font-semibold text-white">No Forms</p>
          <p className="text-xs text-[var(--text-muted)] mt-1">Create forms to capture leads via Instagram DMs</p>
        </div>
      )}
    </div>
  );
}
