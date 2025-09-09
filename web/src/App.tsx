import React, { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ReasoningTraceBox from "./components/ReasoningTraceBox";
import TokenCounter from "./components/TokenCounter";
import { SignedIn, SignedOut, SignInButton, UserButton, useAuth, useUser } from "@clerk/clerk-react";
import CreditBadge from "./components/CreditBadge";
import AdminCreditsPanel from "./components/AdminCreditsPanel";

// Use Vite environment variables for API base URL
const API_BASE = import.meta.env.VITE_API_BASE || '/api';

export default function App() {
  const { getToken, isSignedIn } = useAuth();
  const { user } = useUser();
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [steps, setSteps] = useState<any[]>([]);
  const controllerRef = useRef<AbortController | null>(null);
  const logRef = useRef<HTMLDivElement | null>(null);
  
  // Token tracking state
  const [totalTokensSent, setTotalTokensSent] = useState(0);
  const [totalTokensReceived, setTotalTokensReceived] = useState(0);
  // Credits and admin state
  const [credits, setCredits] = useState<{ euro_balance_cents: number } | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);

  // Fetch my profile and credits when signed in
  useEffect(() => {
    if (!isSignedIn) return;
    (async () => {
      try {
        const token = await getToken();
        if (!token) return;
        const meRes = await fetch(`${API_BASE}/me`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (meRes.ok) {
          const me = await meRes.json();
          setIsAdmin(!!me?.is_admin);
        }
        const crRes = await fetch(`${API_BASE}/me/credits`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (crRes.ok) {
          const cr = await crRes.json();
          setCredits({
            euro_balance_cents: cr?.credits?.euro_balance_cents ?? 0,
          });
        }
      } catch (e) {
        // ignore
      }
    })();
  }, [isSignedIn, getToken]);

  async function ask() {
    setLoading(true);
    setError(null);
    setAnswer(null);
    setSteps([]);
    try {
      const controller = new AbortController();
      controllerRef.current = controller;
      const token = await getToken();
      const res = await fetch(`${API_BASE}/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ query }),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || `HTTP ${res.status}`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || ""; // keep last partial chunk
        for (const part of parts) {
          const lines = part.split("\n");
          for (const line of lines) {
            if (!line.startsWith("data:")) continue;
            const payload = line.slice(5).trim();
            if (!payload) continue;
            let evt: any;
            try {
              evt = JSON.parse(payload);
            } catch {
              continue;
            }
            const t = evt.type;
            console.log("Received event:", t, evt); // Debug logging
            if (t === "final_answer") {
              setAnswer(evt.message || "");
            } else if (t === "error") {
              setError(evt.message || "Unbekannter Fehler");
            }
            // Collect reasoning/tool traces
            if (t === "thinking" || t === "step" || t === "tool_thinking" || t === "tool_event" || t === "reasoning") {
              setSteps((prev) => [...prev, evt]);
            }
            // Track token usage
            if (t === "token_usage") {
              console.log("Token usage event:", evt.tokens_sent, "sent,", evt.tokens_received, "received");
              setTotalTokensSent((prev) => prev + (evt.tokens_sent || 0));
              setTotalTokensReceived((prev) => prev + (evt.tokens_received || 0));
            }
            if (t === "credits") {
              const cr = evt.credits;
              if (cr) {
                setCredits({ euro_balance_cents: cr.euro_balance_cents ?? 0 });
              }
            }
            if (t === "complete") {
              setLoading(false);
            }
          }
        }
      }
    } catch (e: any) {
      if (e?.name === 'AbortError') {
        // user aborted; no error toast
      } else {
        // Fallback to non-streaming endpoint (works better behind some proxies like ngrok)
        try {
          const token = await getToken();
          const res2 = await fetch(`${API_BASE}/ask`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            body: JSON.stringify({ query }),
            signal: controllerRef.current?.signal,
          });
          if (!res2.ok) {
            const data2 = await res2.json().catch(() => ({}));
            throw new Error(data2?.detail || `HTTP ${res2.status}`);
          }
          const data = await res2.json();
          setAnswer(data?.answer ?? "");
          // Update credits if backend returned snapshot
          if (data?.credits) {
            setCredits({
              euro_balance_cents: data.credits.euro_balance_cents ?? 0,
            });
          }
        } catch (e2: any) {
          setError(e2?.message || String(e2));
        }
      }
    } finally {
      setLoading(false);
      controllerRef.current = null;
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !loading && query.trim()) {
      ask();
    }
  };

  return (
    <div style={{
      minHeight: "100vh",
      background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
      padding: "0",
      fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    }}>
      {/* Header */}
      <div style={{
        background: "rgba(255, 255, 255, 0.95)",
        backdropFilter: "blur(20px)",
        borderBottom: "1px solid rgba(255, 255, 255, 0.2)",
        padding: "1.5rem 0",
        position: "sticky",
        top: 0,
        zIndex: 100,
        boxShadow: "0 8px 32px rgba(0, 0, 0, 0.1)"
      }}>
        <div style={{
          maxWidth: "1200px",
          margin: "0 auto",
          padding: "0 2rem",
          display: "flex",
          alignItems: "center",
          gap: "1rem",
          justifyContent: "space-between"
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
            <div style={{
              width: "48px",
              height: "48px",
              background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
              borderRadius: "12px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: "36px",
              boxShadow: "0 4px 16px rgba(102, 126, 234, 0.3)"
            }}>⚖</div>
            <div>
              <h1 style={{
                margin: 0,
                fontSize: "2rem",
                fontWeight: 700,
                background: "linear-gradient(135deg, #2c3e50 0%, #34495e 100%)",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                letterSpacing: "-0.02em"
              }}>LegalGenius – beta testing</h1>
              <p style={{
                margin: "0.25rem 0 0 0",
                color: "#64748b",
                fontSize: "0.95rem",
                fontWeight: 500
              }}>Intelligente Recherche im deutschen Recht</p>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <SignedIn>
              <CreditBadge credits={credits} />
            </SignedIn>
            <SignedOut>
              <SignInButton mode="modal">
                <button style={{
                  padding: '0.6rem 1rem',
                  background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 8,
                  fontWeight: 600
                }}>Anmelden</button>
              </SignInButton>
            </SignedOut>
            <SignedIn>
              <UserButton afterSignOutUrl='/' />
            </SignedIn>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div style={{
        maxWidth: "1200px",
        margin: "0 auto",
        padding: "3rem 2rem"
      }}>
        <SignedOut>
          <div style={{
            background: "rgba(255, 255, 255, 0.95)",
            borderRadius: 16,
            padding: '2rem',
            textAlign: 'center',
            border: '1px solid #e2e8f0'
          }}>
            <h2 style={{ marginTop: 0 }}>Bitte anmelden</h2>
            <p>Sie müssen angemeldet sein, um Fragen zu stellen.</p>
            <SignInButton mode="modal">
              <button style={{
                padding: '0.75rem 1.25rem',
                background: '#111827',
                color: '#fff',
                border: 'none',
                borderRadius: 8,
                fontWeight: 600
              }}>Jetzt anmelden</button>
            </SignInButton>
          </div>
        </SignedOut>

        <SignedIn>
          {/* Query Input Card */}
          <div style={{
            background: "rgba(255, 255, 255, 0.95)",
            backdropFilter: "blur(20px)",
            borderRadius: "20px",
            padding: "2.5rem",
            marginBottom: "2rem",
            boxShadow: "0 20px 40px rgba(0, 0, 0, 0.1), 0 0 0 1px rgba(255, 255, 255, 0.2)",
            border: "1px solid rgba(255, 255, 255, 0.2)"
          }}>
            <div style={{ marginBottom: "1.5rem" }}>
              <label style={{
                display: "block",
                marginBottom: "0.75rem",
                fontSize: "1.1rem",
                fontWeight: 600,
                color: "#1e293b",
                letterSpacing: "-0.01em"
              }}>Ihre Rechtsfrage</label>
              <div style={{ position: "relative" }}>
                <textarea
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={handleKeyDown}
                  rows={5}
                  style={{
                    width: "100%",
                    padding: "1.25rem",
                    paddingRight: "0rem", // Extra right padding to balance with character counter
                    fontSize: "1rem",
                    lineHeight: 1.6,
                    border: "2px solid #e2e8f0",
                    borderRadius: "12px",
                    resize: "vertical",
                    fontFamily: "inherit",
                    transition: "all 0.2s ease",
                    outline: "none",
                    background: "#ffffff",
                    boxShadow: "0 1px 3px rgba(0, 0, 0, 0.1)"
                  }}
                  onFocus={(e) => {
                    e.target.style.borderColor = "#667eea";
                    e.target.style.boxShadow = "0 0 0 3px rgba(102, 126, 234, 0.1), 0 1px 3px rgba(0, 0, 0, 0.1)";
                  }}
                  onBlur={(e) => {
                    e.target.style.borderColor = "#e2e8f0";
                    e.target.style.boxShadow = "0 1px 3px rgba(0, 0, 0, 0.1)";
                  }}
                  placeholder="Stellen Sie hier Ihre Frage zum deutschen Recht... (⌘+Enter zum Senden)"
                />
                <div style={{
                  position: "absolute",
                  bottom: "12px",
                  right: "12px",
                  fontSize: "0.75rem",
                  color: "#94a3b8",
                  fontWeight: 500
                }}>
                  {query.length}/2000
                </div>
              </div>
            </div>
            
            <div style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              flexWrap: "wrap",
              gap: "1rem"
            }}>
              <div style={{ display: "flex", gap: "1rem" }}>
                <button
                  onClick={ask}
                  disabled={loading || !query.trim()}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "0.5rem",
                    padding: "0.875rem 2rem",
                    fontSize: "1rem",
                    fontWeight: 600,
                    color: "white",
                    background: loading || !query.trim() 
                      ? "#94a3b8" 
                      : "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
                    border: "none",
                    borderRadius: "12px",
                    cursor: loading || !query.trim() ? "not-allowed" : "pointer",
                    transition: "all 0.2s ease",
                    boxShadow: loading || !query.trim() 
                      ? "none" 
                      : "0 4px 16px rgba(102, 126, 234, 0.3)",
                    transform: "translateY(0)"
                  }}
                  onMouseOver={(e) => {
                    if (!loading && query.trim()) {
                      (e.target as HTMLButtonElement).style.transform = "translateY(-2px)";
                      (e.target as HTMLButtonElement).style.boxShadow = "0 8px 24px rgba(102, 126, 234, 0.4)";
                    }
                  }}
                  onMouseOut={(e) => {
                    (e.target as HTMLButtonElement).style.transform = "translateY(0)";
                    (e.target as HTMLButtonElement).style.boxShadow = loading || !query.trim() 
                      ? "none" 
                      : "0 4px 16px rgba(102, 126, 234, 0.3)";
                  }}
                >
                  {loading && (
                    <div style={{
                      width: "16px",
                      height: "16px",
                      border: "2px solid rgba(255, 255, 255, 0.3)",
                      borderTop: "2px solid white",
                      borderRadius: "50%",
                      animation: "spin 1s linear infinite"
                    }} />
                  )}
                  {loading ? "Recherchiere..." : "Frage stellen"}
                </button>

                {loading && (
                  <button
                    onClick={() => { controllerRef.current?.abort(); setLoading(false); }}
                    disabled={!loading}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: "0.5rem",
                      padding: "0.875rem 1.5rem",
                      fontSize: "1rem",
                      fontWeight: 600,
                      color: "#dc2626",
                      background: "#fff",
                      border: "2px solid #fecaca",
                      borderRadius: "12px",
                      cursor: "pointer",
                      transition: "all 0.2s ease"
                    }}
                    onMouseOver={(e) => {
                      (e.target as HTMLButtonElement).style.background = "#fef2f2";
                    }}
                    onMouseOut={(e) => {
                      (e.target as HTMLButtonElement).style.background = "#fff";
                    }}
                  >
                    Abbrechen
                  </button>
                )}
                
                <button
                  onClick={() => { 
                    setQuery(""); 
                    setAnswer(null); 
                    setError(null); 
                    setSteps([]); 
                    setTotalTokensSent(0); 
                    setTotalTokensReceived(0); 
                  }}
                  disabled={loading}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "0.5rem",
                    padding: "0.875rem 1.5rem",
                    fontSize: "1rem",
                    fontWeight: 500,
                    color: "#64748b",
                    background: "white",
                    border: "2px solid #e2e8f0",
                    borderRadius: "12px",
                    cursor: loading ? "not-allowed" : "pointer",
                    transition: "all 0.2s ease",
                    opacity: loading ? 0.5 : 1
                  }}
                  onMouseOver={(e) => {
                    if (!loading) {
                      (e.target as HTMLButtonElement).style.borderColor = "#cbd5e1";
                      (e.target as HTMLButtonElement).style.color = "#475569";
                      (e.target as HTMLButtonElement).style.background = "#f8fafc";
                    }
                  }}
                  onMouseOut={(e) => {
                    (e.target as HTMLButtonElement).style.borderColor = "#e2e8f0";
                    (e.target as HTMLButtonElement).style.color = "#64748b";
                    (e.target as HTMLButtonElement).style.background = "white";
                  }}
                >
                  Zurücksetzen
                </button>
              </div>
              
              <div style={{
                fontSize: "0.875rem",
                color: "#94a3b8",
                fontWeight: 500
              }}>
                ⌘+Enter zum Senden
              </div>
            </div>
          </div>

          {/* Research Log Pane (persists; scrollable; shows entire history) */}
          {(loading || steps.length > 0) && (
            <div style={{
              background: "rgba(255, 255, 255, 0.95)",
              backdropFilter: "blur(20px)",
              borderRadius: "20px",
              padding: "2.5rem",
              marginBottom: "2rem",
              boxShadow: "0 20px 40px rgba(0, 0, 0, 0.1)",
              border: "1px solid rgba(255, 255, 255, 0.2)"
            }}>
              <div style={{
                display: "flex",
                alignItems: "center",
                gap: "1.5rem",
                marginBottom: steps.length > 0 ? "1rem" : "0"
              }}>
                {loading ? (
                  <div style={{
                    width: "48px",
                    height: "48px",
                    border: "4px solid #e2e8f0",
                    borderTop: "4px solid #667eea",
                    borderRadius: "50%",
                    animation: "spin 1s linear infinite"
                  }} />
                ) : (
                  <div style={{
                    width: "48px",
                    height: "48px",
                    borderRadius: "50%",
                    background: "#eef2ff",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: "#667eea",
                    fontWeight: 700
                  }}>✓</div>
                )}
                <div>
                  <h3 style={{
                    margin: 0,
                    fontSize: "1.25rem",
                    fontWeight: 600,
                    color: "#1e293b"
                  }}>{loading ? "Durchsuche Rechtsquellen..." : "Recherchelauf (Protokoll)"}</h3>
                  {loading ? (
                    <p style={{ margin: 0, color: "#64748b", fontSize: "0.95rem" }}>Dies kann einige Momente dauern</p>
                  ) : (
                    <p style={{ margin: 0, color: "#64748b", fontSize: "0.95rem" }}>Abgeschlossen – Protokoll der Schritte und Tool-Aufrufe</p>
                  )}
                </div>
              </div>

              {/* Entire step history – scrollable */}
              {steps.length > 0 && (
                <div
                  ref={logRef}
                  style={{
                    borderTop: "1px solid #e2e8f0",
                    paddingTop: "1rem",
                    maxHeight: "320px",
                    overflowY: "auto"
                  }}
                >
                  <ReasoningTraceBox
                    steps={steps} // Show all steps
                    isLoading={loading}
                    compact={true}
                  />
                </div>
              )}
            </div>
          )}

          {/* Error Message */}
          {error && (
            <div style={{
              background: "rgba(254, 242, 242, 0.95)",
              backdropFilter: "blur(20px)",
              border: "1px solid #fecaca",
              borderRadius: "16px",
              padding: "1.5rem",
              marginBottom: "2rem",
              boxShadow: "0 8px 24px rgba(239, 68, 68, 0.1)"
            }}>
              <div style={{
                display: "flex",
                alignItems: "flex-start",
                gap: "1rem"
              }}>
                <div style={{
                  fontSize: "1.25rem",
                  color: "#dc2626"
                }}>✗</div>
                <div>
                  <h4 style={{
                    margin: 0,
                    fontSize: "1rem",
                    fontWeight: 600,
                    color: "#dc2626"
                  }}>Fehler aufgetreten</h4>
                  <p style={{
                    margin: 0,
                    color: "#b91c1c",
                    fontSize: "0.95rem",
                    lineHeight: 1.5
                  }}>{error}</p>
                </div>
              </div>
            </div>
          )}

          {/* Answer Card */}
          {answer !== null && (
            <div style={{
              background: "rgba(255, 255, 255, 0.95)",
              backdropFilter: "blur(20px)",
              borderRadius: "20px",
              overflow: "hidden",
              boxShadow: "0 20px 40px rgba(0, 0, 0, 0.1)",
              border: "1px solid rgba(255, 255, 255, 0.2)"
            }}>
              <div style={{
                background: "linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%)",
                padding: "1.5rem 2rem",
                borderBottom: "1px solid rgba(34, 197, 94, 0.1)"
              }}>
                <h3 style={{
                  margin: 0,
                  fontSize: "1.25rem",
                  fontWeight: 600,
                  color: "#166534",
                  display: "flex",
                  alignItems: "center",
                  gap: "0.75rem"
                }}>
                  <span style={{
                    fontSize: "1.5rem"
                  }}>◆</span>
                  Antwort
                </h3>
              </div>
              <div style={{
                padding: "2rem",
                fontSize: "1rem",
                lineHeight: 1.7,
                color: "#1e293b"
              }}>
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    h1: ({children}) => (
                      <h1 style={{
                        color: '#1e293b',
                        borderBottom: '3px solid #667eea',
                        paddingBottom: '0.75rem',
                        marginBottom: '1.5rem',
                        fontSize: '1.75rem',
                        fontWeight: 700
                      }}>{children}</h1>
                    ),
                    h2: ({children}) => (
                      <h2 style={{
                        color: '#334155',
                        marginTop: '2rem',
                        marginBottom: '1rem',
                        fontSize: '1.5rem',
                        fontWeight: 600
                      }}>{children}</h2>
                    ),
                    h3: ({children}) => (
                      <h3 style={{
                        color: '#475569',
                        marginTop: '1.5rem',
                        marginBottom: '0.75rem',
                        fontSize: '1.25rem',
                        fontWeight: 600
                      }}>{children}</h3>
                    ),
                    p: ({children}) => (
                      <p style={{
                        marginBottom: '1.25rem',
                        lineHeight: 1.7
                      }}>{children}</p>
                    ),
                    strong: ({children}) => (
                      <strong style={{
                        color: '#1e293b',
                        fontWeight: 700
                      }}>{children}</strong>
                    ),
                    em: ({children}) => (
                      <em style={{
                        color: '#64748b',
                        fontStyle: 'italic'
                      }}>{children}</em>
                    ),
                    code: ({children}) => (
                      <code style={{
                        background: '#f1f5f9',
                        padding: '0.25rem 0.5rem',
                        borderRadius: '6px',
                        fontSize: '0.9rem',
                        fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Monaco, Consolas, monospace',
                        border: '1px solid #e2e8f0'
                      }}>{children}</code>
                    ),
                    pre: ({children}) => (
                      <pre style={{
                        background: '#f8fafc',
                        padding: '1.5rem',
                        borderRadius: '12px',
                        overflow: 'auto',
                        border: '1px solid #e2e8f0',
                        fontSize: '0.9rem',
                        lineHeight: 1.6
                      }}>{children}</pre>
                    ),
                    blockquote: ({children}) => (
                      <blockquote style={{
                        borderLeft: '4px solid #667eea',
                        paddingLeft: '1.5rem',
                        margin: '1.5rem 0',
                        fontStyle: 'italic',
                        color: '#64748b',
                        background: '#f8fafc',
                        padding: '1rem 1.5rem',
                        borderRadius: '0 8px 8px 0'
                      }}>{children}</blockquote>
                    ),
                    ul: ({children}) => (
                      <ul style={{
                        paddingLeft: '1.5rem',
                        marginBottom: '1.25rem'
                      }}>{children}</ul>
                    ),
                    ol: ({children}) => (
                      <ol style={{
                        paddingLeft: '1.5rem',
                        marginBottom: '1.25rem'
                      }}>{children}</ol>
                    ),
                    li: ({children}) => (
                      <li style={{
                        marginBottom: '0.5rem',
                        lineHeight: 1.6
                      }}>{children}</li>
                    )
                  }}
                >
                  {answer}
                </ReactMarkdown>
              </div>
            </div>
          )}

          {/* Token Counter Widget */}
          <TokenCounter
            totalTokensSent={totalTokensSent}
            totalTokensReceived={totalTokensReceived}
          />

          {/* Admin Panel for managing credits */}
          {isAdmin && (
            <div style={{ marginTop: '1rem' }}>
              <AdminCreditsPanel onSuccess={(cr: { euro_balance_cents: number }) => setCredits({ euro_balance_cents: cr.euro_balance_cents })} />
            </div>
          )}

          {/* Footer */}
          <div style={{
            textAlign: "center",
            marginTop: "3rem",
            color: "rgba(255, 255, 255, 0.8)",
            fontSize: "0.9rem",
            lineHeight: 1.6
          }}>
            <p style={{ margin: "0 0 0.5rem 0" }}>
              LegalGenius durchsucht eine umfangreiche Sammlung deutscher Rechtsquellen.
            </p>
            <p style={{ margin: 0, fontWeight: 500 }}>
              <strong>Hinweis:</strong> Diese Antworten dienen nur zu Informationszwecken und ersetzen keine Rechtsberatung.
            </p>
          </div>
        </SignedIn>
      </div>

      <style>{`
        @keyframes spin {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
  }

  // Auto-scroll the log to bottom on new events (unless user scrolled up)
  useEffect(() => {
    const el = logRef.current;
    if (!el) return;
    const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    if (isNearBottom) {
      el.scrollTop = el.scrollHeight;
    }
  }, [steps]);
      `}</style>
    </div>
  );
}
