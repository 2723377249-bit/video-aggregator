# 风格调研 · 视频汇总（Cloudflare Pages + Backblaze B2 私有桶）

永久在线、本机可关机、全程免信用卡。

## 架构
- **前端**：`index.html`（卡片/灯箱/提交汇总面板）
- **存储**：Backblaze B2 私有桶 `jinghe001`（视频 + 封面 + videos.json）
- **代理**：Cloudflare Pages Function（`functions/[[path]].js`）用 B2 原生 API 给私有文件
  签发下载令牌并流式回传。前端只引用同源路径 `/media/<file>` 与 `/videos.json`，
  **无需 B2 公开桶、无需绑卡**（B2 公开桶/S3 兼容层均需绑卡，已规避）。

## 为什么不用 B2 公开桶 / S3
- B2 把桶设为「公开」需要账户有支付记录（绑卡）→ 与本机无卡冲突。
- B2 的 S3 兼容网关对该账户的所有 key 返回 `The key ... is not valid` → 不可用。
- 改用 B2 原生 API + Cloudflare 代理：彻底绕开上述两条限制。

## 部署（Cloudflare Pages，无需 API token）
1. 登录 https://dash.cloudflare.com → **Workers & Pages → Create → Pages → Connect to Git**
2. 选仓库 `2723377249-bit/video-aggregator`，分支 `main`
3. Build settings：Framework preset 选 `None`，Build command 留空，Build output directory 填 `cloudflare`
4. **Deploy**；构建完成后进入 **Settings → Environment variables**，添加 4 项（Production）：
   - `B2_KEY_ID` = 你的 applicationKeyId（主密钥即账号 ID）
   - `B2_APP_KEY` = 你的 applicationKey
   - `B2_BUCKET` = `jinghe001`
   - `B2_BUCKET_ID` = `2c859aa45ea11345a701081d`
5. 保存后重新 Deploy。访问 `https://<项目名>.pages.dev` 即可看到 12 个视频。

> 备选：纯 Cloudflare Worker 部署见 `wrangler.toml` + `worker.js`，用 `wrangler deploy` 即可。

## 日常汇总新视频（本机运行）
```bat
set B2_KEY_ID=... & set B2_APP_KEY=... & set B2_BUCKET_ID=... & set B2_BUCKET=jinghe001
python aggregate_local.py add https://www.bilibili.com/video/BVxxxx https://v.douyin.com/xxxx/
```
脚本会下载→上传 B2→更新 `videos.json`，前端刷新即见，无需重新部署。

## 一次性上传种子数据
```bat
set B2_KEY_ID=... & set B2_APP_KEY=... & set B2_BUCKET_ID=... & set B2_BUCKET=jinghe001
python upload_b2.py
```
