import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { HistoryItem, Theme } from "./types";

interface AppContextValue {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  history: HistoryItem[];
  addHistory: (item: Omit<HistoryItem, "id" | "createdAt">) => void;
  removeHistory: (id: string) => void;
  apiBase: string;
  setApiBase: (value: string) => void;
  apiKey: string;
  setApiKey: (value: string) => void;
}

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => (localStorage.getItem("sdm.theme") as Theme) || "dark");
  const [history, setHistory] = useState<HistoryItem[]>(() => JSON.parse(localStorage.getItem("sdm.history") || "[]"));
  const [apiBase, setApiBaseState] = useState(() => localStorage.getItem("sdm.apiBase") || "");
  const [apiKey, setApiKeyState] = useState(() => localStorage.getItem("sdm.apiKey") || "");

  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem("sdm.theme", theme); }, [theme]);
  useEffect(() => localStorage.setItem("sdm.history", JSON.stringify(history.slice(0, 50))), [history]);
  const setTheme = (value: Theme) => setThemeState(value);
  const setApiBase = (value: string) => { setApiBaseState(value); localStorage.setItem("sdm.apiBase", value); };
  const setApiKey = (value: string) => { setApiKeyState(value); localStorage.setItem("sdm.apiKey", value); };
  const addHistory = (item: Omit<HistoryItem, "id" | "createdAt">) => setHistory((items) => [{ ...item, id: crypto.randomUUID(), createdAt: new Date().toISOString() }, ...items]);
  const removeHistory = (id: string) => setHistory((items) => items.filter((item) => item.id !== id));
  const value = useMemo(() => ({ theme, setTheme, history, addHistory, removeHistory, apiBase, setApiBase, apiKey, setApiKey }), [theme, history, apiBase, apiKey]);
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp() {
  const value = useContext(AppContext);
  if (!value) throw new Error("useApp must be used inside AppProvider");
  return value;
}
