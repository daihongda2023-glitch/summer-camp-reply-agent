# WeChat 调试配置页面开关 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 增加由本地配置文件持久化控制的页面调试配置开关，开启后可在工作台页面配置群聊关键字和 `session_id`。

**Architecture:** 在 `WeChatBridgeConfig` 中新增可选布尔字段 `show_debug_config`，默认关闭并随配置文件读写。工作台新增 `GET /api/wechat/config` 读取当前配置，页面加载后按该字段决定是否展示调试配置区；保存配置时使用已加载配置作为基础，避免隐藏字段被覆盖为空。

**Tech Stack:** Python dataclass、`http.server`、内嵌 HTML/CSS/JavaScript、`unittest`。

---

## 文件结构

- `summer_camp_agent/wechat_bridge_config.py`：配置模型、配置文件读写和字段校验。
- `tests/test_wechat_bridge_config.py`：配置模型和配置文件持久化测试。
- `summer_camp_agent/workbench_web.py`：工作台状态、HTTP 路由、内嵌页面。
- `tests/test_workbench_web.py`：工作台 API 与页面 HTML 行为测试。

## Task 1: 配置模型持久化 `show_debug_config`

**Files:**
- Modify: `tests/test_wechat_bridge_config.py`
- Modify: `summer_camp_agent/wechat_bridge_config.py`

- [ ] **Step 1: Write the failing tests**

在 `WeChatBridgeConfigTest` 中加入两个测试：

```python
    def test_config_from_dict_defaults_debug_config_to_false(self):
        config = WeChatBridgeConfig.from_dict({"group_name": "test group"})

        self.assertFalse(config.show_debug_config)

    def test_config_store_round_trips_debug_config_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wechat_bridge_config.json"
            store = WeChatBridgeConfigStore(path)
            config = WeChatBridgeConfig(
                group_name="test group",
                session_id="room@chatroom",
                keywords=["signup"],
                poll_interval_seconds=5,
                enabled=True,
                show_debug_config=True,
            )

            store.save(config)
            loaded = store.load()
            raw = json.loads(path.read_text(encoding="utf-8"))

        self.assertTrue(loaded.show_debug_config)
        self.assertTrue(raw["show_debug_config"])
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -B -m unittest tests.test_wechat_bridge_config
```

Expected: FAIL，报错包含 `AttributeError: 'WeChatBridgeConfig' object has no attribute 'show_debug_config'` 或 `TypeError: WeChatBridgeConfig.__init__() got an unexpected keyword argument 'show_debug_config'`。

- [ ] **Step 3: Write minimal implementation**

在 `WeChatBridgeConfig` dataclass 中新增字段：

```python
    show_debug_config: bool = False
```

在 `from_dict()` 构造参数中新增：

```python
            show_debug_config=bool(raw.get("show_debug_config", False)),
```

`to_dict()` 继续使用 `asdict(self)`，不需要额外逻辑。

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
python -B -m unittest tests.test_wechat_bridge_config
```

Expected: PASS。

- [ ] **Step 5: Commit**

```powershell
git -c safe.directory=D:/workspace/codex/自动回复agent add summer_camp_agent/wechat_bridge_config.py tests/test_wechat_bridge_config.py
git -c safe.directory=D:/workspace/codex/自动回复agent commit -m "feat: persist wechat debug config switch"
```

## Task 2: 增加读取当前微信桥接配置的 Web API

**Files:**
- Modify: `tests/test_workbench_web.py`
- Modify: `summer_camp_agent/workbench_web.py`

- [ ] **Step 1: Write the failing tests**

在 `WorkbenchWebWechatBridgeTest` 中加入状态方法测试：

```python
    def test_get_wechat_config_returns_saved_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "wechat_bridge_config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "base_url": "http://127.0.0.1:5031",
                        "token_env": "WEFLOW_API_TOKEN",
                        "group_name": "test group",
                        "session_id": "room@chatroom",
                        "keywords": ["signup"],
                        "poll_interval_seconds": 7,
                        "enabled": True,
                        "show_debug_config": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            state = WorkbenchWebState(
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
                wechat_config_path=config_path,
            )

            payload = state.get_wechat_config()

        self.assertEqual(payload["config"]["session_id"], "room@chatroom")
        self.assertEqual(payload["config"]["keywords"], ["signup"])
        self.assertTrue(payload["config"]["show_debug_config"])
