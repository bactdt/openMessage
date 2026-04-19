# OpenMessage Plan

## 目标
- 在不影响现有功能（v1）的前提下，逐步走向真正 Zero-Knowledge / E2E。
- 采用 30 个小提交（可回滚、可验证、单一职责）。

## 当前审计快照（2026-04-19）
- 未发现标准日志：全仓库无 `import logging` / `logging.*`。
- 宽泛异常捕获：
  - `app.py:116`
  - `app.py:187`
  - `app.py:240`
  - `storage.py:232`
- `OSError` 被静默忽略（`pass`）：
  - `storage.py:47`
  - `storage.py:56`
  - `storage.py:72`
  - `storage.py:98`
  - `storage.py:134`
  - `storage.py:237`
- 微竞态窗口（密码错误时恢复文件）：
  - `_take_message` / `_restore_held_message` / `verify_and_pop`
  - `storage.py:24`
  - `storage.py:50`
  - `storage.py:170`

---

## 记录（Record Log）

### 2026-04-19 — C01 completed
- 增加 `PROTOCOL_VERSION = "v1"` 常量。
- `save_message()` 写入 `"version": "v1"` 字段。
- 新增 `_ensure_version()` 辅助函数：旧数据无 `version` 字段时默认 `"v1"`。
- `get_message_metadata()` / `pop_message()` / `verify_and_pop()` 读取数据后均调用 `_ensure_version()`。
- 零行为变更：所有现有 API 路由、前端、加解密流程不变。

---

## TodoList（30次提交拆分）

### Phase A: 非功能改动与可观测性（C01-C10）
- [x] C01 增加消息 `version` 字段骨架（无该字段默认 `v1`，兼容旧数据）
- [ ] C02 增加协议版本常量（`v1`/`v2`）与统一校验入口
- [ ] C03 补充 `storage` 兼容性测试（旧数据无 `version` 仍可读）
- [ ] C04 新增日志初始化（统一 logger、级别、格式）
- [ ] C05 `create_message` 异常路径接入 `logging.exception`
- [ ] C06 `view_message_api` 解密异常接入日志（不记录敏感明文/密钥）
- [ ] C07 `storage.py` 中 `OSError` 静默点改为 `warning/error` 日志
- [ ] C08 `cleanup_expired` 增加清理统计日志（扫描/删除/失败计数）
- [ ] C09 增加请求关联 ID（request_id）并带入日志上下文
- [ ] C10 回归测试：确认日志改造不改变现有 API 行为

### Phase B: 竞态与稳定性细节（C11-C16）
- [ ] C11 为存储层引入可重试错误码（如 `locked`）的预留结构
- [ ] C12 增加锁竞争探测（短窗口内区分 not_found 与 transient lock）
- [ ] C13 API 层映射 transient lock 为可重试状态（建议 409）
- [ ] C14 前端对可重试状态增加一次短退避重试
- [ ] C15 并发测试：错误密码 + 并发读取场景
- [ ] C16 文档补充"短暂不可读/重试"语义说明

### Phase C: Async I/O 决策与基线（C17-C20）
- [ ] C17 增加文件存储性能基线脚本（吞吐、p95）
- [ ] C18 记录 ADR：Flask 调优 vs FastAPI 迁移对比
- [ ] C19 Gunicorn 生产参数建议（workers/threads/timeouts）文档化
- [ ] C20 基于基线结果定路线：A 保持 Flask + 调优；B 渐进迁移 FastAPI

### Phase D: Zero-Knowledge / E2E v2（C21-C29）
- [ ] C21 定义 v2 密文包结构（服务端仅存 opaque blob）
- [ ] C22 新增 v2 payload 校验器（仅格式，不涉明文）
- [ ] C23 增加 v2 创建接口（仅接收密文包）
- [ ] C24 增加 v2 一次性取回接口（返回密文后删除）
- [ ] C25 前端 WebCrypto：本地生成密钥与加密 helper
- [ ] C26 前端 WebCrypto：本地解密 helper
- [ ] C27 前端创建流程接入 v2（feature flag 下）
- [ ] C28 前端查看流程接入 v2（feature flag 下，保留 v1 fallback）
- [ ] C29 v1/v2 兼容测试 + 迁移说明

### Phase E: 供应链与安全收敛（C30）
- [ ] C30 本地化第三方静态资源，逐步收紧 CSP（目标去掉 `unsafe-inline`）

---

## 优化专项说明

### 1) Logging（你提的重点）
- 原则：异常必须可追踪，但不能泄露内容、密钥、密码。
- 要求：
  - 统一 logger 命名与格式。
  - `except Exception` 改为分类捕获 + `logging.exception`。
  - `OSError` 不再 `pass`，最少 `warning` + 错误上下文（文件路径可脱敏）。
  - 带 `request_id`、`msg_id`（建议哈希后记录）。

### 2) Async I/O（你提的重点）
- 短期建议：先不直接迁框架，先做基线与调优（更适合拆分小提交）。
- 中期决策门槛：
  - 若文件 I/O 成为瓶颈（吞吐/延迟超过阈值），再进入 FastAPI/ASGI 迁移。
- 这样可避免一次性大改导致风险上升。

### 3) `_take_message` 微竞态（你提的重点）
- 现象：错误密码恢复文件期间，第二个请求可能短暂拿到 not_found。
- 方案（计划中）：
  - 引入 transient lock 语义；
  - API 返回可重试状态；
  - 前端自动一次退避重试；
  - 并发测试覆盖此场景。

---

## 完成定义（DoD）
- 每个提交都：
  - 单一职责；
  - 不破坏现有行为（除明确标注变更）；
  - 有最小验证（测试或手工验证步骤）；
  - 更新本计划中的状态与记录。