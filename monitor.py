#!/usr/bin/env python3
"""
19只A股异动监控脚本（双模式）
数据源：新浪财经(主行情) + 东方财富(资金/公告/龙虎榜) + 巨潮资讯网(公告补充)
推送通道：企业微信群机器人(主) / Server酱(备)
部署方式：GitHub Actions 定时运行 / WorkBuddy 本地自动化

用法:
  python monitor.py --mode trade   # 实时交易监控（交易日9:00-15:30）
  python monitor.py --mode news    # 公告/龙虎榜消息面监控（全天）
"""

import json
import urllib.request
import urllib.parse
import os
import sys
import re
import time as _time
from datetime import datetime, timedelta

# ============ 配 ============
# 监控股票列表（含巨潮资讯网 orgId 和板块）
# 字段: (代码, 名称, 巨潮orgId, 巨潮板块)
STOCKS = [
    ("SH600602", "云赛智联", "gssh0600602", "sse"),
    ("SZ000636", "风华高科", "gssz0000636", "szse"),
    ("SZ001248", "华润新能", "9900062481", "szse"),
    ("SH688825", "长鑫科技", "9920000008", "sse"),
    ("SZ001270", "铖昌科技", "9900052541", "szse"),
    ("SZ000021", "深科技", "gssz0000021", "szse"),
    ("SZ002384", "东山精密", "9900011647", "szse"),
    ("SH600584", "长电科技", "gssh0600584", "sse"),
    ("SZ300274", "阳光电源", "9900021300", "szse"),
    ("SZ002050", "三花智控", "gssz0002050", "szse"),
    ("SZ300502", "新易盛", "9900026455", "szse"),
    ("SZ002281", "光迅科技", "9900007888", "szse"),
    ("SH688019", "安集科技", "9900038987", "sse"),
    ("SH603986", "兆易创新", "9900026561", "sse"),
    ("SZ300450", "先导智能", "9900023846", "szse"),
    ("SZ300073", "当升科技", "9900011167", "szse"),
    ("SZ000333", "美的集团", "9900005965", "szse"),
    ("SH603259", "药明康德", "9900035584", "sse"),
    ("SZ002463", "沪电股份", "9900013929", "szse"),
]

# 推送通道（优先级：企业微信群机器人 > Server酱）
WECOM_WEBHOOK = os.environ.get("WECOM_WEBHOOK", "")
SENDKEY = os.environ.get("SERVERCHAN_SENDKEY", "")

# 去重状态文件（记录已推送的公告/龙虎榜，避免重复推送）
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "news_state.json")

# 关键词：公告标题中出现这些词时视为重要利空利好
IMPORTANT_KEYWORDS = [
    "异常波动", "业绩预告", "业绩快报", "增减持", "回购", "解禁",
    "质押", "冻结", "诉讼", "仲裁", "处分", "监管", "问询函",
    "重大资产", "重组", "收购", "合并", "分立", "停牌", "复牌",
    "分红", "派息", "送股", "转增", "激励", "行权",
    "担保", "减持", "增持", "违规", "立案", "处罚",
    "退市", "风险警示", "问询", "函", "审批", "核准",
]

# 公告去重时间窗（分钟）：只推送最近N分钟内发布的公告
ANNOUNCE_WINDOW_MIN = 40


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


def post_json(url, data, headers=None, retries=3, delay=1):
    """带重试的 POST JSON 请求"""
    for i in range(retries):
        try:
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            if headers:
                for k, v in headers.items():
                    req.add_header(k, v)
            resp = urllib.request.urlopen(req, timeout=15)
            return json.loads(resp.read())
        except Exception as e:
            if i < retries - 1:
                _time.sleep(delay)
                delay += 1
            else:
                print(f"  [WARN] POST失败: {url[:80]}... -> {e}")
                return None


# ============ 去重状态 ============
def load_state():
    """加载已推送记录"""
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"pushed": {}}


def save_state(state):
    """保存状态文件"""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    except Exception as e:
        print(f"  [WARN] 状态保存失败: {e}")


def prune_state(state):
    """清理7天前的记录"""
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    state["pushed"] = {k: v for k, v in state["pushed"].items() if v > cutoff}
    return state


