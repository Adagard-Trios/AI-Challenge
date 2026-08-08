'use client';

import { useState, useRef, useEffect } from 'react';
import { Send, Brain, Trash2, Radio } from 'lucide-react';
import { Badge } from './ui/badge';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './Roger.css';
import { API_BASE, apiFetch } from "@/app/lib/api";

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
            const response = await apiFetch(`${API_BASE}/api/rag/chat`, {
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
            await apiFetch(`${API_BASE}/api/rag/clear`, { method: 'POST' });
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
        <div className={`${isOpen ? 'h-[100vh] w-[100vw]' : ''} fixed z-[9999] bottom-0 right-0`}>
            {/* Backdrop */}
            <div
                onClick={() => setIsOpen(false)}
                className={`absolute top-0 left-0 w-screen h-screen bg-black/60 transition-opacity duration-500 ${isOpen ? 'opacity-40 flex' : 'opacity-0 hidden'}`}
            />

            {/* Roger Button.
                Was a <div onClick>: not focusable, not keyboard-operable, and
                announced as "generic" rather than a button. Same for the close,
                clear and send controls, and the domain filters below. */}
            <button
                type="button"
                onClick={toggleChat}
                aria-expanded={isOpen}
                aria-label={isOpen ? "Close Roger assistant" : "Open Roger assistant"}
                className={`${isOpen ? 'translate-y-[100px]' : 'translate-y-0 delay-300'} select-none transition-transform duration-500 ease-in-out absolute bottom-[15px] right-[15px] sm:bottom-[20px] sm:right-[30px] flex items-center justify-center w-fit bg-card ring-[0.5px] ring-border rounded-full cursor-pointer px-[25px] sm:px-[30px] min-h-[44px] shadow-lg hover:bg-muted transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background`}
            >
                <Radio className="w-5 h-5 mr-2 text-primary" />
                <span className="select-none text-card-foreground text-[18px] sm:text-[18px] font-semibold">Roger</span>
            </button>

            {/* Chat Container.
                `scale-0` hides it visually but leaves everything inside it
                focusable and announced -- a keyboard user tabbing the
                dashboard landed in an invisible chat box, and a screen reader
                read out the whole panel. `inert` takes the subtree out of the
                tab order and the accessibility tree while it is closed, which
                is exactly what the visual state already implies. */}
            <div
                inert={!isOpen}
                aria-hidden={!isOpen}
                className={`${isOpen ? 'scale-100 delay-200' : 'scale-0'} roger-scrollbar absolute bottom-0 right-0 sm:bottom-[20px] sm:right-[30px] origin-bottom-right transition-transform duration-500 ease-in-out flex flex-col bg-card ring-[0.5px] ring-border h-[100dvh] w-[100vw] sm:h-[600px] sm:w-[420px] sm:rounded-[12px] justify-center overflow-hidden`}
            >

                {/* Header - with safe area for iPhone notch */}
                <div className="w-full select-none px-[16px] sm:px-[20px] bg-card text-card-foreground flex flex-row justify-between sm:rounded-t-[12px] py-[14px] sm:py-[18px] pt-[max(14px,env(safe-area-inset-top))] h-fit items-center border-b border-border">
                    <div className="flex items-center gap-3">
                        <div className="p-2 rounded-lg bg-primary/20">
                            <Brain className="w-5 h-5 text-primary" />
                        </div>
                        <div>
                            <p className="text-[20px] sm:text-[18px] font-semibold">Roger</p>
                            <p className="text-[12px] text-muted-foreground">Intelligence Assistant</p>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        <button
                            type="button"
                            onClick={clearHistory}
                            className="cursor-pointer bg-card hover:bg-destructive/20 min-h-[44px] min-w-[44px] flex items-center justify-center rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            title="Clear chat history"
                            aria-label="Clear chat history"
                        >
                            <Trash2 className="w-4 h-4 text-muted-foreground hover:text-destructive" />
                        </button>
                        <button
                            type="button"
                            onClick={toggleChat}
                            aria-label="Close Roger assistant"
                            className="cursor-pointer bg-card hover:bg-muted active:bg-muted min-h-[44px] px-[14px] sm:px-[12px] rounded-[8px] sm:rounded-[6px] transition-colors touch-manipulation text-[14px] sm:text-[13px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                            Close
                        </button>
                    </div>
                </div>

                {/* Domain Filter - scrollable on mobile */}
                {/* Radio group semantics: these are mutually exclusive filters,
                    so aria-pressed on real buttons says which one is active.
                    As <Badge onClick> they were unfocusable divs and the
                    selected state was conveyed by colour alone. */}
                <div
                    role="group"
                    aria-label="Filter by domain"
                    className="flex gap-1.5 sm:gap-1 px-3 sm:px-4 py-3 bg-muted/40 border-b border-border overflow-x-auto sm:flex-wrap intel-scrollbar"
                >
                    {[{ key: null, label: "All" }, ...domains.map(d => ({ key: d, label: d }))].map(
                        ({ key, label }) => (
                            <button
                                key={label}
                                type="button"
                                onClick={() => setDomainFilter(key)}
                                aria-pressed={domainFilter === key}
                                className={`cursor-pointer text-xs whitespace-nowrap rounded-full px-3 py-1.5 sm:px-2 sm:py-1 capitalize transition-colors touch-manipulation focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${domainFilter === key
                                    ? 'bg-primary text-primary-foreground'
                                    : 'bg-card text-muted-foreground hover:bg-muted active:bg-muted'
                                    }`}
                            >
                                {label}
                            </button>
                        ),
                    )}
                </div>

                {/* Messages Container */}
                {messages.length > 0 ? (
                    <div
                        className="flex flex-col flex-1 overflow-y-auto py-4 px-4 bg-background roger-scrollbar"
                        ref={scrollContainerRef}
                        style={{
                            WebkitOverflowScrolling: 'touch',
                            overscrollBehavior: 'contain',
                        }}
                    >
                        {/* Today Badge */}
                        <div className="flex justify-center mt-1 mb-4">
                            <div className="bg-card text-[11px] px-3 py-1 rounded-full border border-border">
                                <p className="text-muted-foreground">Today</p>
                            </div>
                        </div>

                        {messages.map((msg) => (
                            <div
                                className={`flex mb-3 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                                key={msg.id}
                            >
                                <div
                                    className={`max-w-[85%] rounded-[10px] py-[10px] px-[14px] text-[14px] leading-relaxed ${msg.role === 'user'
                                        ? 'bg-primary text-primary-foreground'
                                        : 'bg-muted text-foreground border border-border'
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
                                        <div className="mt-2 pt-2 border-t border-border">
                                            <p className="text-[11px] text-muted-foreground mb-1">Sources:</p>
                                            <div className="flex flex-wrap gap-1">
                                                {msg.sources.slice(0, 3).map((src, i) => (
                                                    <span
                                                        key={i}
                                                        className="text-[10px] bg-muted text-muted-foreground px-2 py-0.5 rounded"
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
                    <div className="flex-1 flex flex-col justify-center items-center bg-background px-6">
                        <div className="p-4 rounded-full bg-primary/10 mb-4">
                            <Radio className="w-12 h-12 text-primary opacity-50" />
                        </div>
                        <div className="text-muted-foreground text-center max-w-[280px]">
                            <p className="text-[16px] mb-3 leading-relaxed">
                                Hello! I&apos;m <strong>Roger</strong>, your intelligence assistant.
                            </p>
                            <p className="text-[14px] text-muted-foreground leading-relaxed">
                                Ask me anything about Sri Lanka&apos;s political, economic, weather, or social intelligence data.
                            </p>
                            {/* Was text-gray-500 on #101010: 3.9:1, below WCAG
                                AA, at 12px. --muted-foreground is tuned to pass
                                in both themes. */}
                            <div className="mt-4 space-y-2 text-[12px] text-muted-foreground">
                                <p>Try asking:</p>
                                <p className="italic">&ldquo;What are the latest political events?&rdquo;</p>
                                <p className="italic">&ldquo;Any weather warnings today?&rdquo;</p>
                            </div>
                        </div>
                    </div>
                )}

                {/* Input Area - with safe area for bottom */}
                <div className="w-full ring-1 ring-border sm:rounded-b-[12px] py-[10px] sm:py-[12px] px-[12px] pb-[max(10px,env(safe-area-inset-bottom))] bg-card">
                    <div className="relative">
                        <textarea
                            onKeyDown={handleKeyDown}
                            onChange={(e) => setInput(e.target.value)}
                            value={input}
                            disabled={isLoading}
                            className="w-full focus:outline-none focus:ring-2 focus:ring-ring min-h-[50px] max-h-[100px] leading-[22px] rounded-[10px] bg-background text-foreground py-[12px] px-[14px] pr-[60px] resize-none text-[15px] placeholder:text-muted-foreground disabled:opacity-50"
                            placeholder="Ask Roger..."
                            rows={2}
                            style={{ fontSize: '16px' }}
                        />
                        <button
                            type="button"
                            onClick={sendMessage}
                            disabled={!input.trim() || isLoading}
                            aria-label="Send message"
                            className={`absolute top-[6px] right-[6px] w-[44px] h-[44px] sm:w-[42px] sm:h-[42px] ring-[0.5px] ring-border cursor-pointer rounded-full flex items-center justify-center transition-all shadow-lg touch-manipulation active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed ${input.trim() && !isLoading
                                ? 'bg-primary hover:bg-primary/90 active:bg-primary/80'
                                : 'bg-card hover:bg-muted active:bg-muted'
                                }`}
                        >
                            <Send className={`w-5 h-5 ml-[2px] ${input.trim() && !isLoading ? 'text-primary-foreground' : 'text-muted-foreground'}`} />
                        </button>
                    </div>
                    <p className="text-[11px] text-muted-foreground mt-2 text-center sm:hidden">
                        Press Enter to send • Shift+Enter for new line
                    </p>
                </div>
            </div>
        </div>
    );
};

export default FloatingChatBox;
