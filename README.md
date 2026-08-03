# 深科技 sz000021 异动监控

交易日盘中每 15 分钟自动监控深科技的行情和资金数据，检测到异动时推送到微信。

## 监控内容

| 数据                      | 来源   |
| ----------------------- | ---- |
| 实时行情（价格、涨跌幅、成交量、买卖五档）   | 新浪财经 |
| 日K线历史（30天，含均线）          | 新浪财经 |
| 实时资金流向（主力/超大单/大单/中单/小单） | 东方财富 |

## 异动信号

检测到以下任一信号时推送到微信：

1. **涨跌幅异动** — 日内涨跌幅超过 ±5%
2. **放量/缩量** — 量比 > 2 或 < 0.5
3. **主力大额流入/流出** — 主力净流入超 ±1亿
4. **资金流向反转** — 主力当日方向与近5日趋势相反
5. **5日累计涨跌** — 超过 ±10%
6. **20日累计涨跌** — 超过 ±20%
7. **买卖盘失衡** — 买卖挂单比超过 1.5 倍

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
git commit -m "深科技异动监控"
git branch -M main
git remote add origin https://github.com/你的用户名/stock-monitor.git
git push -u origin main
```

或者直接在 GitHub 网页上传文件（注意 .github 是隐藏文件夹，需先创建 .github/workflows 目录再上传 monitor.yml）。

### 3. 配置 SendKey 密钥

1. 打开仓库页面 → **Settings** → 左侧 **Secrets and variables** → **Actions**
2. 点 **New repository secret**
3. Name 填：`SERVERCHAN_SENDKEY`
4. Secret 填：你的 Server酱 SendKey（如 `SCT389227Tv80X6NEEHfsq7olY2UJanegR`）
5. 点 **Add secret**

### 4. 启用 GitHub Actions

1. 打开仓库页面 → 顶部 **Actions** 标签
2. 如果提示 "Workflows aren't being run on this repository"，点 **I understand my workflows, go ahead and enable them**
3. 左侧应能看到 **深科技异动监控** 工作流

### 5. 手动测试

1. 在 Actions 页面点击 **深科技异动监控**
2. 点右侧 **Run workflow** → **Run workflow**
3. 等待执行完成（约 30 秒），检查运行日志
4. 如果有异动信号，你的微信会收到方糖服务号的推送

## 运行时间

- **频率**：交易日每 15 分钟（9:25、9:40、9:55...15:05）
- **非交易日**：自动跳过（周末、节假日除外，节假日需手动暂停）
- **暂停方法**：Actions 页面 → 选中工作流 → 点 **...** → **Disable workflow**

## 注意事项

- GitHub Actions 的 cron 定时可能有 1-5 分钟延迟，属正常现象
- 仓库需保持 **Public** 才能享受无限 Actions 分钟数（Private 仓库每月 2000 分钟）
- Server酱免费额度为每天 5 条推送，盘中异动通常够用
- 节假日（国庆、春节等）需手动在 Actions 页面暂停工作流
