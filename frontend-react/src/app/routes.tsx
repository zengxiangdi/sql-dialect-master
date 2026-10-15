import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Shell } from "../components/Shell";
import { ConvertPage } from "../features/ConvertPage";
import { Nl2SqlPage } from "../features/Nl2SqlPage";
import { HistoryPage } from "../features/HistoryPage";

// Keep the first-load workspace focused on conversion and NL2SQL. Library,
// analysis, and settings screens are independent route chunks and are loaded
// only when the user opens them.
const { FunctionsPage, TypesPage } = {
  FunctionsPage: lazy(() => import("../features/LibraryPages").then((module) => ({ default: module.FunctionsPage }))),
  TypesPage: lazy(() => import("../features/LibraryPages").then((module) => ({ default: module.TypesPage }))),
};
const { AnalysisPage, DiffPage, LineagePage, RuntimePage, TemplatesPage } = {
  AnalysisPage: lazy(() => import("../features/UtilityPages").then((module) => ({ default: module.AnalysisPage }))),
  DiffPage: lazy(() => import("../features/UtilityPages").then((module) => ({ default: module.DiffPage }))),
  LineagePage: lazy(() => import("../features/UtilityPages").then((module) => ({ default: module.LineagePage }))),
  RuntimePage: lazy(() => import("../features/UtilityPages").then((module) => ({ default: module.RuntimePage }))),
  TemplatesPage: lazy(() => import("../features/UtilityPages").then((module) => ({ default: module.TemplatesPage }))),
};
const SettingsPage = lazy(() => import("../features/SettingsPage").then((module) => ({ default: module.SettingsPage })));

export function AppRoutes() {
  return <Suspense fallback={<div className="loading-line" role="status">Loading workspace…</div>}><Routes><Route element={<Shell />}><Route path="/convert" element={<ConvertPage />} /><Route path="/nl2sql" element={<Nl2SqlPage />} /><Route path="/diff" element={<DiffPage />} /><Route path="/analysis" element={<AnalysisPage />} /><Route path="/lineage" element={<LineagePage />} /><Route path="/runtime" element={<RuntimePage />} /><Route path="/functions" element={<FunctionsPage />} /><Route path="/types" element={<TypesPage />} /><Route path="/templates" element={<TemplatesPage />} /><Route path="/history" element={<HistoryPage />} /><Route path="/settings" element={<SettingsPage />} /><Route path="*" element={<Navigate to="/convert" replace />} /></Route></Routes></Suspense>;
}
