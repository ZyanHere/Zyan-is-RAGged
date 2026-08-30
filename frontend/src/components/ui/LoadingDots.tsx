// LoadingDots — animated "thinking" indicator

export function LoadingDots() {
  return (
    <div className="flex items-center gap-1 px-1 py-2" aria-label="Assistant is thinking">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="block h-2 w-2 rounded-full bg-neutral-400 animate-bounce"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </div>
  );
}
