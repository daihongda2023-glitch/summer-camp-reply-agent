# WeChat 调试配置页面开关设计

## 背景

当前浏览器版群聊答疑运营工作台已经支持保存 WeFlow/微信桥接配置，后端配置对象包含 `group_name`、`session_id`、`keywords`、`poll_interval_seconds` 和 `enabled` 等字段。页面目前只暴露群聊名称、关键词和轮询间隔，且前端保存配置时把 `session_id` 固定传为空字符串。

调试监听时，经常需要直接指定 WeFlow `session_id` 或临时调整群聊关键字。如果这些字段长期展示在页面上，会让常规运营界面变复杂；如果完全依赖改代码或命令行，又不方便快速调试。因此需要一个持久化的全局页面开关：开启后页面展示调试配置字段，关闭后页面隐藏这些字段。

## 目标

1. 在本地配置文件中持久化控制页面是否展示调试配置区。
2. 开启调试配置区后，可以在页面编辑群聊名称、`session_id`、关键词和轮询间隔。
3. 关闭调试配置区后，页面不展示这些调试字段，避免干扰常规使用。
4. 保持监听逻辑兼容：填写 `session_id` 时优先使用它；未填写时继续按群聊名称搜索会话。
5. 不在配置文件、日志或页面中保存 WeFlow API Token 明文。

## 非目标

1. 不新增 WeFlow Token 明文输入框。
2. 不新增多群聊管理能力。
3. 不改变当前“开始监听、拉取新消息、停止监听、填入微信、确认已发送”的操作模型。
4. 不把 `session_id` 写入监听状态文件；状态文件仍只保存哈希。

## 推荐方案

新增独立字段 `show_debug_config`，默认值为 `False`，写入 `data/wechat_bridge_config.json`。该字段只控制页面展示，不承担监听开关语义。

不复用现有 `enabled` 字段。`enabled` 保留为桥接能力是否启用的配置含义，后续如果需要禁用整个微信桥接能力，可以继续使用该字段；`show_debug_config` 专门表示“是否显示页面调试配置”。

## 配置模型

`WeChatBridgeConfig` 增加字段：

```python
show_debug_config: bool = False
```

读取旧配置时，如果没有该字段，默认关闭。保存配置时，通过 `to_dict()` 输出该字段。

示例配置：

```json
{
  "base_url": "http://127.0.0.1:5031",
  "token_env": "WEFLOW_API_TOKEN",
  "group_name": "沐曦开源英才夏令营咨询群",
  "session_id": "",
  "keywords": ["报名", "报到", "住宿", "交通"],
  "poll_interval_seconds": 5,
  "enabled": true,
  "show_debug_config": true
}
```

## 页面行为

页面加载时调用新的配置读取接口，拿到当前 `WeChatBridgeConfig`。

当 `show_debug_config` 为 `true`：

1. 展示调试配置区。
2. 将 `group_name`、`session_id`、`keywords`、`poll_interval_seconds` 填入页面输入框。
3. 保存监听配置时，把这些字段提交到 `/api/wechat/config`。

当 `show_debug_config` 为 `false`：

1. 隐藏调试配置区。
2. 页面仍保留监听操作按钮。
3. 保存或开始监听时，前端使用已加载的配置作为基础，避免因为隐藏字段而覆盖本地配置文件中的 `session_id` 或关键词。

## 接口行为

新增 `GET /api/wechat/config`，返回当前保存的桥接配置：

```json
{
  "config": {
    "base_url": "http://127.0.0.1:5031",
    "token_env": "WEFLOW_API_TOKEN",
    "group_name": "沐曦开源英才夏令营咨询群",
    "session_id": "",
    "keywords": ["报名", "报到"],
    "poll_interval_seconds": 5,
    "enabled": true,
    "show_debug_config": false
  }
}
```

`POST /api/wechat/config` 继续保存配置。前端需要带上 `show_debug_config`，避免保存后丢失开关状态。

## 数据流

1. 工作台启动，`WorkbenchWebState` 从 `WeChatBridgeConfigStore` 读取配置。
2. 浏览器打开页面，调用 `GET /api/wechat/config`。
3. 前端根据 `show_debug_config` 渲染或隐藏配置区，并缓存当前配置。
4. 用户点击“保存监听配置”或“开始监听”时，前端提交缓存配置和页面字段。
5. 后端保存配置，并在开始监听时把配置传给 `WeFlowLiveListener`。
6. `WeFlowLiveListener` 若发现 `session_id` 非空，直接使用该会话；否则按 `group_name` 搜索群聊。

## 错误处理

1. `base_url` 仍只允许 `http://127.0.0.1` 或 `http://localhost`。
2. `poll_interval_seconds` 仍限制在 2 到 60 秒。
3. `keywords` 保存时去除空白项。
4. 配置文件不是 JSON 对象时继续抛出配置错误。
5. 页面读取配置失败时，在状态栏展示错误，不自动启动监听。

## 测试计划

1. 配置模型测试：`show_debug_config` 能从字典读取，能保存并再次加载；旧配置缺省时默认关闭。
2. 页面 HTML 测试：包含 `session_id` 输入框、调试配置容器和配置初始化脚本。
3. Web 状态测试：`GET /api/wechat/config` 返回当前配置，并包含 `show_debug_config`。
4. 前端保存逻辑测试：页面脚本不再固定传空 `session_id`。
5. 监听兼容测试：已有 `session_id` 优先逻辑继续通过现有测试覆盖。

## 验收标准

1. 将 `data/wechat_bridge_config.json` 中的 `show_debug_config` 改为 `true` 后，刷新页面能看到群聊名称、`session_id`、关键词和轮询间隔配置项。
2. 将 `show_debug_config` 改为 `false` 后，刷新页面不展示这些调试字段。
3. 页面中填写 `session_id` 并保存后，配置文件保存该值。
4. 未填写 `session_id` 时，监听逻辑仍按群聊名称搜索。
5. 单元测试通过，且不新增 Token 明文保存路径。
