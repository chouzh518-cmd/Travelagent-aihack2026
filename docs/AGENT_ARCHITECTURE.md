# Agent 结构

## 对话链路

1. `app.py` 校验团队访问口令并接收对话请求。
2. `agents/rag_agent.py` 读取用户的出差条件与短期对话历史，按当前 demo 资料范围调用检索。
3. `policy_import/` 负责 PDF/图片抽取、OCR、Chroma 向量索引、来源适用范围和资料生命周期。
4. `rag/evidence_retriever.py` 将经过资料范围校验的片段包装为 LlamaIndex Retriever。
5. LlamaIndex `ContextChatEngine` 注入来源片段与对话记忆；`llm/orcarouter.py` 通过 OpenAI 兼容适配器调用 OrcaRouter。
6. 页面展示回答和可展开的原文依据，可将最近一次回答导出为 Markdown 建议书。

## 职责边界

- `agents/`：面向用户的多轮 Agent 编排和回答策略。
- `rag/`：检索结果到 LlamaIndex 的适配。
- `llm/`：模型供应商连接、模型选择和错误映射。
- `policy_import/`：已存在的资料抽取、向量库和权限绑定，不由 Agent 改写。
- `core/`：出差字段校验、报价比较等确定性业务流程。
- `tools/`：航班、列车、酒店等外部工具适配器；尚未配置的工具不会被描述为实时数据。
- `static/`、`templates/`：网页界面。

免费试运行的模型标识默认为 `orcarouter/free`。设置 `ORCAROUTER_API_KEY` 后即可调用；`ORCAROUTER_MODEL` 可在服务环境中覆盖默认值。不要把密钥存进仓库。
