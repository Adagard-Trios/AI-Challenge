'use client';

import { useState, useRef, useEffect } from 'react';
import { Send, Brain, Trash2, Radio } from 'lucide-react';
import { Badge } from './ui/badge';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './Roger.css';

interface Message {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    sources?: Array<{
        domain: string;
        platform: string;
        similarity: number;
    }>;
    timestamp: Date;
}

const FloatingChatBox = () => {
    const [isOpen, setIsOpen] = useState(false);
    const [messages, setMessages] = useState<Message[]>([]);
    const [input, setInput] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [domainFilter, setDomainFilter] = useState<string | null>(null);
    const scrollContainerRef = useRef<HTMLDivElement | null>(null);

    const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

    // Auto-scroll to bottom
    useEffect(() => {
        if (scrollContainerRef.current) {
            scrollContainerRef.current.scrollTop = scrollContainerRef.current.scrollHeight;
        }
    }, [messages, isLoading]);

    // Handle body scroll when chat is open (mobile)
    useEffect(() => {
        if (isOpen) {
            document.body.style.overflow = 'hidden';
        } else {
            document.body.style.overflow = 'unset';
        }
        return () => {
            document.body.style.overflow = 'unset';
        };
    }, [isOpen]);

    const sendMessage = async () => {
        if (!input.trim() || isLoading) return;

        const userMessage: Message = {
            id: Date.now().toString(),
            role: 'user',
            content: input,
            timestamp: new Date()
        };

        setMessages(prev => [...prev, userMessage]);
        const currentInput = input;
        setInput('');
        setIsLoading(true);

        try {
            const response = await fetch(`${API_BASE}/api/rag/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: currentInput,
                    domain_filter: domainFilter,
                    use_history: true
                })
            });

            const data = await response.json();

            const assistantMessage: Message = {
                id: (Date.now() + 1).toString(),
                role: 'assistant',
                content: data.answer || 'No response received.',
                sources: data.sources,
                timestamp: new Date()
            };

            setMessages(prev => [...prev, assistantMessage]);
        } catch (error) {
            const errorMessage: Message = {
                id: (Date.now() + 1).toString(),
                role: 'assistant',
                content: 'Failed to connect to Roger Intelligence. Please ensure the backend is running.',
                timestamp: new Date()
            };
            setMessages(prev => [...prev, errorMessage]);
        } finally {
            setIsLoading(false);
        }
    };

    const clearHistory = async () => {
        try {
            await fetch(`${API_BASE}/api/rag/clear`, { method: 'POST' });
            setMessages([]);
        } catch (error) {
            console.error('Failed to clear history:', error);
        }
    };

    const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    };

    const toggleChat = () => {
        setIsOpen(!isOpen);
    };

    const domains = ['political', 'economic', 'weather', 'social', 'intelligence'];

    return (
        <div className={`${isOpen ? 'h-[100vh] w-[100vw]' : ''} fixed z-[9999] text-white bottom-0 right-0`}>
            {/* Backdrop */}
            <div
                onClick={() => setIsOpen(false)}
                className={`absolute top-0 left-0 w-screen h-screen bg-black transition-opacity duration-500 ${isOpen ? 'opacity-40 flex' : 'opacity-0 hidden'}`}
            />

            {/* Roger Button */}
            <div
                onClick={toggleChat}
                className={`${isOpen ? 'translate-y-[100px]' : 'translate-y-0 delay-300'} select-none transition-transform duration-500 ease-in-out absolute bottom-[15px] right-[15px] sm:bottom-[20px] sm:right-[30px] flex items-center justify-center w-fit bg-[#373435] ring-[0.5px] ring-[#727376] rounded-full cursor-pointer px-[25px] py-[8px] sm:px-[30px] sm:py-[8px] shadow-lg hover:bg-[#4a4a4a] transition-colors`}
            >
                <Radio className="w-5 h-5 mr-2 text-green-400" />
                <p className="select-none text-white text-[18px] sm:text-[18px] font-semibold">Roger</p>
            </div>

            {/* Chat Container */}
            <div className={`${isOpen ? 'scale-100 delay-200' : 'scale-0'} roger-scrollbar absolute bottom-0 right-0 sm:bottom-[20px] sm:right-[30px] origin-bottom-right transition-transform duration-500 ease-in-out flex flex-col bg-[#373435] ring-[0.5px] ring-[#727376] h-[100dvh] w-[100vw] sm:h-[600px] sm:w-[420px] sm:rounded-[12px] justify-center overflow-hidden`}>

                {/* Header - with safe area for iPhone notch */}
                <div className="w-full select-none px-[16px] sm:px-[20px] bg-[#000000] text-white flex flex-row justify-between sm:rounded-t-[12px] py-[14px] sm:py-[18px] pt-[max(14px,env(safe-area-inset-top))] h-fit items-center border-b border-[#373435]">
                    <div className="flex items-center gap-3">
                        <div className="p-2 rounded-lg bg-green-500/20">
                            <Brain className="w-5 h-5 text-green-400" />
                        </div>
                        <div>
                            <p className="text-[20px] sm:text-[18px] font-semibold">Roger</p>
                            <p className="text-[12px] text-gray-400">Intelligence Assistant</p>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        <div
                            onClick={clearHistory}
                            className="cursor-pointer bg-[#373435] hover:bg-red-500/30 p-2 rounded-lg transition-colors"
                            title="Clear chat history"
                        >
                            <Trash2 className="w-4 h-4 text-gray-400 hover:text-red-400" />
                        </div>
                        <div
                            onClick={toggleChat}
                            className="cursor-pointer bg-[#373435] hover:bg-[#4a4a4a] active:bg-[#555] px-[14px] py-[8px] sm:px-[12px] sm:py-[6px] rounded-[8px] sm:rounded-[6px] transition-colors touch-manipulation"
                        >
                            <p className="text-[14px] sm:text-[13px]">Close</p>
                        </div>
                    </div>
                </div>

                {/* Domain Filter - scrollable on mobile */}
                <div className="flex gap-1.5 sm:gap-1 px-3 sm:px-4 py-3 bg-[#1a1a1a] border-b border-[#373435] overflow-x-auto sm:flex-wrap intel-scrollbar">
                    <Badge
                        className={`cursor-pointer text-xs sm:text-xs whitespace-nowrap px-3 py-1.5 sm:px-2 sm:py-1 transition-colors touch-manipulation ${!domainFilter ? 'bg-green-500 text-white' : 'bg-[#373435] text-gray-300 hover:bg-[#4a4a4a] active:bg-[#555]'}`}
                        onClick={() => setDomainFilter(null)}
                    >
                        All
                    </Badge>
                    {domains.map(domain => (
                        <Badge
                            key={domain}
                            className={`cursor-pointer text-xs sm:text-xs whitespace-nowrap px-3 py-1.5 sm:px-2 sm:py-1 capitalize transition-colors touch-manipulation ${domainFilter === domain ? 'bg-green-500 text-white' : 'bg-[#373435] text-gray-300 hover:bg-[#4a4a4a] active:bg-[#555]'}`}
                            onClick={() => setDomainFilter(domain)}
                        >
                            {domain}
                        </Badge>
                    ))}
                </div>

                {/* Messages Container */}
                {messages.length > 0 ? (
                    <div
                        className="flex flex-col flex-1 overflow-y-auto py-4 px-4 bg-[#101010] roger-scrollbar"
                        ref={scrollContainerRef}
                        style={{
                            WebkitOverflowScrolling: 'touch',
                            overscrollBehavior: 'contain',
                        }}
                    >
                        {/* Today Badge */}
                        <div className="flex justify-center mt-1 mb-4">
                            <div className="bg-[#373435] text-[11px] px-3 py-1 rounded-full border border-[#505050]">
                                <p className="text-gray-400">Today</p>
                            </div>
                        </div>

                        {messages.map((msg) => (
                            <div
                                className={`flex mb-3 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                                key={msg.id}
                            >
                                <div
                                    className={`max-w-[85%] rounded-[10px] py-[10px] px-[14px] text-[14px] leading-relaxed ${msg.role === 'user'
                                        ? 'bg-[#505050] text-white border border-[#606060]'
                                        : 'bg-white text-black border border-gray-300'
                                        }`}
                                >
                                    {msg.role === 'assistant' ? (
                                        <div className="roger-markdown">
                                            <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                                {msg.content}
                                            </ReactMarkdown>
                                        </div>
                                    ) : (
                                        <p>{msg.content}</p>
                                    )}

                                    {/* Sources */}
                                    {msg.sources && msg.sources.length > 0 && (
                                        <div className="mt-2 pt-2 border-t border-gray-200">
                                            <p className="text-[11px] text-gray-500 mb-1">Sources:</p>
                                            <div className="flex flex-wrap gap-1">
                                                {msg.sources.slice(0, 3).map((src, i) => (
                                                    <span
                                                        key={i}
                                                        className="text-[10px] bg-gray-100 text-gray-600 px-2 py-0.5 rounded"
                                                    >
                                                        {src.domain} ({Math.round(src.similarity * 100)}%)
                                                    </span>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                </div>
                            </div>
                        ))}

                        {/* Typing Indicator */}
                        {isLoading && (
                            <div className="flex py-2 items-center justify-start mb-3">
                                <div className="rounded-lg p-3 flex h-[50px] justify-center items-center">
                                    <span className="roger-loader"></span>
                                </div>
                            </div>
                        )}
                    </div>
                ) : (
                    <div className="flex-1 flex flex-col justify-center items-center bg-[#101010] px-6">
                        <div className="p-4 rounded-full bg-green-500/10 mb-4">
                            <Radio className="w-12 h-12 text-green-400 opacity-50" />
                        </div>
                        <div className="text-gray-300 text-center max-w-[280px]">
                            <p className="text-[16px] mb-3 leading-relaxed">
                                Hello! I'm <strong>Roger</strong>, your intelligence assistant.
                            </p>
                            <p className="text-[14px] text-gray-400 leading-relaxed">
                                Ask me anything about Sri Lanka's political, economic, weather, or social intelligence data.
                            </p>
                            <div className="mt-4 space-y-2 text-[12px] text-gray-500">
                                <p>Try asking:</p>
                                <p className="italic">"What are the latest political events?"</p>
                                <p className="italic">"Any weather warnings today?"</p>
                            </div>
                        </div>
                    </div>
                )}

                {/* Input Area - with safe area for bottom */}
                <div className="w-full ring-1 ring-[#373435] sm:rounded-b-[12px] py-[10px] sm:py-[12px] px-[12px] pb-[max(10px,env(safe-area-inset-bottom))] bg-[#000000]">
                    <div className="relative">
                        <textarea
                            onKeyDown={handleKeyDown}
                            onChange={(e) => setInput(e.target.value)}
                            value={input}
                            disabled={isLoading}
                            className="w-full focus:outline-none focus:ring-2 focus:ring-green-500 min-h-[50px] max-h-[100px] leading-[22px] rounded-[10px] bg-white text-black py-[12px] px-[14px] pr-[60px] resize-none text-[15px] placeholder-gray-500 disabled:opacity-50"
                            placeholder="Ask Roger..."
                            rows={2}
                            style={{ fontSize: '16px' }}
                        />
                        <div
                            onClick={sendMessage}
                            className={`absolute top-[6px] right-[6px] w-[44px] h-[44px] sm:w-[42px] sm:h-[42px] ring-[0.5px] ring-[#727376] cursor-pointer rounded-full flex items-center justify-center transition-all shadow-lg touch-manipulation active:scale-95 ${input.trim() && !isLoading
                                ? 'bg-green-500 hover:bg-green-600 active:bg-green-700'
                                : 'bg-[#373435] hover:bg-[#4a4a4a] active:bg-[#555]'
                                }`}
                        >
                            <Send className={`w-5 h-5 ml-[2px] ${input.trim() && !isLoading ? 'text-white' : 'text-gray-400'}`} />
                        </div>
                    </div>
                    <p className="text-[11px] text-gray-500 mt-2 text-center sm:hidden">
                        Press Enter to send • Shift+Enter for new line
                    </p>
                </div>
            </div>
        </div>
    );
};

export default FloatingChatBox;
