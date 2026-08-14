# 风格调研 · 视频汇总（Render 版）

一个**免费、免信用卡、本机可关机**的公网视频聚合站：
任何人打开链接既能看 12 个种子视频，也能粘贴 B站/抖音链接一键汇总新视频，
新增对所有访问者可见。**部署在 Render 云端，你的电脑关机也不影响别人使用。**
（Hugging Face 在国内常被墙/403，故改用 Render。）

## 原理
- 后端：Python `aiohttp`（`server.py`），监听 `$PORT`（Render 自动注入）。
- 种子视频：构建镜像时由 `fetch_seeds.py` 从公有源自动拉取并烤进镜像，**无需手动上传 442MB**。
- 运行期新增视频：下载后自动上传到 **S3 兼容对象存储**（B2/R2/S3 等，需配置环境变量），**重启/重新部署都不丢**；未配置时降级存本地（重启会丢）。
- 下载引擎：B站 `yt-dlp`、抖音 `playwright` + `ffmpeg` 合并音视频。

## 部署步骤（约 10–20 分钟，全程免费）
1. 注册 Render：https://dashboard.render.com/ （用 **GitHub 登录**，免信用卡）。
2. 在 GitHub 新建一个**空仓库**（如 `video-aggregator`，Public/Private 均可）。
3. 把本目录（`deploy-render/`）里的**全部文件**复制到该仓库根目录并提交推送：
   ```bash
   git clone https://github.com/<你>/<仓库名>.git
   cp -r deploy-render/.  <仓库名>/
   cd <仓库名>
   git add -A && git commit -m "init" && git push
   ```
   或在本机仓库目录里直接双击 `push_render.bat`。
4. Render Dashboard → **New** → **Blueprint**（或 New → Web Service → 选 Docker）→ 连接该 GitHub 仓库 → 按 `render.yaml` 自动部署。
5. 等**首次构建**（镜像装 ffmpeg + Chromium + 下载 12 视频，约 5–15 分钟）→ 得到
   `https://video-aggregator.onrender.com`，打开即可用。

## 让「新增的视频」重启/重新部署后不丢（强烈建议，免费）
Render **免费版不带持久盘**，若不配置外部存储，运行期一键汇总新增的视频会随实例回收/重新部署丢失
（12 个种子因烤在镜像里不受影响）。本服务支持把新增视频自动上传到**任意 S3 兼容对象存储**，
持久化且对所有人可见。推荐 **Backblaze B2 免费额度（10GB，免信用卡）**。

### 第一步：建一个免费 B2 桶（约 3 分钟）
1. 注册 https://www.backblazeb2.com （邮箱即可，**免费额度不需要信用卡**）。
2. 左侧 **Buckets** → **Create a Bucket** → 取名如 `video-aggregator` → 选 **Public**（公开读，视频才能直接播）→ 创建。
3. 进入桶 → **Bucket Settings** 记下 **Endpoint**（形如 `https://s3.us-west-004.backblazeb2.com`）。
4. 左侧 **Application Keys** → **Add a New Application Key**：
   - Name 随意；**Allow Access to Bucket(s)** 选刚建的桶；**Type of Access** 选 **Read and Write**；
   - 其余默认 → **Create**。页面会显示 `keyID`（= 访问密钥 ID）和 `applicationKey`（= 密钥），**只显示一次，复制保存**。

### 第二步：在 Render 配置环境变量
打开 Render 该服务 → **Environment** → 添加以下变量（名字必须一致）→ **Save Changes**（会触发重新部署）：

| 变量名 | 值 |
|---|---|
| `S3_ENDPOINT` | 桶的 Endpoint，如 `https://s3.us-west-004.backblazeb2.com` |
| `S3_BUCKET` | 桶名，如 `video-aggregator` |
| `S3_REGION` | 桶所在区域，如 `us-west-004`（B2 也可填 `auto`） |
| `S3_ACCESS_KEY` | 上面的 `keyID` |
| `S3_SECRET_KEY` | 上面的 `applicationKey` |
| `S3_PUBLIC_URL` | 桶公开访问基址，如 `https://<桶名>.s3.us-west-004.backblazeb2.com`（与 Endpoint 二选一填，优先用这个） |

> 这套变量是**通用 S3 协议**，所以 Cloudflare R2、AWS S3、阿里云 OSS、腾讯云 COS 等任意一家都能用，
> 只要换成对应 Endpoint / 区域 / 密钥即可。没有配置这些变量时，服务自动降级（新增视频存本地、重启会丢），**部署不会失败**。

### 验证
配置并重新部署后，到站点一键汇总一个 B站链接，等待出现新卡片；然后到 Render 手动 **Restart** 该服务（或等其休眠唤醒），
刷新页面——新视频仍在，即说明已成功持久化到 B2。

## 使用须知
- **免费实例闲置约 15 分钟会休眠**，下次访问需约 30–60 秒唤醒（页面先转圈）。这是免费代价。
- **B站**汇总在云端通常正常；**抖音**依赖 Playwright + 抖音接口，云端 IP 可能触发限流/验证，
  若抖音汇总偶尔失败，可换 B站链接，或回到本机聚合服务。
- GitHub 在国内访问可能偏慢，但本仓库只有几 MB 代码，推送无压力；视频在 Render 云端构建时拉取。

## 本地自测（可选）
```bash
pip install -r requirements.txt
python fetch_seeds.py
PORT=7860 python server.py   # 打开 http://localhost:7860
```
