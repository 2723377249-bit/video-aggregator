# 风格调研 · 视频汇总（Cloudflare Pages + Backblaze B2 私有桶 + GitHub Actions）

永久在线、本机可关机、全程免信用卡；**任何人在网页提交链接，云端自动汇总后所有人可见**。

## 架构
- **前端**：`index.html`（卡片/灯箱/提交汇总面板）
- **存储**：Backblaze B2 私有桶 `jinghe001`（视频 + 封面 + videos.json）
- **代理**：Cloudflare Pages Function（`functions/[[path]].js`）或 Cloudflare Worker（`worker.js`）
  用 B2 原生 API 给私有文件签发下载令牌并流式回传。前端只引用同源路径 `/media/<file>` 与 `/videos.json`，
  **无需 B2 公开桶、无需绑卡**（B2 公开桶/S3 兼容层均需绑卡，已规避）。
- **云端汇总**：前端提交链接 → Worker/Pages Function 调用 GitHub `repository_dispatch` →
  GitHub Actions 运行 `deploy-render/aggregate_remote.py` 下载视频并上传 B2、更新 `videos.json`。

## 为什么不用 B2 公开桶 / S3
- B2 把桶设为「公开」需要账户有支付记录（绑卡）→ 与本机无卡冲突。
- B2 的 S3 兼容网关对该账户的所有 key 返回 `The key ... is not valid` → 不可用。
- 改用 B2 原生 API + Cloudflare 代理：彻底绕开上述两条限制。

## 部署（Cloudflare Pages，无需 API token）
1. 登录 https://dash.cloudflare.com → **Workers & Pages → Create → Pages → Connect to Git**
2. 选仓库 `2723377249-bit/video-aggregator`，分支 `main`
3. Build settings：Framework preset 选 `None`，Build command 留空，Build output directory 填 `cloudflare`
4. **Deploy**；构建完成后进入 **Settings → Environment variables**，添加 6 项（Production）：
   - `B2_KEY_ID` = 你的 applicationKeyId（主密钥即账号 ID）
   - `B2_APP_KEY` = 你的 applicationKey
   - `B2_BUCKET` = `jinghe001`
   - `B2_BUCKET_ID` = `2c859aa45ea11345a701081d`
   - `GITHUB_TOKEN` = GitHub classic token（勾选 `repo` 权限），用于触发 Actions
   - `GITHUB_REPO` = `2723377249-bit/video-aggregator`（可选，默认即此仓库）
5. 保存后重新 Deploy。访问 `https://<项目名>.pages.dev` 即可看到 12 个视频，网页提交的新链接会自动汇总。

> 备选：纯 Cloudflare Worker 部署见 `deploy_cloudflare.py`，用环境变量传入 token 一键部署。

## 触发云端汇总
任何人访问页面，在「提交汇总请求」面板粘贴 B站/抖音 链接并提交。
Worker 会调用 GitHub Actions，约 1–3 分钟后刷新页面即可看到新视频。

## 本地手动汇总（可选备用）
如果云端 Actions 因网络/额度失败，仍可在本机运行：
```bat
set B2_KEY_ID=... & set B2_APP_KEY=... & set B2_BUCKET_ID=... & set B2_BUCKET=jinghe001
python deploy-render/aggregate_local.py add https://www.bilibili.com/video/BVxxxx https://v.douyin.com/xxxx/
```
脚本会下载→上传 B2→更新 `videos.json`，前端刷新即见，无需重新部署。

## 一次性上传种子数据
```bat
set B2_KEY_ID=... & set B2_APP_KEY=... & set B2_BUCKET_ID=... & set B2_BUCKET=jinghe001
python deploy-render/upload_b2.py
```
