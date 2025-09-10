import React, { useEffect, useMemo, useState } from "react";
import { useAuth } from "@clerk/clerk-react";
import AdminCreditsPanel, { CreditsSnapshot } from "./AdminCreditsPanel";

interface UserRow extends CreditsSnapshot {
  updated_at?: number;
  created_at?: number;
}

interface ListUsersResponse {
  total: number;
  items: UserRow[];
}

export default function AdminUsersTab() {
  const { getToken } = useAuth();
  const API_BASE = (import.meta as any).env.VITE_API_BASE || "/api";

  const [q, setQ] = useState("");
  const [limit, setLimit] = useState(25);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [rows, setRows] = useState<UserRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lowBalanceOnly, setLowBalanceOnly] = useState(false);

  const lowBalanceThresholdCents = 20; // €0.20

  const filtered = useMemo(() => {
    if (!lowBalanceOnly) return rows;
    return rows.filter(r => (r.euro_balance_cents ?? 0) < lowBalanceThresholdCents);
  }, [rows, lowBalanceOnly]);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const token = await getToken();
      const url = new URL(`${API_BASE}/admin/users`, window.location.origin);
      if (q) url.searchParams.set("q", q);
      url.searchParams.set("limit", String(limit));
      url.searchParams.set("offset", String(offset));
      const res = await fetch(url.toString(), {
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || `HTTP ${res.status}`);
      }
      const data: ListUsersResponse = await res.json();
      setRows(data.items || []);
      setTotal(data.total || 0);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, limit, offset]);

  function fmtEuroCents(cents?: number) {
    const v = (cents ?? 0) / 100;
    return new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" }).format(v);
  }

  function fmtDate(ts?: number) {
    if (!ts) return "-";
    try {
      return new Date(ts * 1000).toLocaleString();
    } catch {
      return "-";
    }
  }

  return (
    <div style={{
      background: "rgba(255, 255, 255, 0.95)",
      backdropFilter: "blur(20px)",
      borderRadius: 16,
      padding: "1.25rem",
      border: "1px solid rgba(255, 255, 255, 0.2)",
      boxShadow: "0 8px 24px rgba(0, 0, 0, 0.08)",
    }}>
      <h2 style={{ marginTop: 0 }}>Admin – Nutzer & Guthaben</h2>

      <div style={{ display: "flex", gap: "0.75rem", alignItems: "center", marginBottom: "1rem" }}>
        <input
          value={q}
          onChange={(e) => { setOffset(0); setQ(e.target.value); }}
          placeholder="Suche nach user_id oder Email..."
          style={{
            flex: 1,
            padding: "0.75rem 1rem",
            borderRadius: 8,
            border: "1px solid #e2e8f0",
            fontSize: "0.95rem",
          }}
        />
        <label style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: "0.9rem", color: "#334155" }}>
          <input type="checkbox" checked={lowBalanceOnly} onChange={(e) => setLowBalanceOnly(e.target.checked)} />
          Niedriges Guthaben (&lt; {fmtEuroCents(lowBalanceThresholdCents)})
        </label>
        <select value={limit} onChange={(e) => { setOffset(0); setLimit(parseInt(e.target.value, 10)); }} style={{ padding: "0.5rem", borderRadius: 8, border: "1px solid #e2e8f0" }}>
          <option value={10}>10</option>
          <option value={25}>25</option>
          <option value={50}>50</option>
          <option value={100}>100</option>
        </select>
      </div>

      {error && (
        <div style={{
          background: "#fef2f2",
          border: "1px solid #fecaca",
          color: "#991b1b",
          padding: "0.75rem 1rem",
          borderRadius: 8,
          marginBottom: "1rem",
        }}>{error}</div>
      )}

      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "1px solid #e5e7eb" }}>
              <th style={{ padding: "8px 6px" }}>User ID</th>
              <th style={{ padding: "8px 6px" }}>Email</th>
              <th style={{ padding: "8px 6px" }}>Guthaben</th>
              <th style={{ padding: "8px 6px" }}>Zuletzt benutzt</th>
              <th style={{ padding: "8px 6px" }}></th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={5} style={{ padding: 12 }}>Lade...</td></tr>
            ) : filtered.length === 0 ? (
              <tr><td colSpan={5} style={{ padding: 12 }}>Keine Nutzer gefunden.</td></tr>
            ) : (
              filtered.map((r) => (
                <tr key={r.user_id} style={{ borderBottom: "1px solid #f1f5f9" }}>
                  <td style={{ padding: "10px 6px", fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: "0.85rem" }}>{r.user_id}</td>
                  <td style={{ padding: "10px 6px" }}>{r.email || "-"}</td>
                  <td style={{ padding: "10px 6px", fontWeight: 600 }}>{fmtEuroCents(r.euro_balance_cents)}</td>
                  <td style={{ padding: "10px 6px", color: "#475569" }}>{fmtDate(r.updated_at)}</td>
                  <td style={{ padding: "10px 6px" }}>
                    <InlineEditCredits userId={r.user_id} email={r.email || undefined} currentCents={r.euro_balance_cents} onSaved={() => load()} />
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "1rem" }}>
        <div style={{ color: "#475569", fontSize: "0.9rem" }}>
          {Math.min(total, offset + 1)}–{Math.min(total, offset + limit)} von {total}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button disabled={offset <= 0} onClick={() => setOffset(Math.max(0, offset - limit))} style={{ padding: "6px 10px", borderRadius: 8, border: "1px solid #e2e8f0", background: "white" }}>Zurück</button>
          <button disabled={offset + limit >= total} onClick={() => setOffset(offset + limit)} style={{ padding: "6px 10px", borderRadius: 8, border: "1px solid #e2e8f0", background: "white" }}>Weiter</button>
        </div>
      </div>

      <div style={{ marginTop: "1.25rem", paddingTop: "1rem", borderTop: "1px solid #e5e7eb" }}>
        <details>
          <summary style={{ cursor: "pointer", fontWeight: 600 }}>Manuelle Änderung (Formular)</summary>
          <div style={{ marginTop: "0.75rem" }}>
            <AdminCreditsPanel onSuccess={() => load()} />
          </div>
        </details>
      </div>
    </div>
  );
}

