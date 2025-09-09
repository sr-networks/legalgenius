import React, { useState } from "react";
import { useAuth } from "@clerk/clerk-react";

type CreditsSnapshot = {
  user_id: string;
  email?: string | null;
  euro_balance_cents: number;
  total_spent_cents: number;
  total_in_used: number;
  total_out_used: number;
};

export default function AdminCreditsPanel({ onSuccess }: { onSuccess: (cr: { euro_balance_cents: number }) => void }) {
  const { getToken } = useAuth();
  const [userId, setUserId] = useState("");
  const [email, setEmail] = useState("");
  const [euro, setEuro] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const API_BASE = (import.meta as any).env.VITE_API_BASE || "/api";

  async function submit() {
    setBusy(true);
    setMsg(null);
    try {
      const token = await getToken();
      const res = await fetch(`${API_BASE}/admin/set_credits`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          user_id: userId.trim(),
          email: email.trim() || undefined,
          euro_balance_cents: euro === "" ? undefined : Math.round(parseFloat(euro.replace(",", ".")) * 100),
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      const cr: CreditsSnapshot = data?.credits;
      setMsg("Guthaben aktualisiert.");
      if (cr) {
        onSuccess({ euro_balance_cents: cr.euro_balance_cents });
      }
    } catch (e: any) {
      setMsg(e?.message || String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{
      background: "#fff",
      border: "1px solid #e2e8f0",
      borderRadius: 12,
      padding: "1rem",
    }}>
      <div style={{ marginBottom: "0.5rem", fontWeight: 700 }}>Admin: Credits verwalten</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem", marginBottom: "0.75rem" }}>
        <div>
          <label style={{ fontSize: 12, color: "#64748b" }}>User ID</label>
          <input value={userId} onChange={e => setUserId(e.target.value)} placeholder="user_..." style={{ width: "100%", padding: 8, border: "1px solid #e2e8f0", borderRadius: 8 }} />
        </div>
        <div>
          <label style={{ fontSize: 12, color: "#64748b" }}>Email (optional)</label>
          <input value={email} onChange={e => setEmail(e.target.value)} placeholder="user@example.com" style={{ width: "100%", padding: 8, border: "1px solid #e2e8f0", borderRadius: 8 }} />
        </div>
        <div>
          <label style={{ fontSize: 12, color: "#64748b" }}>Guthaben (EUR)</label>
          <input value={euro} onChange={e => setEuro(e.target.value)} placeholder="z.B. 10.00" style={{ width: "100%", padding: 8, border: "1px solid #e2e8f0", borderRadius: 8 }} />
        </div>
      </div>
      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
        <button onClick={submit} disabled={busy || !userId.trim()} style={{ padding: "0.5rem 0.9rem", background: "#111827", color: "#fff", borderRadius: 8, border: 0, fontWeight: 600 }}>
          {busy ? "Speichern..." : "Speichern"}
        </button>
        {msg && <div style={{ color: msg.includes("HTTP") ? "#dc2626" : "#059669" }}>{msg}</div>}
      </div>
    </div>
  );
}