```

在同一个测试类中加入 HTTP 路由测试：

```python
    def test_wechat_config_get_route_returns_current_config(self):
        from http.server import ThreadingHTTPServer
        import threading
        import urllib.request

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "wechat_bridge_config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "base_url": "http://127.0.0.1:5031",
                        "token_env": "WEFLOW_API_TOKEN",
                        "group_name": "test group",
                        "session_id": "room@chatroom",
                        "keywords": ["signup"],
                        "poll_interval_seconds": 7,
                        "enabled": True,
                        "show_debug_config": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            state = WorkbenchWebState(
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
                wechat_config_path=config_path,
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), create_handler(state))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                payload = json.loads(
                    urllib.request.urlopen(
                        f"http://127.0.0.1:{server.server_address[1]}/api/wechat/config",
                        timeout=5,
                    )
                    .read()
                    .decode("utf-8")
                )
            finally:
                server.shutdown()
                server.server_close()

        self.assertEqual(payload["config"]["session_id"], "room@chatroom")
        self.assertTrue(payload["config"]["show_debug_config"])
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -B -m unittest tests.test_workbench_web
```

Expected: FAIL，第一个测试报 `AttributeError: 'WorkbenchWebState' object has no attribute 'get_wechat_config'`。

- [ ] **Step 3: Write minimal implementation**

在 `WorkbenchWebState` 中加入方法：

```python
    def get_wechat_config(self) -> dict[str, Any]:
        return {"config": self.wechat_config.to_dict()}
```

在 `create_handler(...).do_GET()` 中加入路由，放在 `/api/items` 附近：

```python
            if path == "/api/wechat/config":
                self._send_json(state.get_wechat_config())
                return
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
python -B -m unittest tests.test_workbench_web
```

Expected: PASS。

- [ ] **Step 5: Commit**

```powershell
git -c safe.directory=D:/workspace/codex/自动回复agent add summer_camp_agent/workbench_web.py tests/test_workbench_web.py
git -c safe.directory=D:/workspace/codex/自动回复agent commit -m "feat: expose wechat config to workbench"
```

## Task 3: 页面按持久化开关展示调试配置区

**Files:**
- Modify: `tests/test_workbench_web.py`
- Modify: `summer_camp_agent/workbench_web.py`

- [ ] **Step 1: Write the failing HTML tests**

更新 `test_html_exposes_wechat_assisted_controls`，追加这些断言：

```python
        self.assertIn('id="wechatDebugConfig"', WORKBENCH_HTML)
        self.assertIn('id="wechatSessionId"', WORKBENCH_HTML)
        self.assertIn("let currentWechatConfig", WORKBENCH_HTML)
        self.assertIn("loadWechatConfig()", WORKBENCH_HTML)
        self.assertIn("applyWechatConfig", WORKBENCH_HTML)
        self.assertIn("show_debug_config", WORKBENCH_HTML)
        self.assertNotIn("session_id: ''", WORKBENCH_HTML)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -B -m unittest tests.test_workbench_web
```

Expected: FAIL，至少缺少 `wechatDebugConfig` 或 `wechatSessionId`。

- [ ] **Step 3: Write minimal page implementation**

将左侧配置容器改成带 ID 的可隐藏调试区，并新增 `session_id` 输入框：

```html
      <div id="wechatDebugConfig" class="bridge" hidden>
        <label for="wechatGroupName">群聊名称</label>
        <input id="wechatGroupName" value="沐曦开源英才夏令营咨询群">
        <label for="wechatSessionId">Session ID</label>
        <input id="wechatSessionId" value="" placeholder="可选：直接指定 WeFlow session_id">
        <label for="wechatKeywords">关键词</label>
        <input id="wechatKeywords" value="报名,报到,住宿,交通,作业,面试,GPU,算子">
        <label for="wechatPollSeconds">轮询间隔</label>
        <input id="wechatPollSeconds" type="number" min="2" max="60" value="5">
      </div>
