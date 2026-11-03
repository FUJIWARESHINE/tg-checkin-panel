"""多账号任务回归测试：一个任务同时用两个账号签到同一个机器人。

不依赖真实 Telegram：把 `runner` 里的连接池 / 动作流 / peer 换算换成假实现，
验证「一个任务 N 个账号」在接口层、执行层、记录层、重试与补跑层都符合预期。

用法（项目根目录）：
    python backend/tests/multi_account.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

try:  # Windows 控制台默认 GBK，中文/符号输出会炸
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

# 必须在导入 app 之前设置
TMP = Path(tempfile.mkdtemp(prefix="tgcp-multi-"))
os.environ["DATA_DIR"] = str(TMP)
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "admin123")
os.environ.setdefault("TZ", "Asia/Shanghai")

import httpx  # noqa: E402

from app.core import runner  # noqa: E402
from app.core import scheduler as sched  # noqa: E402
from app.core.actions import StepError  # noqa: E402
from app.core.client_pool import TelegramCallError  # noqa: E402
from app.main import app  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  [OK]   {name}")
    else:
        FAILED.append(f"{name} -> {detail}")
        print(f"  [FAIL] {name}  {detail}")


# ---------------------------------------------------------------- 假 Telegram


class FakeRaw:
    """伪装 Telethon 客户端，只提供动作流需要的 get_entity。"""

    def get_entity(self, chat: str) -> object:
        return SimpleNamespace(id=chat)


class FakeAcct:
    def __init__(self, account_id: int, dead: bool = False) -> None:
        self.account_id = account_id
        self.dead = dead

    async def start(self) -> FakeRaw:
        if self.dead:
            raise TelegramCallError("该账号 session 未登录", kind="auth")
        return FakeRaw()

    async def call(self, func, *args, **kwargs):  # noqa: ANN001
        return func(*args, **kwargs)


class FakePool:
    def __init__(self) -> None:
        self.acquired: list[int] = []
        self.released: list[int] = []
        self.dead_accounts: set[int] = set()

    async def acquire(self, account_id: int, *_args, **_kwargs) -> FakeAcct:
        self.acquired.append(account_id)
        return FakeAcct(account_id, dead=account_id in self.dead_accounts)

    async def release(self, account_id: int) -> None:
        self.released.append(account_id)


class FakeFlow:
    """记录每个账号被跑了几次，并可按账号制造失败。"""

    def __init__(self) -> None:
        self.calls: list[int] = []
        self.fail_accounts: set[int] = set()

    async def __call__(self, ctx, *_args, **_kwargs) -> None:  # noqa: ANN001
        account_id = ctx.acct.account_id
        self.calls.append(account_id)
        if account_id in self.fail_accounts:
            raise StepError("机器人没有返回签到结果", step_index=1, step_type="wait_reply")
        ctx.reply_text = "签到成功，积分 +12"
        ctx.matched_keyword = "签到成功"
        ctx.reward_text = "12"
        ctx.note(0, "send_text", "/checkin")


def install_fakes() -> tuple[FakePool, FakeFlow]:
    fake_pool = FakePool()
    fake_flow = FakeFlow()
    runner.pool = fake_pool  # type: ignore[assignment]
    runner.run_flow = fake_flow  # type: ignore[assignment]
    runner.tg_utils = SimpleNamespace(get_peer_id=lambda entity: 10086)  # type: ignore[assignment]
    return fake_pool, fake_flow


# ---------------------------------------------------------------- 用例


def check_migration() -> None:
    """老库（tasks 没有 account_ids 列）升级后要能自动补列并回填。"""
    print("== 数据库迁移：老任务自动回填 account_ids ==")
    import sqlite3

    from sqlalchemy import create_engine

    from app.db import _migrate

    legacy = TMP / "legacy.db"
    with sqlite3.connect(legacy) as raw:
        raw.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, account_id INTEGER)")
        raw.execute("INSERT INTO tasks (id, account_id) VALUES (1, 7)")
        raw.execute("INSERT INTO tasks (id, account_id) VALUES (2, 8)")
        raw.commit()

    engine = create_engine(f"sqlite:///{legacy.as_posix()}")
    with engine.begin() as conn:
        _migrate(conn)
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(tasks)").fetchall()}
        rows = dict(conn.exec_driver_sql("SELECT id, account_ids FROM tasks").fetchall())
    engine.dispose()

    check("已补出 account_ids 列", "account_ids" in columns, str(columns))
    check("老任务回填为 [account_id]", rows == {1: "[7]", 2: "[8]"}, str(rows))


async def main() -> int:
    print(f"数据目录：{TMP}")
    check_migration()
    fake_pool, fake_flow = install_fakes()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            print("\n== 准备：登录 + 两个账号 ==")
            r = await client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
            check("管理员登录", r.status_code == 200 and r.json()["ok"], r.text[:200])

            account_ids: list[int] = []
            for name in ("大号", "小号"):
                r = await client.post(
                    "/api/accounts",
                    json={
                        "name": name,
                        "phone": f"+861380000000{len(account_ids) + 1}",
                        "api_id": 123456,
                        "api_hash": "0123456789abcdef0123456789abcdef",
                    },
                )
                if r.status_code == 200:
                    account_ids.append(r.json()["id"])
            check("创建两个账号", len(account_ids) == 2, str(account_ids))
            big, small = account_ids[0], account_ids[1]

            flow = [
                {"type": "send_text", "text": "/checkin", "delay_after": 1},
                {"type": "wait_reply", "timeout": 20, "match": {"mode": "contains", "keyword": "签到"}},
            ]
            payload = {
                "name": "多账号同机器人签到",
                "remark": "两个号签同一个 bot",
                "account_ids": [big, small],
                "targets": [{"chat": "@samebot", "thread_id": None}],
                "action_flow": flow,
                "schedule_type": "cron",
                "schedule_value": "0 8 * * *",
                "timezone": "",
                "random_delay_sec": 0,
                "timeout_sec": 120,
                "success_rule": {"mode": "contains", "keywords": ["签到成功", "已签到"]},
                "retry_policy": {"max": 2, "interval_sec": 600, "until_success": False},
                "catch_up": False,
                "notify_channel_ids": [],
                "notify_on": ["success", "fail"],
                "enabled": True,
            }

            print("\n== 创建任务时就多选账号 ==")
            r = await client.post("/api/tasks", json=payload)
            task = r.json() if r.status_code == 200 else {}
            task_id = task.get("id")
            check("创建多账号任务", r.status_code == 200, r.text[:400])
            check("account_ids 完整保存", task.get("account_ids") == [big, small], str(task.get("account_ids")))
            check("account_id 落到第一个账号", task.get("account_id") == big, str(task.get("account_id")))
            check(
                "account_names 返回两个昵称",
                task.get("account_names") == ["大号", "小号"],
                str(task.get("account_names")),
            )

            r = await client.get(f"/api/tasks/{task_id}")
            check("详情携带多账号", r.json().get("account_ids") == [big, small], r.text[:300])

            r = await client.get("/api/tasks")
            check("列表携带多账号", r.json()[0].get("account_names") == ["大号", "小号"], r.text[:300])

            r = await client.post("/api/tasks", json={**payload, "name": "坏账号", "account_ids": [big, 999999]})
            check("不存在的账号被拒（400）", r.status_code == 400, f"{r.status_code} {r.text[:200]}")

            r = await client.post("/api/tasks", json={**payload, "name": "空账号", "account_ids": []})
            check("空账号列表被拒（422）", r.status_code == 422, f"{r.status_code}")

            r = await client.post(
                "/api/tasks",
                json={**payload, "name": "老客户端", "account_ids": [], "account_id": big},
            )
            check(
                "只传 account_id 仍兼容",
                r.status_code == 200 and r.json().get("account_ids") == [big],
                r.text[:300],
            )
            legacy_id = r.json().get("id") if r.status_code == 200 else None

            print("\n== 执行：一个任务两个账号 ==")
            fake_pool.acquired.clear()
            fake_flow.calls.clear()
            result = await runner.execute_task(task_id, trigger="manual", force=True)
            check("执行结果 ok", result.get("ok") is True, str(result)[:300])
            check("两个账号都被执行", fake_pool.acquired == [big, small], str(fake_pool.acquired))
            check("两个账号各跑一次动作流", fake_flow.calls == [big, small], str(fake_flow.calls))
            check("返回按账号分组的结果", len(result.get("accounts", [])) == 2, str(result)[:300])

            r = await client.get("/api/records", params={"task_id": task_id})
            items = r.json().get("items", [])
            check("两个账号各落一条记录", len(items) == 2, str(len(items)))
            check(
                "记录里区分账号",
                sorted(i["account_name"] for i in items) == ["大号", "小号"],
                str([i["account_name"] for i in items]),
            )
            check("记录目标为同一个机器人", all(i["target"] == "@samebot" for i in items), "target")
            check("记录都判定成功", all(i["status"] == "success" for i in items), str([i["status"] for i in items]))

            r = await client.get(f"/api/tasks/{task_id}")
            check("任务整体状态为成功", r.json().get("last_status") == "success", r.text[:300])
            check("任务消息提到账号数", "2 个账号" in (r.json().get("last_message") or ""), r.json().get("last_message"))

            print("\n== 非强制执行：两个账号都成功后整体跳过 ==")
            fake_pool.acquired.clear()
            result = await runner.execute_task(task_id, trigger="catchup", force=False)
            check("整体跳过", result.get("skipped") is True, str(result)[:200])
            check("没有重复登录账号", fake_pool.acquired == [], str(fake_pool.acquired))

            print("\n== 改一个账号的成功记录来实现「今天还没签到」状态 ==")
            stale = [
                i["id"]
                for i in items
                if i["account_name"] == "小号" and i["status"] == "success"
            ]
            r = await client.delete("/api/records", params={"scope": "ids", "ids": ",".join(map(str, stale))})
            check("删掉小号今日成功记录", r.json().get("deleted") == len(stale), r.text[:200])
            r = await client.get(f"/api/records", params={"task_id": task_id})
            check("只剩大号的成功记录", r.json().get("total") == 1, r.text[:200])

            print("\n== 只有一个账号成功时：只重试失败的那个 ==")
            fake_flow.fail_accounts = {small}
            fake_pool.acquired.clear()
            result = await runner.execute_task(task_id, trigger="manual", force=True)
            check("任务整体失败", result.get("ok") is False, str(result)[:300])
            failed = [a for a in result.get("accounts", []) if not a["ok"]]
            check("只有小号失败", [a["account_id"] for a in failed] == [small], str(result.get("accounts"))[:300])

            job = sched.scheduler.get_job(f"retry:{task_id}")
            check("已挂重试任务", job is not None, "retry job 缺失")
            check(
                "重试只带失败账号",
                job is not None and job.kwargs.get("account_ids") == [small],
                str(job.kwargs) if job else "",
            )
            sched.remove_task(task_id)

            print("\n== 非强制补跑：只补今天没成功的账号 ==")
            fake_flow.fail_accounts = set()
            fake_pool.acquired.clear()
            result = await runner.execute_task(task_id, trigger="catchup", force=False)
            check("补跑只跑小号", fake_pool.acquired == [small], str(fake_pool.acquired))
            check("补跑后整体成功", result.get("ok") is True, str(result)[:200])

            print("\n== 账号登录失效：只挂掉一个号，另一个号照常签到 ==")
            fake_pool.dead_accounts = {small}
            fake_flow.fail_accounts = set()
            fake_pool.acquired.clear()
            result = await runner.execute_task(task_id, trigger="manual", force=True)
            check("账号级失败不会拖垮整个任务", fake_pool.acquired == [big, small], str(fake_pool.acquired))
            check("任务整体判失败", result.get("ok") is False, str(result)[:200])
            check(
                "另一个账号仍然成功",
                [a["account_id"] for a in result.get("accounts", []) if a["ok"]] == [big],
                str(result.get("accounts"))[:300],
            )
            r = await client.get("/api/records", params={"task_id": task_id, "status": "fail"})
            fails = r.json().get("items", [])
            latest = fails[0] if fails else {}
            check("最新失败记录属于小号", latest.get("account_name") == "小号", str(latest)[:250])
            check(
                "失败原因是账号级异常",
                "session" in (latest.get("error") or ""),
                str(latest.get("error"))[:200],
            )
            accounts_now = {a["name"]: a["status"] for a in (await client.get("/api/accounts")).json()}
            check("失效账号被标记 need_login", accounts_now.get("小号") == "need_login", str(accounts_now))
            sched.remove_task(task_id)
            fake_pool.dead_accounts = set()

            print("\n== 编辑任务：改账号列表 ==")
            r = await client.put(
                f"/api/tasks/{task_id}",
                json={**payload, "account_ids": [small]},
            )
            updated = r.json()
            check("改成单账号", r.status_code == 200 and updated.get("account_ids") == [small], r.text[:300])
            check("主账号同步切换", updated.get("account_id") == small, str(updated.get("account_id")))
            check("昵称只剩一个", updated.get("account_names") == ["小号"], str(updated.get("account_names")))

            r = await client.put(f"/api/tasks/{task_id}", json=payload)
            check("改回两个账号", r.json().get("account_ids") == [big, small], r.text[:300])

            print("\n== 删除账号：多账号任务自动摘除，唯一账号则拦住 ==")
            r = await client.delete(f"/api/accounts/{small}")
            check("删除多账号任务里的账号", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
            r = await client.get(f"/api/tasks/{task_id}")
            check("任务自动只剩大号", r.json().get("account_ids") == [big], r.text[:300])
            check("主账号回落到大号", r.json().get("account_id") == big, r.text[:200])

            r = await client.delete(f"/api/accounts/{big}")
            check("唯一账号被拦住（400）", r.status_code == 400, f"{r.status_code} {r.text[:200]}")
            check("提示里带上任务名", "多账号同机器人签到" in r.text, r.text[:200])

            print("\n== 清理 ==")
            if legacy_id:
                r = await client.delete(f"/api/tasks/{legacy_id}")
                check("删除历史兼容任务", r.status_code == 200, r.text[:200])
            r = await client.delete(f"/api/tasks/{task_id}")
            check("删除多账号任务", r.status_code == 200, r.text[:200])
            r = await client.delete(f"/api/accounts/{big}")
            check("任务删掉后账号可删除", r.status_code == 200, f"{r.status_code} {r.text[:200]}")

    print("\n" + "=" * 62)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    for item in FAILED:
        print(f"  [x] {item}")
    print("=" * 62)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
