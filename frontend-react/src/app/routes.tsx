import { Navigate, Route, Routes } from "react-router-dom";
import { Shell } from "../components/Shell";
import { ConvertPage } from "../features/ConvertPage";
import { Nl2SqlPage } from "../features/Nl2SqlPage";
import { FunctionsPage, TypesPage } from "../features/LibraryPages";
import { AnalysisPage, DiffPage, HistoryPage, LineagePage, RuntimePage, TemplatesPage } from "../features/UtilityPages";
import { SettingsPage } from "../features/SettingsPage";

export function AppRoutes() { return <Routes><Route element={<Shell />}><Route path="/convert" element={<ConvertPage />} /><Route path="/nl2sql" element={<Nl2SqlPage />} /><Route path="/diff" element={<DiffPage />} /><Route path="/analysis" element={<AnalysisPage />} /><Route path="/lineage" element={<LineagePage />} /><Route path="/runtime" element={<RuntimePage />} /><Route path="/functions" element={<FunctionsPage />} /><Route path="/types" element={<TypesPage />} /><Route path="/templates" element={<TemplatesPage />} /><Route path="/history" element={<HistoryPage />} /><Route path="/settings" element={<SettingsPage />} /><Route path="*" element={<Navigate to="/convert" replace />} /></Route></Routes>; }