def is_pushed(state, key):
    return key in state.get("pushed", {})


def mark_pushed(state, key):
    state.setdefault("pushed", {})[key] = datetime.now().isoformat()


# ============ 数据获取 ============
def get_sina_quotes():
    """新浪批量实时行情，一次返回所有股票"""
    symbols = [parse_code(code)[0] + parse_code(code)[1] for code, _, _, _ in STOCKS]
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
            "large_net": d.get("f72", 0),
            "medium_net": d.get("f78", 0),
            "small_net": d.get("f84", 0),
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
            flows.append({"date": parts[0], "main_net": float(parts[1])})
        return flows
    return None


def get_announcements_eastmoney(code):
    """东方财富最新公告，返回带art_code和eiTime的列表"""
    for protocol in ["https", "http"]:
        try:
            url = (
                f"{protocol}://np-anotice-stock.eastmoney.com/api/security/ann"
                f"?page_size=10&page_index=1&ann_type=A&stock_list={code}&f_node=0&s_node=0"
            )
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://data.eastmoney.com/",
            })
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read())
            if data and data.get("data") and data["data"].get("list"):
                result = []
                for item in data["data"]["list"]:
                    title = item.get("title", "")
                    art_code = item.get("art_code", "")
                    ei_time = item.get("eiTime", "")[:19]
                    is_important = any(kw in title for kw in IMPORTANT_KEYWORDS)
                    result.append({
                        "title": title,
                        "art_code": art_code,
                        "ei_time": ei_time,
                        "important": is_important,
                        "source": "东财",
                    })
                return result
        except Exception as e:
            if protocol == "http":
                print(f"  [WARN] 东财公告接口异常({code}): {e}")
    return []


def get_announcements_cninfo(code, org_id, column):
    """巨潮资讯网（证监会指定信息披露平台）最新公告"""
    try:
        url = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
        post_data = urllib.parse.urlencode({
            "pageNum": "1",
            "pageSize": "10",
            "column": column,
            "tabName": "fulltext",
            "stock": f"{code},{org_id}",
            "seDate": "",
        }).encode("utf-8")
        result = post_json(url, post_data, headers={
            "Referer": "https://www.cninfo.com.cn/",
        })
        if not result:
            return []
        anns = result.get("announcements") or []
        out = []
        for item in anns:
            title = item.get("announcementTitle", "")
            ann_id = item.get("announcementId", "")
            ts_ms = item.get("announcementTime", 0)
            if ts_ms:
                ei = datetime.fromtimestamp(ts_ms / 1000)
                ei_time = ei.strftime("%Y-%m-%d %H:%M:%S")
            else:
                ei_time = ""
            is_important = any(kw in title for kw in IMPORTANT_KEYWORDS)
            out.append({
                "title": title,
                "art_code": ann_id,
                "ei_time": ei_time,
                "important": is_important,
                "source": "巨潮",
            })
        return out
    except Exception as e:
        print(f"  [WARN] 巨潮公告接口异常({code}): {e}")
        return []


def get_dragon_tiger(code):
    """东方财富龙虎榜"""
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
def analyze_trade_signals(quote, fund_flow, ff_history, vol_ratio):
    """分析实时交易类异动信号（5类，不含公告/龙虎榜）"""
    signals = []
    if not quote:
        return signals

    change_pct = quote.get("change_pct", 0)
    current = quote.get("current", 0)

    # 1. 涨跌幅异动 (|涨跌|>=5%)
    if abs(change_pct) >= 5:
        tag = "大跌" if change_pct < 0 else "大涨"
        signals.append(f"**{tag}异动**：当前价 {current:.2f}元，涨跌幅 {change_pct:+.2f}%")

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
            signals.append(f"**主力大额{tag}**：净{tag} {abs(main_net)/1e8:.2f}亿")

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

    return signals


def merge_announcements(em_list, cn_list):
    """合并东方财富和巨潮资讯的公告，按标题去重"""
    seen_titles = set()
    merged = []
    for ann in em_list + cn_list:
        title = ann.get("title", "")
        # 标题去重：取较短的作为基准比较，去掉括号差异
        title_key = re.sub(r"[（）()【】\[\]【】]", "", title).strip()
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        merged.append(ann)
    return merged


