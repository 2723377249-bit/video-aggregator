@echo off
REM ============================================================
REM  视频聚合器 → 推送到 GitHub（傻瓜版 / Windows）
REM  用法：双击本文件，按屏幕提示输入即可。
REM  前置：电脑已安装 Git（没装去 https://git-scm.com 下载安装）
REM  前置：已在 github.com 建好一个空仓库（名字随便，如 video-aggregator）
REM ============================================================
setlocal
set SRC=%~dp0

where git >nul 2>nul || (echo [错误] 没检测到 Git，请先安装 https://git-scm.com 后重跑此文件 & pause & exit /b 1)

echo ==^> 正在把部署文件复制到当前文件夹（%CD%）
xcopy "%SRC%*.*" "." /Y /Q >nul

if not exist ".git" (
  git init
  echo [ok] 已初始化本地仓库
)

set /p USER=请输入你的 GitHub 用户名：
set /p REPO=请输入你在 GitHub 上建的仓库名（如 video-aggregator）：
set /p TOKEN=请输入 GitHub Personal Access Token（需 repo 权限；粘贴后回车即可）：

git remote remove origin >nul 2>nul
git remote add origin https://%USER%:%TOKEN%@github.com/%USER%/%REPO%.git

git add -A
git commit -m "deploy video aggregator" || echo （没有新改动，跳过提交）
git branch -M main
git push -u origin main

echo.
echo ============================================================
echo  推送完成！接下来：
echo   1. 打开 https://dashboard.render.com  （用 GitHub 登录）
echo   2. New -^> Blueprint -^> 连接仓库 %REPO%
echo   3. 等 5~15 分钟构建，状态变绿即可访问
echo   链接：https://video-aggregator.onrender.com
echo ============================================================
pause
