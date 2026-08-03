#!/usr/bin/env python3
"""
深科技(sz000021) 异动监控脚本
数据源：新浪财经(主) + 东方财富(辅)
推送通道：Server酱 -> 微信
部署方式：GitHub Actions 定时运行
"""

import json
import urllib.request
import urllib.parse
import os
import time as _time
from datetime import datetime, timedelta

# ============ 配置 ============
STOCK_CODE = "000021"
STOCK_NAME = "深科技"
SECID = "0.000021"  # 0=深圳, 1=上海

SENDKEY = os.environ.get("SERVERCHAN_SENDKEY", "")

# ============ 数据接口 ============
# 新浪（主数据源，最稳定）
SINA_QUOTE_URL = f"https://hq.sinajs.cn/list=sz{STOCK_CODE}"
SINA_KLINE_URL = (
    f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    f"CN_MarketData.getKLineData?symbol=sz{STOCK_CODE}&scale=240&datalen=30"
)

# 东方财富（辅助，资金流向）
EM_FUND_FLOW_URL = (
    f"http://push2.eastmoney.com/api/qt/ulist.np/get"
    f"?secids={SECID}"
    f"&fields=f62,f184,f66,f69,f72,f75,f78,f81,f84,f87"
    f"&ut=bd1d9ddb04089700cf9c05f1d4dbf136"
)
EM_FUND_FLOW_HIST_URL = (
    f"http://push2.eastmoney.com/api/qt/stock/fflow/daykline/get"
    f"?secid={SECID}&lmt=20&klt=101"
    f"&fields1=f1,f2,f3,f7"
    f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63"
    f"&ut=bd1d9ddb04089700cf9c05f1d4dbf136"
)


# ============ 网络请求 ============
def fetch_json(url, retries=3, delay=1):
    """带重试的 JSON 请求"""
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://finance.sina.com.cn/",
            })
            resp = urllib.request.urlopen(req, timeout=15)
            return json.loads(resp.read())
        except Exception as e:
            if i < retries - 1:
                _time.sleep(delay)
                delay += 1
            else:
                print(f"  [WARN] 请求失败: {url[:80]}... -> {e}")
                return None


# ============ 数据获取 ============
def get_sina_quote():
    """新浪实时行情"""
    try:
        req = urllib.request.Request(SINA_QUOTE_URL, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn/",
        })
        resp = urllib.request.urlopen(req, timeout=10)
        content = resp.read().decode("gbk")
        parts = content.split('"')[1].split(",")

        current = float(parts[3])
        prev_close = float(parts[2])
        change = current - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0
        high = float(parts[4])
        low = float(parts[5])
        volume_shares = int(parts[8])

        # 买卖五档（指数10-18为买, 20-28为卖, 奇数位为价格）
        buy_vol = sum(int(parts[i]) for i in range(10, 20, 2))   # 买1-5量
        sell_vol = sum(int(parts[i]) for i in range(20, 30, 2))  # 卖1-5量

        return {
            "name": parts[0],
            "open": float(parts[1]),
            "prev_close": prev_close,
            "current": current,
            "high": high,
            "low": low,
            "volume": volume_shares // 100,  # 转为手
            "amount": float(parts[9]),
            "change": change,
            "change_pct": change_pct,
            "amplitude": ((high - low) / prev_close * 100) if prev_close else 0,
            "buy_vol": buy_vol,
            "sell_vol": sell_vol,
            "date": parts[30],
            "time": parts[31],
        }
    except Exception as e:
        print(f"  [WARN] 新浪行情异常: {e}")
        return None


def get_sina_kline():
    """新浪日K线历史（含5日/10日/30日均线）"""
    data = fetch_json(SINA_KLINE_URL)
    if not data:
        return None
    klines = []
    for item in data:
        klines.append({
            "date": item["day"],
            "open": float(item["open"]),
            "close": float(item["close"]),
            "high": float(item["high"]),
            "low": float(item["low"]),
            "volume": int(item["volume"]),
            "ma5": item.get("ma_price5"),
            "ma_vol5": item.get("ma_volume5"),
            "ma10": item.get("ma_price10"),
            "ma30": item.get("ma_price30"),
        })
    return klines


def get_fund_flow():
    """东方财富实时资金流向"""
    data = fetch_json(EM_FUND_FLOW_URL)
    if data and data.get("data") and data["data"].get("diff"):
        d = data["data"]["diff"][0]
        return {
            "main_net": d.get("f62", 0),
            "main_pct": d.get("f184", 0) / 100,
            "super_large_net": d.get("f66", 0),
            "super_large_pct": d.get("f69", 0) / 100,
            "large_net": d.get("f72", 0),
            "large_pct": d.get("f75", 0) / 100,
            "medium_net": d.get("f78", 0),
            "medium_pct": d.get("f81", 0) / 100,
            "small_net": d.get("f84", 0),
            "small_pct": d.get("f87", 0) / 100,
        }
    return None


