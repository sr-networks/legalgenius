import React from "react";

export type Credits = {
  euro_balance_cents: number;
};

function formatEuro(cents?: number) {
  const v = (cents ?? 0) / 100;
  return v.toLocaleString(undefined, { style: 'currency', currency: 'EUR' });
}

export default function CreditBadge({ credits }: { credits?: Credits | null }) {
  const balCents = credits?.euro_balance_cents ?? 0;
  const text = formatEuro(balCents);
  return (
    <div style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: '0.5rem',
      background: 'rgba(16,185,129,0.12)',
      border: '1px solid rgba(16,185,129,0.3)',
      padding: '0.35rem 0.6rem',
      borderRadius: 999,
      color: '#065f46',
      fontWeight: 700,
      fontSize: '0.875rem'
    }}>
      <span>Guthaben</span>
      <span style={{color: balCents > 0 ? '#065f46' : '#b91c1c'}}>{text}</span>
    </div>
  );
}
