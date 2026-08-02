# 策略回测引擎 Phase 1 — 最终全分支评审

- 日期：2026-08-02
- 范围：`review-cac8a1b..d7860dd`（24 提交 / 12 任务）
- 视角：整体集成 / 端到端正确性 / spec 覆盖，找单任务评审看不到的问题
- 前置：全量 77 passed（不含 integration），本次聚焦代码审阅与推理

## 总体结论

**有阻塞问题（1 个 Critical，须 merge 前修）。** 其余接口一致性、引擎层隔离、T+1/前视偏差、成本计算等整体质量良好；模块间字段/签名/返回结构前后吻合，引擎层除 data_feed 延迟 import app 外无其它 app 依赖。

---

## 新发现问题（本次整体视角新增，非各单任务已修项）

### Critical

- **【复权价/pre_close 口径不一致 → 精确涨跌停判定在完整链路里失效】**
  `data_feed.bars_from_records` 把 `Bar.open/high/low/close` 取**前复权价**（`*_qfq`），
  但 `Bar.pre_close` 直接取库里**原始** `pre_close`（`historical_data_service.py:362`，
  raw tushare 值；全库无 `pre_close_qfq`）。`market_rules.limit_up/down_price` 用
  raw `pre_close` 算涨跌停价，`broker.try_buy/try_sell` 却拿 **qfq 的 `bar.open`**
  去比。两者不同标度：历史 bar 的 qfq 因子 f=adj(T)/adj(latest)<1，于是
  - 卖出侧 `open_qfq > pre_close_raw×0.9` 在 f<0.9（多年分红股极常见）时对**普通交易日**恒为
    False → 误判一字跌停 → 卖单被无限顺延，回测在早段几乎无法卖出；
  - 买入侧 `open_qfq < pre_close_raw×1.1` 恒为 True → 一字涨停封板完全检测不到。
  即 spec §7.1「精确涨跌停」这一头号特性在真实多年分红股回测中系统性失真。
  现有测试未暴露：单测用自洽的合成 pre_close/open，smoke 只跑 7 个月短窗且仅断言曲线长度。
  修复方向：按行推导 qfq 前收 `pre_close_qfq = pre_close_raw × (close_qfq/close_raw)`
  （record 里 raw close 与 close_qfq 都在），令涨跌停判定与 open 同标度。

### Important

- **（spec 覆盖）交易明细缺每笔盈亏 pnl**：spec §8/§10 要求交易明细含每笔「盈亏」，
  但 `Trade` 无 `pnl` 字段，`metrics` 内部按 FIFO 算出的每笔盈亏未回填到 Trade，
  `result.to_dict()` 的 trades 序列化后前端拿不到盈亏列。

### Minor

- **（spec 覆盖）绩效指标缺「平均持仓天数」**：spec §8 明确列出，`compute_metrics`
  返回的 dict 未含 avg holding days。
- **（Plan2 接线，⚠️）ST 主板 5% 判定依赖调用方传 st_service**：`run_backtest` 默认
  `st_service=None` → `is_st` 恒 False → ST 主板涨跌幅退化为 10%。Web 层接入时须显式
  传 `StStatusService`，否则 ST 判定形同虚设。（引擎已支持，属 Plan2 wiring 缺口。）
- **（健壮性）`StStatusService._fmt` 对 `NaT` 透传**：`str(NaT)="NaT"`，非 8 位又不在
  `("None","nan")` 里 → 原样返回 "NaT" 作为 end_date，后续字符串比较会碰巧当「至今」。
  tushare namechange 实测返回字符串/None，触发概率低，但建议把 "NaT" 一并归 None。

---

## 遗留 minor 的 triage 结论

| 遗留项 | 结论 |
|---|---|
| Task1 每次 save 多查一次 qfq / 合并边界 | **可留后续**。Plan1 离线只读库，额外一次查询是同步期开销，不影响回测正确性。 |
| Task2 `is_available` 冗余判断 | **可留后续**。冗余但无害。 |
| Task2 `_fmt` 对 NaT 透传 | **建议顺手修**（见上 Minor），非硬阻塞。 |
| Task2 "ST" 子串匹配 | **可留后续**。A股名称为中文，ST/*ST 是唯一拉丁标记，误匹配风险极低。 |
| Task8 资金不足仅减一手非循环 | **可留后续**。价≥1 元时一手回退（≥100 元）远大于成本溢出（约 5 元），A股价格几乎不低于 1 元，实务恒够。 |
| Plan2：run_backtest 内 asyncio.run 与 Web async 冲突 | **留 Plan2**。Plan1 走同步 worker 不受影响，已知项。 |

**唯一 merge 前必修：Critical 的复权价/pre_close 口径不一致。** Important 的每笔 pnl 与
Minor 的平均持仓天数属 spec §8 引擎层交付项，建议本期补齐以免 Plan2 前端无数据可用；
若拆到 Plan2 首个任务处理亦可，但须显式记账，勿默认已完成。
