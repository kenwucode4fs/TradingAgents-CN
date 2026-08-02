# SDD ledger — plan: docs/superpowers/plans/2026-08-01-backtest-engine-phase1.md

BASE (branch start): cac8a1b
Branch: feature/backtest-engine

## Tasks

Task 1: implementer DONE_WITH_CONCERNS (commits e9a5d88..07c54bc)
Task 1: review — spec ✅, quality 3 Important + 4 Minor
Task 1: minor (deferred): conftest mongo 环境注入作用域宽(⚠️待确认); merge_qfq 硬编码 data_source=tushare(合理); get_news 同款 hasattr bug(范围外); qfq 未 round(与现有 OHLC 一致)
Task 1: fix round 1/5 — 3 addressed, 0 open (a/b/c 全 ADDRESSED, re-review PASS 无新破坏; commit 1d128df)
Task 1: minor (deferred): _get_existing_qfq_map 每次 save 多一次查询(性能非正确性); 合并条件"四字段全None才整体合并"边界取舍
Task 1: complete (commits e9a5d88..1d128df, review clean after 1 fix round)

Task 2: implementer DONE (commit a891ed0)
Task 2: review — spec ✅, quality 1 Important + 3 Minor
Task 2: minor (deferred): is_available 检查冗余; _fmt 对 NaT 异常值透传; "ST" in name 子串匹配极低概率误判
Task 2: fix round 1/5 — 1 addressed (北交所.BJ映射+测试), 多段区间纯单测已补, re-review PASS 无新破坏 (commit 585581d)
Task 2: complete (commits a891ed0..585581d, review clean after 1 fix round)

Task 3: implementer DONE (commit 915ed05)
Task 3: review — spec ✅, quality 2 Important + 1 Minor
Task 3: minor (deferred): M1 __init__ 导出 —— plan 有意 Task3 留空、Task11 导出,按 plan 不动
Task 3: fix round 1/5 — I1/I2 ADDRESSED (str→Literal), __init__ 未动, re-review PASS 无新破坏 (commit 4cd130f)
Task 3: complete (commits 915ed05..4cd130f, review clean after 1 fix round)

Task 4: implementer DONE (commit b18beb1)
Task 4: review — spec ✅, quality 1 Important + 3 Minor
Task 4: minor (deferred): M1 报告误声明 from __future__ import annotations(仅报告不符)
Task 4: fix round 1/5 — Important(Decimal精度)/M2(板块前缀)/M3(对称测试) 全 ADDRESSED, re-review PASS 无新破坏 (commit 4a801a4)
Task 4: complete (commits b18beb1..4a801a4, review clean after 1 fix round)

Task 5: implementer DONE (commit 2df33e4)
Task 5: review — spec ✅, quality 1 Important + 2 Minor
Task 5: fix round 1/5 — Important(逐行qfq校验)/M1(删导入)/M2(load_bars单测) 全 ADDRESSED, re-review PASS 无新破坏 (commit 4c08fe4)
Task 5: complete (commits 2df33e4..4c08fe4, review clean after 1 fix round)

Task 6: implementer DONE (commit c361a7c)
Task 6: review — spec ✅, quality 1 Important + 1 Minor
Task 6: fix round 1/5 — Important RSI 三边界(None/100/0)全 ADDRESSED, 手算断言补上, re-review PASS 无新破坏
Task 6: scope-creep 清理 — fix commit 4f63973 误 git add 了工作区无关文件(docker-compose*/default_config), 已 reset --soft 重写为纯净 commit 2a5c545(仅 indicators+test), 无关改动恢复工作区未提交
Task 6: complete (commits c361a7c..2a5c545, review clean after 1 fix round)
Task 6: LESSON — 后续 dispatch 强调只 git add 本任务文件, 禁用 git add -A/. (工作区有用户无关改动)

Task 7: implementer DONE (commit a906368, diff 干净仅2文件)
Task 7: review — spec ✅, quality 1 Important + 1 Minor
Task 7: fix round 1/5 — Important(消除cross重复,复用+测试)/Minor(op/logic校验) 全 ADDRESSED, re-review PASS 无新破坏 (commit 90ed14c)
Task 7: complete (commits a906368..90ed14c, review clean after 1 fix round)

Task 8: implementer DONE (commit 23bfe71, diff 干净仅2文件)
Task 8: review — spec ✅, quality Approved(0C/0I/3Minor); 4900vs5000 经确认是 brief 内部矛盾,以测试为准正确、不透支、非bug
Task 8: minor (deferred): 资金不足仅减一手非循环(极低价<0.1元股才命中,现实A股不会)
Task 8: fix round 1/5 — 补测试(跌停/market_value)+去重(_budget/buyable_shares_for_part)+死代码转assert 全 ADDRESSED, re-review PASS 无新破坏 (commit 1c2f67b)
Task 8: complete (commits 23bfe71..1c2f67b, review clean after 1 fix round)

