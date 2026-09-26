export interface CrmLead {
  id: number;
  full_name: string;
  phone: string;
  email: string;
  city: string;
  lead_source: string;
  created_time: string;
  submitted_at: string | null;
  received_at: string | null;
  status: string;
  status_label: string;
  sheet_status_raw: string | null;
  stage: string;
  stage_label: string;
  priority: string;
  priority_manual: boolean;
  stage_manual: boolean;
  owner_user_id: number | null;
  owner_name: string | null;
  assignment_source: string | null;
  reassign_count: number;
  person_calling: string;
  salesperson: string;
  next_follow_up_at: string | null;
  last_contact_at: string | null;
  first_contact_at: string | null;
  phone_model: string | null;
  service_type: string | null;
  coverage: string | null;
  potential_value: number | null;
  sale_amount: string | null;
  sale_amount_value: number | null;
  product: string;
  remarks: string;
  appointment_date: string;
  call_date: string;
  is_urgent: boolean;
  first_call_pending: boolean;
  from_sheet: boolean;
  escalated: boolean;
}

export interface CrmPerson {
  id: number;
  name: string;
  role: string;
  sheets: string[];
  available: boolean;
}

export interface CrmMeta {
  role: string;
  user: { id: number; name: string; available: boolean };
  statuses: string[];
  stages: { key: string; label: string }[];
  priorities: string[];
  sheets: string[];
  all_sheets: string[];
  people: CrmPerson[];
  phone_models: string[];
  service_types: string[];
  coverages: string[];
  stores: { id: number; name: string }[];
  can: { reassign: boolean; edit_settings: boolean; export: boolean; edit_prices: boolean; see_team: boolean };
  automation: {
    first_call_minutes: number;
    reassign_minutes: number;
    escalate_minutes: number;
    working_hours: { start: string; end: string; days: number[] };
    enabled: boolean;
  };
  now: string;
}

export interface LeadListResponse {
  items: CrmLead[];
  total: number;
  page: number;
  page_size: number;
  status_counts: Record<string, number>;
  tab_counts: Record<string, number>;
  groups: { key: string | number | null; label: string; count: number }[] | null;
}

export interface TimelineEntry {
  id?: number;
  at: string | null;
  type: string;
  label?: string;
  outcome?: string | null;
  outcome_label?: string | null;
  old_value?: string | null;
  new_value?: string | null;
  notes?: string | null;
  user?: string;
  meta?: Record<string, unknown> | null;
}

export interface Followup {
  id: number;
  kind: string;
  due_at: string;
  reason: string | null;
  overdue?: boolean;
  status?: string;
  attempt_no: number;
  owner_user_id: number | null;
  owner_name: string | null;
  completed_at?: string | null;
  completed_by?: string | null;
  outcome?: string | null;
  lead?: {
    id: number;
    full_name: string;
    phone: string;
    city: string;
    status: string;
    status_label: string;
    stage: string;
    priority: string;
    phone_model: string | null;
    service_type: string | null;
    is_urgent: boolean;
  };
}

export interface LeadDetail {
  lead: CrmLead;
  timeline: TimelineEntry[];
  followups: Followup[];
  appointments: { id: number; scheduled_at: string; purpose: string; attendance: string; store_id: number | null; source: string }[];
}

export interface CrmAlert {
  id: number;
  kind: string;
  level: number;
  title: string;
  body: string | null;
  lead_id: number | null;
  lead_name?: string | null;
  followup_id: number | null;
  created_at: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
}

export interface AgentRow {
  user_id: number;
  name: string;
  role?: string;
  sheets: string[];
  available: boolean;
  total_leads: number;
  converted: number;
  appointments: number;
  will_visit: number;
  call_back_later: number;
  not_interested: number;
  no_status: number;
  active: number;
  calls_connected: number;
  calls_not_connected: number;
  connected_pct: number;
  conversion_pct: number;
  total_sale_amount: number;
  status_counts: Record<string, number>;
  first_calls_total?: number;
  first_calls_on_time?: number;
  first_call_pct?: number | null;
  followups_total?: number;
  followups_on_time?: number;
  followups_on_time_pct?: number | null;
  calls_logged?: number;
  calls_connected_logged?: number;
  connected_logged_pct?: number | null;
  avg_first_call_minutes?: number | null;
  previous: {
    total_leads: number;
    converted: number;
    conversion_pct: number;
    connected_pct: number;
    first_call_pct: number | null;
    followups_on_time_pct: number | null;
    calls_logged: number;
  };
  low_sample: boolean;
  below_target: { first_call: boolean; followups: boolean };
  trend?: { date: string; leads: number; converted: number; contacted: number }[];
}

export interface Targets {
  first_call_pct: number;
  followup_on_time_pct: number;
  followup_grace_minutes: number;
  low_sample_leads: number;
}

export interface QueueTiles {
  first_contact_pending: number;
  due_today: number;
  overdue: number;
  unassigned: number;
}
