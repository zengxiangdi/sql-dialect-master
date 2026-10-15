import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { HistoryItem, Theme } from "./types";

interface AppContextValue {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  history: HistoryItem[];
  addHistory: (item: Omit<HistoryItem, "id" | "createdAt">) => void;
  removeHistory: (id: string) => void;
  clearHistory: () => void;
  apiBase: string;
  setApiBase: (value: string) => void;
  apiKey: string;
  setApiKey: (value: string) => void;
}

const AppContext = createContext<AppContextValue | null>(null);

function readHistory(): HistoryItem[] {
  try {
    const value = JSON.parse(localStorage.getItem("sdm.history") || "[]");
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => (localStorage.getItem("sdm.theme") as Theme) || "dark");
  const [history, setHistory] = useState<HistoryItem[]>(readHistory);
  const [apiBase, setApiBaseState] = useState(() => localStorage.getItem("sdm.apiBase") || "");
  const [apiKey, setApiKeyState] = useState(() => localStorage.getItem("sdm.apiKey") || "");

  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem("sdm.theme", theme); }, [theme]);
  useEffect(() => localStorage.setItem("sdm.history", JSON.stringify(history.slice(0, 50))), [history]);
  const setTheme = (value: Theme) => setThemeState(value);
  const setApiBase = (value: string) => { setApiBaseState(value); localStorage.setItem("sdm.apiBase", value); };
  const setApiKey = (value: string) => { setApiKeyState(value); localStorage.setItem("sdm.apiKey", value); };
  const addHistory = (item: Omit<HistoryItem, "id" | "createdAt">) => {
    const id = crypto.randomUUID?.() || `history-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    setHistory((items) => [{ ...item, id, createdAt: new Date().toISOString() }, ...items]);
  };
  const removeHistory = (id: string) => setHistory((items) => items.filter((item) => item.id !== id));
  const clearHistory = () => setHistory([]);
  const value = useMemo(() => ({ theme, setTheme, history, addHistory, removeHistory, clearHistory, apiBase, setApiBase, apiKey, setApiKey }), [theme, history, apiBase, apiKey]);
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp() {
  const value = useContext(AppContext);
  if (!value) throw new Error("useApp must be used inside AppProvider");
  return value;
}
