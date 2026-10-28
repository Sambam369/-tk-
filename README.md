# TikTok 飞书团队素材库 Skill

关键词 → TikTok 搜索 → 播放/点赞门槛筛选 → 公司共享盘 → 飞书视频附件。

团队成员在飞书填关键词、数量及门槛，点击按钮提交；指定 Windows 执行机串行处理任务。默认不调用 Gemini、Apify 或其他付费采集 API。当前支持巴西葡语，地区为推断结果。

## 安装

将 [`skills/tiktok-feishu-team-library`](skills/tiktok-feishu-team-library) 目录复制到 `~/.codex/skills/`，重新加载技能后使用 `$tiktok-feishu-team-library`。

依赖：Windows、Python 3.11+、ffmpeg、yt-dlp、browser-act CLI、lark-cli，以及使用者自己的 TikTok 登录、飞书授权和可写共享目录。详情见 [配置说明](skills/tiktok-feishu-team-library/references/setup.md)。

把示例配置复制到仓库以外的私有工作目录，填写自己的配置，然后设置 `TIKTOK_LIBRARY_CONFIG` 指向该文件。不要把真实配置或登录凭据提交到仓库。

## 验证

```powershell
python skills/tiktok-feishu-team-library/scripts/verify_package.py
```

已验证离线筛选、默认门槛、自定义零门槛、视频 ID 去重和排名。公开包使用独立 yt-dlp 下载器；部署后需跑一条真实任务，完成浏览器、下载和附件上传的端到端验收。

共享目录格式为 `日期/国家/关键词/视频ID/视频ID.mp4`。该目录只保存视频；运行日志、候选数据和上传临时文件保存在私有配置目录的 runtime 中。

仓库不包含公司表格 ID、浏览器 ID、网盘地址、密钥、Cookie 或视频素材。具体功能及故障处理见 [SKILL.md](skills/tiktok-feishu-team-library/SKILL.md)。
