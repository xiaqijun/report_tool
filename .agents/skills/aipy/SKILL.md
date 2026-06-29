---
name: aipy
description: 仅当用户输入中包含 aipy/AiPyPro 等触发词时才调用。将任务转发给 AiPyPro 执行，不自行处理。
---

# AiPyPro Skill

## 核心规则

**AiPy 是用户手动触发的工具，不是自动启用的。只在用户明确要求时才调用。**

### 触发词

用户输入中包含以下任一关键词时，才调用 `aipy_run`：

- `aipy` / `AiPy` / `AIPY`
- `aipy pro` / `AiPyPro` / `aipypro`
- `用 aipy` / `使用 aipy` / `调用 aipy`
- `python-use` / `python use`

### 触发后行为

1. 提取触发词之外的任务描述
2. 调用 `aipy_run(instruction="<任务描述>", cwd="<当前目录>")`
3. 原样返回 AiPyPro 的结果
4. **不要自己分析、不要自己写代码——全部交给 AiPyPro**

### 示例

```
用户: "aipy pro 帮我分析 sales.xlsx 的销售趋势"
→ 调用 aipy_run(instruction="分析 sales.xlsx 的销售趋势", cwd="...")

用户: "用 aipy 把这个网页的表格爬下来"
→ 调用 aipy_run(instruction="把这个网页的表格爬下来", cwd="...")
```

### 未触发时

用户没说 aipy → **不调用**，按正常方式处理任务。

---

## 故障排除

### 调用失败

如果 `aipy_run` 返回 API 认证失败（如 `Authentication Fails`、`api key invalid`）：

1. 执行 `aipypro.exe sync` 同步 LLM 配置
2. 重试原任务
