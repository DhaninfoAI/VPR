export type Flag = "Yes" | "No" | "Unclear" | "Error";

export interface RuleData {
  jurisdiction_name: string;
  vacant_registration_required: string;
  foreclosure_registration_required: string;
  applies_in_incorporated_areas: string;
  registration_trigger: string | null;
  who_must_register: string | null;
  registration_deadline: string | null;
  ordinance_name: string | null;
  ordinance_url: string | null;
  registration_form_url: string | null;
  registration_portal_url: string | null;
  registration_method: string;
  third_party_platform: string | null;
  registration_fee: string | null;
  renewal_fee: string | null;
  renewal_frequency: string | null;
  additional_links?: { label: string; url: string }[];
  documents_required: string[];
  other_requirements: string[];
  penalties: string | null;
  contact_info: string | null;
  summary: string;
  confidence: string;
  confidence_reason: string;
  source_urls: string[];
}

export interface Rule {
  rule_id: number;
  status: string;
  researched_at: string;
  model: string | null;
  data: RuleData | null;
  sources: { url: string; title: string | null }[];
  link_checks: Record<string, { state: string; status: number | null }>;
  from_cache: boolean;
  error: string | null;
}

export interface LevelEntry {
  level: "city" | "county" | "state";
  jurisdiction: string | null;
  flag: Flag;
  reason: string | null;
  rule: Rule | null;
}

export interface LookupInput {
  address: string;
  city: string;
  state: string;
  zip: string;
  county?: string | null;
}

export interface Lookup {
  id: string;
  status: "pending" | "running" | "done" | "error";
  progress: string | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  input: LookupInput;
  geocode?: {
    source: string;
    matched_address: string | null;
    county: { name: string; full_name: string } | null;
    municipality: { name: string; label: string; kind: string } | null;
  } | null;
  result?: {
    columns: string[];
    row: Record<string, string>;
    levels: Record<"city" | "county" | "state", LevelEntry>;
  } | null;
  summary?: Record<string, string>;
}

export interface Health {
  db: string;
  openai_key_configured: boolean;
  model: string;
  cache_ttl_days: number;
}

export interface SavedRule {
  jurisdiction: string;
  level: string;
  state: string;
  vacant_required: string | null;
  foreclosure_required: string | null;
  registration_fee: string | null;
  ordinance_url: string | null;
  form_url: string | null;
  confidence: string | null;
  status: string;
  researched_at: string;
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const body = await r.json();
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new Error(msg);
  }
  return r.json();
}

export const api = {
  health: () => req<Health>("api/health"),
  states: () => req<{ code: string; name: string }[]>("api/states"),
  create: (body: LookupInput & { force_refresh: boolean }) =>
    req<{ id: string }>("api/lookups", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  get: (id: string) => req<Lookup>(`api/lookups/${id}`),
  list: () => req<Lookup[]>("api/lookups?limit=50"),
  jurisdictions: (state?: string) =>
    req<SavedRule[]>(`api/jurisdictions${state ? `?state=${state}` : ""}`),
};
