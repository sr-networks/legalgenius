export const API_BASE = (typeof window !== 'undefined' && (window as any).ENV?.REACT_APP_API_BASE) || 'http://127.0.0.1:8000';

export interface StreamEvent {
  type: 'thinking' | 'step' | 'tool_thinking' | 'tool_event' | 'token_usage' | 'final_answer' | 'error' | 'complete';
  message?: string;
  tool?: string;
  args?: Record<string, any>;
  tokens_sent?: number;
  tokens_received?: number;
  step?: number;
  event?: {
    type: 'tool_start' | 'tool_complete' | 'tool_error';
    tool: string;
    args: Record<string, any>;
    result?: any;
    error?: string;
    timestamp: number;
  };
  timestamp: number;
}

export async function* streamQuery(query: string, signal?: AbortSignal): AsyncGenerator<StreamEvent, void, unknown> {
  const response = await fetch(`${API_BASE}/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ query }),
    signal,
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data?.detail || `HTTP ${response.status}`);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('No response body reader available');
  }

  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const event = JSON.parse(line.slice(6)) as StreamEvent;
            yield event;
            
            if (event.type === 'complete' || event.type === 'error') {
              return;
            }
          } catch (parseErr) {
            console.warn('Failed to parse SSE data:', line, parseErr);
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}