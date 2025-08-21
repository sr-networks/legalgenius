import React from 'react';

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
  const totalTokens = totalTokensSent + totalTokensReceived;
  
  // Debug logging
  console.log("TokenCounter render:", { totalTokensSent, totalTokensReceived, totalTokens });
  
  // Rough cost estimation (varies by provider/model)
  // Using approximate GPT-4 pricing as baseline: ~$0.03/1K input tokens, ~$0.06/1K output tokens
  const estimatedCost = (totalTokensSent / 1000 * 0.03) + (totalTokensReceived / 1000 * 0.06);

  const formatNumber = (num: number): string => {
    if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
    if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
    return num.toString();
  };

  return (
    <div style={{
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
    }}>
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
      
      <div style={{
        borderTop: '1px solid #e2e8f0',
        paddingTop: '12px',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center'
      }}>
        <div>
          <div style={{
            fontSize: '0.75rem',
            color: '#64748b',
            fontWeight: 500,
            marginBottom: '2px'
          }}>Total</div>
          <div style={{
            fontSize: '1.1rem',
            fontWeight: 700,
            color: '#1e293b'
          }}>{formatNumber(totalTokens)}</div>
        </div>
        
        <div style={{
          textAlign: 'right'
        }}>
          <div style={{
            fontSize: '0.75rem',
            color: '#64748b',
            fontWeight: 500,
            marginBottom: '2px'
          }}>Est. Cost</div>
          <div style={{
            fontSize: '0.9rem',
            fontWeight: 600,
            color: '#059669'
          }}>~${estimatedCost.toFixed(4)}</div>
        </div>
      </div>
      
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