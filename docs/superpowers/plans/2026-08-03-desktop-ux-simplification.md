# 桌面端体验简化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有微信回复工作台重构为三模式、单主操作、可自检、可搜索且支持后台托盘运行的桌面应用。

**Architecture:** 后端新增纯映射函数与运行检查接口，继续复用现有发送和持久化链路；渲染端把模式、推荐动作和置信度展示提取为可测试的纯函数，并重组工作台与设置页；Electron 主进程负责窗口尺寸、外链、托盘和有限通知。所有新增行为先由失败测试定义，再以最小实现通过。

**Tech Stack:** Python 3、标准库 HTTP 服务、pytest、Electron 39、React 19、TypeScript 5、Vite 7、Node 静态测试。

---

### Task 1: 运行模式与就绪检查

**Files:**
- Modify: `summer_camp_agent/desktop_settings.py`
- Modify: `summer_camp_agent/workbench_api.py`
- Modify: `summer_camp_agent/workbench_server.py`
- Test: `tests/test_desktop_settings.py`
- Test: `tests/test_workbench_api.py`

- [x] **Step 1: 写入失败测试**

验证三种业务模式与现有 `send_mode`、`debug_review_mode` 的双向映射，并验证运行检查至少返回引擎、目标群、AI 配置和总体状态。

- [x] **Step 2: 运行测试并确认按预期失败**

Run: `python -m pytest tests/test_desktop_settings.py tests/test_workbench_api.py -q`

Expected: FAIL，提示模式映射或 `get_readiness` 尚不存在。

- [x] **Step 3: 实现最小后端能力**

增加 `operation_profile` 映射辅助函数和 `/api/app/readiness` 只读接口；AI 检查只验证必要配置存在，不发起计费请求。

- [x] **Step 4: 运行定向测试**

Run: `python -m pytest tests/test_desktop_settings.py tests/test_workbench_api.py -q`

Expected: PASS。

### Task 2: 可测试的前端决策模型

**Files:**
- Create: `desktop/src/renderer/workbench-ux.ts`
- Modify: `desktop/tests/static.test.mjs`
- Modify: `desktop/src/shared/types.ts`

- [x] **Step 1: 写入失败的静态契约测试**

要求源码包含三个业务模式、推荐动作、置信度等级、搜索过滤、快捷键和运行检查类型。

- [x] **Step 2: 运行桌面测试并确认失败**

Run: `npm test --prefix desktop`

Expected: FAIL，提示缺少新的 UX 模块或契约。

- [x] **Step 3: 实现纯函数与共享类型**

实现模式映射、置信度等级、推荐主操作、消息搜索和安全 URL 提取，供 React 界面统一调用。

- [x] **Step 4: 运行桌面测试与类型检查**

Run: `npm test --prefix desktop && npm run typecheck --prefix desktop`

Expected: PASS。

### Task 3: 工作台交互重构

**Files:**
- Modify: `desktop/src/renderer/App.tsx`
- Modify: `desktop/src/renderer/styles.css`

- [x] **Step 1: 扩充失败的界面契约测试**

要求工作台包含运行检查、统一监听按钮、队列搜索、一个主操作、更多操作、折叠技术详情和键盘提示。

- [x] **Step 2: 运行测试并确认失败**

Run: `npm test --prefix desktop`

Expected: FAIL，提示界面文案或结构尚未实现。

- [x] **Step 3: 重组 React 状态和视图**

加入忙碌态与短时反馈，处理完成后刷新并选中下一条；使用纯函数确定推荐动作；隐藏开发术语和未完成入口。

- [x] **Step 4: 完成响应式和可访问样式**

统一间距、焦点、状态文本和窄屏降级，确保按钮、搜索框、折叠详情均可键盘访问。

- [x] **Step 5: 运行桌面测试和类型检查**

Run: `npm test --prefix desktop && npm run typecheck --prefix desktop`

Expected: PASS。

### Task 4: 设置、外链、托盘和通知

**Files:**
- Modify: `desktop/src/main/main.ts`
- Modify: `desktop/src/preload/preload.ts`
- Modify: `desktop/src/preload/preload.cjs`
- Modify: `desktop/src/renderer/App.tsx`
- Modify: `desktop/src/shared/types.ts`
- Modify: `summer_camp_agent/desktop_settings.py`

- [x] **Step 1: 写入失败的桌面契约测试**

要求默认大窗口、托盘菜单、受限外链 IPC、基础/高级设置结构和仅异常通知策略。

- [x] **Step 2: 运行测试并确认失败**

Run: `npm test --prefix desktop`

Expected: FAIL，提示主进程或预加载契约缺失。

- [x] **Step 3: 实现 Electron 能力**

主窗口默认 `1180×760`，最小 `960×680`；关闭时驻留托盘；新增待审核或服务异常时通知；外链协议白名单后交由系统浏览器打开。

- [x] **Step 4: 简化设置页**

基础区只保留目标群和业务模式；关键词、轮询和只读 API 信息收进高级折叠区；使用单一保存入口。

- [x] **Step 5: 运行桌面测试、类型检查和构建**

Run: `npm test --prefix desktop && npm run typecheck --prefix desktop && npm run build --prefix desktop`

Expected: PASS。

### Task 5: 完整回归与验收

**Files:**
- Modify: `docs/superpowers/plans/2026-08-03-desktop-ux-simplification.md`

- [x] **Step 1: 运行完整 Python 测试**

Run: `python -m pytest -q`

Expected: 全部通过且 0 failures。

- [x] **Step 2: 运行完整桌面验证**

Run: `npm test --prefix desktop && npm run typecheck --prefix desktop && npm run build --prefix desktop`

Expected: 三条命令退出码均为 0。

- [x] **Step 3: 对照设计逐项复核**

检查三模式、运行检查、单主操作、搜索、忙碌反馈、来源外链、设置简化、大窗口、托盘通知、快捷键和历史记录均有对应实现。

- [x] **Step 4: 检查工作区和敏感信息**

Run: `git status --short && git diff --check`

Expected: 仅包含本功能相关源码、测试和中文文档，且无空白错误或密钥。