function InlineEditCredits({ userId, email, currentCents, onSaved }: { userId: string; email?: string; currentCents: number; onSaved: () => void; }) {
  const { getToken } = useAuth();
  const API_BASE = (import.meta as any).env.VITE_API_BASE || "/api";

  const [euro, setEuro] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    setEuro(((currentCents ?? 0) / 100).toFixed(2));
  }, [currentCents]);

  async function save() {
    setBusy(true);
    setMsg(null);
    try {
      const cents = Math.round(parseFloat(euro.replace(",", ".")) * 100);
      if (Number.isNaN(cents)) throw new Error("Ungültiger Betrag");
      const token = await getToken();
      const res = await fetch(`${API_BASE}/admin/set_credits`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ user_id: userId, euro_balance_cents: cents, email })
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || `HTTP ${res.status}`);
      }
      setMsg("Gespeichert.");
      onSaved();
    } catch (e: any) {
      setMsg(e?.message || String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
      <input
        value={euro}
        onChange={(e) => setEuro(e.target.value)}
        style={{ width: 90, padding: "6px 8px", borderRadius: 6, border: "1px solid #e2e8f0" }}
      />
      <button onClick={save} disabled={busy} style={{ padding: "6px 10px", borderRadius: 8, border: 0, background: "#111827", color: "#fff", fontWeight: 600 }}>{busy ? "Speichere..." : "Speichern"}</button>
      {msg && <span style={{ fontSize: "0.85rem", color: "#475569" }}>{msg}</span>}
    </div>
  );
}
