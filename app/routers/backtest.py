"""策略回测 Web 接口（异步任务）。

任务提交后立即返回 task_id，真正的回测计算通过 FastAPI `BackgroundTasks`
在后台执行；任务状态记录在 MongoDB `backtest_tasks` 集合中（见
`app/services/backtest_service.set_task_status`/`get_task_status`）。

注意：不使用 `app/services/queue_service.py` 里的 Redis 队列——该服务面向
"批量股票分析"场景（create_batch/enqueue_task），语义与鉴权模型都不适合
单次策略回测任务，故这里用一张独立的状态表自行管理任务生命周期。
"""
import uuid
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.routers.auth_db import get_current_user
from app.services import backtest_service
from app.services.backtest_param_mapper import build_backtest_args

router = APIRouter(prefix="/api/backtest", tags=["策略回测"])


@router.post("/run")
async def run(
    payload: Dict[str, Any],
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    """提交一次策略回测任务，返回 task_id，实际计算在后台执行。"""
    # 参数校验（非法参数直接 400，不进入后台任务）
    try:
        build_backtest_args(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    user_id = user["id"]
    task_id = uuid.uuid4().hex

    # 同步插入任务状态记录（status=running），使提交后立即可查询到任务
    await backtest_service.ensure_db()
    await backtest_service.set_task_status(task_id, "running", user_id=user_id)

    async def _run_task():
        """后台执行：跑回测引擎 + 落库，最终更新任务状态为 done/failed。"""
        try:
            await backtest_service.ensure_db()
            await backtest_service.run_backtest_task(task_id, user_id, payload)
            await backtest_service.set_task_status(task_id, "done")
        except Exception as e:
            await backtest_service.set_task_status(task_id, "failed", error=str(e))

    background_tasks.add_task(_run_task)
    return {"success": True, "data": {"task_id": task_id}}


@router.get("/status/{task_id}")
async def status(task_id: str, user: dict = Depends(get_current_user)):
    """查询回测任务状态。

    属主校验：任务不存在 或 属于其他用户，统一返回 404（不用 403），
    避免向非本人泄露"该 task_id 确实存在"这一信息。
    """
    await backtest_service.ensure_db()
    task_status = await backtest_service.get_task_status(task_id)
    if not task_status or task_status.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"success": True, "data": task_status}


@router.get("/result/{task_id}")
async def result(task_id: str, user: dict = Depends(get_current_user)):
    """查询回测结果，任务未完成/不存在/属于其他用户时统一返回 404。"""
    await backtest_service.ensure_db()
    res = await backtest_service.get_result(task_id)
    if not res or res.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="回测结果不存在或未完成")
    return {"success": True, "data": res}


@router.get("/history")
async def history(
    limit: int = 20,
    skip: int = 0,
    user: dict = Depends(get_current_user),
):
    """查询当前用户的历史回测记录。"""
    await backtest_service.ensure_db()
    data = await backtest_service.get_history(user["id"], limit, skip)
    return {"success": True, "data": data}
