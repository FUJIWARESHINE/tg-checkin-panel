"""通知链路回归测试：多账号 / 任务级订阅 / 未配渠道 / 渠道事件过滤 / 失败降噪。

不依赖真实 Telegram 网络：
  - 用假 webhook 适配器记录"到底发出去了几条"
  - 用假 `runner._run_account` 直接给出每个账号的成功/失败结果

用法（在项目根目录）：
    python backend/tests/notify_chain.py
"""

from __future__ import annotations

import functools
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

TMP = Path(tempfile.mkdtemp(prefix="tgcp-notify-"))
os.environ.setdefault("DATA_DIR", str(TMP))
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "admin123")
os.environ.setdefault("TZ", "Asia/Shanghai")

from fastapi.testclient import TestClient  # noqa: E402

from app.core import notifier, runner  # noqa: E402
from app.main import app  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []
SENT: list[dict] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  [OK]   {name}")
    else:
        FAILED.append(f"{name} -> {detail}")
        print(f"  [FAIL] {name}  {detail}")


async def _fake_adapter(cfg: dict, msg) -> str:
    SENT.append(
        {
            "event": msg.event,
            "task": msg.task_name,
            "fields": dict(msg.fields),
            "extra": msg.extra,
            "reply": msg.reply,
            "text": msg.as_text(),
        }
    )
    return "ok"


notifier.ADAPTERS["webhook"] = _fake_adapter

OUTCOMES: dict[int, bool] = {}
OK_REPLY = "签到成功！今日获得 12 积分，连续签到 5 天"
FAIL_REPLY = "服务器繁忙，请稍后再试（错误码 503）"


async def _fake_run_account(task, account, targets, *, trigger, attempt):
    """替身：不连 Telegram，直接给出结果并落执行记录（和真实执行一样写库）。"""
    ok = OUTCOMES.get(account.id, True)
    reply = OK_REPLY if ok else FAIL_REPLY
    record_ids: list[int] = []
    for item in targets:
        record_ids.append(
            await runner._save_record(
                task_id=task.id,
                task_name=task.name,
                account_id=account.id,
                account_name=account.name,
                target=str(item.get("chat")),
                trigger=trigger,
                status="success" if ok else "fail",
                attempt=attempt,
                duration_ms=9000,
                matched_keyword="签到成功" if ok else "",
                reply_snippet=reply,
                error="" if ok else "未收到签到成功回复",
                detail={"fake": True},
            )
        )
    return {
        "account_id": account.id,
        "account_name": account.name,
        "ok": ok,
        "error": "" if ok else "未收到签到成功回复",
        "matched": "签到成功" if ok else "",
        "reward": "",
        "duration_ms": 9000,
        "targets": [
            {"target": str(t.get("chat")), "ok": ok, "error": "", "duration_ms": 9000} for t in targets
        ],
        "reply": runner._compose_reply(
            [(str(t.get("chat")), reply, ok) for t in targets], multi=len(targets) > 1
        ),
        "record_ids": record_ids,
    }


runner._run_account = _fake_run_account


def reset() -> None:
    SENT.clear()
    notifier._dedup = notifier._Dedup()


def wait_until_idle(timeout: float = 10.0) -> None:
    """等后台执行的签到任务跑完：先等它真的开跑，再等它结束。"""
    deadline = time.time() + timeout
    seen_running = False
    while time.time() < deadline:
        if runner._running:
            seen_running = True
        elif seen_running:
            time.sleep(0.2)  # 推送在任务协程里完成，留一点收尾时间
            return
        else:
            time.sleep(0.02)
            continue
        time.sleep(0.05)


def run_task(client, task_id: int) -> None:
    """同步等任务执行完：直接借应用的事件循环跑，避免与断言抢跑。"""
    portal = getattr(client, "portal", None)
    if portal is not None:
        portal.call(functools.partial(runner.execute_task, task_id, trigger="manual"))
        return
    client.post(f"/api/tasks/{task_id}/run", json={"force": True})
    wait_until_idle()


def account_payload(name: str) -> dict:
    return {
        "name": name,
        "phone": "+8613800000001",
        "api_id": 123456,
        "api_hash": "0123456789abcdef0123456789abcdef",
    }


def task_payload(name: str, accounts: list[int], channels: list[int], notify_on: list[str]) -> dict:
    return {
        "name": name,
        "account_ids": accounts,
        "targets": [{"chat": "@testbot", "thread_id": None}],
        "action_flow": [
            {"type": "send_text", "text": "/checkin", "delay_after": 1},
            {"type": "wait_reply", "timeout": 20, "match": {"mode": "contains", "keyword": "签到"}},
        ],
        "schedule_type": "cron",
        "schedule_value": "0 8 * * *",
        "timezone": "",
        "random_delay_sec": 0,
        "timeout_sec": 120,
        "success_rule": {"mode": "contains", "keywords": ["签到成功"]},
        "retry_policy": {"max": 0, "interval_sec": 600, "until_success": False},
        "catch_up": False,
        "notify_channel_ids": channels,
        "notify_on": notify_on,
        "enabled": True,
    }


