# 19只A股异动监控

交易日盘中每 5 分钟自动监控 19 只A股的行情和资金数据，检测到当天异动时推送到企业微信群机器人（企业微信失败时自动用 Server酱 兜底）。

## 监控股票

| 代码 | 名称 | 代码 | 名称 | 代码 | 名称 |
| ---- | ---- | ---- | ---- | ---- | ---- |
| SH600602 | 云赛智联 | SZ002384 | 东山精密 | SH688019 | 安集科技 |
| SZ000636 | 风华高科 | SH600584 | 长电科技 | SH603986 | 兆易创新 |
| SZ001248 | 华润新能 | SZ300274 | 阳光电源 | SZ300450 | 先导智能 |
| SH688825 | 长鑫科技 | SZ002050 | 三花智控 | SZ300073 | 当升科技 |
| SZ001270 | 铖昌科技 | SZ300502 | 新易盛 | SZ000333 | 美的集团 |
| SZ000021 | 深科技 | SZ002281 | 光迅科技 | SH603259 | 药明康德 |
| | | | | SZ002463 | 沪电股份 |

## 监控内容

| 数据                      | 来源   |
| ----------------------- | ---- |
| 实时行情（价格、涨跌幅、成交量、买卖五档）   | 新浪财经 |
| 日K线历史（30天，含均线）          | 新浪财经 |
| 实时资金流向（主力/超大单/大单/中单/小单） | 东方财富 |
| 历史资金流向（近20日）              | 东方财富 |
| 最新公告（含关键词识别）             | 东方财富 |
| 龙虎榜数据（当日是否上榜）            | 东方财富 |

## 异动信号

检测到以下任一信号时推送（只看当天实时数据）：

1. **涨跌幅异动** — 日内涨跌幅超过 ±5%
2. **放量/缩量** — 量比 > 2 或 < 0.5
3. **主力大额流入/流出** — 主力净流入超 ±1亿
4. **资金流向反转** — 主力当日方向与近5日趋势相反
5. **买卖盘失衡** — 买卖挂单比超过 1.5 倍
6. **当天重要公告** — 公告标题含业绩、增减持、重组、监管等关键词
7. **当天龙虎榜上榜** — 当日登上龙虎榜

## 推送方式

支持两种推送通道，**企业微信群机器人**（推荐，无条数限制）和 **Server酱**（备选，每天5条）。两种可以同时配置，企业微信优先，失败时自动用 Server酱 兜底。

## 部署步骤

### 1. 创建 GitHub 仓库

1. 登录 GitHub，点右上角 **+** → **New repository**
2. 仓库名填 `stock-monitor`，选择 **Public**（免费额度无限）
3. 点 **Create repository**

### 2. 上传代码

将本目录下所有文件上传到仓库：

```
stock-monitor/
├── monitor.py                      # 监控脚本
├── .github/workflows/monitor.yml   # GitHub Actions 配置
├── requirements.txt
└── README.md
```

可以用 git 命令：

```bash
cd stock-monitor
git init
git add .
git commit -m "19只A股异动监控"
git branch -M main
git remote add origin https://github.com/你的用户名/stock-monitor.git
git push -u origin main
```

或者直接在 GitHub 网页上传文件（注意 .github 是隐藏文件夹，需先创建 .github/workflows 目录再上传 monitor.yml）。

### 3. 配置推送密钥

#### 方式A：企业微信群机器人（推荐）

**第1步：在企业微信创建一个内部群**

1. 打开**企业微信手机版或电脑版**
2. 点右上角 **+** → **发起群聊**
3. **重要**：只能选择「企业内部联系人」，不要选「外部联系人」。如果群里有外部联系人，就不会出现「群机器人」选项
4. 随便拉1个同事进来（之后可以移出），创建群聊

**第2步：在群里添加机器人**

1. 进入刚创建的群聊
2. 点右上角 **...**（或群名称）→ 进入群设置
3. 往下滑，找到 **「群机器人」**
4. 点 **「添加」** → **「新创建一个机器人」**
5. 机器人名字填「股票监控」
6. 创建后会显示一个 **Webhook 地址**，格式：
   ```
   https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx-xxxx-xxxx
   ```
7. **复制这个 Webhook 地址**

> **找不到「群机器人」？**
> 
> 如果第3步看不到「群机器人」，可能是以下原因：
> - 群里有外部联系人 → 重新建一个纯内部群
> - 管理员关闭了群机器人功能 → 让管理员登录 work.weixin.qq.com → 我的企业 → 设置 → 确认「群机器人」已开启
> - 企业微信版本太旧 → 更新到最新版

**第3步：配置 GitHub Secret**

1. 打开仓库页面 → **Settings** → 左侧 **Secrets and variables** → **Actions**
2. 点 **New repository secret**
3. Name 填：`WECOM_WEBHOOK`
4. Secret 填：刚才复制的完整 Webhook 地址
5. 点 **Add secret**

#### 方式B：Server酱（备选）

1. 打开 **sct.ftqq.com**，微信扫码登录
2. 复制页面上的 **SendKey**
3. 打开仓库 **Settings** → **Secrets and variables** → **Actions**
4. 点 **New repository secret**
5. Name 填：`SERVERCHAN_SENDKEY`
6. Secret 填：你的 SendKey
7. 点 **Add secret**

> Server酱免费额度每天5条。如果同时配置了企业微信，企业微信优先推送，Server酱只在企业微信失败时兜底。

### 4. 启用 GitHub Actions

1. 打开仓库页面 → 顶部 **Actions** 标签
2. 如果提示 "Workflows aren't being run on this repository"，点 **I understand my workflows, go ahead and enable them**
3. 左侧应能看到 **19只A股异动监控** 工作流

### 5. 手动测试

1. 在 Actions 页面点击 **19只A股异动监控**
2. 点右侧 **Run workflow** → **Run workflow**
3. 等待执行完成（约 1-2 分钟），检查运行日志
4. 如果有异动信号，企业微信群（或方糖服务号）会收到推送

## 运行时间

- **频率**：交易日每 5 分钟（9:25、9:30、9:35...15:05）
- **非交易日**：自动跳过（周末、节假日除外，节假日需手动暂停）
- **暂停方法**：Actions 页面 → 选中工作流 → 点 **...** → **Disable workflow**

## 注意事项

- GitHub Actions 的 cron 定时可能有 1-5 分钟延迟，属正常现象
- 仓库需保持 **Public** 才能享受无限 Actions 分钟数（Private 仓库每月 2000 分钟）
- 企业微信群机器人**无推送条数限制**
- Server酱免费额度为每天 5 条推送
- 节假日（国庆、春节等）需手动在 Actions 页面暂停工作流
- 如果同时配置了 WECOM_WEBHOOK 和 SERVERCHAN_SENDKEY，优先用企业微信，失败时自动切换 Server酱
- 19只股票全部轮询一次约需 1-2 分钟，每次只推送触发异动的股票，无异动不打扰
