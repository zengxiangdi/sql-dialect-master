# React 前端重构目标与实施计划

## 目标

SQL Dialect Master 的主前端重构为 React + TypeScript 开发工作台，围绕 SQL 转换任务组织信息和交互。Convert 是首屏主任务，NL2SQL、Diff、Lineage、Query Analysis 构成分析工作区，Functions、Types、Templates、History 构成知识与资产库。

React 应用放在 `frontend-react/`，默认开发端口为 `5174`，现在是唯一产品前端。后端 API 和 Python SDK 保持兼容，React 不依赖真实数据库即可完成转换、解析、NL2SQL、函数查询和类型查询演示。

## 体验目标

- 采用深色优先的专业开发工具视觉：三层深色背景、蓝色主色、绿色成功、黄色提醒、红色错误；支持浅色主题。
- 使用可折叠侧栏、顶部命令栏、面包屑、可拖拽编辑器分栏和统一状态反馈，降低页面切换成本。
- SQL 编辑区使用等宽字体、清晰的行高和焦点状态，提供 Format、Convert、Copy、Download、Open Diff 等连续操作。
- 所有异步请求都有 loading、empty、error、鉴权失败、503、504 和 retry 状态；旧结果在输入变化后清除或标记为 stale。
- 支持键盘操作：`Cmd/Ctrl + K` 打开命令面板，`Cmd/Ctrl + Enter` 执行主任务，Escape 关闭浮层，所有控件有可见焦点。
- 通过 `localStorage` 保留主题、API 地址、草稿和历史记录；跨页面跳转通过 URL 参数携带 SQL 与方言，刷新后仍可恢复。

## 页面范围

| 页面 | 首版交付 |
| --- | --- |
| Convert | 双编辑器、12 方言、交换方言、格式化、转换、复制、下载、结果元数据、历史保存 |
| NL2SQL | 中文/英文输入、方言、表提示、示例、置信度、evidence、生成 SQL、送入 Convert/Diff |
| Semantic Diff | 源/目标编辑器、文本 Diff、结果状态、warning/error、从 Convert 带入 |
| Query Analysis | 静态解析指标、表/列/Join/函数/过滤条件，明确静态分析边界 |
| Lineage | 静态表和列关系展示，暂无真实执行计划 |
| Functions | 搜索、分类、方言对照、详情抽屉 |
| Types | 类型矩阵、源/目标筛选、映射状态、详情 |
| Templates | 分类卡片、SQL 预览、Use in Convert |
| History | 搜索、状态筛选、重用、删除、收藏、分页 |
| Settings | API 地址、API Key、主题、快捷键和版本信息 |
| Runtime | 未配置数据库时显示清晰的静态分析边界和配置提示 |

## 技术与目录

```text
frontend-react/
├── src/
│   ├── app/              # Router、AppShell、providers、错误边界
│   ├── components/       # Button、Card、Badge、Editor、Modal、Toast 等
│   ├── features/         # convert、nl2sql、diff、library、history、settings
│   ├── lib/api/          # typed client、请求错误、API response types
│   ├── stores/           # theme、workspace、history、settings
│   └── styles/           # design tokens、全局样式、响应式布局
├── index.html
├── package.json
├── tsconfig.json
└── vite.config.ts
```

基线采用 Vite、React、TypeScript、React Router、Lucide React；请求层保持轻量，统一处理 `X-API-Key`、Bearer Token、`X-Request-ID`、超时、Retry-After 和错误码。Monaco 等大型编辑器依赖放在后续迭代，首版使用可访问的原生 textarea 编辑器以控制首屏体积。

## 分步计划与完成门

### 0. 基线与契约

- [x] 盘点旧 Python UI 页面、FastAPI API 和现有状态/导航契约。
- [x] 写入本计划、视觉 token、API 错误处理和兼容策略。
- [x] 冻结 React 使用的 API response types，并为未提供 REST API 的 Diff/Lineage/Analysis 标记本地静态计算边界。

### 1. React 壳层

- [x] 建立 Vite + React + TypeScript 项目和 npm lockfile。
- [x] 完成 AppShell、侧栏、顶部栏、主题、命令面板、响应式布局和基础错误提示。
- [x] 完成 design tokens、Button/Input/Select/Card/Badge/EmptyState/ErrorPanel 等基础组件。

### 2. Convert MVP

- [x] 完成 typed API client、dialect metadata、API 状态和 API Key 设置。
- [x] 完成双编辑器、方言交换、Convert、Copy、Download 和结果报告。
- [x] 完成草稿恢复、stale result 提示、超时/503/504 错误展示和本地历史写入。

### 3. 分析工作区

- [x] 完成 NL2SQL 生成、置信度/evidence、错误解释和 Convert handoff。
- [x] 完成 Semantic Diff 编辑器和静态分析边界提示。
- [x] 完成 Query Analysis、Lineage 和 Runtime 的无数据库体验；Query Analysis/Lineage 已接入 `/api/parse`。

### 4. 资产库

- [x] 完成 Functions 搜索/分类基础视图。
- [x] 完成 Types 矩阵/映射状态基础视图。
- [x] 完成 Templates 预览和 Use in Convert。
- [x] 完成 History 搜索、删除、复制和本地持久化。

### 5. 质量与发布

- [x] 添加 Vitest + Testing Library 基线测试，覆盖方言注册表和 Convert 壳层渲染。
- [ ] 添加 Playwright 或等价的浏览器验收，覆盖 Convert、NL2SQL、主题、命令面板和模板回填。
- [x] 添加 TypeScript strict、ESLint、npm build 检查和前端 CI job。
- [x] 更新 README、CONTRIBUTING 和 React workspace README；React 成为唯一产品入口。

## 验收标准

```bash
npm --prefix frontend-react run lint
npm --prefix frontend-react run typecheck
npm --prefix frontend-react run test
npm --prefix frontend-react run build
.venv/bin/python -m pytest -q
```

功能验收要求 12 方言可选、Convert/NL2SQL/Diff/Lineage/Analysis/Functions/Types/Templates/History/Settings 全可达，错误与空状态可恢复，输入编辑不会展示旧结果，跨页 SQL/方言不丢失。视觉验收要求桌面和窄屏可用，键盘路径完整，焦点和对比度可见，首屏构建产物保持轻量。发布前必须确保 Python 回归测试和 React 构建检查通过。

## 当前实施状态

当前重构已完成并可独立构建。React 通过独立静态站点部署，是唯一产品前端；Python wheel 仅包含后端运行包。
