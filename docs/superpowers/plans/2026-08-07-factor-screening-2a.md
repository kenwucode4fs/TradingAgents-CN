# 因子打分选股器（子项目 2a）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增「多因子选股」能力——用户配置一组因子与权重，系统对全市场 A 股做横截面标准化加权打分，选出 TopN 榜单，可跳阶段①单股回测验证。

**Architecture:** 开源打分层 `tradingagents/factor/`（纯函数：15 因子计算 + 百分位标准化 + 加权 + 排序，不触库可独立单测）；后端 `app/services/factor_screening_service.py` + `app/routers/factor_screening.py` 异步执行（复用阶段①的 BackgroundTasks + 轮询 + 属主校验 + 主循环预取避跨事件循环坑）；前端 `frontend/src/views/FactorScreening/` 新页。零新增数据同步——估值读 `stock_screening_view` 宽表，量价读 `stock_daily_quotes` 前复权序列。

**Tech Stack:** Python（纯函数打分层 + FastAPI 异步）、MongoDB（Motor）、Vue 3 + Element Plus + vue-echarts、Docker。

## Global Constraints

- **每完成一个任务都必须先跑测试通过再 git 提交**；**不能为了让测试通过而修改测试用例**——测试失败要改实现，不是改断言。
- 打分层 `tradingagents/factor/` 是**开源纯函数层**，不得触库、不得 import `app.*`；所有数据由调用方（service）预取后注入。
- **零新增数据同步**。数据源固定：
  - 估值/分类/流动性截面 ← `stock_screening_view`（字段：`code, name, industry, pe, pb, total_mv, close, amount, volume, list_date, trade_date`；股票用 `code`="000001"）。
  - 量价历史 ← `stock_daily_quotes`（字段：`symbol`="000001", `trade_date`, `close_qfq`, `volume`；**前复权**用 `close_qfq`，可能为 `null` 需过滤）。
- 后端异步**复用阶段①模式**：`BackgroundTasks` 提交；任务状态值 **`running`/`done`/`failed`**；结果/状态接口按 `user_id` 属主校验，**非本人返回 404**（不泄露存在性）；引擎计算若触库，**先在主事件循环 `await` 预取数据，再 `loop.run_in_executor` 跑纯计算**（避免阶段①踩过的「线程池内 asyncio.run 复用主循环 Motor 客户端 → attached to a different loop」）。
- 前端 `request` 封装：baseURL 为空，接口路径**显式带 `/api` 前缀**（与 `api/analysis.ts` 一致）。
- 标准化 = **横截面百分位排名**；某股在任一选中因子上缺失值 → **整股剔除出榜**。
- MongoDB 集合：任务 `factor_screen_tasks`，结果 `factor_screen_results`。
- 授权：`tradingagents/factor/` 开源；`app/`、`frontend/` 专有。

---

## 文件结构

- `tradingagents/factor/scoring.py` — 标准化/加权/排序纯函数
- `tradingagents/factor/factors.py` — 15 个因子计算函数 + `FACTORS` 注册表 + 辅助（RSI/BOLL 末值）
- `tradingagents/factor/__init__.py` — `score_universe` 编排；导出 `FACTORS`, `score_universe`
- `app/services/factor_screening_service.py` — 候选池过滤 + 批量预取日线 + run_in_executor 打分 + 落库 + 任务状态
- `app/routers/factor_screening.py` — run/status/result/history/factors 接口 + 属主校验
- `app/main.py` — 注册路由（Modify）
- `tests/factor/` — 打分层与后端测试
- `frontend/src/api/factorScreening.ts` — 前端 API 层
- `frontend/src/views/FactorScreening/index.vue` — 主页
- `frontend/src/views/FactorScreening/components/FactorConfig.vue` — 因子配置区
- `frontend/src/views/FactorScreening/components/ResultTable.vue` — 榜单表
- `frontend/src/router/index.ts`、`frontend/src/components/Layout/SidebarMenu.vue` — 路由+菜单（Modify）

---

### Task 1: 打分核心纯函数 `scoring.py`

**Files:**
- Create: `tradingagents/factor/scoring.py`
- Create: `tradingagents/factor/__init__.py`（本任务先建空文件或仅占位，Task 3 补 `score_universe`）
- Test: `tests/factor/test_scoring.py`

**Interfaces:**
- Produces:
  - `percentile_normalize(values: list[float | None], direction: str) -> list[float | None]`：对一列因子值做横截面百分位标准化。`direction` ∈ `{"asc","desc"}`。`None` 值位置返回 `None`（不参与排名）。`desc`（越大越好）→ 值大的百分位高；`asc`（越小越好）→ 值小的百分位高。有效值数 `N`：单个有效值记 `1.0`；否则 `rank/(N-1)`，rank 从 0（最差）到 N-1（最好）。并列取相同（用「小于该值的个数/(N-1)」）。
  - `weighted_score(norm_by_factor: dict[str, float], weights: dict[str, float]) -> float`：加权归一，`Σ(w_k·norm_k)/Σ(w_k)`。要求 `norm_by_factor` 的 key 与 `weights` 一致且都非 None（缺失剔除在 Task 3 处理）。
  - `rank_topn(scored: list[dict], n: int) -> list[dict]`：按 `score` 降序排序，赋 `rank`（从 1 起），取前 `n`。

- [ ] **Step 1: 写失败测试**

```python
# tests/factor/test_scoring.py
import math
from tradingagents.factor.scoring import percentile_normalize, weighted_score, rank_topn


def test_percentile_desc_larger_is_better():
    # 值 [10,20,30]，desc：30 最好=1.0，10 最差=0.0，20 居中=0.5
    assert percentile_normalize([10, 20, 30], "desc") == [0.0, 0.5, 1.0]


def test_percentile_asc_smaller_is_better():
    # 值 [10,20,30]，asc：10 最好=1.0，30 最差=0.0
    assert percentile_normalize([10, 20, 30], "asc") == [1.0, 0.5, 0.0]


def test_percentile_keeps_none_and_excludes_from_rank():
    # None 不参与排名，返回位置仍是 None；有效值 [10,30] → 10=0.0,30=1.0
    assert percentile_normalize([10, None, 30], "desc") == [0.0, None, 1.0]


def test_percentile_single_valid_is_one():
    assert percentile_normalize([None, 42, None], "desc") == [None, 1.0, None]


def test_percentile_ties_share_rank():
    # 并列：[10,10,30] desc → 两个 10 同为最差 0.0，30=1.0
    assert percentile_normalize([10, 10, 30], "desc") == [0.0, 0.0, 1.0]


def test_weighted_score_normalizes_by_weight_sum():
    # norm{a:1.0,b:0.0}, weights{a:3,b:1} → (3*1+1*0)/4 = 0.75
    assert weighted_score({"a": 1.0, "b": 0.0}, {"a": 3, "b": 1}) == 0.75


def test_rank_topn_sorts_and_truncates():
    scored = [{"code": "A", "score": 0.2}, {"code": "B", "score": 0.9}, {"code": "C", "score": 0.5}]
    top = rank_topn(scored, 2)
    assert [x["code"] for x in top] == ["B", "C"]
    assert [x["rank"] for x in top] == [1, 2]
```

