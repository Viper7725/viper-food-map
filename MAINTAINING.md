# 发布者维护

此仓库是对外分享版。餐厅库、skill 规则或查询脚本变更后，需要同时发布新的 `version.json` 才会触发使用者的新版提醒。

## 发布新版

1. 修改本仓库中的文件。更新餐厅库时使用去除账号专属链接、本机路径和个人偏好的分享数据；同步 `metadata`、`references/collection-origin.md` 和 README 的采集日期、条数及覆盖范围。原始采集材料留在自己的工作目录。
2. 在本仓库目录运行以下命令。版本采用 `年.月.日.序号`，同一天从 1 递增，必须大于上一版；示例版本请按实际发布日期替换。

```shell
python -X utf8 -m unittest discover -s tests -v
python -X utf8 scripts/prepare_release.py --version 2026.10.08.2
python -X utf8 scripts/prepare_release.py --check
git status --short
git diff --stat
git add README.md MAINTAINING.md SKILL.md version.json .gitignore .gitattributes agents data references scripts tests
git commit -m "Update food map release"
git push origin main
```

发布前核对 `git diff --cached`，确保没有意外资料。`prepare_release.py` 会验证餐厅数据、个人字段和常见不适合公开的内容，并计算发布文件摘要；它不能替代人工检查。生成版本后若再改发布文件，重新准备版本或修正后再检查，不要直接推送过期摘要。

3. 推送成功后运行 `python -X utf8 scripts/check_update.py --force`，应显示 `up_to_date`。仓库主页和 ZIP 下载会使用 `main` 的最新内容；已安装的用户在下一次检查时看到新版提醒，最长受成功缓存 6 小时影响。

## 本地资料分工

- `data/favorites.json`：所有使用者共享的已清理收藏快照。
- `data/preferences.example.json`：空偏好模板，不保存发布者或收件人的长期偏好。
- `user-data/`：仅属于本机使用者，Git 忽略。不要强制加入版本控制。
- `version.json`：软件发布版本；数据采集日期仍以餐厅库 metadata 为准。

发布只上传当前仓库内的已跟踪文件。仓库外的原始导入材料、维护者自己的 skill 和个人偏好无需上传。
