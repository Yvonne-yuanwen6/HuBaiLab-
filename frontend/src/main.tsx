import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "./layout/AppLayout";
import { CadGeneratePage } from "./pages/CadGenerate";
import { CaseDetailPage } from "./pages/CaseDetail";
import { CasesPage } from "./pages/Cases";
import { DashboardPage } from "./pages/Dashboard";
import { ExportPage } from "./pages/Export";
import { MonitorPage } from "./pages/Monitor";
import { QueuePage } from "./pages/Queue";
import { TrashPage } from "./pages/Trash";
import "antd/dist/reset.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 5000, retry: 1 },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ConfigProvider locale={zhCN}>
        <BrowserRouter>
          <Routes>
            <Route element={<AppLayout />}>
              <Route index element={<DashboardPage />} />
              <Route path="cases" element={<CasesPage />} />
              <Route path="cases/:slug" element={<CaseDetailPage />} />
              <Route path="cad" element={<CadGeneratePage />} />
              <Route path="export" element={<ExportPage />} />
              <Route path="queue" element={<QueuePage />} />
              <Route path="monitor" element={<MonitorPage />} />
              <Route path="trash" element={<TrashPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </ConfigProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
