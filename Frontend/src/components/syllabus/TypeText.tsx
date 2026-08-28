import { useEffect, useState } from "react";

/** Streaming-style reveal for bot answers. */
export function TypeText({
  text,
  speed = 12,
  animate = true,
  className,
}: {
  text: string;
  speed?: number;
  animate?: boolean;
  className?: string;
}) {
  const [count, setCount] = useState(animate ? 0 : text.length);

  useEffect(() => {
    if (!animate) {
      setCount(text.length);
      return;
    }
    setCount(0);
    let i = 0;
    const id = setInterval(() => {
      i += 3;
      if (i >= text.length) {
        setCount(text.length);
        clearInterval(id);
      } else {
        setCount(i);
      }
    }, speed);
    return () => clearInterval(id);
  }, [text, speed, animate]);

  const done = count >= text.length;

  return (
    <p className={className}>
      {text.slice(0, count)}
      {!done && <span className="ml-0.5 inline-block h-4 w-2 translate-y-0.5 bg-primary" />}
    </p>
  );
}
