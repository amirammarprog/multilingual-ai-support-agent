import { useCallback, useEffect, useState } from "react";

export function useTheme(): { dark: boolean; toggle: () => void } {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try {
      localStorage.setItem("theme", dark ? "dark" : "light");
    } catch {
      /* ignore */
    }
  }, [dark]);

  const toggle = useCallback(() => setDark((d) => !d), []);
  return { dark, toggle };
}
