import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import type {
  AgentRow, CrmAlert, CrmLead, CrmMeta, Followup, LeadDetail, LeadListResponse, QueueTiles, Targets,
} from "./types";

function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  });
  const s = sp.toString();
  return s ? `?${s}` : "";
}

/** Every CRM query key starts with "crm" so one invalidation refreshes all. */
export const CRM_KEY = "crm";

export function useInvalidateCrm() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: [CRM_KEY] });
    qc.invalidateQueries({ queryKey: ["dashboard"] });
  };
}

export function useCrmMeta() {
  return useQuery({
    queryKey: [CRM_KEY, "meta"],
    queryFn: () => api.get<CrmMeta>("/crm/meta"),
    staleTime: 60_000,
  });
}

export interface LeadQuery {
  tab?: string;
  status?: string;
  stage?: string;
  owner?: string;
  sheet?: string;
  priority?: string;
  q?: string;
  sort?: string;
  group_by?: string;
  page?: number;
  page_size?: number;
  start?: string;
  end?: string;
}

export function useCrmLeads(params: LeadQuery) {
  return useQuery({
    queryKey: [CRM_KEY, "leads", params],
    queryFn: () => api.get<LeadListResponse>(`/crm/leads${qs({ ...params })}`),
    placeholderData: (prev) => prev,
    refetchInterval: 60_000,
  });
}

export function useLeadDetail(id: number | null) {
  return useQuery({
    queryKey: [CRM_KEY, "lead", id],
    queryFn: () => api.get<LeadDetail>(`/crm/leads/${id}`),
    enabled: !!id,
  });
}

function useCrmMutation<TVars, TRes = unknown>(fn: (vars: TVars) => Promise<TRes>) {
  const invalidate = useInvalidateCrm();
  return useMutation({ mutationFn: fn, onSuccess: () => invalidate() });
}

export interface ActivityBody {
  outcome: string;
  notes?: string;
  callback_at?: string;
  next_follow_up_at?: string;
  appointment_at?: string;
  appointment_purpose?: string;
  store_id?: number | null;
  sale_amount?: string;
}

export function useLogActivity() {
  return useCrmMutation(({ leadId, body }: { leadId: number; body: ActivityBody }) =>
    api.post<{ ok: boolean; lead: CrmLead; next_follow_up: { due_at: string; kind: string; reason: string } | null }>(
      `/crm/leads/${leadId}/activities`, body),
  );
}

export function usePatchLead() {
  return useCrmMutation(({ leadId, body }: { leadId: number; body: Record<string, unknown> }) =>
    api.patch<{ ok: boolean; lead: CrmLead }>(`/crm/leads/${leadId}`, body),
  );
}

export function useAssignLead() {
  return useCrmMutation(({ leadId, ownerId }: { leadId: number; ownerId: number | null }) =>
    api.post<{ ok: boolean; lead: CrmLead }>(`/crm/leads/${leadId}/assign`, { owner_user_id: ownerId }),
  );
}

export function useBulkAssign() {
  return useCrmMutation(({ leadIds, ownerId }: { leadIds: number[]; ownerId: number | null }) =>
    api.post<{ ok: boolean; changed: number; skipped: number }>(`/crm/leads/bulk-assign`, {
      lead_ids: leadIds, owner_user_id: ownerId,
    }),
  );
}

export function useCreateLead() {
  return useCrmMutation((body: Record<string, unknown>) =>
    api.post<{ ok: boolean; lead: CrmLead }>(`/crm/leads`, body),
  );
}

export interface OverviewResponse {
  mine: boolean;
  tiles: QueueTiles;
  inbox: { total: number; items: CrmAlert[] };
  followups: Followup[];
  sales: {
    open_pipeline_value: number;
    converted_this_month_value: number;
    converted_this_month_count: number;
    appointments_today: number;
  };
  pipeline: { stage: string; label: string; count: number; value: number }[];
  data_health: {
    missing_phone: number;
    no_status_24h: number;
    unassigned_open: number;
    missing_model: number;
    unknown_status: number;
  };
}

export function useOverview(mine?: boolean) {
  return useQuery({
    queryKey: [CRM_KEY, "overview", mine],
    queryFn: () => api.get<OverviewResponse>(`/crm/overview${qs({ mine: mine === undefined ? "" : mine ? 1 : 0 })}`),
    refetchInterval: 60_000,
  });
}

