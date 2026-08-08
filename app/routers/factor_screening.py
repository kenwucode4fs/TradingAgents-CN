"""因子打分选股（子项目 2a）Web 接口（异步任务）。

任务提交后立即返回 task_id，真正的选股计算通过 FastAPI `BackgroundTasks`
在后台执行；任务状态记录在 MongoDB `factor_screen_tasks` 集合中（见
`app/services/factor_screening_service.set_task_status`/`get_task_status`）。
属主校验/BackgroundTasks 写法照 `app/routers/backtest.py`。
"""
import uuid
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.routers.auth_db import get_current_user
from app.services import factor_screening_service as svc
from tradingagents.factor import FACTORS

router = APIRouter(prefix="/api/factor-screen", tags=["factor-screen"])


@router.get("/factors")
async def list_factors(user: dict = Depends(get_current_user)):
    """返回可选因子元信息（无需鉴权数据敏感性低，但仍加 get_current_user 保持一致）。"""
    data = [
        {"key": k, "name": m["name"], "category": m["category"],
         "default_direction": m["default_direction"]}
        for k, m in FACTORS.items()
    ]
    return {"success": True, "data": data}


def _validate(payload: Dict[str, Any]) -> None:
    """选股请求参数校验，非法参数直接 400，不进入后台任务。"""
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
async def run(
    payload: Dict[str, Any],
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    """提交一次因子选股任务，返回 task_id，实际计算在后台执行。"""
    _validate(payload)

    user_id = user["id"]
    task_id = uuid.uuid4().hex

    await svc.ensure_db()
    await svc.set_task_status(task_id, "running", user_id=user_id)

    async def _run_task():
        try:
            await svc.ensure_db()
            await svc.run_screen_task(task_id, user_id, payload)
            await svc.set_task_status(task_id, "done", user_id=user_id)
        except Exception as e:  # noqa: BLE001
            await svc.set_task_status(task_id, "failed", error=str(e), user_id=user_id)

    background_tasks.add_task(_run_task)
    return {"success": True, "data": {"task_id": task_id}}


@router.get("/status/{task_id}")
async def status(task_id: str, user: dict = Depends(get_current_user)):
    """查询选股任务状态。

    属主校验：任务不存在 或 属于其他用户，统一返回 404（不用 403），
    避免向非本人泄露“该 task_id 确实存在”这一信息。
    """
    await svc.ensure_db()
    task_status = await svc.get_task_status(task_id)
    if not task_status or task_status.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"success": True, "data": task_status}


@router.get("/result/{task_id}")
async def result(task_id: str, user: dict = Depends(get_current_user)):
    """查询选股结果，任务未完成/不存在/属于其他用户时统一返回 404。"""
    await svc.ensure_db()
    res = await svc.get_result(task_id)
    if not res or res.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="结果不存在")
    return {"success": True, "data": res}


@router.get("/history")
async def history(
    limit: int = 20,
    skip: int = 0,
    user: dict = Depends(get_current_user),
):
    """查询当前用户的历史选股记录。"""
    await svc.ensure_db()
    data = await svc.get_history(user["id"], limit, skip)
    return {"success": True, "data": data}
