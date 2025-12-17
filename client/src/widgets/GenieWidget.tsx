import React, { useState } from 'react';
import { Send, Bot } from 'lucide-react';
import type { WidgetProps } from '../widgetRegistry';

export const GenieWidget: React.FC<WidgetProps> = () => {
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<{role: 'user' | 'assistant', content: string}[]>([
    { role: 'assistant', content: 'Hello! I am Genie, your Supply Chain AI assistant. Ask me about inventory risks or supplier status.' }
  ]);

  const handleSend = () => {
    if (!input.trim()) return;
    setMessages(prev => [...prev, { role: 'user', content: input }]);
    setTimeout(() => {
        setMessages(prev => [...prev, { role: 'assistant', content: `I've analyzed the data for "${input}". It seems standard deviation is within acceptable limits, but keep an eye on the Singapore logistics hub.` }]);
    }, 1000);
    setInput('');
  };

  return (
    <div className="h-full flex flex-col bg-gray-50/50">
       <div className="flex-1 overflow-y-auto p-3 space-y-3">
          {messages.map((m, i) => (
            <div key={i} className={`flex gap-2 ${m.role === 'user' ? 'flex-row-reverse' : ''}`}>
               {m.role === 'assistant' && (
                 <div className="w-8 h-8 rounded-full bg-qualcomm-blue flex items-center justify-center text-white shrink-0">
                   <Bot className="w-5 h-5" />
                 </div>
               )}
               <div className={`p-2 rounded-lg text-sm max-w-[80%] ${
                 m.role === 'user' ? 'bg-qualcomm-navy text-white' : 'bg-white border border-gray-200'
               }`}>
                 {m.content}
               </div>
            </div>
          ))}
       </div>
       <div className="p-2 border-t border-gray-200 bg-white flex gap-2">
         <input 
           type="text" 
           value={input} 
           onChange={e => setInput(e.target.value)}
           onKeyDown={e => e.key === 'Enter' && handleSend()}
           placeholder="Ask Genie..."
           className="flex-1 px-3 py-1.5 border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-qualcomm-blue"
         />
         <button onClick={handleSend} className="p-2 bg-qualcomm-blue text-white rounded-md hover:bg-blue-600">
           <Send className="w-4 h-4" />
         </button>
       </div>
    </div>
  );
};

