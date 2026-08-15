# Recall 验收清单

更新时间：2026-08-15

## 自动化验证

- [x] `backend`: `D:/python3/python.exe -m pytest tests -q`，隔离 SQLite 服务测试通过。
- [x] `backend`: `D:/python3/python.exe -m compileall -q app` 通过。
- [x] `frontend`: `npm run test:run`，卡片翻面与四档质量提交通过。
- [x] `frontend`: `npm run build`，TypeScript 与生产构建通过。
- [x] `frontend`: `npm audit --json`，生产和开发依赖均无已知漏洞。

## 本地服务冒烟

- [x] 健康检查：`GET /api/health` 返回 `code: 0`。
- [x] 分类迁移：启动时补齐 `error_detail`、`ReviewSession.mode/config_json/submitted_at`，旧 SQLite 数据不删除。
- [x] 学习计划：`/api/review-plan/daily` 返回逾期优先队列、上限、剩余量；`/calendar` 返回完整月份。
- [x] 看板：`/api/dashboard/learning-plan`、`/alerts`、`/distributions` 可读。
- [x] 周报：`/api/export/weekly/markdown` 可下载，PDF 使用运行时生成时间。
- [x] 相似题：`/api/questions/{id}/similar` 在向量不可用时仍返回关键词/知识点结果。

## 浏览器验收

- [x] 仪表盘显示队列、逾期提示、学习处方、月历与卡片入口。
- [x] 卡片页先显示题干，翻面后显示答案并提供四档 SM-2 评价。
- [x] 举一反三页可切换日常变式/考前专题卷；专题卷显示考试日期配置。
- [x] 错题本支持移动端侧栏抽屉、批量编辑、保存筛选、相似题查看与确认后合并。

## 第三方依赖边界

- AI 归类、变式、批改、OCR 和手写批改依赖用户配置的模型及网络；不可用时已保留本地题目、原题练习或可读错误提示。
- 本项目为本地优先版本，不包含账号、云同步、局域网共享或跨设备冲突处理。
