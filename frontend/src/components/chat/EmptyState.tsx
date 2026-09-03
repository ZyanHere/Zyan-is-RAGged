// EmptyState — shown before any messages exist

interface EmptyStateProps {
  onPromptClick: (prompt: string) => void;
}

const SUGGESTED_PROMPTS = [
  "Summarise the key points of my document",
  "What are the main findings?",
  "List the action items mentioned",
  "Explain this in simple terms",
];

export function EmptyState({ onPromptClick }: EmptyStateProps) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-8 px-4 py-16 text-center">
      {/* Logo mark */}
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-500 to-violet-600 shadow-lg">
        <svg
          className="h-8 w-8 text-white"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M9 12h6M9 16h6M17 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V5a2 2 0 00-2-2z" />
          <path d="M13 3v4h4" />
        </svg>
      </div>

      <div className="space-y-2">
        <h2 className="text-xl font-semibold text-neutral-800">
          Ask anything about your documents
        </h2>
        <p className="text-sm text-neutral-500 max-w-xs">
          Upload a document and ask questions. Every answer will be grounded in
          your source material with citations.
        </p>
      </div>

      {/* Suggested prompts */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-lg">
        {SUGGESTED_PROMPTS.map((prompt) => (
          <button
            key={prompt}
            onClick={() => onPromptClick(prompt)}
            className="rounded-xl border border-neutral-200 bg-white px-4 py-3 text-sm text-left text-neutral-600 hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 transition-all shadow-sm"
          >
            {prompt}
          </button>
        ))}
      </div>
    </div>
  );
}
