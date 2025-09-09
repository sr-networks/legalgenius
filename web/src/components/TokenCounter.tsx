import React, { useEffect, useState } from 'react';

interface TokenCounterProps {
  totalTokensSent: number;
  totalTokensReceived: number;
  currentSessionCost?: number;
}

export default function TokenCounter({ 
  totalTokensSent, 
  totalTokensReceived, 
  currentSessionCost 
}: TokenCounterProps) {
  
  // Debug logging
  console.log("TokenCounter render:", { totalTokensSent, totalTokensReceived });
  
  // Detect small screens to avoid overlaying main content on phones
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mql = window.matchMedia('(max-width: 640px)');
    const handler = (e: MediaQueryListEvent | MediaQueryList) => {
      // Support both initial call (MediaQueryList) and change events (MediaQueryListEvent)
      const matches = 'matches' in e ? (e as MediaQueryList).matches : (e as MediaQueryListEvent).matches;
      setIsMobile(matches);
    };
    // Set initial
    setIsMobile(mql.matches);
    // Listen for changes (modern + legacy)
    if (mql.addEventListener) mql.addEventListener('change', handler as (ev: Event) => void);
    else mql.addListener(handler as (this: MediaQueryList, ev: MediaQueryListEvent) => void);
    return () => {
      if (mql.removeEventListener) mql.removeEventListener('change', handler as (ev: Event) => void);
      else mql.removeListener(handler as (this: MediaQueryList, ev: MediaQueryListEvent) => void);
    };
  }, []);
  
  // Removed estimated cost display

  const formatNumber = (num: number): string => {
    if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
    if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
    return num.toString();
  };

  // Base container style; switch to in-flow on mobile
  const containerStyle: React.CSSProperties = {
    position: 'fixed',
    bottom: '20px',
    right: '20px',
    background: 'rgba(255, 255, 255, 0.95)',
    backdropFilter: 'blur(20px)',
    borderRadius: '16px',
    padding: '16px 20px',
    boxShadow: '0 8px 32px rgba(0, 0, 0, 0.1), 0 0 0 1px rgba(255, 255, 255, 0.2)',
    border: '1px solid rgba(255, 255, 255, 0.2)',
    minWidth: '220px',
    fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    fontSize: '0.875rem',
    zIndex: 1000
  };

  if (isMobile) {
    containerStyle.position = 'static';
    containerStyle.width = '100%';
    containerStyle.minWidth = 'unset';
    // Add a bit of spacing when in flow
    (containerStyle as any).marginTop = '12px';
  }

  return (
    <div style={containerStyle}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        marginBottom: '12px'
      }}>
        <span style={{
          fontSize: '1.25rem'
        }}>🪙</span>
        <h4 style={{
          margin: 0,
          fontSize: '0.95rem',
          fontWeight: 600,
          color: '#1e293b',
          letterSpacing: '-0.01em'
        }}>Token Usage</h4>
      </div>
      
      <div style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: '8px',
        marginBottom: '12px'
      }}>
        <div style={{
          background: 'linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%)',
          borderRadius: '8px',
          padding: '8px 12px',
          textAlign: 'center'
        }}>
          <div style={{
            fontSize: '0.75rem',
            color: '#1e40af',
            fontWeight: 500,
            marginBottom: '2px'
          }}>Sent</div>
          <div style={{
            fontSize: '1rem',
            fontWeight: 700,
            color: '#1e40af'
          }}>{formatNumber(totalTokensSent)}</div>
        </div>
        
        <div style={{
          background: 'linear-gradient(135deg, #dcfce7 0%, #bbf7d0 100%)',
          borderRadius: '8px',
          padding: '8px 12px',
          textAlign: 'center'
        }}>
          <div style={{
            fontSize: '0.75rem',
            color: '#166534',
            fontWeight: 500,
            marginBottom: '2px'
          }}>Received</div>
          <div style={{
            fontSize: '1rem',
            fontWeight: 700,
            color: '#166534'
          }}>{formatNumber(totalTokensReceived)}</div>
        </div>
      </div>
      
      {/* Total and estimated cost removed per request */}
      
      <div style={{
        marginTop: '12px',
        fontSize: '0.75rem',
        color: '#64748b',
        textAlign: 'center',
        fontStyle: 'italic'
      }}>
        Session Total • {new Date().toLocaleDateString()}
      </div>
    </div>
  );
}