def analyze_news_signals(announcements, dragon_tiger, stock_code, state):
    """分析消息面异动信号（公告+龙虎榜），带去重"""
    signals = []
    now = datetime.now()

    # 6. 重要公告（仅最近N分钟内发布的，且未推送过）
    if announcements:
        for ann in announcements:
            if not ann.get("important"):
                continue
            try:
                ei = datetime.strptime(ann["ei_time"], "%Y-%m-%d %H:%M:%S")
            except (ValueError, KeyError):
                continue
            age = (now - ei).total_seconds() / 60
            if age < 0 or age > ANNOUNCE_WINDOW_MIN:
                continue
            art_code = ann.get("art_code", ann["title"])
            dedup_key = f"ann_{art_code}"
            if is_pushed(state, dedup_key):
                continue
            source_tag = f"[{ann.get('source', '')}]" if ann.get("source") else ""
            signals.append(f"**重要公告**{source_tag}：{ann['title']}")
            mark_pushed(state, dedup_key)

    # 7. 当天龙虎榜上榜（TRADE_DATE == 今天，且未推送过）
    if dragon_tiger:
        today_str = now.strftime("%Y-%m-%d")
        for item in dragon_tiger:
            if item["date"] != today_str:
                continue
            lhb_key = f"lhb_{stock_code}_{item['date']}"
            if is_pushed(state, lhb_key):
                continue
            net = item.get("net_buy", 0)
            net_str = f"净买入{abs(net)/1e8:.2f}亿" if net >= 0 else f"净卖出{abs(net)/1e8:.2f}亿"
            signals.append(f"**龙虎榜上榜**：{item.get('reason', '')}，{net_str}")
            mark_pushed(state, lhb_key)

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
    payload = json.dumps({"msgtype": "markdown", "markdown": {"content": content}}).encode("utf-8")
    try:
        req = urllib.request.Request(WECOM_WEBHOOK, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read())
        if result.get("errcode") == 0:
            print(f"  [OK] 企业微信推送成功")
            return True
        print(f"  [ERROR] 企业微信推送失败: {result}")
        return False
    except Exception as e:
        print(f"  [ERROR] 企业微信推送异常: {e}")
        return False


def format_trade_report(results):
    """格式化实时交易异动推送内容"""
    now_str = datetime.now().strftime("%H:%M")
    r = f"## 实时异动提醒（{len(results)}只）\n时间：{now_str}\n\n"
    for item in results:
        q = item["quote"]
        r += f"### {item['name']}({item['code']}) {q['current']:.2f}元({q['change_pct']:+.2f}%)\n"
        for i, s in enumerate(item["signals"], 1):
            r += f"{i}. {s}\n"
        parts = []
        if item["fund_flow"]:
            net = item["fund_flow"]["main_net"] / 1e8
            color = "info" if net >= 0 else "warning"
            parts.append(f"主力<font color=\"{color}\">{net:+.2f}亿</font>")
        if item["vol_ratio"]:
            parts.append(f"量比{item['vol_ratio']:.1f}")
        parts.append(f"成交额{q['amount']/1e8:.1f}亿")
        r += " | ".join(parts) + "\n\n"
    return r


def format_news_report(results):
    """格式化消息面异动推送内容"""
    now_str = datetime.now().strftime("%m-%d %H:%M")
    r = f"## 公告/龙虎榜提醒（{len(results)}只）\n时间：{now_str}\n\n"
    for item in results:
        r += f"### {item['name']}({item['code']})\n"
        for i, s in enumerate(item["signals"], 1):
            r += f"{i}. {s}\n"
        r += "\n"
    return r


def push(title, report):
    """推送：企业微信优先，Server酱兜底"""
    pushed = False
    if WECOM_WEBHOOK:
        pushed = send_wecom(report)
    if not pushed and SENDKEY:
        send_serverchan(title, report)
    if not WECOM_WEBHOOK and not SENDKEY:
        print("  [WARN] 未配置任何推送通道")


# ============ 主流程 ============
def is_trading_time():
    """判断是否在交易时段（交易日 9:00-15:30）"""
    now = datetime.now()
    if now.weekday() >= 5:
        return False, "周末"
    hm = now.hour * 100 + now.minute
    if 900 <= hm <= 1530:
        return True, ""
    return False, "非交易时段"


