import { useEffect, useMemo, useRef, useState } from "react";
import { api, Flag, LevelEntry, Lookup, Rule, RuleData, SavedRule } from "./api";
import { Icon } from "./icons";

type Page = "lookup" | "history" | "saved";

const NAV: { id: Page; label: string; icon: string }[] = [
  { id: "lookup", label: "New lookup", icon: "search" },
  { id: "history", label: "History", icon: "clock" },
  { id: "saved", label: "Jurisdictions", icon: "map" },
];

export default function App() {
  const [page, setPage] = useState<Page>("lookup");
  const [openId, setOpenId] = useState<string | null>(() => location.hash.match(/^#\/lookup\/(.+)$/)?.[1] ?? null);

  useEffect(() => {
    if (openId) history.replaceState(null, "", `#/lookup/${openId}`);
  }, [openId]);

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="mark">V</div>
          <div>
            <div className="brand-name">VPR Desk</div>
            <div className="brand-sub">Registration lookup</div>
          </div>
        </div>
        <nav className="nav">
          {NAV.map((n) => (
            <button key={n.id} className={page === n.id ? "active" : ""} onClick={() => setPage(n.id)}>
              <Icon name={n.icon} />
              {n.label}
            </button>
          ))}
        </nav>
        <div className="theme-wrap">
          <ThemeSwitch />
        </div>
      </aside>

      <div className="main">
        {page === "lookup" && <LookupPage openId={openId} setOpenId={setOpenId} />}
        {page === "history" && (
          <HistoryPage
            onOpen={(id) => {
              setOpenId(id);
              setPage("lookup");
            }}
          />
        )}
        {page === "saved" && <SavedPage />}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ theme */

type Theme = "system" | "light" | "dark";
const THEME_KEY = "vpr-theme";

function readTheme(): Theme {
  try {
    const t = localStorage.getItem(THEME_KEY);
    return t === "light" || t === "dark" ? t : "system";
  } catch {
    return "system";
  }
}

function applyTheme(t: Theme) {
  const root = document.documentElement;
  if (t === "system") delete root.dataset.theme;
  else root.dataset.theme = t;
}

applyTheme(readTheme()); // before first paint, so there is no flash of the wrong theme

function ThemeSwitch() {
  const [theme, setTheme] = useState<Theme>(readTheme);
  useEffect(() => {
    applyTheme(theme);
    try {
      if (theme === "system") localStorage.removeItem(THEME_KEY);
      else localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* storage unavailable - theme still applies for this visit */
    }
  }, [theme]);
  const opts: { id: Theme; icon: string; label: string }[] = [
    { id: "system", icon: "monitor", label: "Auto" },
    { id: "light", icon: "sun", label: "Light" },
    { id: "dark", icon: "moon", label: "Dark" },
  ];
  return (
    <div className="theme-switch" role="radiogroup" aria-label="Color theme">
      {opts.map((o) => (
        <button
          key={o.id}
          type="button"
          role="radio"
          aria-checked={theme === o.id}
          title={`${o.label} theme`}
          className={theme === o.id ? "active" : ""}
          onClick={() => setTheme(o.id)}
        >
          <Icon name={o.icon} size={14} />
          <span className="label">{o.label}</span>
        </button>
      ))}
    </div>
  );
}


function PageHead({ title, sub, actions }: { title: string; sub: string; actions?: React.ReactNode }) {
  return (
    <header className="page-head">
      <div>
        <h1>{title}</h1>
        <p>{sub}</p>
      </div>
      {actions && <div className="head-actions">{actions}</div>}
    </header>
  );
}

/* ------------------------------------------------------------------ badges */

const FLAG_TEXT: Record<Flag, string> = { Yes: "Required", No: "Not required", Unclear: "Needs review", Error: "Failed" };

function Badge({ flag, children }: { flag: string; children?: React.ReactNode }) {
  const tone = ({ Yes: "red", No: "green", Unclear: "amber", Error: "gray" } as Record<string, string>)[flag] ?? "gray";
  return <span className={`badge ${tone}`}>{children ?? FLAG_TEXT[flag as Flag] ?? flag}</span>;
}

/* ------------------------------------------------------------------ lookup */

function LookupPage({ openId, setOpenId }: { openId: string | null; setOpenId: (id: string) => void }) {
  const [states, setStates] = useState<{ code: string; name: string }[]>([]);
  const [form, setForm] = useState({ address: "", city: "", state: "", zip: "", county: "", force_refresh: false });
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [lookup, setLookup] = useState<Lookup | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    api.states().then(setStates).catch(() => {});
  }, []);

  useEffect(() => {
    if (!openId) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const lk = await api.get(openId);
        if (cancelled) return;
        setLookup(lk);
        if (lk.status === "pending" || lk.status === "running") timer.current = window.setTimeout(poll, 2000);
      } catch (e: any) {
        if (!cancelled) setErr(e.message);
      }
    };
    poll();
    return () => {
      cancelled = true;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [openId]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    setSubmitting(true);
    try {
      const { id } = await api.create({ ...form, county: form.county || null });
      setLookup(null);
      setOpenId(id);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm({ ...form, [k]: e.target.type === "checkbox" ? (e.target as HTMLInputElement).checked : e.target.value });

  const busy = !!lookup && (lookup.status === "pending" || lookup.status === "running");

  return (
    <>
      <PageHead
        title="New lookup"
        sub="Check vacant and foreclosure property registration requirements for any US address."
      />

      <form className="panel search-panel" onSubmit={submit}>
        <div className="fields">
          <Field label="Street address" className="span-2">
            <input required value={form.address} onChange={set("address")} placeholder="123 Main St" />
          </Field>
          <Field label="City">
            <input required value={form.city} onChange={set("city")} placeholder="Springfield" />
          </Field>
          <Field label="State">
            <select required value={form.state} onChange={set("state")}>
              <option value="">Select state</option>
              {states.map((s) => (
                <option key={s.code} value={s.code}>
                  {s.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="ZIP">
            <input value={form.zip} onChange={set("zip")} placeholder="12345" inputMode="numeric" maxLength={10} />
          </Field>
          <Field label="County" hint="Optional">
            <input value={form.county} onChange={set("county")} placeholder="Auto-detected" />
          </Field>
        </div>
        <div className="search-foot">
          <label className="toggle">
            <input type="checkbox" checked={form.force_refresh} onChange={set("force_refresh")} />
            <span>Ignore saved rules and research again</span>
          </label>
          <button className="btn primary" disabled={submitting || busy}>
            <Icon name="search" />
            {busy ? "Lookup running…" : submitting ? "Starting…" : "Run lookup"}
          </button>
        </div>
        {err && <div className="alert">{err}</div>}
      </form>

      {!lookup && !openId && <EmptyState />}
      {lookup && <LookupView lookup={lookup} />}
    </>
  );
}

function Field({ label, hint, className, children }: { label: string; hint?: string; className?: string; children: React.ReactNode }) {
  return (
    <label className={`field ${className ?? ""}`}>
      <span className="field-label">
        {label}
        {hint && <span className="field-hint">{hint}</span>}
      </span>
      {children}
    </label>
  );
}

function EmptyState() {
  const items = [
    { icon: "pin", t: "Real jurisdiction", d: "The address is matched with the US Census to find the true county and city limits." },
    { icon: "file", t: "Everything to register", d: "Ordinance, form link, fees, renewal, deadline and the full documents checklist." },
    { icon: "database", t: "Saved for next time", d: "Each city, county and state is researched once and reused for 3 days." },
  ];
  return (
    <div className="feature-grid">
      {items.map((i) => (
        <div key={i.t} className="panel feature">
          <div className="feature-icon">
            <Icon name={i.icon} size={18} />
          </div>
          <h3>{i.t}</h3>
          <p>{i.d}</p>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ progress */

interface Steps {
  phase: string;
  jurisdictions: { key: string; name: string; level: string; state: string }[];
}

function parseSteps(p: string | null): Steps | null {
  if (!p) return null;
  try {
    return JSON.parse(p);
  } catch {
    return null;
  }
}

function Elapsed({ since }: { since: string }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const s = Math.max(0, Math.round((now - new Date(since).getTime()) / 1000));
  return <>{Math.floor(s / 60)}:{String(s % 60).padStart(2, "0")}</>;
}

function StepIcon({ state }: { state: string }) {
  if (state === "running" || state === "researching") return <span className="step-icon spin" />;
  if (state === "done" || state === "cached")
    return (
      <span className="step-icon done">
        <Icon name="check" size={12} />
      </span>
    );
  if (state === "error")
    return (
      <span className="step-icon fail">
        <Icon name="x" size={12} />
      </span>
    );
  return <span className="step-icon wait" />;
}

function ProgressView({ lookup }: { lookup: Lookup }) {
  const steps = parseSteps(lookup.progress);
  const geocoded = !!steps && steps.phase !== "geocoding";
  const stateText: Record<string, string> = {
    waiting: "Queued",
    researching: "Researching the web – usually 1–3 minutes",
    cached: "Used saved rule",
    skipped: "Not reviewed – foreclosure registration found at a more local level",
    done: "Researched",
    error: "Research failed",
  };
  return (
    <div className="panel">
      <div className="panel-head">
        <div>
          <div className="overline">Lookup in progress</div>
          <h2>{fullAddress(lookup)}</h2>
        </div>
        <span className="muted mono">
          <Elapsed since={lookup.created_at} />
        </span>
      </div>
      <ol className="steps">
        <li>
          <StepIcon state={geocoded ? "done" : "running"} />
          <div>
            <div className="step-title">Match address with US Census</div>
            <div className="step-sub">Find the county and whether the property is inside city limits</div>
          </div>
        </li>
        {steps?.jurisdictions.map((j) => (
          <li key={j.key}>
            <StepIcon state={j.state} />
            <div>
              <div className="step-title">{j.name}</div>
              <div className="step-sub">{stateText[j.state] ?? j.state}</div>
            </div>
          </li>
        ))}
        <li>
          <StepIcon state="waiting" />
          <div>
            <div className="step-title">Prepare notes and sheet row</div>
          </div>
        </li>
      </ol>
    </div>
  );
}

/* ------------------------------------------------------------------ result */

function fullAddress(l: Lookup) {
  const i = l.input;
  return `${i.address}, ${i.city}, ${i.state}${i.zip ? " " + i.zip : ""}`;
}

const LEVEL_LABEL = { city: "City / Town", county: "County", state: "State" };

function LookupView({ lookup }: { lookup: Lookup }) {
  const [tab, setTab] = useState<string>("overview");
  useEffect(() => setTab("overview"), [lookup.id]);

  if (lookup.status === "pending" || lookup.status === "running") return <ProgressView lookup={lookup} />;
  if (lookup.status === "error") {
    return (
      <div className="panel">
        <div className="overline">Lookup failed</div>
        <h2>{fullAddress(lookup)}</h2>
        <div className="alert">{lookup.error}</div>
      </div>
    );
  }

  const res = lookup.result!;
  const geo = lookup.geocode;
  const levels = (["city", "county", "state"] as const).map((l) => res.levels[l]);
  const tabs = levels.filter((e) => e.rule);

  return (
    <div className="result">
      <div className="panel">
        <div className="panel-head">
          <div>
            <div className="overline">Property</div>
            <h2 className="address">{fullAddress(lookup)}</h2>
            <div className="meta">
              {geo?.source === "census" ? (
                <span className="meta-item verified">
                  <Icon name="check" size={13} /> Census verified
                </span>
              ) : (
                <span className="meta-item warn">Not geocoded – used entered county</span>
              )}
              {geo?.county && <span className="meta-item">{geo.county.full_name}</span>}
              <span className="meta-item">
                {geo?.municipality ? `${geo.municipality.label} of ${geo.municipality.name}` : "Unincorporated area"}
              </span>
              <span className="meta-item">Confidence: {res.row["Confidence"]}</span>
            </div>
          </div>
          <div className="head-actions">
            <CopyButton text={res.row["Notes"]} label="Copy notes" />
            <a className="btn" href={`api/lookups/${lookup.id}/export.xlsx`}>
              <Icon name="download" /> Excel
            </a>
          </div>
        </div>

        <div className="metrics">
          {levels.map((e) => (
            <Metric key={e.level} entry={e} />
          ))}
        </div>
      </div>

      <div className="tabbar">
        <button className={tab === "overview" ? "active" : ""} onClick={() => setTab("overview")}>
          Overview
        </button>
        {tabs.map((e) => (
          <button key={e.level} className={tab === e.level ? "active" : ""} onClick={() => setTab(e.level)}>
            <span className={`tab-dot ${e.flag.toLowerCase()}`} />
            {e.jurisdiction}
          </button>
        ))}
        <button className={tab === "row" ? "active" : ""} onClick={() => setTab("row")}>
          Sheet row
        </button>
      </div>

      {tab === "overview" && <Overview res={res} levels={levels} />}
      {tab === "row" && (
        <div className="panel">
          <dl className="desc">
            {res.columns.map((c) => (
              <Row key={c} k={c} v={res.row[c]} />
            ))}
          </dl>
        </div>
      )}
      {tabs.map((e) => tab === e.level && <LevelDetail key={e.level} entry={e} />)}
    </div>
  );
}

function Metric({ entry }: { entry: LevelEntry }) {
  const d = entry.rule?.data;
  const type = d
    ? [d.vacant_registration_required === "Yes" && "Vacant", d.foreclosure_registration_required === "Yes" && "Foreclosure"]
        .filter(Boolean)
        .join(" + ")
    : "";
  const sub =
    entry.flag === "Yes"
      ? [type, d?.registration_fee].filter(Boolean).join(" · ")
      : entry.flag === "No" && entry.reason
        ? entry.reason
        : "";
  return (
    <div className="metric">
      <div className="metric-label">{LEVEL_LABEL[entry.level]}</div>
      <div className="metric-name">{entry.jurisdiction ?? "Not applicable"}</div>
      <Badge flag={entry.flag} />
      {sub && <div className="metric-sub">{sub}</div>}
    </div>
  );
}

function Overview({ res, levels }: { res: NonNullable<Lookup["result"]>; levels: LevelEntry[] }) {
  const required = levels.filter((e) => e.flag === "Yes" && e.rule?.data);
  return (
    <div className="overview">
      <div className="panel">
        <div className="panel-head tight">
          <h3>Operator notes</h3>
          <CopyButton text={res.row["Notes"]} label="Copy" small />
        </div>
        <div className="notes">
          <Linkify text={res.row["Notes"]} />
        </div>
      </div>

      {required.length === 0 && (
        <div className="panel">
          <h3>No registration required</h3>
          <p className="muted">
            None of the jurisdictions covering this address require vacant or foreclosure registration. Open the
            jurisdiction tabs to see the ordinance checked and the sources.
          </p>
        </div>
      )}

      {required.map((e) => {
        const d = e.rule!.data!;
        return (
          <div className="panel" key={e.level}>
            <div className="panel-head tight">
              <div>
                <div className="overline">{LEVEL_LABEL[e.level]} requirement</div>
                <h3>{e.jurisdiction}</h3>
              </div>
              <Badge flag="Yes" />
            </div>
            <div className="two-col">
              <dl className="desc">
                <Row k="Registration fee" v={d.registration_fee} />
                <Row k="Renewal" v={[d.renewal_fee, d.renewal_frequency].filter(Boolean).join(" · ")} />
                <Row k="Deadline" v={d.registration_deadline} />
                <Row k="Required when" v={d.requirement_conditions || d.registration_trigger} />
                <Row k="How to register" v={method(d)} />
              </dl>
              <div className="links">
                <LinkCard label="Ordinance" sub={d.ordinance_name} url={d.ordinance_url} checks={e.rule!.link_checks} />
                <LinkCard label="Registration form" url={d.registration_form_url} checks={e.rule!.link_checks} />
                <LinkCard label="Registration portal" url={d.registration_portal_url} checks={e.rule!.link_checks} />
                {(d.additional_links ?? []).map((l) => (
                  <LinkCard key={l.url} label={l.label} url={l.url} checks={e.rule!.link_checks} />
                ))}
              </div>
            </div>
            {d.documents_required.length > 0 && <Checklist title="Documents required" items={d.documents_required} />}
          </div>
        );
      })}
    </div>
  );
}

function method(d: RuleData) {
  return d.registration_method + (d.third_party_platform ? ` – ${d.third_party_platform}` : "");
}

function Checklist({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="checklist">
      <div className="section-title">
        {title} <span className="count">{items.length}</span>
      </div>
      <ul>
        {items.map((x, i) => (
          <li key={i}>
            <span className="check-box">
              <Icon name="check" size={11} />
            </span>
            <span>{x}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function LevelDetail({ entry }: { entry: LevelEntry }) {
  const r = entry.rule!;
  const d = r.data;
  return (
    <div className="panel">
      <div className="panel-head tight">
        <div>
          <div className="overline">{LEVEL_LABEL[entry.level]}</div>
          <h3>{entry.jurisdiction}</h3>
          <div className="muted small">
            {r.from_cache ? "Saved rule" : "Researched now"} · {new Date(r.researched_at).toLocaleString()}
            {r.model ? ` · ${r.model}` : ""}
          </div>
        </div>
        <Badge flag={entry.flag} />
      </div>
      {entry.reason && <div className="callout">{entry.reason}</div>}
      {r.error && <div className="alert">{r.error}</div>}
      {d && (
        <>
          <p className="summary">{d.summary}</p>
          <div className="two-col">
            <dl className="desc">
              <Row k="Vacant registration" v={d.vacant_registration_required} />
              <Row k="Foreclosure registration" v={d.foreclosure_registration_required} />
              {entry.level === "county" && <Row k="Applies inside cities" v={d.applies_in_incorporated_areas} />}
              <Row k="Required when" v={d.requirement_conditions} />
              <Row k="Trigger" v={d.registration_trigger} />
              <Row k="Who must register" v={d.who_must_register} />
              <Row k="Deadline" v={d.registration_deadline} />
              <Row k="How to register" v={method(d)} />
              <Row k="Registration fee" v={d.registration_fee} />
              <Row k="Renewal" v={[d.renewal_fee, d.renewal_frequency].filter(Boolean).join(" · ")} />
              <Row k="Penalties" v={d.penalties} />
              <Row k="Contact" v={d.contact_info} />
            </dl>
            <div className="links">
              <LinkCard label="Ordinance" sub={d.ordinance_name} url={d.ordinance_url} checks={r.link_checks} />
              <LinkCard label="Registration form" url={d.registration_form_url} checks={r.link_checks} />
              <LinkCard label="Registration portal" url={d.registration_portal_url} checks={r.link_checks} />
              {(d.additional_links ?? []).map((l) => (
                <LinkCard key={l.url} label={l.label} url={l.url} checks={r.link_checks} />
              ))}
            </div>
          </div>
          {d.documents_required.length > 0 && <Checklist title="Documents required" items={d.documents_required} />}
          {d.other_requirements.length > 0 && (
            <div className="checklist">
              <div className="section-title">Ongoing requirements</div>
              <ul className="plain">
                {d.other_requirements.map((x, i) => (
                  <li key={i}>{x}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="callout subtle">
            <strong>Confidence: {d.confidence}.</strong> {d.confidence_reason}
          </div>
          <div className="checklist">
            <div className="section-title">Sources</div>
            <ul className="sources">
              {Array.from(new Set([...d.source_urls, ...r.sources.map((s) => s.url)])).map((u) => (
                <li key={u}>
                  <a href={u} target="_blank" rel="noreferrer">
                    {u}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </div>
  );
}

function Row({ k, v }: { k: string; v: string | null | undefined }) {
  if (!v) return null;
  return (
    <div className="desc-row">
      <dt>{k}</dt>
      <dd>
        <Linkify text={String(v)} />
      </dd>
    </div>
  );
}

function LinkCard({ label, sub, url, checks }: { label: string; sub?: string | null; url: string | null; checks: Rule["link_checks"] }) {
  if (!url) return null;
  const c = checks[url];
  const state = c?.state;
  const text = !c ? null : state === "ok" ? "Link works" : state === "blocked" ? "Site blocks automatic checks" : state === "unreachable" ? "Site did not respond to check" : `Link problem (${c.status})`;
  return (
    <a className="link-card" href={url} target="_blank" rel="noreferrer">
      <div className="link-top">
        <span className="link-label">{label}</span>
        <Icon name="external" size={14} />
      </div>
      {sub && <div className="link-sub">{sub}</div>}
      <div className="link-url">{url.replace(/^https?:\/\//, "")}</div>
      {text && <span className={`link-check ${state}`}>{text}</span>}
    </a>
  );
}

function Linkify({ text }: { text: string }) {
  const parts = text.split(/(https?:\/\/[^\s]+)/g);
  return (
    <span className="pre">
      {parts.map((p, i) =>
        /^https?:\/\//.test(p) ? (
          <a key={i} href={p} target="_blank" rel="noreferrer">
            {p}
          </a>
        ) : (
          p
        )
      )}
    </span>
  );
}

function CopyButton({ text, label, small }: { text: string; label: string; small?: boolean }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className={`btn ${small ? "sm" : ""}`}
      onClick={() =>
        navigator.clipboard.writeText(text).then(() => {
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        })
      }
    >
      <Icon name={done ? "check" : "copy"} />
      {done ? "Copied" : label}
    </button>
  );
}

/* ------------------------------------------------------------------ history */

function HistoryPage({ onOpen }: { onOpen: (id: string) => void }) {
  const [rows, setRows] = useState<Lookup[] | null>(null);
  const [q, setQ] = useState("");
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.list().then(setRows).catch((e) => setErr(e.message));
  }, []);
  const filtered = useMemo(
    () => (rows ?? []).filter((r) => fullAddress(r).toLowerCase().includes(q.toLowerCase())),
    [rows, q]
  );
  return (
    <>
      <PageHead
        title="History"
        sub="Every address looked up. Click a row to open the result."
        actions={
          <a className="btn" href="api/export.xlsx">
            <Icon name="download" /> Export all
          </a>
        }
      />
      <div className="panel flush">
        <div className="table-tools">
          <div className="search-input">
            <Icon name="search" />
            <input placeholder="Search address" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <span className="muted small">{filtered.length} lookups</span>
        </div>
        {err && <div className="alert m">{err}</div>}
        <div className="scroll">
          <table className="table">
            <thead>
              <tr>
                <th>Property</th>
                <th>County</th>
                <th>City wise</th>
                <th>County wise</th>
                <th>State wise</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr key={r.id} onClick={() => onOpen(r.id)} className="clickable">
                  <td className="strong">{fullAddress(r)}</td>
                  <td>{r.summary?.["County"] || "—"}</td>
                  {r.status === "done" ? (
                    <>
                      <td><Badge flag={r.summary?.["City Wise"] ?? ""} /></td>
                      <td><Badge flag={r.summary?.["County Wise"] ?? ""} /></td>
                      <td><Badge flag={r.summary?.["State Wise"] ?? ""} /></td>
                    </>
                  ) : (
                    <td colSpan={3}>
                      <Badge flag={r.status === "error" ? "Error" : "Unclear"}>
                        {r.status === "error" ? "Failed" : "Running"}
                      </Badge>
                    </td>
                  )}
                  <td className="muted nowrap">{new Date(r.created_at).toLocaleString()}</td>
                </tr>
              ))}
              {rows && filtered.length === 0 && (
                <tr>
                  <td colSpan={6} className="empty-row">No lookups yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ saved */

function SavedPage() {
  const [rows, setRows] = useState<SavedRule[] | null>(null);
  const [q, setQ] = useState("");
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.jurisdictions().then(setRows).catch((e) => setErr(e.message));
  }, []);
  const filtered = useMemo(
    () => (rows ?? []).filter((r) => `${r.jurisdiction} ${r.state}`.toLowerCase().includes(q.toLowerCase())),
    [rows, q]
  );
  const yn = (v: string | null) =>
    v === "Yes" ? <Badge flag="Yes" /> : v === "No" ? <Badge flag="No" /> : v ? <Badge flag="Unclear" /> : "—";
  return (
    <>
      <PageHead
        title="Jurisdictions"
        sub="Every state, county and city researched so far – the start of your nationwide VPR database."
      />
      <div className="panel flush">
        <div className="table-tools">
          <div className="search-input">
            <Icon name="search" />
            <input placeholder="Search jurisdiction or state" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <span className="muted small">{filtered.length} saved</span>
        </div>
        {err && <div className="alert m">{err}</div>}
        <div className="scroll">
          <table className="table">
            <thead>
              <tr>
                <th>Jurisdiction</th>
                <th>Level</th>
                <th>Vacant</th>
                <th>Foreclosure</th>
                <th>Fee</th>
                <th>Confidence</th>
                <th>Researched</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r, i) => (
                <tr key={i}>
                  <td className="strong">
                    {r.jurisdiction}, {r.state}
                  </td>
                  <td className="cap">{r.level}</td>
                  <td>{yn(r.vacant_required)}</td>
                  <td>{yn(r.foreclosure_required)}</td>
                  <td className="clip">{r.registration_fee || "—"}</td>
                  <td>{r.confidence ?? "—"}</td>
                  <td className="muted nowrap">{new Date(r.researched_at).toLocaleDateString()}</td>
                  <td>
                    {r.ordinance_url && (
                      <a className="icon-link" href={r.ordinance_url} target="_blank" rel="noreferrer" title="Open ordinance">
                        <Icon name="external" />
                      </a>
                    )}
                  </td>
                </tr>
              ))}
              {rows && filtered.length === 0 && (
                <tr>
                  <td colSpan={8} className="empty-row">Nothing saved yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
