import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ALL_DIALECTS, type HistoryItem, type Theme } from "./types";
import {
  HISTORY_STORAGE_KEY,
  normalizeHistory,
  safeGetJson,
  safeGetItem,
  safeRemoveItem,
  safeSetItem,
  safeSetJson,
} from "./storage";

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
  const value = safeGetJson<unknown>(HISTORY_STORAGE_KEY, []);
  if (!Array.isArray(value)) return [];
  const valid = value.filter((item): item is HistoryItem => Boolean(
    item && typeof item === "object" &&
    typeof item.id === "string" && typeof item.source === "string" &&
    typeof item.target === "string" && ALL_DIALECTS.includes(item.sourceDialect) &&
    ALL_DIALECTS.includes(item.targetDialect) && typeof item.createdAt === "string" &&
    (item.truncated === undefined || typeof item.truncated === "boolean") &&
    (item.status === "success" || item.status === "warning" || item.status === "error" || item.status === "neutral"),
  ));
  return normalizeHistory(valid);
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => (safeGetItem("sdm.theme") as Theme) || "dark");
  const [history, setHistory] = useState<HistoryItem[]>(readHistory);
  const [apiBase, setApiBaseState] = useState(() => safeGetItem("sdm.apiBase") || "");
  const [apiKey, setApiKeyState] = useState(() => safeGetItem("sdm.apiKey") || "");

  useEffect(() => { document.documentElement.dataset.theme = theme; safeSetItem("sdm.theme", theme); }, [theme]);
  useEffect(() => { safeSetJson(HISTORY_STORAGE_KEY, normalizeHistory(history)); }, [history]);
  const setTheme = useCallback((value: Theme) => setThemeState(value), []);
  const setApiBase = useCallback((value: string) => { setApiBaseState(value); safeSetItem("sdm.apiBase", value); }, []);
  const setApiKey = useCallback((value: string) => { setApiKeyState(value); safeSetItem("sdm.apiKey", value); }, []);
  const addHistory = useCallback((item: Omit<HistoryItem, "id" | "createdAt">) => {
    const id = crypto.randomUUID?.() || `history-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    setHistory((items) => normalizeHistory([{ ...item, id, createdAt: new Date().toISOString() }, ...items]));
  }, []);
  const removeHistory = useCallback((id: string) => setHistory((items) => items.filter((item) => item.id !== id)), []);
  const clearHistory = useCallback(() => { setHistory([]); safeRemoveItem(HISTORY_STORAGE_KEY); }, []);
  const value = useMemo(() => ({ theme, setTheme, history, addHistory, removeHistory, clearHistory, apiBase, setApiBase, apiKey, setApiKey }), [theme, setTheme, history, addHistory, removeHistory, clearHistory, apiBase, setApiBase, apiKey, setApiKey]);
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp() {
  const value = useContext(AppContext);
  if (!value) throw new Error("useApp must be used inside AppProvider");
  return value;
}
