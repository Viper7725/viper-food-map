# 使用者自己的偏好与反馈

所有路径相对于安装的 skill 目录。`user-data/` 被 Git 忽略，不会提交到共享仓库；Git 拉取新版会保留它。不要把个人资料写回 `data/favorites.json`。

## 长期偏好

只有使用者明确要求保存时才创建 `user-data/`，将 `data/preferences.example.json` 复制成 `user-data/preferences.json`，然后写入使用者确认的值和确认时间。不存在时读取空模板；空值表示未知，不表示不限或无忌口。

## 反馈

`user-data/feedback.json` 使用查询结果里的稳定 `id` 作为键。下例的 `店铺实际id` 需换成真实查询结果，不按店名猜 ID：

```json
{
  "schema_version": 1,
  "restaurants": {
    "店铺实际id": {
      "visited": true,
      "liked": null,
      "user_feedback": [
        {"text": "使用者的原话", "recorded_at": "2026-10-08T12:00:00+08:00"}
      ]
    }
  }
}
```

只允许覆盖 `visited`、`liked`、`user_feedback`；价格、地址和来源状态不会被反馈文件覆盖。`visited`/`liked` 只接受 true/false/null。未出现的店铺沿用共享数据；新库移除的店铺反馈仍留在文件里，不会自动删除。查询自定义 `--data` 时默认不套用共享库反馈，必要时另给 `--feedback`。

从旧静态包升级：先备份整个旧文件夹；把旧 `data/preferences.json` 复制到新包的 `user-data/preferences.json`；把旧餐厅记录中已填写的上述三个个人字段按 `id` 提取到 `user-data/feedback.json`。确认偏好和反馈迁移后再替换安装。其他自定义资料需单独保留，不将旧餐厅库整体覆盖到新版。
