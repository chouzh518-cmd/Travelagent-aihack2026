# Render 免费部署准备

当前服务默认只监听本机 `127.0.0.1`。Render 免费部署使用容器监听 `0.0.0.0`，运行期资料、Chroma 向量索引和模型缓存统一写入 `/var/data`。免费实例的文件系统是临时的，重启或休眠后上传资料和缓存可能消失。

## 部署前

1. 将本项目代码放入一个**私有 Git 仓库**并连接 Render。不要把 `.env`、`data/policies`、`storage` 或 `output` 提交到仓库；`data/projects` 是员工页面所需的静态项目目录，应按去敏后的项目资料一并发布。`.dockerignore` 只排除运行期规程快照，不排除 `data/projects`。
2. 推荐在 Render 选择 **Blueprint**，使用仓库根目录的 `render.yaml`。它会选择免费 Web Service、Dockerfile 和 `/healthz` 健康检查。首次创建时只需填写 `APP_ACCESS_PASSWORD` 与 `ORCAROUTER_API_KEY` 两个 secret。
3. 如果不使用 Blueprint，则手动创建 Docker Web Service，选择免费计算方案、部署分支和 `Dockerfile`，并设置 `APP_DATA_DIR=/var/data`、`APP_BIND_HOST=0.0.0.0`、`PORT=10000`。免费方案不要添加持久磁盘。
4. 设置随机且仅团队成员知道的 `APP_ACCESS_PASSWORD`。Agent 使用免费路由试运行时，再设置 OrcaRouter 提供的 `ORCAROUTER_API_KEY`，并设置 `ORCAROUTER_MODEL=orcarouter/free`。不要把 API Key 写入代码或提交到 Git。Render 会提供 `RENDER_EXTERNAL_HOSTNAME`；应用只接受该准确主机名的请求。

   应用默认拒绝复杂度分流器选择的有费或自动路由，所有模型请求实际使用 `orcarouter/free`。只有组织明确批准并设置 `ORCAROUTER_ALLOW_PAID=true` 时，才允许使用配置中的其他路由；未设置或其他值均保持免费降级。
5. 将健康检查路径设为 `/healthz`。部署完成后，Render 会分配 `https://<你选择的服务名>.onrender.com` 固定地址；服务名必须在 Render 全局唯一。

部署成功后，把 Render 显示的 `https://...onrender.com` 发给其他人即可打开。第一次访问时，页面会要求输入 `APP_ACCESS_PASSWORD`。免费服务空闲 15 分钟后会休眠，首次重新访问需要等待实例启动。如果需要自己的域名，可在 Render 的 Custom Domains 中绑定，不需要修改应用代码。

服务需要访问公网才能在首次使用时下载约 220 MB 的 FastEmbed 模型。免费实例重启后可能需要重新下载模型。免费实例不会永久保留 `/var/data` 上的资料快照、Chroma 向量库、模型和运行记录；演示资料应放在 `data/projects` 并随代码发布，用户上传资料只作为临时资料使用。

## 资料访问

页面本身可打开；资料 API、上传和删除操作需要团队访问口令。团队成员首次打开页面时输入同一个 `APP_ACCESS_PASSWORD`。Render Web Service 使用 HTTPS；不要在公开 HTTP 站点上输入访问口令。

## Agent 配置

本地 PowerShell 可在启动服务前临时设置 `ORCAROUTER_API_KEY` 和 `ORCAROUTER_MODEL=orcarouter/free`。免费路由有请求频率限制；遇到 429 时稍后再试。页面会显示模型和资料库连接状态。Agent 目前依据已上传资料生成建议，不包含实时航班、列车、酒店价格或预订能力。

Render 免费 Web Service 会在空闲时休眠，且不支持持久磁盘；它不适合保存这个项目上传的资料。以上配置为单实例服务，因为本地 Chroma 库不支持多实例共享写入。

## 备用方案

如果 Render 账号、付费持久磁盘或 Docker 构建不可用，先使用同一 Dockerfile 部署到任意支持 Docker 和持久卷的 Web Service 平台；必须保留 `APP_DATA_DIR=/var/data`、`PORT`、`/healthz` 和单实例约束。若暂时没有可用云平台，则只能使用内网穿透临时演示，不能作为长期资料服务，也不要把访问口令用于公开无 HTTPS 地址。
