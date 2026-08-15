#!/usr/bin/env python3
"""
19只A股异动监控脚本
数据源：新浪财经(主) + 东方财富(辅)
推送通道：企业微信群机器人(主) / Server酱(备)
部署方式：GitHub Actions 定时运行
"""

import json
import urllib.request
import urllib.parse
import os
import time as _time
from datetime import datetime

# ============ 配置 ============
# 监控股票列表（自动解析交易所）
STOCKS = [
    ("SH600602", "云赛智联"),
    ("SZ000636", "风华高科"),
    ("SZ001248", "华润新能"),
    ("SH688825", "长鑫科技"),
    ("SZ001270", "铖昌科技"),
    ("SZ000021", "深科技"),
    ("SZ002384", "东山精密"),
    ("SH600584", "长电科技"),
    ("SZ300274", "阳光电源"),
    ("SZ002050", "三花智控"),
    ("SZ300502", "新易盛"),
    ("SZ002281", "光迅科技"),
    ("SH688019", "安集科技"),
    ("SH603986", "兆易创新"),
    ("SZ300450", "先导智能"),
    ("SZ300073", "当升科技"),
    ("SZ000333", "美的集团"),
    ("SH603259", "药明康德"),
    ("SZ002463", "沪电股份"),
]

# 推送通道（优先级：企业微信群机器人 > Server酱）
WECOM_WEBHOOK = os.environ.get("WECOM_WEBHOOK", "")
SENDKEY = os.environ.get("SERVERCHAN_SENDKEY", "")

# 关键词：公告标题中出现这些词时视为重要利空利好
IMPORTANT_KEYWORDS = [
    "异常波动", "业绩预告", "业绩快报", "增减持", "回购", "解禁",
    "质押", "冻结", "诉讼", "仲裁", "处分", "监管", "问询函",
    "重大资产", "重组", "收购", "合并", "分立", "停牌", "复牌",
    "分红", "派息", "送股", "转增", "激励", "行权",
]


# ============ 工具函数 ============
def parse_code(raw):
    """解析 SH/SZ 前缀，返回小写市场标识和纯数字代码"""
    raw = raw.strip().upper()
    if raw.startswith("SH"):
        return "sh", raw[2:], "1." + raw[2:]
    if raw.startswith("SZ"):
        return "sz", raw[2:], "0." + raw[2:]
    raise ValueError(f"无法解析股票代码: {raw}")


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


def fetch_text(url, encoding="gbk", retries=3, delay=1):
    """带重试的文本请求"""
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://finance.sina.com.cn/",
            })
            resp = urllib.request.urlopen(req, timeout=10)
            return resp.read().decode(encoding)
        except Exception as e:
            if i < retries - 1:
                _time.sleep(delay)
                delay += 1
            else:
                print(f"  [WARN] 请求失败: {url[:80]}... -> {e}")
                return None


# ============ 数据获取 ============
def get_sina_quotes():
    """新浪批量实时行情，一次返回所有股票"""
    symbols = [parse_code(code)[0] + parse_code(code)[1] for code, _ in STOCKS]
    url = "https://hq.sinajs.cn/list=" + ",".join(symbols)
    content = fetch_text(url)
    if not content:
        return {}

    results = {}
    for line in content.split(";"):
        line = line.strip()
        if not line or "=" not in line:
            continue
        prefix, data_part = line.split("=", 1)
        symbol = prefix.split("_")[-1]
        raw = data_part.strip().strip('"')
        if not raw:
            continue
        parts = raw.split(",")
        if len(parts) < 32:
            continue

        current = float(parts[3])
        prev_close = float(parts[2])
        change = current - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0
        high = float(parts[4])
        low = float(parts[5])
        volume_shares = int(parts[8])

        # 买卖五档（指数10-18为买, 20-28为卖, 奇数位为价格）
        buy_vol = sum(int(parts[i]) for i in range(10, 20, 2))
        sell_vol = sum(int(parts[i]) for i in range(20, 30, 2))

        results[symbol] = {
            "name": parts[0],
            "open": float(parts[1]),
            "prev_close": prev_close,
            "current": current,
            "high": high,
            "low": low,
            "volume": volume_shares // 100,
            "amount": float(parts[9]),
            "change": change,
            "change_pct": change_pct,
            "amplitude": ((high - low) / prev_close * 100) if prev_close else 0,
            "buy_vol": buy_vol,
            "sell_vol": sell_vol,
            "date": parts[30],
            "time": parts[31],
        }
    return results


def get_sina_kline(market, code):
    """新浪日K线历史（含5日/10日/30日均线）"""
    url = (
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketData.getKLineData?symbol={market}{code}&scale=240&datalen=30"
    )
    data = fetch_json(url)
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


def get_fund_flow(secid):
    """东方财富实时资金流向"""
    url = (
        "http://push2.eastmoney.com/api/qt/ulist.np/get"
        f"?secids={secid}"
        f"&fields=f62,f184,f66,f69,f72,f75,f78,f81,f84,f87"
        f"&ut=bd1d9ddb04089700cf9c05f1d4dbf136"
    )
    data = fetch_json(url)
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


