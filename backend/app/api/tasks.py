"""任务接口：CRUD / 启停 / 立即执行 / 模板。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from ..core import scheduler as sched
from ..core import runner
from ..db import session_scope
from ..logging_setup import logger
from ..models import Account, Task, TaskTemplate
from ..schemas import (
    OkOut,
    RunNowIn,
    TaskCreate,
    TaskOut,
    TaskTemplateIn,
    TaskTemplateOut,
    TaskToggleIn,
    TaskUpdate,
)
from ..settings import settings
from ..utils.cron import (
    ScheduleError,
    describe_schedule,
    next_run_times,
    parse_interval,
    to_cron_expression,
)
from .deps import current_user

router = APIRouter(prefix="/api", tags=["tasks"])


def _to_out(task: Task, account_name: str = "") -> TaskOut:
    data = TaskOut.model_validate(
        {
            **{c.name: getattr(task, c.name) for c in task.__table__.columns},
            "account_name": account_name,
        }
    )
    tz_name = task.timezone or settings.tz
    data.schedule_text = describe_schedule(task.schedule_type, task.schedule_value)
    data.next_runs = next_run_times(task.schedule_type, task.schedule_value, tz_name)
    live = sched.next_run_time(task.id)
    if live:
        data.next_run_at = live
    return data


async def _account_name(account_id: int) -> str:
    async with session_scope() as session:
        account = await session.get(Account, account_id)
        return account.name if account else ""


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(_: str = Depends(current_user)) -> list[TaskOut]:
    async with session_scope() as session:
        tasks = (await session.execute(select(Task).order_by(Task.id))).scalars().all()
        accounts = {a.id: a.name for a in (await session.execute(select(Account))).scalars().all()}
        return [_to_out(t, accounts.get(t.account_id, "")) for t in tasks]


@router.get("/tasks/{task_id}", response_model=TaskOut)
async def get_task(task_id: int, _: str = Depends(current_user)) -> TaskOut:
    async with session_scope() as session:
        task = await session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        account = await session.get(Account, task.account_id)
        return _to_out(task, account.name if account else "")


@router.post("/tasks", response_model=TaskOut)
async def create_task(payload: TaskCreate, _: str = Depends(current_user)) -> TaskOut:
    async with session_scope() as session:
        account = await session.get(Account, payload.account_id)
        if account is None:
            raise HTTPException(status_code=400, detail="所选账号不存在")
        task = Task(**payload.model_dump())
        session.add(task)
        await session.flush()
        await session.flush()
        session.expunge(task)
    sched.schedule_task(task)
    logger.info("新增任务：%s", task.name)
    return _to_out(task, account.name)


@router.put("/tasks/{task_id}", response_model=TaskOut)
async def update_task(task_id: int, payload: TaskUpdate, _: str = Depends(current_user)) -> TaskOut:
    async with session_scope() as session:
        task = await session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        account = await session.get(Account, payload.account_id)
        if account is None:
            raise HTTPException(status_code=400, detail="所选账号不存在")
        for key, value in payload.model_dump().items():
            setattr(task, key, value)
        await session.flush()
        session.expunge(task)
    sched.remove_task(task_id)
    sched.schedule_task(task)
    logger.info("更新任务：%s", task.name)
    return _to_out(task, account.name)


@router.delete("/tasks/{task_id}", response_model=OkOut)
async def delete_task(task_id: int, _: str = Depends(current_user)) -> OkOut:
    async with session_scope() as session:
        task = await session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        name = task.name
        await session.delete(task)
    sched.remove_task(task_id)
    logger.info("删除任务：%s", name)
    return OkOut(message=f"任务「{name}」已删除")


@router.post("/tasks/{task_id}/toggle", response_model=TaskOut)
async def toggle_task(task_id: int, payload: TaskToggleIn, _: str = Depends(current_user)) -> TaskOut:
    async with session_scope() as session:
        task = await session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        task.enabled = payload.enabled
        account = await session.get(Account, task.account_id)
        await session.flush()
        session.expunge(task)
    sched.remove_task(task_id)
    if task.enabled:
        sched.schedule_task(task)
    return _to_out(task, account.name if account else "")


@router.post("/tasks/{task_id}/run", response_model=OkOut)
async def run_task(task_id: int, payload: RunNowIn, _: str = Depends(current_user)) -> OkOut:
    async with session_scope() as session:
        task = await session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        if runner.is_running(task_id):
            raise HTTPException(status_code=409, detail="该任务正在执行中")

    asyncio.create_task(runner.execute_task(task_id, trigger="manual", force=payload.force))
    return OkOut(message="已开始执行，可在「签到记录 / 实时日志」查看结果")


# ---------------------------------------------------------------- 模板


@router.get("/templates", response_model=list[TaskTemplateOut])
async def list_templates(_: str = Depends(current_user)) -> list[TaskTemplateOut]:
    async with session_scope() as session:
        rows = (await session.execute(select(TaskTemplate).order_by(TaskTemplate.id))).scalars().all()
        counts = dict(
            (
                await session.execute(
                    select(Task.template_id, func.count(Task.id)).group_by(Task.template_id)
                )
            ).all()
        )
        return [
            TaskTemplateOut(
                **{
                    **{c.name: getattr(r, c.name) for c in r.__table__.columns},
                    "ref_count": counts.get(r.id, 0),
                }
            )
            for r in rows
        ]


@router.post("/templates", response_model=TaskTemplateOut)
async def create_template(payload: TaskTemplateIn, _: str = Depends(current_user)) -> TaskTemplateOut:
    async with session_scope() as session:
        template = TaskTemplate(
            name=payload.name,
            description=payload.description,
            action_flow=payload.action_flow,
            success_rule=payload.success_rule.model_dump(),
            retry_policy=payload.retry_policy.model_dump(),
        )
        session.add(template)
        await session.flush()
        session.expunge(template)
    return TaskTemplateOut(**{**template.__dict__, "ref_count": 0})


@router.put("/templates/{template_id}", response_model=TaskTemplateOut)
async def update_template(
    template_id: int, payload: TaskTemplateIn, _: str = Depends(current_user)
) -> TaskTemplateOut:
    async with session_scope() as session:
        template = await session.get(TaskTemplate, template_id)
        if template is None:
            raise HTTPException(status_code=404, detail="模板不存在")
        template.name = payload.name
        template.description = payload.description
        template.action_flow = payload.action_flow
        template.success_rule = payload.success_rule.model_dump()
        template.retry_policy = payload.retry_policy.model_dump()

        # 同步刷新所有引用该模板的任务
        refs = (
            (await session.execute(select(Task).where(Task.template_id == template_id))).scalars().all()
        )
        for task in refs:
            task.action_flow = payload.action_flow
            task.success_rule = payload.success_rule.model_dump()
            task.retry_policy = payload.retry_policy.model_dump()
        count = len(refs)
        await session.flush()
        session.expunge(template)
    logger.info("模板 %s 已更新，同步 %s 个任务", payload.name, count)
    return TaskTemplateOut(**{**template.__dict__, "ref_count": count})


@router.delete("/templates/{template_id}", response_model=OkOut)
async def delete_template(template_id: int, _: str = Depends(current_user)) -> OkOut:
    async with session_scope() as session:
        template = await session.get(TaskTemplate, template_id)
        if template is None:
            raise HTTPException(status_code=404, detail="模板不存在")
        await session.delete(template)
    return OkOut(message="模板已删除")


# ---------------------------------------------------------------- 调度预览


@router.post("/schedule/preview")
async def preview_schedule(
    payload: dict[str, str], _: str = Depends(current_user)
) -> dict[str, object]:
    schedule_type = payload.get("schedule_type", "cron")
    schedule_value = payload.get("schedule_value", "")
    timezone_name = payload.get("timezone") or settings.tz
    try:
        # 先做硬校验：非法表达式必须报错，不能静默返回空列表
        if schedule_type == "interval":
            parse_interval(schedule_value)
        else:
            to_cron_expression(schedule_type, schedule_value)
        times = next_run_times(schedule_type, schedule_value, timezone_name, count=5)
        return {
            "ok": True,
            "text": describe_schedule(schedule_type, schedule_value),
            "next_runs": [t.isoformat() for t in times],
        }
    except ScheduleError as exc:
        return {"ok": False, "message": str(exc), "next_runs": []}
