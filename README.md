# 风格调研 · 视频汇总（Render 版）

一个**免费、免信用卡、本机可关机**的公网视频聚合站：
任何人打开链接既能看 12 个种子视频，也能粘贴 B站/抖音链接一键汇总新视频，
新增对所有访问者可见。**部署在 Render 云端，你的电脑关机也不影响别人使用。**
（Hugging Face 在国内常被墙/403，故改用 Render。）

## 原理
- 后端：Python `aiohttp`（`server.py`），监听 `$PORT`（Render 自动注入）。
- 种子视频：构建镜像时由 `fetch_seeds.py` 从公有源自动拉取并烤进镜像，**无需手动上传 442MB**。
- 运行期新增视频：默认写在容器可写层；**若挂载 Persistent Disk 到 `/data` 则持久化**（见下）。
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

## 可选：让「新增的视频」重启/休眠后不丢
Render **免费版不带持久盘**，运行期一键汇总新增的视频会随实例休眠/重启丢失（12 个种子因烤在镜像里不受影响）。
如需持久化：Render 服务里加一个 **Persistent Disk** 挂载到容器路径 `/data`（需升级到付费套餐，约 $0.02/GB·月）。
服务检测到 `/data` 存在会自动把新增视频与清单写入其中。

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
