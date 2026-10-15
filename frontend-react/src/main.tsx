import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { AppProvider } from "./lib/app-context";
import { AppRoutes } from "./app/routes";
import "./styles/global.css";

ReactDOM.createRoot(document.getElementById("root")!).render(<React.StrictMode><BrowserRouter><AppProvider><AppRoutes /></AppProvider></BrowserRouter></React.StrictMode>);
