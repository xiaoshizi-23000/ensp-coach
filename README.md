# 网络实验陪练 · eNSP Coach

AI 驱动的华为 eNSP 实验陪练。不替你敲命令，做三件事：把实验环境搭好、把大实验拆成能一步步啃的小步骤、在你卡住的时候读你设备的真实配置告诉你差在哪。

面向华为认证备考和在岗网络工程师，纯本地运行，附零依赖绿色包。

## 功能

- 一键搭建：生成 .topo 并自动调起 eNSP，设备状态实时监测
- 分步实验：8-10 步小步走，每步做完立刻回读设备配置判分，检查失败自动给出命令级差异（缺哪条、多哪条）
- 三级提示：方向 → 思路 → 完整命令，看提示和答案会计入评分
- AI 诊断：读取你所有设备的 current-configuration，结合程序比对出的差异，告诉你做到哪、下一步敲什么
- 排错实验室：自动配好正常网络后悄悄注入单点故障，只给现象，check + keep 双重判定（修好了没有、有没有改坏别的）
- 一句话生成实验：说清要练什么，自动产出拓扑、步骤、检查点，先过结构校验再入库，还能自动试跑一遍
- 原理知识库：57 条知识点（HCIA/HCIP/HCIE），每条含生活化比喻、不限字数的原理详解、常用命令、踩坑、常问
- 排错速练：14 道纯知识型排错选择题，看现象和回显选故障点，答完即判分
- 试卷与判分：组卷、逐题评分、成绩历史，看提示扣 5%/12%/22%，看答案扣 45%
- 考证路线：按考纲排成 10 站 + HCIE 进阶 6 站，上一站交卷及格解锁下一站
- 复盘：自动记录每次检查失败和交卷成绩，统计最容易卡住的命令
- 双主题：苹果 / 华为
- MCP 接口：15 个工具，可接入 Claude Desktop、Cursor 等

## 快速开始

环境要求：Windows 10/11（64 位）、华为 eNSP（含配套 VirtualBox 5.2.x）、DeepSeek API Key。

```bat
git clone git@github.com:xiaoshizi-23000/ensp-coach.git
cd ensp-coach
python app.py
```

首次运行会做环境自检（eNSP / VirtualBox 版本 / Hyper-V / console 端口），然后在浏览器打开 http://127.0.0.1:7317 ，在界面右上角填入 API Key（或直接改 `config.json`）。

完整说明见 [使用手册](使用手册.md)（运行时在 /help 也能看）。

视频教程：（录制中，传好后把链接贴在这里）

也可以不装 Python：`build.py` 打出约 30 MB 的绿色包，双击「启动.bat」即可运行。

## 目录结构

```
app.py           Web 服务与全部接口
ai.py            DeepSeek 客户端
ailab.py         AI 生成实验（生成 + 结构校验 + 修复重试）
ensp_kit.py      拓扑生成、设备命令行、接口映射
doctor.py        环境自检
mcp_server.py    MCP 服务
gen_labs.py      批量出题（实验）
gen_trouble.py   批量出题（排错实验室）
gen_quiz.py      批量出题（速练）
gen_kb.py        批量生成知识库
build.py         打包绿色版
labs/            实验库（JSON，可直接改）
kb/              知识点（JSON，可直接改）
quiz/            速练题库
course.json      考证路线
web/             前端页面
```

## 说明

- eNSP 与相关镜像归华为所有，本工具不打包、不分发 eNSP 本体，仅供个人学习使用
- 防火墙 USG、无线 AC/AP 在 eNSP 的模拟范围内起不来，相关知识点只能查不能练
- API Key 存在本地 config.json，不会上传