Task 9: implementer DONE (commit 2682c67, diff 干净仅2文件); 核心正确性(前视/T+1/顺延/HOLD/净值)评审逐行确认通过
Task 9: review — spec ✅, quality 1 Important + 2 Minor (均为测试覆盖gap,非bug)
Task 9: fix round 1/5 — Important(反向信号死单锁定测试)/Minor(跌停SELL顺延对称/trades引用docstring) 全 ADDRESSED, re-review PASS engine.py仅改docstring无逻辑改动 (commit 71a68e4)
Task 9: complete (commits 2682c67..71a68e4, review clean after 1 fix round)

Task 10: implementer DONE (commit 420f792, diff 干净仅2文件)
Task 10: review — spec ✅, quality 1 Important + 2 Minor
Task 10: fix round 1/5 — Important(股数FIFO逐股配对)ADDRESSED(复审独立手算两分批场景验证)/Minor(约定注释) 全处理, re-review PASS 其他指标无破坏 (commit 080fd8a)
Task 10: complete (commits 420f792..080fd8a, review clean after 1 fix round)

Task 11: implementer DONE (commit b7f9576, diff 干净仅3文件); 全量 77 passed 含端到端
Task 11: review — spec ✅, quality Approved (0C/0I/0Minor) 一次通过零finding
Task 11: complete (commit b7f9576, review clean no fix round)

Task 12: implementer DONE (commit d7860dd, diff 干净仅1文件); 真实数据冒烟跑通 000001 双均线 总收益0.154% vs 基准4.49%
Task 12: review — spec ✅, quality Approved (0C/0I/0Minor); 独立复现结果一致
Task 12: PLAN2-INPUT — run_backtest 内部 asyncio.run,Web层(FastAPI async handler)/Jupyter 交互环境直接调用会冲突,Plan 2 需拆 async 版 load_bars。仅影响 Plan2,Plan1 无缺陷
Task 12: complete (commit d7860dd, review clean no fix round)

=== 全部 12 任务完成。进入全分支最终评审 ===

FINAL REVIEW (opus, cac8a1b..d7860dd): 有阻塞 — 1 Critical + 1 Important + 3 Minor
- CRITICAL(必修): pre_close 口径不一致 — Bar.open/close 用qfq但 pre_close 用库原始价,market_rules 涨跌停判定标度错→多年分红股系统性误判涨跌停。合成数据测试未暴露
- IMPORTANT(本期补): Trade 无 pnl 字段, metrics 每笔盈亏未回填(spec §8/§10 交易明细含盈亏)
- MINOR(本期顺手): 平均持仓天数未实现(spec §8); _fmt 对 "NaT" 透传
- MINOR(留Plan2/记账): ST主板5%依赖Web传st_service(run_backtest默认None,Plan2 wiring); run_backtest asyncio.run Web冲突; Task1多查qfq; Task2 is_available冗余/"ST"子串; Task8减一手非循环
FINAL FIX WAVE 启动 — Critical(pre_close复权口径)+Important(Trade.pnl)+Minor(平均持仓天数/_fmt NaT); FIX_BASE=d7860dd
FINAL FIX WAVE — 全 4 项 ADDRESSED (commits 097ba06/49980f0/4060483), re-review 手工推演验证Critical标度正确, 无新破坏, 86 passed; VERDICT 可合并
PARKED(已知局限,非bug): pre_close idx==0 若窗口首日恰为除权除息日有理论边界误差(查询窗口固有局限,前一日不在窗口内)

=== PLAN 1 (数据准备+引擎层) 全部完成 ===
分支 feature/backtest-engine, 12 任务 + 最终fix wave 全部 review-clean, 86 单元测试通过 + 真实数据冒烟通过
Plan 2 (Web接入) 待办; Plan2 已知输入: run_backtest 需 async 版 load_bars(避免事件循环冲突); ST主板5%需Web传st_service
DEFERRED MINORS 汇总(交最终评审 triage):
- Task1: _get_existing_qfq_map 每次save多一次查询(性能); 合并条件"四字段全None才整体合并"边界
- Task2: is_available检查冗余; _fmt对NaT透传; "ST"子串匹配极低误判
- Task4: 报告曾误声明 from __future__ import annotations(已在fix澄清)
- Task8: 资金不足仅减一手非循环(极低价<0.1元股才命中,现实A股不会)
