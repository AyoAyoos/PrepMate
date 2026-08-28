export function ThinkingIndicator() {
  return (
    <div className="inline-flex items-center gap-3 border-2 border-foreground bg-card px-4 py-3 shadow-brutal-sm">
      <span className="relative flex size-5 items-center justify-center">
        <span className="absolute inset-0 animate-spin rounded-full border-2 border-foreground border-t-transparent" />
        <span className="size-1.5 rounded-full bg-primary" />
      </span>
      <span className="text-[11px] font-black uppercase tracking-widest">
        Retrieving &amp; generating…
      </span>
    </div>
  );
}