def get_fund_flow_history():
    """东方财富历史资金流向"""
    data = fetch_json(EM_FUND_FLOW_HIST_URL)
    if data and data.get("data") and data["data"].get("klines"):
        flows = []
        for line in data["data"]["klines"]:
            parts = line.split(",")
            flows.append({
                "date": parts[0],
                "main_net": float(parts[1]),
            })
        return flows
    return None


def calc_volume_ratio(quote, kline_history):
    """估算量比 = 今日成交量 / 5日均量"""
    if not quote or not kline_history or len(kline_history) < 6:
        return None
    # 取最近5个完整交易日的均量（不含今天）
    recent_5 = kline_history[-6:-1] if len(kline_history) >= 6 else kline_history[:-1]
    if not recent_5:
        return None
    avg_vol = sum(k["volume"] for k in recent_5) / len(recent_5)
    if avg_vol == 0:
        return None
    # 今日成交量（股）与5日均量（股）比较
    today_vol = quote.get("volume", 0) * 100  # 手转股
    return today_vol / avg_vol


# ============ 异动分析 ============
def analyze_signals(quote, fund_flow, ff_history, kline_history, vol_ratio):
    """分析异动信号"""
    signals = []

    if not quote:
        return signals

    change_pct = quote.get("change_pct", 0)
    current = quote.get("current", 0)

    # 1. 涨跌幅异动 (|涨跌|>=5%)
    if abs(change_pct) >= 5:
        tag = "大跌" if change_pct < 0 else "大涨"
        signals.append(
            f"**{tag}异动**：当前价 {current:.2f}元，涨跌幅 {change_pct:+.2f}%"
        )

    # 2. 量比异动
    if vol_ratio is not None:
        if vol_ratio > 2.0:
            signals.append(f"**放量异动**：量比约 {vol_ratio:.2f}，成交额骤放")
        elif vol_ratio < 0.5:
            signals.append(f"**极度缩量**：量比约 {vol_ratio:.2f}，成交萎缩")

    # 3. 主力大额流入/流出 (|净流入|>=1亿)
    if fund_flow:
        main_net = fund_flow["main_net"]
        if abs(main_net) >= 1e8:
            tag = "流入" if main_net > 0 else "流出"
            signals.append(
                f"**主力大额{tag}**：净{tag} {abs(main_net)/1e8:.2f}亿"
            )

    # 4. 资金流向反转
    if fund_flow and ff_history and len(ff_history) >= 2:
        today_main = fund_flow["main_net"]
        recent = ff_history[-6:-1] if len(ff_history) >= 6 else ff_history[:-1]
        if recent:
            recent_sum = sum(f["main_net"] for f in recent)
            if today_main > 5e7 and recent_sum < -5e7:
                signals.append(
                    f"**资金流向反转**：主力今日净流入 {today_main/1e8:.2f}亿，"
                    f"但近5日累计净流出 {abs(recent_sum)/1e8:.2f}亿"
                )
            elif today_main < -5e7 and recent_sum > 5e7:
                signals.append(
                    f"**资金流向反转**：主力今日净流出 {abs(today_main)/1e8:.2f}亿，"
                    f"但近5日累计净流入 {recent_sum/1e8:.2f}亿"
                )

    # 5. 5日累计涨跌幅 (|涨跌|>=10%)
    if kline_history and len(kline_history) >= 6:
        recent_5 = kline_history[-5:]
        first_close = recent_5[0]["close"]
        last_close = recent_5[-1]["close"]
        if first_close > 0:
            change_5d = (last_close - first_close) / first_close * 100
            if abs(change_5d) >= 10:
                tag = "下跌" if change_5d < 0 else "上涨"
                signals.append(
                    f"**5日累计{tag}**：{change_5d:+.2f}%"
                    f"（{recent_5[0]['date'][:10]} {first_close:.2f} -> "
                    f"{recent_5[-1]['date'][:10]} {last_close:.2f}）"
                )

    # 6. 20日累计涨跌幅 (|涨跌|>=20%)
    if kline_history and len(kline_history) >= 20:
        recent_20 = kline_history[-20:]
        first_close = recent_20[0]["close"]
        last_close = recent_20[-1]["close"]
        if first_close > 0:
            change_20d = (last_close - first_close) / first_close * 100
            if abs(change_20d) >= 20:
                tag = "下跌" if change_20d < 0 else "上涨"
                signals.append(f"**20日累计{tag}**：{change_20d:+.2f}%")

    # 7. 买卖盘失衡
    buy_v = quote.get("buy_vol", 0)
    sell_v = quote.get("sell_vol", 0)
    if buy_v > 0 and sell_v > 0:
        ratio = max(buy_v, sell_v) / min(buy_v, sell_v)
        if ratio >= 1.5:
            tag = "买盘" if buy_v > sell_v else "卖盘"
            signals.append(
                f"**买卖盘失衡**：{tag}占优，"
                f"买盘{buy_v/10000:.1f}万手 vs 卖盘{sell_v/10000:.1f}万手"
            )

    return signals