- [ ] **Step 2: 运行确认失败**

Run: `./venv/bin/python -m pytest tests/factor/test_scoring.py -v`
Expected: FAIL（ModuleNotFoundError: tradingagents.factor.scoring）

- [ ] **Step 3: 实现 `scoring.py`**

```python
# tradingagents/factor/scoring.py
"""因子打分核心纯函数：横截面百分位标准化、加权合成、排序取 TopN。不触库。"""
from typing import List, Optional, Dict


def percentile_normalize(values: List[Optional[float]], direction: str) -> List[Optional[float]]:
    """对一列因子值做横截面百分位标准化，返回 [0,1]（越大越好），None 原样保留。

    direction='desc' 越大越好；'asc' 越小越好。并列取相同百分位（小于该值的个数占比）。
    有效值 N==1 记 1.0；N==0 全 None。
    """
    if direction not in ("asc", "desc"):
        raise ValueError(f"非法 direction: {direction!r}，期望 'asc' 或 'desc'")
    valid = [v for v in values if v is not None]
    n = len(valid)
    out: List[Optional[float]] = []
    for v in values:
        if v is None:
            out.append(None)
            continue
        if n == 1:
            out.append(1.0)
            continue
        # 以「严格小于该值的个数」定 rank（并列共享），rank ∈ [0, n-1]
        less = sum(1 for x in valid if x < v)
        p = less / (n - 1)  # p: 值小→0，值大→1（此为 asc-越小分越低 的原始百分位）
        out.append(p if direction == "desc" else 1.0 - p)
    return out


def weighted_score(norm_by_factor: Dict[str, float], weights: Dict[str, float]) -> float:
    """加权归一：Σ(w·norm)/Σ(w)。norm_by_factor 的值须全部非 None。"""
    wsum = sum(weights[k] for k in norm_by_factor)
    if wsum <= 0:
        raise ValueError("权重之和必须为正")
    return sum(weights[k] * norm_by_factor[k] for k in norm_by_factor) / wsum


def rank_topn(scored: List[dict], n: int) -> List[dict]:
    """按 score 降序，赋 rank（从 1 起），取前 n。"""
    ordered = sorted(scored, key=lambda x: x["score"], reverse=True)
    for i, item in enumerate(ordered):
        item["rank"] = i + 1
    return ordered[:n]
```

同时建 `tradingagents/factor/__init__.py`（空文件，Task 3 填充）：

```python
# tradingagents/factor/__init__.py
"""因子打分选股（子项目 2a）开源打分层。"""
```

- [ ] **Step 4: 运行确认通过**

Run: `./venv/bin/python -m pytest tests/factor/test_scoring.py -v`
Expected: PASS（7 passed）

- [ ] **Step 5: 提交**

```bash
git add tradingagents/factor/scoring.py tradingagents/factor/__init__.py tests/factor/test_scoring.py
git commit -m "feat(factor): 打分核心纯函数(百分位标准化/加权/排序)"
```

---

### Task 2: 15 个因子计算 `factors.py`

**Files:**
- Create: `tradingagents/factor/factors.py`
- Test: `tests/factor/test_factors.py`

**Interfaces:**
- Consumes: 无（纯函数）。
- Produces:
  - 每个因子计算函数签名统一：`fn(cross: dict, closes: list[float], volumes: list[float]) -> Optional[float]`。`cross` 是该股截面字段 `{pe,pb,total_mv,amount,close,...}`；`closes` 是**前复权收盘价升序序列**（已过滤 None）；`volumes` 是与 closes 对齐的成交量升序序列。数据不足或非法（如 pe≤0、序列长度不够）返回 `None`。
  - `FACTORS: dict[str, dict]` 注册表：`key -> {"name": str, "category": str, "default_direction": "asc"|"desc", "fn": callable}`。共 15 项。
  - 辅助纯函数 `_rsi(closes, period=14) -> Optional[float]`、`_boll_pos(closes, period=20) -> Optional[float]`。

- [ ] **Step 1: 写失败测试**

```python
# tests/factor/test_factors.py
import math
from tradingagents.factor.factors import FACTORS, _rsi, _boll_pos


def _seq(n, start=10.0, step=1.0):
    return [start + i * step for i in range(n)]  # 单调上升序列


def test_registry_has_15_factors():
    assert len(FACTORS) == 15
    # 抽查 key 与元信息
    assert FACTORS["pe"]["default_direction"] == "asc"
    assert FACTORS["mom_20"]["default_direction"] == "desc"
    for meta in FACTORS.values():
        assert set(meta) >= {"name", "category", "default_direction", "fn"}
        assert meta["default_direction"] in ("asc", "desc")


def test_pe_rejects_nonpositive():
    fn = FACTORS["pe"]["fn"]
    assert fn({"pe": 12.5}, [], []) == 12.5
    assert fn({"pe": 0}, [], []) is None
    assert fn({"pe": -3}, [], []) is None
    assert fn({"pe": None}, [], []) is None


def test_mom_20_needs_21_points():
    fn = FACTORS["mom_20"]["fn"]
    closes = _seq(21, start=100.0, step=1.0)  # close[-1]=120, close[-21]=100
    assert math.isclose(fn({}, closes, []), 120 / 100 - 1)
    assert fn({}, _seq(20), []) is None  # 不足 21 点


def test_high_250_prox_at_new_high_is_one():
    fn = FACTORS["high_250_prox"]["fn"]
    closes = _seq(250, start=1.0, step=1.0)  # 末值即最高
    assert math.isclose(fn({}, closes, []), 1.0)


def test_vol_60_of_constant_is_zero():
    fn = FACTORS["vol_60"]["fn"]
    closes = [10.0] * 61  # 收益全 0 → 波动率 0
    assert math.isclose(fn({}, closes, []), 0.0, abs_tol=1e-12)


def test_turnover_proxy_amount_over_mv():
    fn = FACTORS["turnover_proxy"]["fn"]
    assert math.isclose(fn({"amount": 200.0, "total_mv": 1000.0}, [], []), 0.2)
    assert fn({"amount": None, "total_mv": 1000.0}, [], []) is None


def test_vol_ratio_recent_over_long():
    fn = FACTORS["vol_ratio"]["fn"]
    vols = [100.0] * 55 + [200.0] * 5  # 近5均=200，近60均=(55*100+5*200)/60
    expected = 200.0 / ((55 * 100 + 5 * 200) / 60)
    assert math.isclose(fn({}, [1.0] * 60, vols), expected)


def test_rsi_all_up_is_100():
    assert math.isclose(_rsi(_seq(20), 14), 100.0)


def test_boll_pos_in_unit_range():
    p = _boll_pos(_seq(25), 20)
    assert p is None or 0.0 <= p <= 1.5  # 上升序列末值可能触及上轨附近
```

