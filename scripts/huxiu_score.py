#!/usr/bin/env python3
"""虎嗅选题逻辑评分模型（纯 stdlib，无外部依赖）。

Jack 2026-09-15: 用选题方法论校准雷达打分——
- 三支柱: 反常识/冲突视角、数据驱动(具体数字)、差异化信息增量(重复报道惩罚)
- 红线: 不写公司通稿视角 → 公关腔扣分
- 时效降权: 时间不占优必须在深度/角度上占优，时效只保留小权重
总分 = 相关性(22-50) + 选题(0-25) + 权威(0-10) + 深度(0-5) + 时效(0-20) + 写作(0-5) − 通稿(15) − 冗余(18/10)
"""
import re

# ---- 冲突/反常识信号（虎嗅支柱一+二：核心矛盾、反主流判断） ----
HX_CONFLICT_CN = [
    '真的', '为何', '为什么', '还能', '还敢', '何以', '凭什么', '谁能', '谁在', '怎么',
    '一夜之间', '悄悄', '突然', '翻车', '凉凉', '凉了', '遇冷', '缩水', '腰斩', '暴雷',
    '崩盘', '塌房', '泡沫', '幻觉', '神话', '祛魅', '出局', '退场', '离场', '跑路',
    '裁员', '解雇', '离职', '下架', '叫停', '熄火', '争议', '质疑', '拷问', '吐槽',
    '打脸', '反转', '变脸', '改口', '道歉', '跳水', '蒸发', '悬了', '困局', '尴尬',
    '滞销', '无人', '没人', '卖不动', '不行', '不再是', '不再', '尴尬', '两难', '悖论',
    '暴跌', '大跌', '大跌', '锐减', '超60%', '拒绝', '否决', '禁止', '封禁', '罚款',
]
HX_CONFLICT_EN = [
    ' why', 'still', 'really', 'despite', 'fail', 'flop', 'lawsuit', 'layoff',
    'shrink', 'slump', 'crash', 'doubt', 'debate', 'controvers', 'struggl',
    'stall', 'delay', 'collapse', 'plunge', ' quits', 'leaves', 'banned', 'fined',
    'myth', 'bubble', 'sink', 'miss', 'lost', 'despit',
]

# ---- 数据驱动信号（虎嗅支柱三：具体数字代替"大幅增长"） ----
HX_NUM = re.compile(
    r'\d+(?:\.\d+)?\s*(?:%|％|万|亿|千|万元|亿元|万美元|亿欧元|日元|元|美元|台|辆|套|款|'
    r'倍|个百分点|吨|公斤|kg|g|ms|岁|人|家|起|次|轮|亿美元|亿欧元)')
HX_NUM_EN = re.compile(r'\$\s?\d|\d+(?:\.\d+)?\s*(?:billion|million|bn|m\b|%)', re.I)

# ---- 公关通稿腔（虎嗅红线：不写公司通稿视角） ----
HX_PR_CN = [
    '战略合作', '签署', '签约', '隆重', '盛大', '圆满', '荣获', '入选', '点赞',
    '好评如潮', '赋能', '再创', '里程碑', '捷报', '强势来袭', '引领全球', '开创',
    '授牌', '致辞', '座谈会', '圆满收官', '盛大开幕', '重磅官宣', '强势入驻',
]
HX_PR_EN = ['strategic partnership', 'awarded', 'partners with', 'wins big', 'launched grand']

# ---- 自媒体噪声信号 ----
def hx_is_junk(title: str) -> bool:
    return '##' in title or 't.cn' in title


def huxiu_signals(title: str, desc: str = '') -> tuple:
    """返回 (topic 0-25, conflict 0-10, data_pts 0-10, pr_penalty 0/15)。"""
    t = (title or '').lower()
    d = (desc or '').lower()
    conflict = 10 if any(k in t for k in HX_CONFLICT_CN) or any(k in ' ' + t for k in HX_CONFLICT_EN) \
        else (5 if any(k in d for k in HX_CONFLICT_CN) else 0)
    n_title = len(HX_NUM.findall(title or '')) + len(HX_NUM_EN.findall(title or ''))
    n_desc = len(HX_NUM.findall(desc or '')) + len(HX_NUM_EN.findall(desc or ''))
    data_pts = 10 if n_title >= 2 else (6 if n_title == 1 else (4 if n_desc else 0))
    topic = min(25, conflict + data_pts)
    pr_penalty = 15 if (any(k in t for k in HX_PR_CN) or any(k in t for k in HX_PR_EN)) and conflict < 10 else 0
    return topic, conflict, data_pts, pr_penalty


