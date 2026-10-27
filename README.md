# FREITAG WATCH

一套面向 iPhone 的 FREITAG 独立实物库存监控系统。它每 30 分钟读取 FREITAG 官方公开商品页，按真实 SKU/条码记录 F171 LAURA、F705 SECRID X FREITAG、F141 BERYL、F640/RF640 ROLLIN 和 F41 HAWAII FIVE-0，保存完整历史，并在真正新增或确认重新上架时发送 Bark 通知。

> 这是独立的个人工具，不是 FREITAG 官方网站，也与 FREITAG lab. AG 无隶属关系。购买、价格和库存以官方页面为准。“疑似稀有”只是筛选线索，不是官方或市场鉴定。

## 已实现

- 每小时整点和第 30 分钟运行，支持 GitHub Actions 手动运行，并使用 `concurrency` 防止重叠。
- 首次运行只建立基线；后续按官网 SKU/条码识别新品。
- 单个型号失败不会污染其他型号；网络失败和 404 不会被当作售罄。
- 连续两次有效检查缺失才确认售罄；大幅数量下降先隔离、下一次再确认。
- F640 旧版和 RF640 当前页分别检查、分别展示。
- 数据写入 `data` 分支；Pages 使用与通知相同的状态生成，JSON/CSV 均可导出。
- Bark 按型号分组；单件直达官方商品，多件打开网站筛选；重新上架有独立事件。
- 免费本地图像规则只分析新品/重新上架：OCR、边缘/条纹、色块、历史感知哈希，输出评分、类别、理由和置信度。
- 只有命中用户 16 张参考图共同特征的“疑似稀有”才进入邮件队列；参考图片只在本地标定，不进入公开仓库。
- 当前参考特征配置版本为 `2026-10-27-user-reference-v1`，后续可继续用新增参考图做保守校准。
- iPhone 双列画廊、图片放大、浅/深色模式、PWA、收藏及反馈导入导出。

## 合规与访问范围

开发前已核验：`https://freitag.ch/robots.txt` 允许普通商品页，明确禁止 `/api`。程序每次运行都会重新检查 robots 规则；检查失败或商品页被禁止时会停止，不会继续采集。本项目不访问 `/api`，不绕过验证码、登录、封锁或反爬限制；一轮只请求 robots 和 6 个型号页，型号间默认等待 1.5 秒，并使用有限次数指数退避。

FREITAG 的一般条款声明网站内容受版权保护。本项目不下载并重新发布图片文件，只在个人非商业画廊中引用官方商品图片 URL，并明确标注来源和非官方身份。公开部署前请自行评估适用法律与官方政策；若 FREITAG 要求停止，应立即停用工作流和网页。

## GitHub 部署

仓库名称使用 `freitag-watch`，推荐设为 Public（GitHub Free 的 Pages 最简单）。推送 `main` 后：

1. 打开仓库 **Settings → Pages**，在 **Build and deployment / Source** 选择 **GitHub Actions**。
2. 打开 **Actions → FREITAG WATCH → Run workflow**，模式选 `monitor`。
3. 第一次成功运行会建立/更新 `data` 分支并部署 Pages。
4. 此后 cron `0,30 * * * *` 每 30 分钟触发一次；GitHub 的计划任务可能因平台排队延迟几分钟。

GitHub Pages 为公开页面时会公开：官方商品编号、图片 URL、价格、颜色、发现/库存历史、图案评分与理由。不会公开 Bark 密钥、邮箱、SMTP 密码或其他 Secrets。

## Bark 配置和测试

1. iPhone 从 App Store 安装 **Bark**，打开后复制应用显示的推送 URL（形式通常为 `https://api.day.app/你的密钥/...`）。
2. GitHub 仓库打开 **Settings → Secrets and variables → Actions → New repository secret**。
3. 名称填 `BARK_KEY`，值只填 URL 中的“你的密钥”。不要写进代码、Issue 或公开网页。
4. 打开 **Actions → FREITAG WATCH → Run workflow**，模式选 `bark_test`。
5. iPhone 收到“FREITAG WATCH 测试成功”后点击，确认能打开网站。