def get_fund_flow_history(secid):
    """东方财富历史资金流向"""
    url = (
        "http://push2.eastmoney.com/api/qt/stock/fflow/daykline/get"
        f"?secid={secid}&lmt=20&klt=101"
        f"&fields1=f1,f2,f3,f7"
        f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63"
        f"&ut=bd1d9ddb04089700cf9c05f1d4dbf136"
    )
    data = fetch_json(url)
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


def get_announcements(code):
    """东方财富最新公告（5条）"""
    for protocol in ["https", "http"]:
        try:
            url = (
                f"{protocol}://np-anotice-stock.eastmoney.com/api/security/ann"
                f"?page_size=5&page_index=1&ann_type=A&stock_list={code}&f_node=0&s_node=0"
            )
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://data.eastmoney.com/",
                },
            )
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read())
            if data and data.get("data") and data["data"].get("list"):
                result = []
                for item in data["data"]["list"]:
                    title = item.get("title", "")
                    notice_date = item.get("notice_date", "")[:10]
                    column_name = ""
                    if item.get("columns"):
                        column_name = item["columns"][0].get("column_name", "")
                    is_important = any(kw in title for kw in IMPORTANT_KEYWORDS)
                    result.append({
                        "title": title,
                        "date": notice_date,
                        "category": column_name,
                        "important": is_important,
                    })
                return result
        except Exception as e:
            if protocol == "http":
                print(f"  [WARN] 公告接口异常: {e}")
    return []


def get_dragon_tiger(code):
    """东方财富龙虎榜（检查是否上榜）"""
    url = (
        "https://datacenter-web.eastmoney.com/api/data/v1/get"
        "?sortColumns=TRADE_DATE&sortTypes=-1&pageSize=10&pageNumber=1"
        "&reportName=RPT_DAILYBILLBOARD_DETAILS&columns=ALL"
        f"&filter=(SECURITY_CODE%3D%22{code}%22)"
    )
    data = fetch_json(url)
    if not data or not data.get("success"):
        return []
    result = []
    if data.get("result") and data["result"].get("data"):
        for item in data["result"]["data"]:
            result.append({
                "date": str(item.get("TRADE_DATE", ""))[:10],
                "reason": item.get("EXPLAIN", ""),
                "net_buy": item.get("NET_AMOUNT", 0),
                "buy_amount": item.get("BUY_AMOUNT", 0),
                "sell_amount": item.get("SELL_AMOUNT", 0),
            })
    return result


def calc_volume_ratio(quote, kline_history):
    """估算量比 = 今日成交量 / 5日均量"""
    if not quote or not kline_history or len(kline_history) < 6:
        return None
    recent_5 = kline_history[-6:-1]
    if not recent_5:
        return None
    avg_vol = sum(k["volume"] for k in recent_5) / len(recent_5)
    if avg_vol == 0:
        return None
    today_vol = quote.get("volume", 0) * 100
    return today_vol / avg_vol


# ============ 异动分析 ============
def analyze_signals(quote, fund_flow, ff_history, vol_ratio, announcements=None, dragon_tiger=None):
    """分析单只股票的异动信号"""
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

    # 5. 买卖盘失衡
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

    # 6. 当天重要公告（仅今天的，标题含关键词）
    if announcements:
        today = datetime.now().date()
        for ann in announcements:
            try:
                ann_date = datetime.strptime(ann["date"], "%Y-%m-%d").date()
                if ann_date == today and ann.get("important"):
                    signals.append(f"**重要公告**：{ann['title']}")
            except (ValueError, KeyError):
                pass

    # 7. 当天龙虎榜上榜（仅今天的）
    if dragon_tiger:
        today = datetime.now().date()
        for item in dragon_tiger:
            try:
                lhb_date = datetime.strptime(item["date"], "%Y-%m-%d").date()
                if lhb_date == today:
                    net = item.get("net_buy", 0)
                    net_str = f"净买入{abs(net)/1e8:.2f}亿" if net >= 0 else f"净卖出{abs(net)/1e8:.2f}亿"
                    signals.append(
                        f"**龙虎榜上榜**：{item.get('reason', '')}，{net_str}"
                    )
            except (ValueError, KeyError):
                pass

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
            print(f"  [OK] Server酱推送成功")
            return True
        else:
            print(f"  [ERROR] Server酱推送失败: {result}")
            return False
    except Exception as e:
        print(f"  [ERROR] Server酱推送异常: {e}")
        return False


def send_wecom(content):
    """企业微信群机器人推送（Markdown格式）"""
    if not WECOM_WEBHOOK:
        print("  [INFO] 未配置 WECOM_WEBHOOK，跳过企业微信推送")
        return False

    payload = json.dumps({
        "msgtype": "markdown",
        "markdown": {"content": content},
    }).encode("utf-8")
    try:
        req = urllib.request.Request(WECOM_WEBHOOK, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read())
        if result.get("errcode") == 0:
            print(f"  [OK] 企业微信推送成功")
            return True
        else:
            print(f"  [ERROR] 企业微信推送失败: {result}")
            return False
    except Exception as e:
        print(f"  [ERROR] 企业微信推送异常: {e}")
        return False


