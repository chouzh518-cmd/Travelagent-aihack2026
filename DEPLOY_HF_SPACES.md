# Hugging Face Spaces 部署

本项目使用 Docker Space。当前应用不是 Gradio 或 Streamlit 页面，直接使用 Docker 可以保留现有的三页前端、计划书生成和天气/日历模擬逻辑。

## 创建 Space

1. 在 Hugging Face 创建一个 Space，SDK 选择 **Docker**。
2. 将本项目文件推送到 Space 仓库。
3. 根目录的 `README.md` 已包含 `sdk: docker` 和 `app_port: 7860`。
4. 等待 Docker 构建完成后访问 Space 提供的 `https://<用户名>-<space名>.hf.space` 地址。

## 必要的 Secrets / Variables

在 Space 的 Settings → Variables and secrets 中设置：

- `APP_ACCESS_PASSWORD`：团队访问口令。必须设置。
- `APP_TRUSTED_HOSTS`：填写 Space 的准确主机名，例如 `<用户名>-<space名>.hf.space`，不要填写协议、路径或通配符。
- `APP_BIND_HOST`：`0.0.0.0`。
- `PORT`：`7860`。
- `APP_DATA_DIR`：`/var/data`。

`ORCAROUTER_API_KEY` 为可选项；没有配置时，应用仍使用本地规则、规程检索、模擬报价和邮件模板降级路径。

## 部署后检查

先打开 `/healthz`，确认返回 HTTP 200，再打开根页面。首次访问会要求输入 `APP_ACCESS_PASSWORD`。确认以下路径：

1. 选择 `planty` 项目。
2. 进入「相談」并生成计划书。
3. 自动进入「計画書」页面。
4. 计划书显示日历/天气模擬结果；恶劣天气场景显示红色提示。
5. 使用「メール」页面生成可编辑草稿。

## 数据保留说明

Hugging Face Space 的默认运行磁盘不应当作为长期资料库。未配置持久存储时，重启或重新构建可能清除上传资料、快照和向量索引。正式使用前应配置平台支持的持久存储，或只把 Space 用作去敏演示环境。

## 备用方案

如果 Space 无法使用持久存储，仍可使用公开项目资料和本地模擬数据演示；上传资料和运行快照应在外部受控存储中维护。若 Docker 构建不可用，可使用现有 `render.yaml` 部署到 Render，但必须配置其持久磁盘和两个 secret。
