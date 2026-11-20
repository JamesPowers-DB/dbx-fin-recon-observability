import { useEffect, useRef, useState, type RefObject } from "react";

/** Width of a container element, updated on resize (for SVG charts). */
export function useWidth<T extends HTMLElement>(fallback = 600): [RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const cw = Math.floor(entries[0].contentRect.width);
      if (cw > 0) setW(cw);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}