def format_stock_block(stock_name, stock_code, quote, signals, fund_flow, vol_ratio):
    """格式化单只股票的异动块"""
    price = quote["current"]
    chg = quote["change_pct"]
    market_prefix = stock_code[:2]
    display_code = stock_code[2:]

    r = f"### {stock_name}({market_prefix}{display_code}) {price:.2f}元({chg:+.2f}%)\n"
    for i, s in enumerate(signals, 1):
        r += f"{i}. {s}\n"

    parts = []
    if fund_flow:
        net = fund_flow["main_net"] / 1e8
        color = "info" if net >= 0 else "warning"
        parts.append(f"主力<font color=\"{color}\">{net:+.2f}亿</font>")
    if vol_ratio:
        parts.append(f"量比{vol_ratio:.1f}")
    parts.append(f"成交额{quote['amount']/1e8:.1f}亿")
    r += " | ".join(parts) + "\n\n"
    return r


def format_report_wecom(results):
    """格式化合并推送内容"""
    now_str = datetime.now().strftime("%H:%M")
    r = f"## 股票异动提醒（{len(results)}只）\n"
    r += f"时间：{now_str}\n\n"
    for item in results:
        r += format_stock_block(
            item["name"], item["code"], item["quote"],
            item["signals"], item["fund_flow"], item["vol_ratio"]
        )
    return r


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


def monitor_one_stock(raw_code, stock_name, all_quotes):
    """监控单只股票，返回包含异动的结果或None"""
    market, code, secid = parse_code(raw_code)
    symbol = market + code

    print(f"\n  --- {stock_name}({raw_code}) ---")
    quote = all_quotes.get(symbol)
    if not quote:
        print(f"  [WARN] 未获取到行情")
        return None

    print(f"  当前价: {quote['current']:.2f}元  涨跌幅: {quote['change_pct']:+.2f}%")

    _time.sleep(0.3)
    print("  [1/5] 获取K线历史...")
    kline = get_sina_kline(market, code)

    _time.sleep(0.3)
    print("  [2/5] 获取资金流向...")
    fund_flow = get_fund_flow(secid)

    _time.sleep(0.3)
    print("  [3/5] 获取历史资金流向...")
    ff_history = get_fund_flow_history(secid)

    _time.sleep(0.3)
    print("  [4/5] 获取最新公告...")
    announcements = get_announcements(code)

    _time.sleep(0.3)
    print("  [5/5] 检查龙虎榜...")
    dragon_tiger = get_dragon_tiger(code)

    vol_ratio = calc_volume_ratio(quote, kline)
    if vol_ratio:
        print(f"  量比(估): {vol_ratio:.2f}")
    if fund_flow:
        print(f"  主力净流入: {fund_flow['main_net']/1e8:+.2f}亿")

    signals = analyze_signals(quote, fund_flow, ff_history, vol_ratio, announcements, dragon_tiger)
    if signals:
        print(f"  检测到 {len(signals)} 个异动信号")
        for s in signals:
            print(f"    - {s}")
        return {
            "name": stock_name,
            "code": raw_code,
            "quote": quote,
            "fund_flow": fund_flow,
            "vol_ratio": vol_ratio,
            "signals": signals,
        }
    else:
        print(f"  无明显异动")
        return None


def main():
    print(f"=== 19只A股异动监控 ===")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    trading, reason = is_trading_time()
    if not trading:
        print(f"  {reason}，跳过")
        return

    # 批量获取所有股票实时行情
    print("\n  [批量] 获取实时行情(新浪)...")
    all_quotes = get_sina_quotes()
    if not all_quotes:
        print("  [ERROR] 无法获取行情数据，退出")
        return

    print(f"  成功获取 {len(all_quotes)}/{len(STOCKS)} 只股票行情")

    # 逐只分析
    alerted = []
    for raw_code, stock_name in STOCKS:
        try:
            result = monitor_one_stock(raw_code, stock_name, all_quotes)
            if result:
                alerted.append(result)
        except Exception as e:
            print(f"  [ERROR] 处理 {raw_code} 异常: {e}")
        _time.sleep(0.5)

    # 推送
    print(f"\n  --- 汇总 ---")
    if alerted:
        print(f"  共 {len(alerted)} 只股票触发异动")
        report = format_report_wecom(alerted)

        pushed = False
        if WECOM_WEBHOOK:
            pushed = send_wecom(report)
        if not pushed and SENDKEY:
            title = f"股票异动提醒（{len(alerted)}只）"
            send_serverchan(title, report)
        if not WECOM_WEBHOOK and not SENDKEY:
            print("  [WARN] 未配置任何推送通道")
    else:
        print(f"  19只股票均无异常")


if __name__ == "__main__":
    main()