def hx_bigrams(s: str) -> set:
    s = re.sub(r'\s+', '', s or '').lower()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def summary_quality(desc: str) -> tuple:
    """摘要长度 → (深度, 写作) 梯度分：≥100→5/5, ≥60→3/3, ≥30→1/1, 更短 0。"""
    L = len((desc or '').strip())
    if L >= 100:
        return 5, 5
    if L >= 60:
        return 3, 3
    if L >= 30:
        return 1, 1
    return 0, 0


def hx_similarity(a: str, b: str) -> float:
    ga, gb = hx_bigrams(a), hx_bigrams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


import datetime as _dt, time as _time


def _age_hours(item: dict, now_ts: float) -> float:
    pa = item.get('published_at')
    if not pa:
        return 999.0
    try:
        dt = _dt.datetime.fromisoformat(str(pa).replace('Z', '+00:00'))
        return max(0.0, (now_ts - dt.timestamp()) / 3600)
    except Exception:
        return 999.0


def calibrate_scores(items: list, now_ts: float | None = None) -> list:
    """虎嗅选题逻辑校准（Jack 2026-09-15），enricher 补摘要后调用。

    总分 = 相关性(22-50) + 选题(0-25, 冲突+数据) + 权威(0/5/10) + 深度(0-5)
          + 时效(0-20, 降权) + 写作(0-5) − 通稿(15) − 冗余(0-18) − 垃圾(25)
    冗余 = 与更高排名条目标题的最大 bigram 相似度 ×18（同文多平台只奖励首发高分版）。
    就地写回 total_score/relevance/authority/timeliness/depth/writing_value +
    hx_* 明细字段，返回按新总分降序排好的列表。
    """
    now_ts = now_ts or _time.time()
    for it in items:
        depth, writing = summary_quality(it.get('description', ''))
        it['depth'], it['writing_value'] = depth, writing
        topic, conflict, data_pts, pr_pen = huxiu_signals(it['title'], it.get('description', ''))
        rel_scaled = min(50.0, max(22.0, it.get('relevance', 0.35) * 100 * 0.625))
        auth = 10 if (it.get('authority') or 0) >= 15 else 5
        age = _age_hours(it, now_ts)
        tim = min(20.0, max(0.0, 20 - max(0.0, age - 4) * 0.8))
        it['_hx'] = dict(topic=topic, conflict=conflict, data=data_pts,
                         pr_pen=pr_pen, rel=rel_scaled, auth=auth, tim=tim,
                         writing=writing, depth=depth,
                         junk=25 if hx_is_junk(it['title']) else 0)
    # 贪心冗余：高分/高相关优先保留，后到者按与已收录条目的最大相似度扣分
    order = sorted(items, key=lambda i: (-i['_hx']['rel'], -(i['_hx']['topic'] + i['_hx']['auth'] + i['_hx']['depth'] + i['_hx']['tim'] + i['_hx']['writing'])))
    accepted = []
    for it in order:
        t = re.sub(r'\s+-\s+[^-–—]+$', '', it['title']).strip()
        best_t, best_sim = None, 0.0
        for at, asrc in accepted:
            s = hx_similarity(t, at)
            if s > best_sim:
                best_sim, best_t = s, asrc
        it['_hx']['dup_pen'] = round(18.0 * best_sim, 1)
        it['_hx']['dup_of'] = bool(best_t and best_sim >= 0.35)
        accepted.append((t, it['_hx']))
    # 合成总分
    for it in items:
        h = it['_hx']
        total = (h['rel'] + h['topic'] + h['auth'] + h['depth'] + h['tim'] + h['writing']
                 - h['pr_pen'] - h['dup_pen'] - h['junk'])
        it['total_score'] = round(total, 1)
        it['relevance'] = round(h['rel'] / 100, 3)   # 回写缩放后相关性，保证前端明细与总分自洽
        it['timeliness'] = round(h['tim'], 1)
        it['authority'] = h['auth']
        it['hx_topic'] = h['topic']
        it['hx_conflict'] = h['conflict']
        it['hx_data'] = h['data']
        it['hx_pr_penalty'] = -h['pr_pen']
        it['hx_dup_penalty'] = -h['dup_pen']
    items.sort(key=lambda x: x['total_score'], reverse=True)
    return items