```

在脚本状态中加入当前配置缓存：

```javascript
    let currentWechatConfig = {
      base_url: 'http://127.0.0.1:5031',
      token_env: 'WEFLOW_API_TOKEN',
      group_name: '',
      session_id: '',
      keywords: [],
      poll_interval_seconds: 5,
      enabled: true,
      show_debug_config: false
    };
```

新增配置加载和应用函数：

```javascript
    function applyWechatConfig(config) {
      currentWechatConfig = {...currentWechatConfig, ...(config || {})};
      const debugConfig = document.getElementById('wechatDebugConfig');
      debugConfig.hidden = !currentWechatConfig.show_debug_config;
      document.getElementById('wechatGroupName').value = currentWechatConfig.group_name || '';
      document.getElementById('wechatSessionId').value = currentWechatConfig.session_id || '';
      document.getElementById('wechatKeywords').value = (currentWechatConfig.keywords || []).join(',');
      document.getElementById('wechatPollSeconds').value = currentWechatConfig.poll_interval_seconds || 5;
    }

    async function loadWechatConfig() {
      const data = await requestJson('/api/wechat/config');
      applyWechatConfig(data.config);
      return data.config;
    }
```

更新 `readWechatConfig()`，开启调试配置区时读取页面字段，关闭时保留缓存字段：

```javascript
    function readWechatConfig() {
      const config = {...currentWechatConfig};
      if (config.show_debug_config) {
        config.group_name = document.getElementById('wechatGroupName').value.trim();
        config.session_id = document.getElementById('wechatSessionId').value.trim();
        config.keywords = document.getElementById('wechatKeywords').value.split(',').map(x => x.trim()).filter(Boolean);
        config.poll_interval_seconds = Number(document.getElementById('wechatPollSeconds').value || 5);
      }
      return config;
    }
```

更新 `normalizePollIntervalSeconds()`，隐藏调试区时使用缓存配置：

```javascript
    function normalizePollIntervalSeconds() {
      const source = currentWechatConfig.show_debug_config
        ? document.getElementById('wechatPollSeconds').value
        : currentWechatConfig.poll_interval_seconds;
      const raw = Number(source || 5);
      if (!Number.isFinite(raw)) return 5;
      return Math.max(2, Math.min(60, raw));
    }
```

在页面初始化处先加载配置，再加载演示数据：

```javascript
    async function boot() {
      try {
        await loadWechatConfig();
      } catch (error) {
        setStatus(error.message);
      }
      await loadDemo();
    }

    boot();
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
python -B -m unittest tests.test_workbench_web
```

Expected: PASS。

- [ ] **Step 5: Commit**

```powershell
git -c safe.directory=D:/workspace/codex/自动回复agent add summer_camp_agent/workbench_web.py tests/test_workbench_web.py
git -c safe.directory=D:/workspace/codex/自动回复agent commit -m "feat: add workbench debug config controls"
```

## Task 4: 全量验证

**Files:**
- No source changes expected.

- [ ] **Step 1: Run focused tests**

Run:

```powershell
python -B -m unittest tests.test_wechat_bridge_config tests.test_workbench_web tests.test_wechat_live_listener
```

Expected: PASS。

- [ ] **Step 2: Compile touched modules**

Run:

```powershell
python -B -m py_compile summer_camp_agent/wechat_bridge_config.py summer_camp_agent/wechat_live_listener.py summer_camp_agent/workbench_web.py
```

Expected: PASS，无输出。

- [ ] **Step 3: Confirm final git diff**

Run:

```powershell
git -c safe.directory=D:/workspace/codex/自动回复agent status --short
```

Expected: 只剩用户原本未提交的无关改动，或当前任务相关改动已全部提交。

## 自检结果

- 规格覆盖：配置字段、页面展示逻辑、接口读取、保存兼容、`session_id` 优先使用、Token 不落盘均有任务覆盖。
- 红旗扫描：计划中不包含待填实现步骤。
- 类型一致性：字段统一为 `show_debug_config`，页面输入 ID 统一为 `wechatSessionId`，接口返回统一为 `{"config": ...}`。
