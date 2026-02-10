import React, { useState, useEffect, useRef } from 'react';
import { Send, Bot, Loader2, AlertCircle, Database } from 'lucide-react';
import type { WidgetProps } from '../widgetRegistry';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  sql?: string;
  rows?: any[];
  row_count?: number;
  error?: boolean;
}

interface GenieWidgetData {
  space_id?: string;
  name?: string;
}

export const GenieWidget: React.FC<WidgetProps> = ({ data }) => {
  // Use provided config or fall back to defaults from registry
  const config = (data as GenieWidgetData) || {};

  if (!config.space_id) {
    return (
      <div className="h-full flex items-center justify-center p-4">
        <div className="text-center text-gray-500">
          <Bot className="w-12 h-12 mx-auto mb-2 text-gray-400" />
          <p className="font-semibold">No Genie Space Configured</p>
          <p className="text-sm mt-1">Please configure this widget to select a Genie Space.</p>
        </div>
      </div>
    );
  }

  const spaceId = config.space_id;
  const genieName = config.name || 'Genie Assistant';

  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      content: `Hello! I am ${genieName}, your Supply Chain AI assistant. Ask me about supply demand information.`
    }
  ]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [showSql, setShowSql] = useState<{ [key: number]: boolean }>({});
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;

    const userMessage = input.trim();
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
    setIsLoading(true);

    try {
      const response = await fetch('/api/genie/query', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          question: userMessage,
          conversation_id: conversationId,
          space_id: spaceId,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(errorData.detail || `HTTP ${response.status}`);
      }

      const result = await response.json();

      // Update conversation ID if this is the first message
      if (!conversationId && result.conversation_id) {
        setConversationId(result.conversation_id);
      }

      // Add assistant response
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: result.answer || result.description || 'I received your question but have no response.',
        sql: result.sql,
        rows: result.rows,
        row_count: result.row_count,
      }]);
    } catch (error) {
      console.error('Error querying genie:', error);
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `Sorry, I encountered an error: ${error instanceof Error ? error.message : 'Unknown error'}`,
        error: true,
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  const toggleSql = (index: number) => {
    setShowSql(prev => ({ ...prev, [index]: !prev[index] }));
  };

  return (
    <div className="h-full flex flex-col bg-gray-50/50">
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {messages.map((m, i) => (
          <div key={i} className={`flex gap-2 ${m.role === 'user' ? 'flex-row-reverse' : ''}`}>
            {m.role === 'assistant' && (
              <div className={`w-8 h-8 rounded-full flex items-center justify-center text-white shrink-0 ${m.error ? 'bg-red-500' : 'bg-qualcomm-blue'
                }`}>
                {m.error ? <AlertCircle className="w-5 h-5" /> : <Bot className="w-5 h-5" />}
              </div>
            )}
            <div className="flex-1 max-w-[80%]">
              <div className={`p-2 rounded-lg text-sm ${m.role === 'user'
                ? 'bg-qualcomm-navy text-white'
                : m.error
                  ? 'bg-red-50 border border-red-200 text-red-800'
                  : 'bg-white border border-gray-200'
                }`}>
                {m.content}
              </div>

              {/* Show SQL if available */}
              {m.sql && (
                <div className="mt-2">
                  <button
                    onClick={() => toggleSql(i)}
                    className="text-xs text-qualcomm-blue hover:underline flex items-center gap-1"
                  >
                    <Database className="w-3 h-3" />
                    {showSql[i] ? 'Hide' : 'Show'} SQL Query
                  </button>
                  {showSql[i] && (
                    <pre className="mt-1 p-2 bg-gray-900 text-gray-100 text-xs rounded overflow-x-auto">
                      {m.sql}
                    </pre>
                  )}
                </div>
              )}

              {/* Show data table if available */}
              {m.rows && m.rows.length > 0 && (
                <div className="mt-2 overflow-x-auto">
                  <div className="text-xs text-gray-500 mb-1">
                    {m.row_count} row{m.row_count !== 1 ? 's' : ''} returned
                  </div>
                  <table className="min-w-full text-xs border border-gray-200 rounded">
                    <thead className="bg-gray-100">
                      <tr>
                        {Object.keys(m.rows[0]).map((key) => (
                          <th key={key} className="px-2 py-1 text-left font-semibold border-b">
                            {key}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="bg-white">
                      {m.rows.slice(0, 10).map((row, idx) => (
                        <tr key={idx} className="border-b">
                          {Object.values(row).map((val: any, vidx) => (
                            <td key={vidx} className="px-2 py-1">
                              {val !== null && val !== undefined ? String(val) : '-'}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {m.rows.length > 10 && (
                    <div className="text-xs text-gray-500 mt-1">
                      Showing 10 of {m.rows.length} rows
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
        {isLoading && (
          <div className="flex gap-2">
            <div className="w-8 h-8 rounded-full bg-qualcomm-blue flex items-center justify-center text-white shrink-0">
              <Loader2 className="w-5 h-5 animate-spin" />
            </div>
            <div className="p-2 rounded-lg text-sm bg-white border border-gray-200">
              Thinking...
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>
      <div className="p-2 border-t border-gray-200 bg-white flex gap-2">
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !e.shiftKey && handleSend()}
          placeholder="Ask Genie..."
          disabled={isLoading}
          className="flex-1 px-3 py-1.5 border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-qualcomm-blue disabled:bg-gray-100 disabled:cursor-not-allowed"
        />
        <button
          onClick={handleSend}
          disabled={isLoading || !input.trim()}
          className="p-2 bg-qualcomm-blue text-white rounded-md hover:bg-blue-600 disabled:bg-gray-300 disabled:cursor-not-allowed"
        >
          {isLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
        </button>
      </div>
    </div>
  );
};
