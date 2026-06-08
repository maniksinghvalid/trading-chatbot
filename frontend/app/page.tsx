import ChatWindow from "@/components/ChatWindow";

/**
 * Home page — server component that renders the ChatWindow client component.
 * The ChatWindow manages all streaming state client-side.
 */
export default function Home() {
  return (
    <main className="flex min-h-screen flex-col">
      <header className="border-b border-gray-800 px-4 py-3 flex items-center gap-3">
        <span className="text-lg font-semibold text-white">Trading Chatbot</span>
        <span className="text-xs text-gray-500 hidden sm:block">
          Pinecone RAG · SSE streaming
        </span>
      </header>
      <div className="flex-1 flex flex-col">
        <ChatWindow />
      </div>
    </main>
  );
}