ALL_EVENTS = ["success", "fail", "auth_expired"]


def main() -> int:
    print(f"数据目录：{TMP}")
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})

        a1 = client.post("/api/accounts", json=account_payload("小号")).json()["id"]
        a2 = client.post("/api/accounts", json=account_payload("主号")).json()["id"]

        chan = client.post(
            "/api/notify",
            json={
                "name": "测试渠道",
                "type": "webhook",
                "config": {"url": "https://example.invalid/hook"},
                "enabled": True,
                "on_events": [],
                "quiet_start": "",
                "quiet_end": "",
                "quiet_only_fail": True,
            },
        ).json()["id"]

        # ------------------------------------------------------------ 1
        print("\n== 场景 1：多账号成功，应各推一条 ==")
        reset()
        OUTCOMES.update({a1: True, a2: True})
        t1 = client.post("/api/tasks", json=task_payload("多号成功任务", [a1, a2], [chan], ALL_EVENTS)).json()
        client.post(f"/api/tasks/{t1['id']}/run", json={"force": True})
        wait_until_idle()
        check("2 个账号成功 → 2 条通知", len(SENT) == 2, f"实际 {len(SENT)} 条：{[m['fields'].get('账号') for m in SENT]}")
        check("通知事件均为 success", all(m["event"] == "success" for m in SENT), str([m["event"] for m in SENT]))
        check(
            "成功通知带机器人原文",
            all(OK_REPLY in m["reply"] for m in SENT),
            str([m["reply"] for m in SENT])[:200],
        )
        check(
            "成功通知正文含「返回内容」",
            all("返回内容" in m["text"] and OK_REPLY in m["text"] for m in SENT),
            str([m["text"] for m in SENT])[:200],
        )

        # ------------------------------------------------------------ 2
        print("\n== 场景 2：多账号失败，应各推一条失败通知 ==")
        reset()
        OUTCOMES.update({a1: False, a2: False})
        t2 = client.post("/api/tasks", json=task_payload("多号失败任务", [a1, a2], [chan], ALL_EVENTS)).json()
        run_task(client, t2["id"])
        check("2 个账号失败 → 2 条通知", len(SENT) == 2, f"实际 {len(SENT)} 条：{[m['fields'].get('账号') for m in SENT]}")
        check("通知事件均为 fail", all(m["event"] == "fail" for m in SENT), str([m["event"] for m in SENT]))
        check(
            "失败通知带机器人原文",
            all(FAIL_REPLY in m["reply"] for m in SENT),
            str([m["reply"] for m in SENT])[:200],
        )
        check(
            "失败通知带「失败原因」",
            all(m["fields"].get("失败原因") for m in SENT),
            str([m["fields"] for m in SENT])[:200],
        )

        # ------------------------------------------------------------ 3
        print("\n== 场景 3：任务只订阅 success，失败时不应推送 ==")
        reset()
        OUTCOMES.update({a1: False, a2: False})
        t3 = client.post(
            "/api/tasks", json=task_payload("只订成功任务", [a1], [chan], ["success"])
        ).json()
        run_task(client, t3["id"])
        check("只订阅 success 时失败不推送", len(SENT) == 0, f"实际 {len(SENT)} 条")

        # ------------------------------------------------------------ 4
        print("\n== 场景 4：任务没选推送渠道，应留痕而不是静默 ==")
        reset()
        OUTCOMES.update({a1: True})
        t4 = client.post("/api/tasks", json=task_payload("未配渠道任务", [a1], [], ALL_EVENTS)).json()
        run_task(client, t4["id"])
        check("未配渠道 → 不推送", len(SENT) == 0, f"实际 {len(SENT)} 条")
        logs = client.get("/api/system/logs", params={"limit": 300}).json().get("items", [])
        text = "\n".join(str(item.get("message", "")) for item in logs)
        check("未配渠道 → 日志有 WARNING 留痕", "未配置推送渠道" in text, text[-400:])

        # ------------------------------------------------------------ 5
        print("\n== 场景 5：渠道不订阅 success，成功时不应推送 ==")
        reset()
        chan2 = client.post(
            "/api/notify",
            json={
                "name": "只收失败渠道",
                "type": "webhook",
                "config": {"url": "https://example.invalid/hook"},
                "enabled": True,
                "on_events": ["fail"],
                "quiet_start": "",
                "quiet_end": "",
                "quiet_only_fail": True,
            },
        ).json()["id"]
        OUTCOMES.update({a1: True})
        t5 = client.post("/api/tasks", json=task_payload("渠道过滤任务", [a1], [chan2], ALL_EVENTS)).json()
        run_task(client, t5["id"])
        check("渠道未订阅 success → 不推送", len(SENT) == 0, f"实际 {len(SENT)} 条")

        # ------------------------------------------------------------ 6
        print("\n== 场景 6：执行记录里能看出到底推送了没有 ==")
        rows = client.get("/api/records", params={"page_size": 50}).json().get("items", [])
        marked = [r for r in rows if r.get("notify_status")]
        check("执行记录带通知状态", len(marked) > 0, f"{len(rows)} 条记录里 0 条有 notify_status")
        statuses = {r["notify_status"] for r in marked}
        print(f"        通知状态取值：{sorted(statuses)}")
        check(
            "未配渠道的记录标记为 skip:no-channel",
            any(r["notify_status"] == "skip:no-channel" for r in marked),
            str(sorted(statuses)),
        )

        # ------------------------------------------------------------ 7
        print("\n== 场景 7：降噪不能跨账号 / 跨天误吞 ==")
        dedup = notifier._Dedup()
        day1 = "2026-11-04"
        check("账号A 首失败推送", dedup.should_send("t1:a1", "fail", day=day1)[0] is True)
        check(
            "账号B 首失败也推送（不被账号A的连续失败吞掉）",
            dedup.should_send("t1:a2", "fail", day=day1)[0] is True,
        )
        check("账号A 第 2 次失败降噪", dedup.should_send("t1:a1", "fail", day=day1)[0] is False)
        check(
            "隔天首失败重新推送（不继承昨天的连续失败计数）",
            dedup.should_send("t1:a1", "fail", day="2026-11-05")[0] is True,
        )
        dedup.should_send("t1:a1", "fail", day="2026-11-05")
        ok, note = dedup.should_send("t1:a1", "success", day="2026-11-05")
        check("成功后恢复正常并带恢复提示", ok is True and "恢复" in note, note)

        # ------------------------------------------------------------ 8
        print("\n== 场景 8：通知链路自检接口 ==")
        r = client.get("/api/notify/diagnose")
        data = r.json() if r.status_code == 200 else {}
        check("自检接口可用", r.status_code == 200 and data.get("ok") is True, r.text[:300])
        tasks = data.get("tasks", [])
        bad = [t for t in tasks if t.get("id") == t4["id"]]
        check("自检能指出未配渠道的任务", bool(bad) and any("渠道" in p for p in bad[0].get("problems", [])), str(bad)[:300])

        # ------------------------------------------------------------ 9
        print("\n== 场景 9：启用中却没有注册调度（任务不会跑、自然也没通知）==")
        from app.core import scheduler as sched

        sched.remove_task(t5["id"])
        listed = {t["id"]: t for t in client.get("/api/tasks").json()}
        check(
            "任务列表里该任务算不出下次执行时间",
            listed.get(t5["id"], {}).get("next_run_at") is None,
            str(listed.get(t5["id"], {}).get("next_run_at")),
        )
        data = client.get("/api/notify/diagnose").json()
        row = next((t for t in data.get("tasks", []) if t["id"] == t5["id"]), None)
        check(
            "自检报出未调度任务",
            row is not None and row["scheduled"] is False and any("调度" in p for p in row["problems"]),
            str(row)[:300],
        )

        # ------------------------------------------------------------ 10
        print("\n== 场景 10：推送正文渲染（成功带原文 / 失败带原因）==")
        ok_msg = notifier.build_message(
            event="success",
            task_name="演示任务",
            account_name="小号",
            target="@bot",
            duration_ms=9000,
            attempt=1,
            matched_keyword="签到成功",
            reply="签到成功\n今日 +12 积分",
        )
        ok_text = ok_msg.as_text()
        check("成功正文含返回内容", "返回内容：" in ok_text and "今日 +12 积分" in ok_text, ok_text)
        check("成功正文不出现失败原因", "失败原因" not in ok_text)
        check("HTML 把原文放进等宽块", "<pre>" in ok_msg.as_html() and "今日 +12 积分" in ok_msg.as_html())
        check("HTML 转义原文里的尖括号", "<script>" not in notifier.build_message(
            event="success", task_name="t", reply="<script>alert(1)</script>"
        ).as_html())
        check("Markdown 渲染含原文", "今日 +12 积分" in ok_msg.as_markdown())

        fail_msg = notifier.build_message(
            event="fail", task_name="演示任务", error="等待回复超时（30s）", reply=FAIL_REPLY
        )
        fail_text = fail_msg.as_text()
        check("失败正文带失败原因", "失败原因：等待回复超时（30s）" in fail_text, fail_text)
        check("失败正文带返回内容", FAIL_REPLY in fail_text, fail_text)
        check("超长原文被截断", len(notifier.clean_reply("长" * 2000)) <= notifier.REPLY_LIMIT + 20)
        check(
            "多目标优先展示失败目标的原文",
            runner._compose_reply([("@a", "成功文案", True), ("@b", "失败文案", False)], multi=True)
            == "【@b】\n失败文案",
        )
        check("没有原文时不塞空块", runner._compose_reply([("@a", "", True)]) == "")
        check("多条回复按顺序合并", runner._join_replies(["签到成功", "获得 12 积分"]) == "签到成功\n获得 12 积分")
        check("多条回复只保留最后三条", runner._join_replies(["a", "b", "c", "d"]) == "b\nc\nd")
        check("单条回复不加前缀", runner._join_replies(["签到成功"]) == "签到成功")

    print("\n" + "=" * 62)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    for item in FAILED:
        print(f"  x {item}")
    print("=" * 62)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