def run_trade_mode():
    """实时交易监控模式"""
    print(f"=== 实时交易监控（{len(STOCKS)}只）===")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    trading, reason = is_trading_time()
    if not trading:
        print(f"  {reason}，跳过")
        return

    print("\n  [批量] 获取实时行情(新浪)...")
    all_quotes = get_sina_quotes()
    if not all_quotes:
        print("  [ERROR] 无法获取行情数据，退出")
        return
    print(f"  成功获取 {len(all_quotes)}/{len(STOCKS)} 只")

    alerted = []
    for raw_code, stock_name, _, _ in STOCKS:
        try:
            market, code, secid = parse_code(raw_code)
            symbol = market + code
            quote = all_quotes.get(symbol)
            if not quote:
                continue
            print(f"\n  --- {stock_name}({raw_code}) {quote['current']:.2f}元({quote['change_pct']:+.2f}%) ---")
            _time.sleep(0.3)
            kline = get_sina_kline(market, code)
            _time.sleep(0.3)
            fund_flow = get_fund_flow(secid)
            _time.sleep(0.3)
            ff_history = get_fund_flow_history(secid)
            vol_ratio = calc_volume_ratio(quote, kline)
            signals = analyze_trade_signals(quote, fund_flow, ff_history, vol_ratio)
            if signals:
                print(f"  检测到 {len(signals)} 个异动信号")
                alerted.append({
                    "name": stock_name, "code": raw_code, "quote": quote,
                    "fund_flow": fund_flow, "vol_ratio": vol_ratio, "signals": signals,
                })
            else:
                print(f"  无异动")
        except Exception as e:
            print(f"  [ERROR] 处理 {raw_code} 异常: {e}")
        _time.sleep(0.3)

    print(f"\n  --- 汇总 ---")
    if alerted:
        print(f"  共 {len(alerted)} 只触发实时异动")
        push(f"实时异动提醒（{len(alerted)}只）", format_trade_report(alerted))
    else:
        print(f"  均无实时异动")


def run_news_mode():
    """公告/龙虎榜消息面监控模式（全天运行）"""
    print(f"=== 公告/龙虎榜监控（{len(STOCKS)}只）===")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    state = prune_state(load_state())
    new_state = False
    alerted = []

    for raw_code, stock_name, org_id, column in STOCKS:
        try:
            _, code, _ = parse_code(raw_code)
            print(f"\n  --- {stock_name}({raw_code}) ---")
            _time.sleep(0.3)
            # 公告数据源1: 东方财富
            em_anns = get_announcements_eastmoney(code)
            _time.sleep(0.3)
            # 公告数据源2: 巨潮资讯网（证监会指定信息披露平台）
            cn_anns = get_announcements_cninfo(code, org_id, column)
            _time.sleep(0.3)
            # 合并去重
            all_anns = merge_announcements(em_anns, cn_anns)
            print(f"  公告: 东财{len(em_anns)}条 + 巨潮{len(cn_anns)}条 = 合并后{len(all_anns)}条")
            # 龙虎榜
            dragon_tiger = get_dragon_tiger(code)
            signals = analyze_news_signals(all_anns, dragon_tiger, raw_code, state)
            if signals:
                print(f"  检测到 {len(signals)} 条消息")
                new_state = True
                alerted.append({"name": stock_name, "code": raw_code, "signals": signals})
            else:
                print(f"  无新消息")
        except Exception as e:
            print(f"  [ERROR] 处理 {raw_code} 异常: {e}")
        _time.sleep(0.3)

    print(f"\n  --- 汇总 ---")
    if alerted:
        print(f"  共 {len(alerted)} 只有新消息")
        push(f"公告/龙虎榜提醒（{len(alerted)}只）", format_news_report(alerted))
        new_state = True
    else:
        print(f"  无新消息")

    if new_state:
        save_state(state)


def main():
    mode = "trade"
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--mode" and i + 1 < len(args):
            mode = args[i + 1]

    if mode == "news":
        run_news_mode()
    else:
        run_trade_mode()


if __name__ == "__main__":
    main()
