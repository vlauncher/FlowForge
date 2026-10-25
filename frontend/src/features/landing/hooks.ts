import { useEffect, useRef, useState } from "react";

const hasIO = () => typeof window !== "undefined" && "IntersectionObserver" in window;

/** Adds the `in` class once the element scrolls into view. */
export function useReveal<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (!hasIO()) {
      el.classList.add("in");
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            e.target.classList.add("in");
            io.unobserve(e.target);
          }
        }
      },
      { threshold: 0.15, rootMargin: "0px 0px -8% 0px" }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return ref;
}

/** Counts from 0 to `target` once visible. */
export function useCountUp(target: number, durationMs = 1600, decimals = 0) {
  const ref = useRef<HTMLSpanElement>(null);
  const [value, setValue] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let raf = 0;
    const run = () => {
      const start = performance.now();
      const step = (now: number) => {
        const t = Math.min(1, (now - start) / durationMs);
        const eased = 1 - Math.pow(1 - t, 4);
        setValue(target * eased);
        if (t < 1) raf = requestAnimationFrame(step);
      };
      raf = requestAnimationFrame(step);
    };
    if (!hasIO()) {
      setValue(target);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          run();
          io.disconnect();
        }
      },
      { threshold: 0.4 }
    );
    io.observe(el);
    return () => {
      io.disconnect();
      cancelAnimationFrame(raf);
    };
  }, [target, durationMs]);
  return { ref, text: value.toFixed(decimals) };
}

/** Writes pointer position into --mx/--my so CSS can paint a spotlight. */
export function useSpotlight<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onMove = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      el.style.setProperty("--mx", `${e.clientX - r.left}px`);
      el.style.setProperty("--my", `${e.clientY - r.top}px`);
    };
    el.addEventListener("pointermove", onMove);
    return () => el.removeEventListener("pointermove", onMove);
  }, []);
  return ref;
}

/** Cycles through `words`, typing and deleting. */
export function useTypewriter(words: string[], typeMs = 70, holdMs = 1500) {
  const [text, setText] = useState(words[0] ?? "");
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    let i = 0;
    let pos = words[0].length;
    let deleting = true;
    let timer = 0;
    const tick = () => {
      const word = words[i];
      if (!deleting) {
        pos++;
        setText(word.slice(0, pos));
        if (pos === word.length) {
          deleting = true;
          timer = window.setTimeout(tick, holdMs);
          return;
        }
      } else {
        pos--;
        setText(word.slice(0, Math.max(pos, 0)));
        if (pos <= 0) {
          deleting = false;
          i = (i + 1) % words.length;
        }
      }
      timer = window.setTimeout(tick, deleting ? typeMs / 2 : typeMs);
    };
    timer = window.setTimeout(tick, holdMs);
    return () => window.clearTimeout(timer);
  }, [words, typeMs, holdMs]);
  return text;
}