# ============ 推送 ============
def send_serverchan(title, desp):
    """Server酱推送"""
    if not SENDKEY:
        print("  [INFO] 未配置 SENDKEY，跳过推送")
        return False

    url = f"https://sctapi.ftqq.com/{SENDKEY}.send"
    data = urllib.parse.urlencode({"title": title, "desp": desp}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data, method="POST")
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read())
        if result.get("code") == 0:
            print(f"  [OK] 推送成功")
            return True
        else:
            print(f"  [ERROR] 推送失败: {result}")
            return False
    except Exception as e:
        print(f"  [ERROR] 推送异常: {e}")
        return False


# ============ 主流程 ============
def is_trading_time():
    """判断是否在交易时段"""
    now = datetime.now()
    if now.weekday() >= 5:
        return False, "周末"
    hm = now.hour * 100 + now.minute
    if 925 <= hm <= 1135 or 1255 <= hm <= 1505:
        return True, ""
    return False, "非交易时段"


def main():
    print(f"=== 深科技异动监控 ===")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    trading, reason = is_trading_time()
    if not trading:
        print(f"  {reason}，跳过")
        return

    # 获取数据
    print("  [1/4] 获取实时行情(新浪)...")
    quote = get_sina_quote()
    _time.sleep(0.5)

    print("  [2/4] 获取K线历史(新浪)...")
    kline = get_sina_kline()
    _time.sleep(0.5)

    print("  [3/4] 获取资金流向(东方财富)...")
    fund_flow = get_fund_flow()
    _time.sleep(0.5)

    print("  [4/4] 获取历史资金流向(东方财富)...")
    ff_history = get_fund_flow_history()

    if not quote:
        print("  [ERROR] 无法获取行情数据，退出")
        return

    # 计算量比
    vol_ratio = calc_volume_ratio(quote, kline)

    # 数据摘要
    print(f"\n  --- 数据摘要 ---")
    print(f"  股票: {quote['name']}({STOCK_CODE})")
    print(f"  当前价: {quote['current']:.2f}元  涨跌幅: {quote['change_pct']:+.2f}%")
    if vol_ratio:
        print(f"  量比(估): {vol_ratio:.2f}")
    print(f"  成交量: {quote['volume']:,}手  成交额: {quote['amount']/1e8:.2f}亿")
    if fund_flow:
        print(f"  主力净流入: {fund_flow['main_net']/1e8:+.2f}亿")
    if kline:
        print(f"  K线历史: {len(kline)}天")

    # 分析异动
    print(f"\n  --- 异动分析 ---")
    signals = analyze_signals(quote, fund_flow, ff_history, kline, vol_ratio)

    if signals:
        print(f"  检测到 {len(signals)} 个异动信号:")
        for i, s in enumerate(signals, 1):
            print(f"    {i}. {s}")

        # 构建推送内容
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        report = f"## 深科技 sz000021 异动提醒\n\n"
        report += f"**时间**: {now_str}\n\n"
        report += f"**当前价**: {quote['current']:.2f}元 "
        report += f"({quote['change_pct']:+.2f}%)\n\n"
        report += f"### 异动信号\n\n"
        for i, s in enumerate(signals, 1):
            report += f"{i}. {s}\n\n"
        report += f"### 关键数据\n\n"
        report += f"| 指标 | 数值 |\n|------|------|\n"
        report += f"| 当前价 | {quote['current']:.2f}元 |\n"
        report += f"| 涨跌幅 | {quote['change_pct']:+.2f}% |\n"
        if vol_ratio:
            report += f"| 量比(估) | {vol_ratio:.2f} |\n"
        report += f"| 成交额 | {quote['amount']/1e8:.2f}亿 |\n"
        report += f"| 振幅 | {quote['amplitude']:.2f}% |\n"
        if fund_flow:
            report += f"| 主力净流入 | {fund_flow['main_net']/1e8:+.2f}亿 |\n"
            report += f"| 超大单 | {fund_flow['super_large_net']/1e8:+.2f}亿 |\n"
            report += f"| 大单 | {fund_flow['large_net']/1e8:+.2f}亿 |\n"
            report += f"| 中单 | {fund_flow['medium_net']/1e8:+.2f}亿 |\n"
            report += f"| 小单 | {fund_flow['small_net']/1e8:+.2f}亿 |\n"
        if kline and len(kline) >= 6:
            recent_5 = kline[-5:]
            chg5 = (recent_5[-1]["close"] - recent_5[0]["close"]) / recent_5[0]["close"] * 100
            report += f"| 5日涨跌 | {chg5:+.2f}% |\n"
        report += f"\n> 数据来源: 新浪财经/东方财富"

        print(f"\n  --- 推送到微信 ---")
        send_serverchan(
            f"深科技异动 {quote['current']:.2f}元({quote['change_pct']:+.2f}%)",
            report,
        )
    else:
        print(f"  无明显异动")
        status = (
            f"深科技{STOCK_CODE} 无明显异动，"
            f"{quote['current']:.2f}元({quote['change_pct']:+.2f}%)"
        )
        if fund_flow:
            status += f"，主力{fund_flow['main_net']/1e8:+.2f}亿"
        print(f"  {status}")


if __name__ == "__main__":
    main()