- [ ] **Step 2: 运行确认失败**

Run: `./venv/bin/python -m pytest tests/factor/test_factors.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 `factors.py`**

```python
# tradingagents/factor/factors.py
"""15 个因子计算函数 + FACTORS 注册表。全部纯函数，数据不足/非法返回 None。

约定：closes 为前复权收盘价升序序列（已过滤 None）；volumes 与之对齐；
cross 为该股截面字段（pe/pb/total_mv/amount/close 等）。
"""
import math
from statistics import pstdev
from typing import List, Optional


def _ret_series(closes: List[float]) -> List[float]:
    return [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes)) if closes[i - 1]]


def _rsi(closes: List[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    for i in range(len(closes) - period, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains += max(ch, 0.0)
        losses += max(-ch, 0.0)
    if losses == 0:
        return 100.0
    rs = (gains / period) / (losses / period)
    return 100.0 - 100.0 / (1.0 + rs)


def _boll_pos(closes: List[float], period: int = 20) -> Optional[float]:
    if len(closes) < period:
        return None
    window = closes[-period:]
    mid = sum(window) / period
    sd = pstdev(window)
    up, low = mid + 2 * sd, mid - 2 * sd
    if up == low:
        return None
    return (closes[-1] - low) / (up - low)


# --- 估值类（截面）---
def _pe(cross, closes, volumes):
    v = cross.get("pe")
    return v if (v is not None and v > 0) else None

def _pb(cross, closes, volumes):
    v = cross.get("pb")
    return v if (v is not None and v > 0) else None

def _total_mv(cross, closes, volumes):
    return cross.get("total_mv")

# --- 动量/趋势类（前复权序列）---
def _mom(closes, lookback):
    if len(closes) < lookback + 1 or not closes[-lookback - 1]:
        return None
    return closes[-1] / closes[-lookback - 1] - 1

def _mom_20(cross, closes, volumes): return _mom(closes, 20)
def _mom_60(cross, closes, volumes): return _mom(closes, 60)
def _mom_120(cross, closes, volumes): return _mom(closes, 120)
def _rev_5(cross, closes, volumes): return _mom(closes, 5)

def _high_250_prox(cross, closes, volumes):
    if len(closes) < 60:  # 至少要一段历史才有意义
        return None
    window = closes[-250:]
    hi = max(window)
    return closes[-1] / hi if hi else None

# --- 波动/风险类 ---
def _vol_60(cross, closes, volumes):
    if len(closes) < 61:
        return None
    rets = _ret_series(closes[-61:])
    return pstdev(rets) if len(rets) >= 2 else None

def _mdd_120(cross, closes, volumes):
    if len(closes) < 60:
        return None
    window = closes[-120:]
    peak, mdd = window[0], 0.0
    for p in window:
        peak = max(peak, p)
        if peak:
            mdd = max(mdd, (peak - p) / peak)
    return mdd

# --- 技术类 ---
def _ma20_bias(cross, closes, volumes):
    if len(closes) < 20:
        return None
    ma = sum(closes[-20:]) / 20
    return closes[-1] / ma - 1 if ma else None

def _rsi14(cross, closes, volumes): return _rsi(closes, 14)
def _boll_pos_f(cross, closes, volumes): return _boll_pos(closes, 20)

# --- 流动性类 ---
def _turnover_proxy(cross, closes, volumes):
    a, mv = cross.get("amount"), cross.get("total_mv")
    if a is None or not mv:
        return None
    return a / mv

def _vol_ratio(cross, closes, volumes):
    if len(volumes) < 60:
        return None
    short = sum(volumes[-5:]) / 5
    long = sum(volumes[-60:]) / 60
    return short / long if long else None


FACTORS = {
    "pe":            {"name": "市盈率",       "category": "估值",  "default_direction": "asc",  "fn": _pe},
    "pb":            {"name": "市净率",       "category": "估值",  "default_direction": "asc",  "fn": _pb},
    "total_mv":      {"name": "总市值",       "category": "估值",  "default_direction": "asc",  "fn": _total_mv},
    "mom_20":        {"name": "20日动量",     "category": "动量",  "default_direction": "desc", "fn": _mom_20},
    "mom_60":        {"name": "60日动量",     "category": "动量",  "default_direction": "desc", "fn": _mom_60},
    "mom_120":       {"name": "120日动量",    "category": "动量",  "default_direction": "desc", "fn": _mom_120},
    "rev_5":         {"name": "5日反转",      "category": "动量",  "default_direction": "asc",  "fn": _rev_5},
    "high_250_prox": {"name": "52周高接近度", "category": "动量",  "default_direction": "desc", "fn": _high_250_prox},
    "vol_60":        {"name": "60日波动率",   "category": "波动",  "default_direction": "asc",  "fn": _vol_60},
    "mdd_120":       {"name": "120日最大回撤","category": "波动",  "default_direction": "asc",  "fn": _mdd_120},
    "ma20_bias":     {"name": "均线偏离",     "category": "技术",  "default_direction": "asc",  "fn": _ma20_bias},
    "rsi14":         {"name": "RSI14",        "category": "技术",  "default_direction": "asc",  "fn": _rsi14},
    "boll_pos":      {"name": "布林位置",     "category": "技术",  "default_direction": "asc",  "fn": _boll_pos_f},
    "turnover_proxy":{"name": "换手率代理",   "category": "流动性","default_direction": "asc",  "fn": _turnover_proxy},
    "vol_ratio":     {"name": "量比",         "category": "流动性","default_direction": "asc",  "fn": _vol_ratio},
}
```

- [ ] **Step 4: 运行确认通过**

Run: `./venv/bin/python -m pytest tests/factor/test_factors.py -v`
Expected: PASS（10 passed）

- [ ] **Step 5: 提交**

```bash
git add tradingagents/factor/factors.py tests/factor/test_factors.py
git commit -m "feat(factor): 15个因子计算函数与注册表"
```

---

### Task 3: 打分编排 `score_universe`

**Files:**
- Modify: `tradingagents/factor/__init__.py`
- Test: `tests/factor/test_score_universe.py`

**Interfaces:**
- Consumes: `FACTORS`（Task 2）、`percentile_normalize`/`weighted_score`/`rank_topn`（Task 1）。
- Produces:
  - `score_universe(stocks: list[dict], factor_configs: list[dict], top_n: int) -> list[dict]`
    - `stocks`：每股一个 dict `{"code","name","industry","cross": {...截面...}, "closes": [...], "volumes": [...]}`。
    - `factor_configs`：`[{"key","weight","direction"}]`（direction 由前端传，缺省用 `FACTORS[key]["default_direction"]`）。
    - 流程：对每股算每个选中因子原始值 → 每因子横截面 `percentile_normalize` → **任一选中因子缺失的股整体剔除** → `weighted_score` → `rank_topn`。
    - 返回榜单：`[{"code","name","industry","score","rank","factors": {key: {"value","norm","direction"}}}]`。
    - 非法：`factor_configs` 为空 → `ValueError`；`top_n<=0` → `ValueError`。

- [ ] **Step 1: 写失败测试**

```python
# tests/factor/test_score_universe.py
import pytest
from tradingagents.factor import score_universe


def _stock(code, pe, closes):
    return {"code": code, "name": code, "industry": "银行",
            "cross": {"pe": pe}, "closes": closes, "volumes": [1.0] * len(closes)}


def test_score_universe_ranks_by_weighted_percentile():
    # 单因子 pe(asc,越小越好)：pe 越小 score 越高
    stocks = [_stock("A", 30, [1.0]), _stock("B", 10, [1.0]), _stock("C", 20, [1.0])]
    cfg = [{"key": "pe", "weight": 1, "direction": "asc"}]
    top = score_universe(stocks, cfg, top_n=3)
    assert [x["code"] for x in top] == ["B", "C", "A"]  # pe 10<20<30
    assert top[0]["rank"] == 1
    assert top[0]["factors"]["pe"]["value"] == 10


def test_missing_factor_excludes_stock():
    # C 的 pe 非法(<=0) → 缺失 → 被剔除，不出现在榜单
    stocks = [_stock("A", 30, [1.0]), _stock("B", 10, [1.0]), _stock("C", -1, [1.0])]
    cfg = [{"key": "pe", "weight": 1, "direction": "asc"}]
    codes = [x["code"] for x in score_universe(stocks, cfg, top_n=10)]
    assert "C" not in codes and set(codes) == {"A", "B"}


def test_topn_truncates():
    stocks = [_stock(c, pe, [1.0]) for c, pe in [("A", 30), ("B", 10), ("C", 20)]]
    cfg = [{"key": "pe", "weight": 1, "direction": "asc"}]
    assert len(score_universe(stocks, cfg, top_n=2)) == 2


def test_empty_config_raises():
    with pytest.raises(ValueError):
        score_universe([_stock("A", 10, [1.0])], [], top_n=5)
```

- [ ] **Step 2: 运行确认失败**

Run: `./venv/bin/python -m pytest tests/factor/test_score_universe.py -v`
Expected: FAIL（ImportError: cannot import name 'score_universe'）

- [ ] **Step 3: 实现 `score_universe`（写入 `__init__.py`）**

```python
# tradingagents/factor/__init__.py
"""因子打分选股（子项目 2a）开源打分层。"""
from typing import List, Optional

from .factors import FACTORS
from .scoring import percentile_normalize, weighted_score, rank_topn

__all__ = ["FACTORS", "score_universe", "percentile_normalize", "weighted_score", "rank_topn"]


def score_universe(stocks: List[dict], factor_configs: List[dict], top_n: int) -> List[dict]:
    """对候选股按选中因子做横截面标准化加权打分，剔除缺失，返回 TopN 榜单。"""
    if not factor_configs:
        raise ValueError("至少选择一个因子")
    if top_n <= 0:
        raise ValueError("top_n 必须为正")

    keys = [c["key"] for c in factor_configs]
    directions = {c["key"]: c.get("direction") or FACTORS[c["key"]]["default_direction"]
                  for c in factor_configs}
    weights = {c["key"]: c["weight"] for c in factor_configs}

    # 1) 每股每因子原始值
    raw = {k: [] for k in keys}   # key -> [每股原始值(可 None)]
    for s in stocks:
        for k in keys:
            fn = FACTORS[k]["fn"]
            raw[k].append(fn(s.get("cross", {}), s.get("closes", []), s.get("volumes", [])))

    # 2) 每因子横截面标准化
    norm = {k: percentile_normalize(raw[k], directions[k]) for k in keys}

    # 3) 组装每股，剔除任一因子缺失者
    scored = []
    for i, s in enumerate(stocks):
        norm_by_factor = {}
        factors_detail = {}
        missing = False
        for k in keys:
            nv = norm[k][i]
            if nv is None:
                missing = True
                break
            norm_by_factor[k] = nv
            factors_detail[k] = {"value": raw[k][i], "norm": nv, "direction": directions[k]}
        if missing:
            continue
        scored.append({
            "code": s["code"], "name": s.get("name", ""), "industry": s.get("industry", ""),
            "score": weighted_score(norm_by_factor, weights),
            "factors": factors_detail,
        })

    # 4) 排序取 TopN
    return rank_topn(scored, top_n)
```

- [ ] **Step 4: 运行确认通过**

Run: `./venv/bin/python -m pytest tests/factor/ -v`
Expected: PASS（全部 factor 测试通过）

- [ ] **Step 5: 提交**

```bash
git add tradingagents/factor/__init__.py tests/factor/test_score_universe.py
git commit -m "feat(factor): score_universe编排(标准化+加权+剔除缺失+TopN)"
```

---

### Task 4: 后端选股服务 `factor_screening_service.py`

**Files:**
- Create: `app/services/factor_screening_service.py`
- Test: `tests/factor/test_factor_service.py`

**Interfaces:**
- Consumes: `score_universe`（Task 3）；参考阶段① `app/services/backtest_service.py` 的 `ensure_db`、`set_task_status`/`get_task_status`、`get_result`/`get_history`、`run_in_executor` 模式。
- Produces:
  - `async def get_candidates(universe: dict) -> list[dict]`：从 `stock_screening_view` 按选股域取候选截面，返回 `[{code,name,industry,cross:{pe,pb,total_mv,amount,close}}]`。`universe` = `{exclude_st,exclude_new,industries,mv_min,mv_max}`。
  - `async def fetch_price_series(codes: list[str], lookback: int = 260) -> dict[str, dict]`：批量从 `stock_daily_quotes` 取每股最近 `lookback` 条前复权序列，返回 `{code: {"closes": [...], "volumes": [...]}}`（按 trade_date 升序，过滤 close_qfq 为 None）。
  - `async def run_screen_task(task_id: str, user_id: str, payload: dict, stocks=None) -> dict`：预取（主循环）→ `run_in_executor` 跑 `score_universe` → 落库 `factor_screen_results` → 返回结果。`stocks` 参数供测试注入，绕开库。
  - `async def set_task_status(task_id, status, error=None, user_id=None)`、`get_task_status`、`get_result`、`get_history(user_id, ...)`（集合 `factor_screen_tasks`/`factor_screen_results`，与阶段①同构）。
  - `ensure_db()`（复用/照抄阶段① `backtest_service.ensure_db` 的回填逻辑）。

- [ ] **Step 1: 写失败测试（注入 stocks，绕库，验证打分落库与状态）**

```python
# tests/factor/test_factor_service.py
import pytest
from app.services import factor_screening_service as svc


@pytest.mark.integration
def test_run_screen_task_with_injected_stocks(monkeypatch):
    import asyncio

    async def _run():
        await svc.ensure_db()
        stocks = [
            {"code": "000001", "name": "平安银行", "industry": "银行",
             "cross": {"pe": 5.0, "pb": 0.5, "total_mv": 2000.0, "amount": 1.0, "close": 11.0},
             "closes": [10.0 + i for i in range(130)], "volumes": [1.0] * 130},
            {"code": "600000", "name": "浦发银行", "industry": "银行",
             "cross": {"pe": 6.0, "pb": 0.6, "total_mv": 3000.0, "amount": 1.0, "close": 8.0},
             "closes": [20.0 - i * 0.05 for i in range(130)], "volumes": [1.0] * 130},
        ]
        payload = {"factors": [{"key": "pe", "weight": 1, "direction": "asc"},
                               {"key": "mom_20", "weight": 1, "direction": "desc"}],
                   "universe": {}, "top_n": 10}
        res = await svc.run_screen_task("t-fac-1", "user-x", payload, stocks=stocks)
        assert len(res["items"]) == 2
        assert res["items"][0]["rank"] == 1
        # 落库可查
        got = await svc.get_result("t-fac-1")
        assert got is not None and got["user_id"] == "user-x"
        assert len(got["items"]) == 2

    asyncio.run(_run())
```

- [ ] **Step 2: 运行确认失败**

Run: `MONGODB_DATABASE=tradingagents MONGODB_DATABASE_SCOPE=explicit ./venv/bin/python -m pytest tests/factor/test_factor_service.py -v -m integration`
Expected: FAIL（AttributeError: module has no attribute 'run_screen_task'）

- [ ] **Step 3: 实现 `factor_screening_service.py`**

先读 `app/services/backtest_service.py` 的 `ensure_db`/`set_task_status`/`get_result`/`get_history` 照其模式实现（相同的 `db_module` 回填、集合 upsert、属主字段）。核心：

```python
# app/services/factor_screening_service.py（关键片段，其余状态方法照 backtest_service 同构实现）
import asyncio
from datetime import datetime, timezone

import app.core.database as db_module
from app.core.database import get_mongo_db, db_manager
from tradingagents.factor import score_universe

async def ensure_db() -> None:
    if getattr(db_manager, "mongo_db", None) is None:
        await db_manager.init_mongodb()
    db_module.mongo_client = db_manager.mongo_client
    db_module.mongo_db = db_manager.mongo_db

def _results():
    return get_mongo_db().factor_screen_results

def _tasks():
    return get_mongo_db().factor_screen_tasks

async def get_candidates(universe: dict) -> list:
    q = {}
    if universe.get("exclude_st"):
        q["name"] = {"$not": {"$regex": "ST"}}
    if universe.get("industries"):
        q["industry"] = {"$in": universe["industries"]}
    mv = {}
    if universe.get("mv_min") is not None:
        mv["$gte"] = universe["mv_min"]
    if universe.get("mv_max") is not None:
        mv["$lte"] = universe["mv_max"]
    if mv:
        q["total_mv"] = mv
    proj = {"_id": 0, "code": 1, "name": 1, "industry": 1, "pe": 1, "pb": 1,
            "total_mv": 1, "amount": 1, "close": 1, "list_date": 1}
    out = []
    async for d in get_mongo_db().stock_screening_view.find(q, proj):
        if universe.get("exclude_new") and _is_new(d.get("list_date")):
            continue
        out.append({"code": d["code"], "name": d.get("name", ""), "industry": d.get("industry", ""),
                    "cross": {"pe": d.get("pe"), "pb": d.get("pb"), "total_mv": d.get("total_mv"),
                              "amount": d.get("amount"), "close": d.get("close")}})
    return out

def _is_new(list_date) -> bool:
    # list_date 形如 "20230101"，空串视为未知(不剔除)
    if not list_date or len(str(list_date)) != 8:
        return False
    from datetime import date
    try:
        y, m, dd = int(list_date[:4]), int(list_date[4:6]), int(list_date[6:8])
        days = (date.today() - date(y, m, dd)).days
        return days < 365
    except ValueError:
        return False

async def fetch_price_series(codes: list, lookback: int = 260) -> dict:
    proj = {"_id": 0, "symbol": 1, "trade_date": 1, "close_qfq": 1, "volume": 1}
    cur = get_mongo_db().stock_daily_quotes.find(
        {"symbol": {"$in": codes}, "close_qfq": {"$ne": None}}, proj
    ).sort("trade_date", 1)
    by_code = {}
    async for d in cur:
        by_code.setdefault(d["symbol"], []).append(d)
    out = {}
    for code, rows in by_code.items():
        rows = rows[-lookback:]
        out[code] = {"closes": [r["close_qfq"] for r in rows],
                     "volumes": [r.get("volume") or 0 for r in rows]}
    return out

async def run_screen_task(task_id: str, user_id: str, payload: dict, stocks=None) -> dict:
    if stocks is None:
        candidates = await get_candidates(payload.get("universe", {}))
        series = await fetch_price_series([c["code"] for c in candidates])
        stocks = []
        for c in candidates:
            s = series.get(c["code"], {"closes": [], "volumes": []})
            stocks.append({**c, "closes": s["closes"], "volumes": s["volumes"]})
    loop = asyncio.get_event_loop()
    items = await loop.run_in_executor(None, lambda: score_universe(
        stocks, payload["factors"], payload.get("top_n", 50)))
    doc = {"task_id": task_id, "user_id": user_id, "config": payload,
           "items": items, "created_at": datetime.now(timezone.utc)}
    await _results().update_one({"task_id": task_id}, {"$set": doc}, upsert=True)
    return doc

# set_task_status / get_task_status / get_result / get_history：照 backtest_service.py 同名实现，
# 集合换成 factor_screen_tasks / factor_screen_results，字段一致（含 user_id、running/done/failed）。
```

（实现者：`set_task_status`/`get_task_status`/`get_result`/`get_history` 请对照 `app/services/backtest_service.py` 逐字照搬结构，仅替换集合名。）

- [ ] **Step 4: 运行确认通过**

Run: `MONGODB_DATABASE=tradingagents MONGODB_DATABASE_SCOPE=explicit ./venv/bin/python -m pytest tests/factor/test_factor_service.py -v -m integration`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/factor_screening_service.py tests/factor/test_factor_service.py
git commit -m "feat(factor): 选股服务(候选池+批量预取日线+run_in_executor打分+落库)"
```

---

### Task 5: 后端接口 `routers/factor_screening.py`

**Files:**
- Create: `app/routers/factor_screening.py`
- Modify: `app/main.py`（注册路由，参考已有 `from app.routers import backtest` 的注册方式）
- Test: `tests/factor/test_factor_api.py`

**Interfaces:**
- Consumes: `factor_screening_service`（Task 4）、`FACTORS`（Task 2）、`get_current_user`（`app.routers.auth_db`）。
- Produces（前缀 `/api/factor-screen`）：
  - `POST /run`：body `{factors:[{key,weight,direction}], universe:{...}, top_n}`；校验（≥1 因子、每个 key 在 FACTORS、weight>0、top_n>0）→ 生成 `uuid4().hex` task_id → `set_task_status(running, user_id=...)` → `BackgroundTasks` 跑 `run_screen_task` 并在完成/异常时更新状态 → 返回 `{task_id}`。
  - `GET /status/{task_id}`、`GET /result/{task_id}`：属主校验（`user_id != user["id"]` → 404）。
  - `GET /history`：按 `user_id` 列表。
  - `GET /factors`：返回 `FACTORS` 元信息 `[{key,name,category,default_direction}]`（无需鉴权数据敏感性低，但仍加 `get_current_user` 保持一致）。

- [ ] **Step 1: 写失败测试**

```python
# tests/factor/test_factor_api.py
import pytest
from fastapi.testclient import TestClient


def test_factors_meta_and_bad_params():
    from app.main import app
    from app.routers.auth_db import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "username": "admin"}
    try:
        client = TestClient(app)
        # /factors 返回 15 项元信息
        r = client.get("/api/factor-screen/factors")
        assert r.status_code == 200
        data = r.json().get("data", r.json())
        assert len(data) == 15
        # /run 非法：空因子 → 400
        r2 = client.post("/api/factor-screen/run", json={"factors": [], "universe": {}, "top_n": 10})
        assert r2.status_code == 400
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.integration
def test_status_result_ownership():
    from app.main import app
    from app.routers.auth_db import get_current_user
    from app.services import factor_screening_service as svc
    import asyncio

    async def seed():
        await svc.ensure_db()
        await svc.set_task_status("t-own", "done", user_id="owner")
        await svc._results().update_one({"task_id": "t-own"},
            {"$set": {"task_id": "t-own", "user_id": "owner", "items": [], "config": {}}}, upsert=True)
    asyncio.run(seed())

    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: {"id": "intruder", "username": "x"}
    try:
        assert client.get("/api/factor-screen/status/t-own").status_code == 404
        assert client.get("/api/factor-screen/result/t-own").status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides[get_current_user] = lambda: {"id": "owner", "username": "o"}
    try:
        assert client.get("/api/factor-screen/status/t-own").status_code == 200
    finally:
        app.dependency_overrides.pop(get_current_user, None)
```

- [ ] **Step 2: 运行确认失败**

Run: `MONGODB_DATABASE=tradingagents MONGODB_DATABASE_SCOPE=explicit ./venv/bin/python -m pytest tests/factor/test_factor_api.py -v`
Expected: FAIL（404 路由不存在）

- [ ] **Step 3: 实现路由**（照 `app/routers/backtest.py` 结构）

```python
# app/routers/factor_screening.py（关键结构，属主校验/BackgroundTasks 照 backtest.py）
import uuid
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.routers.auth_db import get_current_user
from app.services import factor_screening_service as svc
from tradingagents.factor import FACTORS

router = APIRouter(prefix="/api/factor-screen", tags=["factor-screen"])


@router.get("/factors")
async def list_factors(user=Depends(get_current_user)):
    data = [{"key": k, "name": m["name"], "category": m["category"],
             "default_direction": m["default_direction"]} for k, m in FACTORS.items()]
    return {"success": True, "data": data}


def _validate(payload: dict):
    factors = payload.get("factors") or []
    if not factors:
        raise HTTPException(status_code=400, detail="至少选择一个因子")
    for f in factors:
        if f.get("key") not in FACTORS:
            raise HTTPException(status_code=400, detail=f"未知因子: {f.get('key')}")
        if not (f.get("weight", 0) > 0):
            raise HTTPException(status_code=400, detail="因子权重必须为正")
    if payload.get("top_n", 0) <= 0:
        raise HTTPException(status_code=400, detail="top_n 必须为正")


@router.post("/run")
async def run(payload: dict, background: BackgroundTasks, user=Depends(get_current_user)):
    _validate(payload)
    await svc.ensure_db()
    task_id = uuid.uuid4().hex
    uid = user["id"]
    await svc.set_task_status(task_id, "running", user_id=uid)

    async def _job():
        try:
            await svc.run_screen_task(task_id, uid, payload)
            await svc.set_task_status(task_id, "done", user_id=uid)
        except Exception as e:  # noqa
            await svc.set_task_status(task_id, "failed", error=str(e), user_id=uid)

    background.add_task(_job)
    return {"success": True, "data": {"task_id": task_id}}


@router.get("/status/{task_id}")
async def status(task_id: str, user=Depends(get_current_user)):
    await svc.ensure_db()
    st = await svc.get_task_status(task_id)
    if not st or st.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"success": True, "data": st}


@router.get("/result/{task_id}")
async def result(task_id: str, user=Depends(get_current_user)):
    await svc.ensure_db()
    r = await svc.get_result(task_id)
    if not r or r.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="结果不存在")
    return {"success": True, "data": r}


@router.get("/history")
async def history(limit: int = 20, skip: int = 0, user=Depends(get_current_user)):
    await svc.ensure_db()
    return {"success": True, "data": await svc.get_history(user["id"], limit, skip)}
```

在 `app/main.py` 注册（照 `backtest` 的写法）：`from app.routers import factor_screening` 且 `app.include_router(factor_screening.router)`。

- [ ] **Step 4: 运行确认通过**

Run: `MONGODB_DATABASE=tradingagents MONGODB_DATABASE_SCOPE=explicit ./venv/bin/python -m pytest tests/factor/test_factor_api.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/routers/factor_screening.py app/main.py tests/factor/test_factor_api.py
git commit -m "feat(factor): 选股API路由(run/status/result/history/factors+属主校验)"
```

---

### Task 6: 后端端到端集成（真实库小域选股）

**Files:**
- Test: `tests/factor/test_factor_e2e.py`

**Interfaces:**
- Consumes: Task 5 的 API。验证真实库跑通「提交→轮询→结果」，覆盖 `run_screen_task` 的 `stocks=None` 真实路径（候选池 + 批量预取 + run_in_executor），确认不触发跨事件循环冲突。

- [ ] **Step 1: 写端到端测试**

```python
# tests/factor/test_factor_e2e.py
import time
import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
def test_full_factor_screen_flow():
    from app.main import app
    from app.routers.auth_db import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {"id": "e2e-fac", "username": "admin"}
    try:
        client = TestClient(app)
        body = {
            "factors": [{"key": "pe", "weight": 2, "direction": "asc"},
                        {"key": "mom_60", "weight": 1, "direction": "desc"},
                        {"key": "total_mv", "weight": 1, "direction": "asc"}],
            "universe": {"exclude_st": True, "industries": ["银行"]},  # 小域，加速
            "top_n": 10,
        }
        tid = client.post("/api/factor-screen/run", json=body).json()["data"]["task_id"]
        final = None
        for _ in range(60):
            st = client.get(f"/api/factor-screen/status/{tid}").json()["data"]
            if st["status"] in ("done", "failed"):
                final = st
                break
            time.sleep(1)
        assert final and final["status"] == "done", f"最终状态: {final}"
        data = client.get(f"/api/factor-screen/result/{tid}").json()["data"]
        assert len(data["items"]) >= 1
        top = data["items"][0]
        assert 0.0 <= top["score"] <= 1.0 and top["rank"] == 1
        assert "pe" in top["factors"]
        print("TopN:", [(x["code"], round(x["score"], 3)) for x in data["items"][:5]])
    finally:
        app.dependency_overrides.pop(get_current_user, None)
```

- [ ] **Step 2: 运行确认通过（真实库）**

Run: `MONGODB_DATABASE=tradingagents MONGODB_DATABASE_SCOPE=explicit ./venv/bin/python -m pytest tests/factor/test_factor_e2e.py -v -m integration -s`
Expected: PASS，打印银行业 TopN。若 `银行` 行业无数据（宽表 industry 可能为空串），改用不带 industry 的小市值域重试并在报告中说明。

- [ ] **Step 3: 提交**

```bash
git add tests/factor/test_factor_e2e.py
git commit -m "test(factor): 选股后端端到端集成(真实库小域)"
```

---

### Task 7: 前端 API 层 + 路由/菜单 + 占位页

**Files:**
- Create: `frontend/src/api/factorScreening.ts`
- Create: `frontend/src/views/FactorScreening/index.vue`（占位）
- Modify: `frontend/src/router/index.ts`、`frontend/src/components/Layout/SidebarMenu.vue`

**Interfaces:**
- Produces: `factorApi.run/status/result/history/factors`（照 `frontend/src/api/backtest.ts` 的封装，baseURL 空、路径带 `/api`）。

- [ ] **Step 1: 实现 `factorScreening.ts`**（先读 `frontend/src/api/backtest.ts` 对齐 request 用法）

```typescript
// frontend/src/api/factorScreening.ts
import request from './request'
export const factorApi = {
  factors: () => request.get('/api/factor-screen/factors'),
  run: (payload: any) => request.post('/api/factor-screen/run', payload),
  status: (taskId: string) => request.get(`/api/factor-screen/status/${taskId}`),
  result: (taskId: string) => request.get(`/api/factor-screen/result/${taskId}`),
  history: (params?: any) => request.get('/api/factor-screen/history', { params }),
}
```

- [ ] **Step 2: 路由 + 菜单**：`router/index.ts` 加 `/factor-screening` → `views/FactorScreening/index.vue`（照 `/backtest` 块）；`SidebarMenu.vue` 加「多因子选股」条目（照「策略回测」，图标如 `Filter`）。`index.vue` 先放占位 `el-empty`。

- [ ] **Step 3: 构建确认**

Run: `cd frontend && npm run build`
Expected: 构建通过（vue-tsc 无报错）

- [ ] **Step 4: 提交**

```bash
git add frontend/src/api/factorScreening.ts frontend/src/views/FactorScreening/index.vue frontend/src/router/index.ts frontend/src/components/Layout/SidebarMenu.vue
git commit -m "feat(factor-web): 前端选股API与路由菜单"
```

---

### Task 8: 因子配置组件 `FactorConfig.vue`

**Files:**
- Create: `frontend/src/views/FactorScreening/components/FactorConfig.vue`

**Interfaces:**
- Props: `modelValue: Array<{key,weight,direction}>`（已选因子配置）；`factorsMeta: Array<{key,name,category,default_direction}>`（来自 `/factors`）。
- Emits: `update:modelValue`。
- 行为：按 `category` 分组列出因子，每个可勾选启用；启用后显示权重输入（`el-input-number`，默认 1，>0）+ 方向切换（`el-radio-group`：越大越好=desc / 越小越好=asc，默认取 `default_direction`）。勾选/改权重/改方向都 emit 出 `[{key,weight,direction}]`（仅含已启用项）。用本地副本，避免直接 mutate props（参考阶段① `ConditionEditor.vue` 的 v-model 防回环写法）。

- [ ] **Step 1: 实现组件**（读 `frontend/src/views/Backtest/components/ConditionEditor.vue` 学 v-model 防回环模式）。核心：本地 `reactive` 记录每个 key 的 `{enabled,weight,direction}`，`watch` 外部 `modelValue` 同步、`emitUpdate` 输出已启用项数组，用快照比较防回环。

- [ ] **Step 2: 构建确认**

Run: `cd frontend && npm run build`
Expected: 构建通过

- [ ] **Step 3: 提交**

```bash
git add frontend/src/views/FactorScreening/components/FactorConfig.vue
git commit -m "feat(factor-web): 因子配置组件(勾选+权重+方向)"
```

---

### Task 9: 榜单结果表 `ResultTable.vue`

**Files:**
- Create: `frontend/src/views/FactorScreening/components/ResultTable.vue`

**Interfaces:**
- Props: `items: Array<{code,name,industry,score,rank,factors}>`；`selectedFactorKeys: string[]`（当前选中的因子 key，用于动态列）。
- 行为：`el-table` 展示 排名/代码/名称/行业/总分 + 每个选中因子一列（显示该因子 `norm` 得分，`el-tooltip` 展示原始 `value`），可按列排序；每行「→ 单股回测」按钮，`emit('backtest', code)`。空数据用 `el-table` 空态。总分保留 3 位小数。

- [ ] **Step 1: 实现组件**（动态列用 `v-for` 遍历 `selectedFactorKeys` 生成 `el-table-column`，`:key` 用因子 key 保证稳定）。

- [ ] **Step 2: 构建确认**

Run: `cd frontend && npm run build`
Expected: 构建通过

- [ ] **Step 3: 提交**

```bash
git add frontend/src/views/FactorScreening/components/ResultTable.vue
git commit -m "feat(factor-web): 榜单结果表组件(动态因子列+单股回测跳转)"
```

---

### Task 10: 主页组装 `index.vue`

**Files:**
- Modify: `frontend/src/views/FactorScreening/index.vue`（从占位改为完整页）

**Interfaces:**
- 组装：`onMounted` 拉 `factorApi.factors()` → 传给 `FactorConfig`；选股域表单（剔除ST开关、剔除次新开关、行业多选、市值区间 min/max、TopN）；「开始选股」→ `factorApi.run({factors, universe, top_n})` → 轮询 `status`（running/done/failed，参考阶段① index.vue 的轮询与 `onUnmounted` 清定时器）→ done 取 `result` → 传 `ResultTable`。`ResultTable` 的 `@backtest` → `router.push({path:'/backtest', query:{symbol: code}})` 跳阶段①。历史区 `factorApi.history()` 列表点击回看。

- [ ] **Step 1: 实现主页**（提交前校验：至少 1 个因子、top_n>0；失败 `ElMessage`。轮询与清定时器照阶段① `Backtest/index.vue`）。

- [ ] **Step 2: 构建确认**

Run: `cd frontend && npm run build`
Expected: 构建通过

- [ ] **Step 3: 提交**

```bash
git add frontend/src/views/FactorScreening/index.vue
git commit -m "feat(factor-web): 多因子选股主页(配置+选股域+轮询+榜单+回测跳转)"
```

---

### Task 11: 浏览器端到端验证 + 重建前端镜像

**Files:** 无新增（验证任务）

- [ ] **Step 1: 重建前端镜像并起容器**

```bash
docker compose -f docker-compose.yml build frontend
docker compose -f docker-compose.yml up -d --force-recreate frontend
```

- [ ] **Step 2: 浏览器验证**：`http://localhost:3000` → 登录 admin/admin123 → 「多因子选股」→ 勾选 PE(越小越好)+60日动量(越大越好)+总市值(越小越好)，各设权重 → 剔除 ST、TopN=20 → 「开始选股」→ 确认：进度→榜单表出现 TopN（总分+各因子得分列）→ 点某行「→单股回测」跳到策略回测页且带入该股代码。

- [ ] **Step 3: 记录验证结果**（文字/截图），有 bug 回到对应 Task 修复。

---

## Self-Review

**1. Spec coverage：**
- 打分层（15 因子/标准化/加权/剔除/TopN）→ Task 1-3 ✅
- 后端异步（候选池/预取/run_in_executor/落库/属主校验/状态 running-done-failed）→ Task 4-5 ✅
- 后端 e2e → Task 6 ✅
- 前端（API/路由/因子配置/榜单/主页/单股回测跳转）→ Task 7-10 ✅
- 浏览器验证 → Task 11 ✅
- 选股域（剔除ST/次新/行业/市值区间）→ Task 4 `get_candidates` ✅
- `/factors` 元信息接口 → Task 5 ✅
- 数据源（宽表估值 + 日线前复权量价，零同步）→ Task 4 ✅
- 组合回测/财务因子明确不在本计划 → 符合 spec 2b 边界 ✅

**2. Placeholder scan：** 各代码步含真实实现；状态方法在 Task 4 明确「照 backtest_service 同构」并给了其余核心代码——非占位，是显式复用指令。✅

**3. Type consistency：** `score_universe(stocks, factor_configs, top_n)` 签名在 Task 3 定义、Task 4 调用一致；榜单字段 `{code,name,industry,score,rank,factors}` 贯穿 Task 3→4→5→9；状态值 `running/done/failed` 全程一致；集合名 `factor_screen_tasks`/`factor_screen_results` 一致；前端 `factorApi` 方法名与后端路径一致。✅