export function useFollowups(mine?: boolean, owner?: string) {
  return useQuery({
    queryKey: [CRM_KEY, "followups", mine, owner],
    queryFn: () =>
      api.get<{ mine: boolean; overdue: Followup[]; today: Followup[]; upcoming: Followup[] }>(
        `/crm/followups${qs({ mine: mine === undefined ? "" : mine ? 1 : 0, owner })}`,
      ),
    refetchInterval: 60_000,
  });
}

export function useCompleteFollowup() {
  return useCrmMutation(({ id, notes }: { id: number; notes?: string }) =>
    api.post(`/crm/followups/${id}/complete`, { notes }),
  );
}

export interface AppointmentItem {
  id: number | null;
  lead_id: number;
  lead_name: string;
  phone: string;
  city: string;
  scheduled_at: string;
  date: string;
  has_time: boolean;
  purpose: string;
  attendance: string;
  source: "app" | "sheet";
  store_id: number | null;
  owner_name: string | null;
}

export function useAppointments(start: string, days: number, mine?: boolean) {
  return useQuery({
    queryKey: [CRM_KEY, "appointments", start, days, mine],
    queryFn: () =>
      api.get<{ start: string; days: number; mine: boolean; columns: { date: string; items: AppointmentItem[] }[] }>(
        `/crm/appointments${qs({ start, days, mine: mine === undefined ? "" : mine ? 1 : 0 })}`,
      ),
  });
}

export function useCreateAppointment() {
  return useCrmMutation((body: { lead_id: number; scheduled_at: string; purpose?: string; store_id?: number | null; attendance?: string }) =>
    api.post<{ ok: boolean; id: number }>(`/crm/appointments`, body),
  );
}

export function usePatchAppointment() {
  return useCrmMutation(({ id, body }: { id: number; body: Record<string, unknown> }) =>
    api.patch(`/crm/appointments/${id}`, body),
  );
}

export function usePipeline(params: { mine?: boolean; sheet?: string; owner?: string; q?: string }) {
  return useQuery({
    queryKey: [CRM_KEY, "pipeline", params],
    queryFn: () =>
      api.get<{ columns: { stage: string; label: string; count: number; value: number; cards: CrmLead[] }[] }>(
        `/crm/pipeline${qs({ mine: params.mine ? 1 : 0, sheet: params.sheet, owner: params.owner, q: params.q })}`,
      ),
    placeholderData: (prev) => prev,
  });
}

export function useAlerts(state: "open" | "all" = "open") {
  return useQuery({
    queryKey: [CRM_KEY, "alerts", state],
    queryFn: () =>
      api.get<{ lead_alerts: CrmAlert[]; performance: CrmAlert[]; open_count: number }>(`/crm/alerts?state=${state}`),
    refetchInterval: 60_000,
  });
}

export function useAckAlert() {
  return useCrmMutation((id: number) => api.post(`/crm/alerts/${id}/acknowledge`));
}

export interface SavedView {
  id: number;
  name: string;
  filters: Record<string, string>;
  columns: string[];
}

export function useSavedViews(page = "leads") {
  return useQuery({
    queryKey: [CRM_KEY, "views", page],
    queryFn: () => api.get<{ views: SavedView[] }>(`/crm/views?page=${page}`),
  });
}

export function useSaveView() {
  return useCrmMutation((body: { name: string; page?: string; filters: Record<string, string>; columns: string[] }) =>
    api.post(`/crm/views`, body),
  );
}

export function useDeleteView() {
  return useCrmMutation((id: number) => api.del(`/crm/views/${id}`));
}

export function useSetAvailability() {
  return useCrmMutation(({ userId, available }: { userId?: number; available: boolean }) =>
    userId
      ? api.put(`/crm/team/${userId}/availability`, { available })
      : api.put(`/crm/me/availability`, { available }),
  );
}

export interface TeamMember {
  id: number;
  name: string;
  role: string;
  sheets: string[];
  available: boolean;
  open_leads: number;
}

export function useTeam(enabled = true) {
  return useQuery({
    queryKey: [CRM_KEY, "team"],
    queryFn: () =>
      api.get<{ agents: TeamMember[]; can_change: boolean }>(`/crm/team`),
    enabled,
  });
}

