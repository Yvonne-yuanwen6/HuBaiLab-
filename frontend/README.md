# HuBaiLab 前端

React + Vite + TypeScript + Ant Design。

**用户使用说明**（安装、**启动**、页面、工作流、API）：[`docs/Abaqus_WebUI使用说明.md`](../docs/Abaqus_WebUI使用说明.md) — 见 **§2 启动方式**。

## 开发

先按文档 §2.0 完成 `npm install`，再启动（API 须在另一终端运行于 `:8000`）：

```powershell
cd D:\HuBaiLab\frontend
npm run dev    # http://localhost:5173 ，/api 代理到 :8000
```

## 构建

```powershell
npm run build  # 输出 frontend/dist/，由 FastAPI 单进程托管见文档 §2.2
```

## 维护文档

修改页面、组件或 `src/api/client.ts` 中 API 调用时，请同步更新 [`docs/Abaqus_WebUI使用说明.md`](../docs/Abaqus_WebUI使用说明.md) 对应章节（见该文档 §9）。
