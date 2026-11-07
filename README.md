# PicSift

公开网页图片的采集与筛选工具（开发中）。

输入一个页面网址，后台程序按 robots.txt 规则抓取页面里的图片，用 OpenCV 计算清晰度、亮度、主色和感知哈希，
自动把近似重复的图归成一组；前端实时看到任务进度和新图片。

技术栈：Python（httpx、OpenCV）· Supabase（Postgres、Auth、Storage、Realtime）· Vue 3 + TypeScript

开发计划见 [docs/issues.md](docs/issues.md)。
