# 开发计划（GitHub issues）

每条照抄到 GitHub 新建 issue。实现时从 main 拉分支，提 PR 时在描述里写 `Closes #编号`，CI 通过后合并。

---

## #1 初始化仓库：目录结构、CI、README 骨架
分支：`chore/bootstrap`
- [ ] `.gitignore`、`.env.example`、`LICENSE`
- [ ] `.github/workflows/ci.yml`：worker 跑 ruff + pytest，web 跑类型检查 + vitest + 构建
- [ ] README 写清项目目标和架构图

## #2 数据库表结构与行级安全
分支：`feat/schema`
- [ ] `crawl_jobs`、`images` 两张表，必要的索引（待处理任务用部分索引）
- [ ] RLS：用户只能读自己的数据；前端只能新建 pending 任务
- [ ] 私有存储桶 `thumbs`，按路径第一段（用户 id）做读权限
- [ ] 验收：在 SQL Editor 执行无报错；用两个账号互相看不到对方的数据

## #3 礼貌爬取
分支：`feat/crawler`
- [ ] 读取并缓存 robots.txt；5xx 时整站不抓
- [ ] 同站限速；429/503 按 Retry-After 退避
- [ ] 从 img/srcset/picture/og:image 提取图片地址，转绝对地址并去重
- [ ] 下载时校验 Content-Type 和大小上限
- [ ] 验收：`tests/test_crawl.py` 全部通过

## #4 图像分析
分支：`feat/imaging`
- [ ] 缩略图（只缩不放）、按文件头识别格式
- [ ] dHash 感知哈希 + 汉明距离，结果能存进 Postgres bigint
- [ ] 清晰度（拉普拉斯方差）、亮度、k-means 主色
- [ ] 验收：哈希对缩放和重压缩稳定，不同图距离足够大，`tests/test_imaging.py` 全部通过

## #5 采集流程与本地模式
分支：`feat/pipeline`
- [ ] `run_job`：抓页面 → 找图 → 下载 → 分析 → 查重 → 保存，单张失败不影响整体
- [ ] 本地模式 `python -m picsift local <url>`，结果写 out/
- [ ] 验收：端到端测试覆盖重复判定、robots 跳过、GIF 跳过、重复运行不重复保存

## #6 接入 Supabase：任务领取与入库
分支：`feat/supabase-worker`
- [ ] `claim_job()`（FOR UPDATE SKIP LOCKED）、`similar_images()`（库内算汉明距离）
- [ ] 缩略图上传 Storage，元数据写 images，任务结束回写状态和统计
- [ ] `python -m picsift worker` 常驻轮询
- [ ] 验收：前端插一条任务，worker 能领取、处理并回写 done

## #7 前端：登录与任务面板
分支：`feat/web-jobs`
- [ ] 邮箱密码登录/注册，未配置 .env 时给出提示
- [ ] 新建任务；任务列表订阅 Realtime 实时更新状态
- [ ] 验收：提交任务后状态从排队中 → 处理中 → 完成自动变化

## #8 前端：图库与筛选
分支：`feat/web-gallery`
- [ ] 缩略图批量签名显示；新图通过 Realtime 实时出现
- [ ] 按清晰度下限、任务筛选，隐藏近似重复，多种排序
- [ ] 筛选逻辑抽成纯函数并写 vitest
- [ ] 验收：`npm test` 通过；隐藏重复后每组只剩一张

## #9 部署与文档
分支：`docs/deploy`
- [ ] 前端部署到 Vercel 或 Cloudflare Pages，README 放线上地址和截图
- [ ] worker 的 Dockerfile
- [ ] README 补充技术要点和本地运行说明