export interface ReportResponse {
  period: { start: string; end: string };
  previous_period: { start: string; end: string };
  targets: Targets;
  first_call_minutes: number;
  rows: AgentRow[];
  can_coach: boolean;
  sheets: string[];
  go_live: string | null;
}

export function useAgentReport(params: { start: string; end: string; sheet?: string; agent?: string }) {
  return useQuery({
    queryKey: [CRM_KEY, "report", params],
    queryFn: () => api.get<ReportResponse>(`/crm/reports/agents${qs(params)}`),
    placeholderData: (prev) => prev,
  });
}

export function useCoach() {
  return useCrmMutation((body: { user_id: number; note: string }) => api.post(`/crm/reports/coach`, body));
}

export async function downloadExport(params: Record<string, string>) {
  const res = await api.fetchRaw(`/crm/reports/export${qs(params)}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Export failed (${res.status})`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `telecalling-leads-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export interface AutomationSettings {
  enabled: boolean;
  auto_assign: boolean;
  working_hours: { start: string; end: string; days: number[] };
  first_call_minutes: number;
  reassign_minutes: number;
  escalate_minutes: number;
  no_answer_retry_minutes: number;
  busy_retry_minutes: number;
  max_calls_per_day: number;
  overdue_tl_minutes: number;
  overdue_admin_minutes: number;
}

export function useAutomationSettings() {
  return useQuery({
    queryKey: [CRM_KEY, "automation-settings"],
    queryFn: () =>
      api.get<{ automation: AutomationSettings; targets: Targets; can_edit: boolean; go_live: string | null }>(
        `/crm/settings/automation`,
      ),
  });
}

export function useSaveAutomation() {
  return useCrmMutation((body: { automation?: Partial<AutomationSettings>; targets?: Partial<Targets> }) =>
    api.put(`/crm/settings/automation`, body),
  );
}

export function useAutomationLog() {
  return useQuery({
    queryKey: [CRM_KEY, "automation-log"],
    queryFn: () =>
      api.get<{
        stats: { open_first_calls: number; urgent: number };
        items: { at: string; lead_id: number; lead_name: string; city: string; type: string; from: string | null; to: string | null; notes: string | null; source: string | null }[];
      }>(`/crm/automation/log`),
    refetchInterval: 60_000,
  });
}

export interface PriceRow {
  phone_model: string;
  service_type: string;
  prices: Record<string, number | null>;
  updated_at: string | null;
}

export function usePriceBook() {
  return useQuery({
    queryKey: [CRM_KEY, "price-book"],
    queryFn: () => api.get<{ rows: PriceRow[]; coverages: string[]; can_edit: boolean }>(`/crm/price-book`),
  });
}

export function useSavePriceRow() {
  return useCrmMutation((body: {
    phone_model: string; service_type: string; prices: Record<string, number | string | null>;
    original_phone_model?: string; original_service_type?: string;
  }) => api.put(`/crm/price-book`, body));
}

export function useDeletePriceRow() {
  return useCrmMutation(({ phone_model, service_type }: { phone_model: string; service_type: string }) =>
    api.del(`/crm/price-book${qs({ phone_model, service_type })}`),
  );
}

export function useDataQuality(enabled = true) {
  return useQuery({
    queryKey: [CRM_KEY, "data-quality"],
    queryFn: () => api.get<any>(`/crm/data-quality`),
    enabled,
  });
}

export function useAudit(enabled = true) {
  return useQuery({
    queryKey: [CRM_KEY, "audit"],
    queryFn: () =>
      api.get<{ items: { id: number; at: string; user: string; action: string; resource: string; resource_id: number | null; before: unknown; after: unknown }[] }>(
        `/crm/audit`,
      ),
    enabled,
  });
}

export function useIntegrations(enabled = true) {
  return useQuery({
    queryKey: [CRM_KEY, "integrations"],
    queryFn: () => api.get<any>(`/crm/integrations`),
    enabled,
    refetchInterval: 60_000,
  });
}

export function useAliases(enabled = true) {
  return useQuery({
    queryKey: [CRM_KEY, "aliases"],
    queryFn: () => api.get<{ aliases: { alias: string; user_id: number; user_name: string | null }[] }>(`/crm/settings/aliases`),
    enabled,
  });
}

export function useSetAlias() {
  return useCrmMutation((body: { alias: string; user_id: number | null }) => api.put(`/crm/settings/aliases`, body));
}
