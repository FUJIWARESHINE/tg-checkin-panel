"""签到记录接口。"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select

from ..db import session_scope
from ..logging_setup import logger
from ..models import Record
from ..schemas import Page, RecordOut, StatsOut
from .deps import current_user

router = APIRouter(prefix="/api/records", tags=["records"])


def _query(
    task_id: int | None,
    status: str | None,
    keyword: str | None,
    start: datetime | None,
    end: datetime | None,
    account_id: int | None = None,
):
    stmt = select(Record)
    if task_id:
        stmt = stmt.where(Record.task_id == task_id)
    if account_id:
        stmt = stmt.where(Record.account_id == account_id)
    if status:
        stmt = stmt.where(Record.status == status)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            Record.target.like(like)
            | Record.task_name.like(like)
            | Record.reply_snippet.like(like)
            | Record.error.like(like)
        )
    if start:
        stmt = stmt.where(Record.run_at >= start)
    if end:
        stmt = stmt.where(Record.run_at <= end)
    return stmt


@router.get("", response_model=Page)
async def list_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    task_id: int | None = None,
    account_id: int | None = None,
    status: str | None = None,
    keyword: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    _: str = Depends(current_user),
) -> Page:
    async with session_scope() as session:
        base = _query(task_id, status, keyword, start, end, account_id)
        total = (
            await session.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
        rows = (
            (
                await session.execute(
                    base.order_by(Record.run_at.desc()).offset((page - 1) * page_size).limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        return Page(
            total=total,
            page=page,
            page_size=page_size,
            items=[RecordOut.model_validate(r) for r in rows],
        )


@router.get("/stats", response_model=StatsOut)
async def stats(days: int = Query(30, ge=7, le=90), _: str = Depends(current_user)) -> StatsOut:
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=6)
    window_start = today_start - timedelta(days=days - 1)

    async with session_scope() as session:
        today_rows = (
            (
                await session.execute(
                    select(Record.status, func.count(Record.id))
                    .where(Record.run_at >= today_start)
                    .group_by(Record.status)
                )
            ).all()
        )
        today_map = {status: count for status, count in today_rows}

        week_rows = (
            (
                await session.execute(
                    select(Record.status, func.count(Record.id))
                    .where(Record.run_at >= week_start)
                    .group_by(Record.status)
                )
            ).all()
        )
        week_map = {status: count for status, count in week_rows}
        week_total = sum(week_map.values())
        week_success = week_map.get("success", 0)

        day_expr = func.strftime("%Y-%m-%d", Record.run_at)
        heat_rows = (
            (
                await session.execute(
                    select(day_expr.label("day"), Record.status, func.count(Record.id))
                    .where(Record.run_at >= window_start)
                    .group_by("day", Record.status)
                )
            ).all()
        )
        heatmap: dict[str, dict[str, int]] = {}
        for day, status, count in heat_rows:
            bucket = heatmap.setdefault(str(day), {"success": 0, "fail": 0})
            bucket[status if status in ("success", "fail") else "fail"] += count

        recent = (
            (
                await session.execute(select(Record).order_by(Record.run_at.desc()).limit(10))
            )
            .scalars()
            .all()
        )

    series = []
    for offset in range(days - 1, -1, -1):
        day = (today_start - timedelta(days=offset)).strftime("%Y-%m-%d")
        bucket = heatmap.get(day, {"success": 0, "fail": 0})
        series.append({"date": day, "success": bucket["success"], "fail": bucket["fail"]})

    return StatsOut(
        today_success=today_map.get("success", 0),
        today_fail=today_map.get("fail", 0),
        today_total=sum(today_map.values()),
        success_rate_7d=round(week_success / week_total * 100, 1) if week_total else 0.0,
        heatmap=series,
        recent=[RecordOut.model_validate(r) for r in recent],
    )


@router.get("/export")
async def export_csv(
    task_id: int | None = None,
    status: str | None = None,
    keyword: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(5000, ge=1, le=50000),
    _: str = Depends(current_user),
) -> StreamingResponse:
    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    _query(task_id, status, keyword, start, end)
                    .order_by(Record.run_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

    buffer = io.StringIO()
    buffer.write("\ufeff")  # BOM，避免 Excel 打开中文乱码
    writer = csv.writer(buffer)
    writer.writerow(["时间(UTC)", "任务", "账号", "目标", "触发", "状态", "尝试", "耗时(ms)", "命中", "奖励", "错误"])
    for r in rows:
        writer.writerow(
            [
                r.run_at.strftime("%Y-%m-%d %H:%M:%S") if r.run_at else "",
                r.task_name,
                r.account_name,
                r.target,
                r.trigger,
                r.status,
                r.attempt,
                r.duration_ms,
                r.matched_keyword,
                r.reward_text,
                r.error,
            ]
        )
    buffer.seek(0)
    filename = f"checkin-records-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("")
async def delete_records(
    scope: str | None = Query(
        None,
        description="all=清空全部 / before=删除 days 天以前 / ids=删除指定记录；不传时按 days 兼容旧行为",
    ),
    days: int = Query(30, ge=0, le=3650),
    ids: str = Query("", description="scope=ids 时使用，逗号分隔的记录 id，例如 1,2,3"),
    _: str = Depends(current_user),
) -> dict[str, object]:
    """删除签到记录。

    - `scope=ids&ids=1,2,3`：只删除选中的记录
    - `scope=before&days=30`：删除 N 天以前的记录
    - `scope=all`：清空全部记录
    - 不传 scope 时：days>0 等价于 before，days=0 等价于 all（保持旧版调用兼容）
    """
    if scope is None:
        scope = "before" if days > 0 else "all"
    if scope not in ("all", "before", "ids"):
        raise HTTPException(status_code=400, detail="scope 只能是 all / before / ids")

    stmt = delete(Record).execution_options(synchronize_session=False)
    if scope == "ids":
        try:
            id_list = [int(part) for part in ids.split(",") if part.strip()]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="ids 必须是逗号分隔的数字") from exc
        if not id_list:
            return {"ok": True, "deleted": 0, "message": "没有选中任何记录"}
        if len(id_list) > 1000:
            raise HTTPException(status_code=400, detail="一次最多删除 1000 条记录")
        stmt = stmt.where(Record.id.in_(id_list))
    elif scope == "before":
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = stmt.where(Record.run_at < cutoff)

    async with session_scope() as session:
        result = await session.execute(stmt)
        count = int(result.rowcount or 0)

    if scope == "ids":
        message = f"已删除选中的 {count} 条记录"
    elif scope == "all" or days <= 0:
        message = f"已清空全部记录（{count} 条）"
    else:
        message = f"已清理 {days} 天前的 {count} 条记录"
    logger.info("删除签到记录：scope=%s days=%s ids=%s -> %s 条", scope, days, ids, count)
    return {"ok": True, "deleted": count, "message": message}
