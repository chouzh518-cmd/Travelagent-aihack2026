# Render 部署准备

当前服务默认只监听本机 `127.0.0.1`。Render 部署使用容器监听 `0.0.0.0`，资料、Chroma 向量索引和模型缓存统一写入 `/var/data`。

## 部署前

1. 将本项目代码放入一个**私有 Git 仓库**并连接 Render。不要把 `.env`、`data`、`storage` 或 `output` 提交到仓库；`.gitignore` 和 `.dockerignore` 已排除它们。
2. 在 Render 创建 Web Service，选择 Dockerfile 构建，部署分支由仓库管理员选择。
3. 选择 Singapore 区域和 `1c-2g` 实例。该实例当前标价为每月 USD 25；附加持久磁盘另计 USD 0.25/GB/月。至少挂载 1 GB 磁盘到 `/var/data`。价格可能变动，创建服务前请以 Render 控制台为准。
4. 设置环境变量：`APP_DATA_DIR=/var/data`、`APP_BIND_HOST=0.0.0.0`、`PORT=10000`，并设置随机且仅团队成员知道的 `APP_ACCESS_PASSWORD`。Agent 使用免费路由试运行时，还需设置 OrcaRouter 提供的 `ORCAROUTER_API_KEY`，并设置 `ORCAROUTER_MODEL=orcarouter/free`。不要把 API Key 写入代码或提交到 Git。Render 会提供 `RENDER_EXTERNAL_HOSTNAME`；应用只接受该准确主机名的请求。
5. 将健康检查路径设为 `/healthz`。部署完成后，Render 会分配 `https://<你选择的服务名>.onrender.com` 固定地址；服务名必须在 Render 全局唯一。

服务需要访问公网才能在首次使用时下载约 220 MB 的 FastEmbed 模型。模型缓存会保存在 `/var/data/models`，重启后不需要重新下载。`/var/data` 上的资料快照、Chroma 向量库、模型和运行记录会跨部署保留。

## 资料访问

页面本身可打开；资料 API、上传和删除操作需要团队访问口令。团队成员首次打开页面时输入同一个 `APP_ACCESS_PASSWORD`。Render Web Service 使用 HTTPS；不要在公开 HTTP 站点上输入访问口令。

## Agent 配置

本地 PowerShell 可在启动服务前临时设置 `ORCAROUTER_API_KEY` 和 `ORCAROUTER_MODEL=orcarouter/free`。免费路由有请求频率限制；遇到 429 时稍后再试。页面会显示模型和资料库连接状态。Agent 目前依据已上传资料生成建议，不包含实时航班、列车、酒店价格或预订能力。

Render 免费 Web Service 会在空闲时休眠，且不支持持久磁盘；它不适合保存这个项目上传的资料。以上配置为单实例服务，因为本地 Chroma 库和持久磁盘不支持多实例共享写入。
