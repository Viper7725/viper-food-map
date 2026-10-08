# Viper 的美食地图

用 Viper 分享的 **764 家大众点评美食收藏**，按城市、人数、口味推荐餐厅。内含 Codex skill、离线餐厅库和 Python 查询脚本；无需登录分享者的大众点评账号。

收藏数据采集于 **2026-10-08**。收藏不代表去过或喜欢，未知价格、口味、桌型和营业状态需要另行核实。覆盖范围见 [收藏来源](references/collection-origin.md)。

## 安装

需要 Python 3.9 或更新版本，无第三方 Python 依赖。推荐通过 Git 安装，方便以后更新。也可以把本仓库链接发给 Codex，说：

> 请将 https://github.com/Viper7725/viper-food-map 安装为我的个人 skill，保留已有同名 skill 中的偏好和反馈。

### Windows（PowerShell）

```powershell
git clone https://github.com/Viper7725/viper-food-map.git "$env:USERPROFILE\.agents\skills\viper-food-map"
```

### macOS / Linux

```bash
git clone https://github.com/Viper7725/viper-food-map.git "$HOME/.agents/skills/viper-food-map"
```

如果同名目录已存在，先备份并确认它是否为本仓库的 Git 安装；Git 安装按下文更新，旧静态包按[个人数据说明](references/personal-data.md)迁移。

没有 Git 时，下载 [最新版 ZIP](https://github.com/Viper7725/viper-food-map/archive/refs/heads/main.zip)，将解压后的文件夹重命名为 `viper-food-map`，放入个人 skills 目录。最终文件位置应为 `~/.agents/skills/viper-food-map/SKILL.md`，不要多套一层文件夹。

Codex 会检测 skill 更改；未出现时重启 Codex。避免在 `.codex/skills`、`.agents/skills` 同时保留同名的不同版本。安装目录依据：[OpenAI 官方说明](https://developers.openai.com/codex/skills/)。

## 使用

在 Codex 中说：

> 使用 $viper-food-map 推荐美食：杭州，4 个人，想吃烤肉，别太辣。

缺少城市、人数或口味时会先询问。也可以在本仓库目录里直接查询：

```shell
python -X utf8 scripts/query_food.py --summary
python -X utf8 scripts/query_food.py --city 杭州 --keyword 烤肉 --limit 20
```

macOS / Linux 可将 `python` 换成 `python3`。

## 新版提醒与更新

每次查询会读取 `update` 结果：首次联网检查，以后成功结果缓存 6 小时、失败结果缓存 15 分钟。有新版本时，skill 会提示本地版本、新版和更新方式。**只提示，不自动下载或修改已安装版本。** 网络不可用时继续查询本地数据，并说明无法确认最新版。

手动立即检查：

```shell
python -X utf8 scripts/check_update.py --force
```

完全离线查询：

```shell
python -X utf8 scripts/query_food.py --summary --no-update-check
```

Git 安装的 Windows 用户更新：

```powershell
git -C "$env:USERPROFILE\.agents\skills\viper-food-map" pull --ff-only
```

macOS / Linux：

```bash
git -C "$HOME/.agents/skills/viper-food-map" pull --ff-only
```

出现冲突或本地修改阻止更新时，先保留修改再处理，不使用强制重置。ZIP 用户下载新版，先备份旧安装的 `user-data`，将它复制到新解压的目录，确认无误后替换安装。其他自定义文件也应自行保留。

个人偏好和反馈保存在 Git 忽略的 `user-data/`，按[个人数据格式](references/personal-data.md)写入，不修改共享餐厅库。更新检查只访问 GitHub 的公开版本文件，不上传偏好或餐厅反馈。

GitHub 版本检查需要发布者发布新版；它不会自动抓取大众点评收藏，也不是后台定时任务。不执行查询时不会检查。

发布者更新流程见 [维护说明](MAINTAINING.md)。
