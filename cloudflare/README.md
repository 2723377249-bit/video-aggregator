# 风格调研 · 视频汇总（Cloudflare Pages + Backblaze B2）

完全免信用卡的部署方案：
- **前端**：Cloudflare Pages（纯静态，免卡，国内极佳，永久在线）
- **存储**：Backblaze B2（对象存储，免卡，10GB 免费，S3 兼容，持久）
- **汇总**：你在本机运行 `aggregate_local.py` 下载并上传（朋友不能在网页直接点汇总，
  因为 Cloudflare Workers 是 V8 隔离运行、跑不了 yt-dlp/Playwright）

结果：朋友随时能看全部视频、本机可关机、新增视频永久保存、全程零信用卡。

---

## 一、注册 Backblaze B2（免卡，邮箱即可）
1. 打开 https://www.backblaze.com/sign-up/cloud-storage 注册（页面注明 *No credit card required*）
2. 进入 **B2 Cloud Storage** → **Create a Bucket**
   - Bucket Name：全局唯一，例如 `style-research-video`
   - 位置：选离你近的区域（US / EU）
   - **设为 Public**（桶设置里打开 Public 访问）
3. 记下以下信息：
   - **Bucket Name**
   - **Account ID**（控制台顶部）
   - **S3 Endpoint**（桶页面显示，形如 `s3.us-west-004.backblazeb2.com`）
   - **Region**（即 endpoint 里 `s3.` 和 `.backblazeb2.com` 之间的部分，如 `us-west-004`）
4. **Application Keys** → **Add a New Application Key**
   - 允许访问刚建的桶，权限 **Read & Write**
   - 记下 **keyID**（= `B2_KEY_ID`）和 **applicationKey**（= `B2_APP_KEY`，**只显示一次**）

> 视频公开访问基址为：`https://f<AccountID>.backblazeb2.com/file/<BucketName>`
> 例如 `https://f0123456789.backblazeb2.com/file/style-research-video`

## 二、注册 Cloudflare（免卡，邮箱即可）
1. 打开 https://dash.cloudflare.com/sign-up 注册
2. 部署前端（任选一种）：
   - **方式 A · 网页连 GitHub（推荐）**：左侧 *Workers & Pages* → *Create* → *Pages* →
     *Connect to Git* → 选本仓库 → Build command 留空、Build output directory 填 `cloudflare`
     （因为前端文件在仓库的 `cloudflare/` 子目录）。部署后得到 `https://<项目名>.pages.dev`
   - **方式 B · Wrangler CLI**：`npx wrangler pages deploy cloudflare`

## 三、填入 B2 地址并重新部署
1. 编辑 `cloudflare/config.js`，把 `b2Base` 改成你的公开基址：
   ```js
   window.APP_CONFIG = {
     b2Base: "https://f<AccountID>.backblazeb2.com/file/<BucketName>"
   };
   ```
2. 重新部署前端（GitHub 方式直接 `git push`；Wrangler 方式重新 `deploy`）

## 四、上传种子视频（首次）
在本机（装有 venv + ffmpeg + `media/` 种子视频的机器）设置环境变量后运行：
```bat
set B2_ENDPOINT=https://s3.us-west-004.backblazeb2.com
set B2_REGION=us-west-004
set B2_BUCKET=你的桶名
set B2_KEY_ID=你的keyID
set B2_APP_KEY=你的applicationKey
set B2_ACCOUNT_ID=你的AccountID

python aggregate_local.py seeds
```
会把 `media/` 下 442MB 种子视频 + 封面 + `videos.json` 全部上传到 B2。
完成后打开 Pages 地址即可看到 12 个视频。

## 五、日常汇总新视频（本机运行）
```bat
python aggregate_local.py add https://www.bilibili.com/video/BVxxxx https://v.douyin.com/xxxx/
```
脚本会：下载（B站用 yt-dlp、抖音用 Playwright）→ 上传 B2 → 追加到 `videos.json`。
朋友刷新前端即见，永久保存、所有人可见。

## 说明
- B2 免费额度 10GB；超出部分约 $0.006/GB/月，极便宜。
- 前端「提交汇总请求」会把链接存在**访客本机**（localStorage），需你运行上面的脚本才真正入库；
  朋友也可直接把链接发给你处理。
- 若想让朋友的提交直接进入云端队列（无需手动转发），可加一个 Cloudflare Worker + KV 做接收，
  属进阶可选，本仓库未包含。
