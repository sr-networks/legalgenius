import React from 'react';

interface ToolEvent {
  type: 'tool_start' | 'tool_complete';
  tool: string;
  args: Record<string, any>;
  result?: any;
  timestamp: number;
}

interface ReasoningStep {
  type: 'thinking' | 'step' | 'tool_thinking' | 'tool_event' | 'reasoning';
  message?: string;
  content?: string; // For reasoning content
  tool?: string;
  args?: Record<string, any>;
  event?: ToolEvent;
  timestamp: number;
}

interface ReasoningTraceBoxProps {
  steps: ReasoningStep[];
  isLoading: boolean;
  compact?: boolean; // New compact mode for embedding in loading state
}

const ReasoningTraceBox: React.FC<ReasoningTraceBoxProps> = ({ steps, isLoading, compact = false }) => {
  const formatTimestamp = (timestamp: number) => {
    return new Date(timestamp * 1000).toLocaleTimeString('de-DE', {
      hour12: false,
      timeStyle: 'medium'
    });
  };

  // Process steps to show only current tool execution and completed steps
  const processSteps = () => {
    const processed = [];
    let currentToolInProgress = null;
    
    for (let i = 0; i < steps.length; i++) {
      const step = steps[i];
      
      if (step.type === 'thinking' || step.type === 'step' || step.type === 'reasoning') {
        // Always keep thinking, step, and reasoning messages
        processed.push(step);
      } else if (step.type === 'tool_thinking') {
        // This starts a new tool execution - replace any previous tool in progress
        currentToolInProgress = step;
      } else if (step.type === 'tool_event' && step.event?.type === 'tool_complete') {
        // Tool completed - add the final result and clear in-progress
        if (currentToolInProgress) {
          processed.push({
            ...currentToolInProgress,
            event: step.event,
            type: 'tool_event' as const
          });
          currentToolInProgress = null;
        }
      }
    }
    
    // Add current tool in progress if any
    if (currentToolInProgress) {
      processed.push(currentToolInProgress);
    }
    
    return processed;
  };

  const getStepIcon = (type: string) => {
    switch (type) {
      case 'thinking': return '●';
      case 'step': return '→';
      case 'reasoning': return '🧠';
      case 'tool_thinking': return '○';
      case 'tool_event': return '✓';
      default: return '•';
    }
  };

  const getStepColor = (type: string) => {
    switch (type) {
      case 'thinking': return 'bg-yellow-50 border-yellow-200 text-yellow-800';
      case 'step': return 'bg-blue-50 border-blue-200 text-blue-800';
      case 'reasoning': return 'bg-indigo-50 border-indigo-200 text-indigo-800';
      case 'tool_thinking': return 'bg-purple-50 border-purple-200 text-purple-800';
      case 'tool_event': return 'bg-green-50 border-green-200 text-green-800';
      default: return 'bg-gray-50 border-gray-200 text-gray-800';
    }
  };

  const formatToolArgs = (args: Record<string, any>) => {
    const entries = Object.entries(args);
    if (entries.length === 0) return null;
    
    return entries.slice(0, 3).map(([key, value]) => {
      const displayValue = typeof value === 'string' 
        ? value.length > 50 ? value.substring(0, 50) + '...' 
        : value
        : JSON.stringify(value);
      
      return (
        <span key={key} className="text-xs bg-white bg-opacity-60 px-2 py-1 rounded mr-2">
          <span className="font-medium">{key}:</span> {displayValue}
        </span>
      );
    });
  };

  const formatToolResult = (result: any) => {
    if (!result) return null;
    
    if (typeof result === 'string') {
      return result.length > 100 ? result.substring(0, 100) + '...' : result;
    }
    
    if (result.matches && Array.isArray(result.matches)) {
      return `${result.matches.length} Treffer gefunden`;
    }
    
    if (result.files && Array.isArray(result.files)) {
      return `${result.files.length} Dateien gefunden`;
    }
    
    if (result.text) {
      return result.text.length > 100 ? result.text.substring(0, 100) + '...' : result.text;
    }
    
    return JSON.stringify(result).substring(0, 100) + '...';
  };

  if (!isLoading && steps.length === 0) {
    return null;
  }

  // Compact mode - just the traces without container
  if (compact) {
    return (
      <div className="space-y-2">
        {processSteps().map((step, index) => (
          <div key={index} className={`p-2 rounded border text-xs ${getStepColor(step.type)}`}>
            <div className="flex items-start justify-between">
              <div className="flex items-start flex-1">
                <span className="text-xs mr-2">{getStepIcon(step.type)}</span>
                <div className="flex-1">
                  <div className="font-medium text-xs mb-1">
                    {step.message}
                    {step.tool && (
                      <span className="ml-2 text-xs bg-white bg-opacity-50 px-1 py-0.5 rounded font-mono">
                        {step.tool}
                      </span>
                    )}
                  </div>
                  
                  {step.content && (
                    <div className="text-xs bg-white bg-opacity-60 p-2 rounded mt-1 border-l-2 border-indigo-300">
                      <div className="font-medium mb-1 text-indigo-700">Reasoning:</div>
                      <div className="whitespace-pre-wrap font-mono text-xs leading-relaxed max-h-20 overflow-y-auto">
                        {step.content.length > 200 ? step.content.substring(0, 200) + '...' : step.content}
                      </div>
                    </div>
                  )}
                  
                  {step.args && Object.keys(step.args).length > 0 && (
                    <div className="mb-1">
                      {formatToolArgs(step.args)}
                    </div>
                  )}
                  
                  {step.event?.type === 'tool_complete' && step.event.result && (
                    <div className="text-xs bg-white bg-opacity-40 p-1 rounded mt-1">
                      <div className="font-medium mb-1">Ergebnis:</div>
                      <div className="font-mono text-xs">
                        {formatToolResult(step.event.result)}
                      </div>
                    </div>
                  )}
                </div>
              </div>
              
              <span className="text-xs opacity-60 ml-2">
                {formatTimestamp(step.timestamp)}
              </span>
            </div>
          </div>
        ))}
      </div>
    );
  }

  // Full mode - complete component with header
  return (
    <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 mb-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-700 flex items-center">
          <span className="mr-2">▶</span>
          Recherche-Verlauf
        </h3>
        {isLoading && (
          <div className="flex items-center text-xs text-blue-600">
            <div className="animate-spin w-3 h-3 border border-blue-600 border-t-transparent rounded-full mr-1"></div>
            Aktiv
          </div>
        )}
      </div>
      
      <div className="space-y-2 max-h-64 overflow-y-auto">
        {processSteps().map((step, index) => (
          <div key={index} className={`p-3 rounded border text-xs ${getStepColor(step.type)}`}>
            <div className="flex items-start justify-between">
              <div className="flex items-start flex-1">
                <span className="text-sm mr-2">{getStepIcon(step.type)}</span>
                <div className="flex-1">
                  <div className="font-medium mb-1">
                    {step.message}
                    {step.tool && (
                      <span className="ml-2 text-xs bg-white bg-opacity-50 px-2 py-1 rounded font-mono">
                        {step.tool}
                      </span>
                    )}
                  </div>
                  
                  {step.content && (
                    <div className="text-xs bg-white bg-opacity-60 p-3 rounded mt-2 border-l-2 border-indigo-300">
                      <div className="font-medium mb-1 text-indigo-700">Reasoning:</div>
                      <div className="whitespace-pre-wrap font-mono text-xs leading-relaxed max-h-32 overflow-y-auto">
                        {step.content}
                      </div>
                    </div>
                  )}
                  
                  {step.args && Object.keys(step.args).length > 0 && (
                    <div className="mb-2">
                      {formatToolArgs(step.args)}
                    </div>
                  )}
                  
                  {step.event?.type === 'tool_complete' && step.event.result && (
                    <div className="text-xs bg-white bg-opacity-40 p-2 rounded mt-2">
                      <div className="font-medium mb-1">Ergebnis:</div>
                      <div className="font-mono text-xs">
                        {formatToolResult(step.event.result)}
                      </div>
                    </div>
                  )}
                </div>
              </div>
              
              <span className="text-xs opacity-60 ml-2">
                {formatTimestamp(step.timestamp)}
              </span>
            </div>
          </div>
        ))}
        
        {isLoading && (
          <div className="p-3 rounded border bg-blue-50 border-blue-200 text-blue-800 text-xs">
            <div className="flex items-center">
              <div className="animate-pulse w-2 h-2 bg-blue-600 rounded-full mr-2"></div>
              <span>Verarbeite Anfrage...</span>
            </div>
          </div>
        )}
      </div>
      
      {processSteps().length > 0 && (
        <div className="mt-3 pt-2 border-t border-gray-300">
          <div className="text-xs text-gray-600 flex justify-between">
            <span>{processSteps().length} Schritte</span>
            <span>
              {processSteps().filter(s => s.type === 'tool_event' && s.event?.type === 'tool_complete').length} Tools abgeschlossen
            </span>
          </div>
        </div>
      )}
    </div>
  );
};

export default ReasoningTraceBox;