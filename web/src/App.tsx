import React, { useState } from "react";

const API_BASE = "http://127.0.0.1:8000";

export default function App() {
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function ask() {
    setLoading(true);
    setError(null);
    setAnswer(null);
    try {
      const res = await fetch(`${API_BASE}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setAnswer(data.answer ?? "");
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ maxWidth: 900, margin: "2rem auto", fontFamily: "Inter, system-ui, Arial" }}>
      <h1 style={{ marginBottom: 8 }}>LegalGenius</h1>
      <p style={{ color: "#666", marginTop: 0 }}>Ask a question about German law. The backend will search the local corpus.</p>

      <textarea
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        rows={6}
        style={{ width: "100%", padding: 12, fontSize: 14, lineHeight: 1.4 }}
        placeholder="Geben Sie Ihre Frage ein…"
      />
      <div style={{ display: "flex", gap: 12, marginTop: 12 }}>
        <button onClick={ask} disabled={loading || !query.trim()} style={{ padding: "10px 16px" }}>
          {loading ? "Bitte warten…" : "Frage stellen"}
        </button>
        <button onClick={() => { setQuery(""); setAnswer(null); setError(null); }} disabled={loading}>
          Zurücksetzen
        </button>
      </div>

      {error && (
        <div style={{ marginTop: 16, color: "#b00020" }}>Fehler: {error}</div>
      )}

      {answer !== null && (
        <div style={{ marginTop: 24 }}>
          <h3>Antwort</h3>
          <pre style={{ whiteSpace: "pre-wrap" }}>{answer}</pre>
        </div>
      )}
    </div>
  );
}
