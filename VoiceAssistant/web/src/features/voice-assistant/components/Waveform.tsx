import { useEffect, useState } from "react";

import styles from "./Waveform.module.css";

export interface WaveformProps {
  active: boolean;
  stream?: MediaStream | null;
  className?: string;
}

const BAR_COUNT = 16;
const IDLE_LEVELS = Array<number>(BAR_COUNT).fill(0.2);

export default function Waveform({
  active,
  stream,
  className = "",
}: WaveformProps) {
  const [levels, setLevels] = useState<number[]>(IDLE_LEVELS);
  const useAnalyser = active && Boolean(stream);

  useEffect(() => {
    if (!active || !stream || typeof AudioContext === "undefined") return;

    const context = new AudioContext();
    const source = context.createMediaStreamSource(stream);
    const analyser = context.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);

    const data = new Uint8Array(analyser.frequencyBinCount);
    let frame = 0;

    const tick = () => {
      analyser.getByteFrequencyData(data);
      setLevels(
        Array.from({ length: BAR_COUNT }, (_, index) => {
          const start = Math.floor((index / BAR_COUNT) * data.length);
          const end = Math.floor(((index + 1) / BAR_COUNT) * data.length);
          let total = 0;
          for (let i = start; i < end; i += 1) total += data[i];
          const average = end > start ? total / (end - start) : 0;
          return Math.max(0.2, Math.min(1, average / 160));
        }),
      );
      frame = requestAnimationFrame(tick);
    };

    tick();

    return () => {
      cancelAnimationFrame(frame);
      source.disconnect();
      analyser.disconnect();
      void context.close();
    };
  }, [active, stream]);

  return (
    <div
      className={`${styles.waveform} ${className}`.trim()}
      aria-hidden="true"
    >
      {Array.from({ length: BAR_COUNT }, (_, index) => (
        <span
          key={index}
          className={`${styles.bar} ${
            useAnalyser
              ? styles.analyserBar
              : active
                ? styles.animatedBar
                : ""
          }`}
          style={
            useAnalyser
              ? { transform: `scaleY(${levels[index]})` }
              : { animationDelay: `${index * 60}ms` }
          }
        />
      ))}
    </div>
  );
}