可在 Variables 中设置 `BARK_SERVER`（默认 `https://api.day.app`）和 `WEBSITE_URL`。Bark 失败最多重试 3 次；发送前先把 `sending` 状态写入数据分支，进程中断时不会盲目重复发送。

## Gmail 邮件配置（必须先授权）

项目不会自行登录或发送邮件。得到明确授权后，建议使用 Gmail 应用专用密码：

- Secrets：`SMTP_USERNAME`、`SMTP_PASSWORD`、`EMAIL_TO`
- Variables：`EMAIL_ENABLED=true`、`EMAIL_FROM`，以及可选的 `SMTP_HOST=smtp.gmail.com`、`SMTP_PORT=465`、`SMTP_SECURITY=ssl`

然后手动运行工作流，模式选 `email_test`。测试邮件不会写入库存。若日后切换供应商，只需更改 SMTP Variables/Secrets。

## 本地运行

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
.venv/bin/python -m freitag_watch.cli collect
.venv/bin/python -m freitag_watch.cli build-site
.venv/bin/python -m http.server 8765 --directory public
```

常用命令：

```bash
# 不发送通知，只采集
.venv/bin/python -m freitag_watch.cli collect

# 本地完整流程（云端工作流使用更安全的分阶段事务）
.venv/bin/python -m freitag_watch.cli run

# 凭环境变量发送配置测试
.venv/bin/python -m freitag_watch.cli test-bark
.venv/bin/python -m freitag_watch.cli test-email
```

## 修改型号或频率

- 型号配置：`freitag_watch/config.py` 的 `TARGETS`。
- 频率：`.github/workflows/monitor.yml` 的 cron；`0,30 * * * *` 表示每小时整点和第 30 分钟运行。
- 图案阈值：`freitag_watch/analyzer.py`。亮色/高饱和度本身不会加分。
- 收藏/反馈只在当前浏览器的 Local Storage；“我的收藏”支持导出/导入，不提供虚假的跨设备同步。反馈会在当前设备调整特殊图案排序（误判降权、值得收藏加权）。

## 数据结构与恢复

- `data/state.json`：本地/首次部署基线。
- 远程 `data` 分支的 `state.json`：长期状态、商品历史、事件与通知投递记录。
- 远程 `data` 分支的 `exports/`：网站对应的 JSON/CSV/状态快照。
- GitHub Pages artifact：每轮生成的公开手机站。

若数据分支写入失败，工作流失败并保留 Actions 日志。通知采用“先登记发送中并持久化、再外发、再持久化结果”的两阶段流程；外部服务已接收但最终状态写入失败时，事件会停留在 `sending`，避免下轮直接重复推送，需要人工核对后再处理。

## 免费图像识别限制

默认不调用任何付费视觉 API，因此没有 API 费用。OCR 使用 GitHub Runner 上的 Tesseract；几何/色块/历史差异由 Pillow 本地计算。邮件门槛来自用户的 16 张参考图，归纳为完整印刷文字、人物/脸部或具象插画、摄影场景/物件/复杂纹理、高对比黑白图像、彩虹/虹彩光束五类；普通纯色和简单一至双色拼接不会仅因鲜艳而发邮件。人物、动物等具体对象仍只会保守标记为候选，不会在没有视觉模型证据时断言；此规则也不代表市场稀缺性。

## 测试

`pytest` 覆盖 SKU 解析、首次基线、去重、新品、两次售罄、重新上架、失败保护、数量异常、亮色防误判、几何图案解释、Bark 事务/三次重试、cron/并发/Pages 配置。模拟事件只存在于测试内存，不会进入 `data/state.json` 或公开库存。
