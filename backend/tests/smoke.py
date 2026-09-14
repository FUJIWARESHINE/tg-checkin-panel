"""后端冒烟测试：建库 → 启动 → 打通关键接口。不依赖真实 Telegram 网络。

用法（在项目根目录）：
    python backend/tests/smoke.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

# 必须在导入 app 之前设置
TMP = Path(tempfile.mkdtemp(prefix="tgcp-smoke-"))
os.environ.setdefault("DATA_DIR", str(TMP))
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "admin123")
os.environ.setdefault("TZ", "Asia/Shanghai")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import session_scope  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Record  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  [OK]   {name}")
    else:
        FAILED.append(f"{name} -> {detail}")
        print(f"  [FAIL] {name}  {detail}")


async def seed_data() -> None:
    """在应用启动前直接写入历史记录，用于验证统计 / 导出 / 时间过滤。

    只写 records，不建 account/task，避免影响后面 id 从 1 开始的断言。
    （SQLite 默认不强制外键，因此 task_id 可以指向不存在的任务。）

    注意：必须在 TestClient 启动之前完成，避免跨事件循环复用 aiosqlite 连接。
    """
    from app.db import init_db

    await init_db()
    now = datetime.now(timezone.utc)
    async with session_scope() as session:
        session.add_all(
            [
                Record(
                    task_id=99,
                    task_name="历史任务",
                    account_id=99,
                    account_name="历史账号",
                    target="@legacybot",
                    trigger="manual",
                    status="success",
                    attempt=1,
                    duration_ms=6400,
                    matched_keyword="签到成功",
                    reply_snippet="签到成功，积分 +12",
                    reward_text="12",
                    run_at=now,
                ),
                Record(
                    task_id=99,
                    task_name="历史任务",
                    account_id=99,
                    account_name="历史账号",
                    target="@legacybot",
                    trigger="retry",
                    status="fail",
                    attempt=2,
                    duration_ms=15000,
                    error="等待回复超时（25s）",
                    run_at=now - timedelta(days=2),
                ),
                Record(
                    task_id=99,
                    task_name="历史任务",
                    account_id=99,
                    account_name="历史账号",
                    target="@legacybot",
                    trigger="schedule",
                    status="success",
                    attempt=1,
                    duration_ms=5200,
                    matched_keyword="已签到",
                    run_at=now - timedelta(days=2, hours=1),
                ),
            ]
        )


def main() -> int:
    print(f"数据目录：{TMP}")
    print("预置历史数据…")
    import asyncio

    asyncio.run(seed_data())
    print("启动应用…\n")

    with TestClient(app) as client:
        print("== 基础 ==")
        r = client.get("/healthz")
        check("GET /healthz", r.status_code == 200 and r.json()["ok"], r.text[:200])
        check("调度器已运行", r.json().get("scheduler") is True, str(r.json()))

        print("\n== 鉴权 ==")
        r = client.get("/api/system/info")
        check("未登录被拒（401）", r.status_code == 401, f"{r.status_code} {r.text[:120]}")

        r = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        check("错误密码被拒", r.status_code == 401, f"{r.status_code}")

        r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        check("登录成功", r.status_code == 200 and r.json()["ok"], r.text[:200])
        check("默认密码被标记", r.json().get("must_change_password") is True, r.text[:120])

        r = client.get("/api/auth/me")
        check("GET /api/auth/me", r.status_code == 200 and r.json()["username"] == "admin", r.text[:200])

        print("\n== 账号 ==")
        r = client.get("/api/accounts")
        check("空账号列表", r.status_code == 200 and r.json() == [], r.text[:200])

        r = client.post(
            "/api/accounts",
            json={
                "name": "测试号",
                "phone": "+8613800000000",
                "api_id": 123456,
                "api_hash": "0123456789abcdef0123456789abcdef",
                "proxy": "",
            },
        )
        check("创建账号", r.status_code == 200 and r.json()["id"] == 1, r.text[:300])
        account_id = r.json()["id"] if r.status_code == 200 else 0
        check("api_hash 已脱敏", r.json().get("api_hash_masked") == "********", r.text[:200])

        print("\n== 任务 ==")
        flow = [
            {"type": "send_text", "text": "/checkin", "delay_after": 1},
            {"type": "wait_reply", "timeout": 20, "match": {"mode": "contains", "keyword": "签到"}},
        ]
        payload = {
            "name": "每日签到",
            "remark": "冒烟测试",
            "account_id": account_id,
            "targets": [{"chat": "@testbot", "thread_id": None}],
            "action_flow": flow,
            "schedule_type": "cron",
            "schedule_value": "0 8 * * *",
            "timezone": "",
            "random_delay_sec": 60,
            "timeout_sec": 120,
            "success_rule": {"mode": "contains", "keywords": ["签到成功", "已签到"]},
            "retry_policy": {"max": 2, "interval_sec": 600, "until_success": False},
            "catch_up": True,
            "notify_channel_ids": [],
            "notify_on": ["success", "fail"],
            "enabled": True,
        }
        r = client.post("/api/tasks", json=payload)
        check("创建任务", r.status_code == 200, r.text[:400])
        task = r.json() if r.status_code == 200 else {}
        check("调度描述生成", bool(task.get("schedule_text")), str(task.get("schedule_text")))
        check("下次执行时间已算", bool(task.get("next_runs")), str(task.get("next_runs"))[:120])

        r = client.get("/api/tasks")
        check("任务列表", r.status_code == 200 and len(r.json()) == 1, r.text[:200])

        r = client.post(f"/api/tasks/{task.get('id')}/toggle", json={"enabled": False})
        check("停用任务", r.status_code == 200 and r.json()["enabled"] is False, r.text[:200])
        r = client.post(f"/api/tasks/{task.get('id')}/toggle", json={"enabled": True})
        check("启用任务", r.status_code == 200 and r.json()["enabled"] is True, r.text[:200])

        print("\n== 调度表达式校验 ==")
        r = client.post(
            "/api/schedule/preview", json={"schedule_type": "cron", "schedule_value": "0 8 * * *"}
        )
        check("cron 预览", r.json().get("ok") is True, r.text[:200])
        r = client.post(
            "/api/schedule/preview", json={"schedule_type": "interval", "schedule_value": "12h"}
        )
        check("interval 预览", r.json().get("ok") is True, r.text[:200])
        r = client.post(
            "/api/schedule/preview", json={"schedule_type": "cron", "schedule_value": "not a cron"}
        )
        check("非法 cron 被拦", r.json().get("ok") is False, r.text[:200])

        r = client.post(
            "/api/tasks",
            json={**payload, "name": "非法任务", "action_flow": [{"type": "不存在的动作"}]},
        )
        check("非法动作类型被拒（422）", r.status_code == 422, f"{r.status_code}")

        r = client.post("/api/tasks", json={**payload, "name": "非法调度", "schedule_type": "cron", "schedule_value": "99 99 * * *"})
        check("非法 cron 创建被拒（422）", r.status_code == 422, f"{r.status_code}")

        print("\n== 模板 ==")
        r = client.post(
            "/api/templates",
            json={
                "name": "标准文字签到",
                "description": "发指令等待回复",
                "action_flow": flow,
                "success_rule": {"mode": "contains", "keywords": ["签到成功"]},
                "retry_policy": {"max": 3, "interval_sec": 3600, "until_success": False},
            },
        )
        check("创建模板", r.status_code == 200, r.text[:300])

        print("\n== 推送渠道 ==")
        r = client.get("/api/notify/types")
        check("渠道类型元数据", r.status_code == 200 and "telegram" in r.json()["types"], r.text[:200])

        r = client.post(
            "/api/notify",
            json={
                "name": "我的 TG 通知",
                "type": "telegram",
                "config": {"bot_token": "123456:ABCDEFGHIJKLMNOP", "chat_id": "99887766"},
                "enabled": True,
                "on_events": ["success", "fail"],
                "quiet_start": "",
                "quiet_end": "",
                "quiet_only_fail": True,
            },
        )
        check("创建渠道", r.status_code == 200, r.text[:300])
        check("token 已脱敏", r.json().get("config_masked", {}).get("bot_token") == "********", r.text[:300])

        r = client.get("/api/notify")
        check("渠道列表", r.status_code == 200 and len(r.json()) == 1, r.text[:200])

        print("\n== 记录与统计 ==")
        r = client.get("/api/records?page=1&page_size=10")
        data = r.json() if r.status_code == 200 else {}
        check("记录分页 total=3", data.get("total") == 3, r.text[:200])
        check("按时间倒序返回", data.get("items", [{}])[0].get("status") == "success", str(data)[:200])

        r = client.get("/api/records?status=fail")
        check("按状态过滤", r.json().get("total") == 1, r.text[:200])
        r = client.get("/api/records?keyword=积分")
        check("按关键词过滤", r.json().get("total") == 1, r.text[:200])
        r = client.get(f"/api/records?task_id=99")
        check("按任务过滤", r.json().get("total") == 3, r.text[:200])

        start = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
        r = client.get("/api/records", params={"start": start})
        check("按时间范围过滤（近 6 小时）", r.json().get("total") == 1, r.text[:200])

        r = client.get("/api/records/stats?days=30")
        stats = r.json() if r.status_code == 200 else {}
        check("统计 heatmap 长度 30", len(stats.get("heatmap", [])) == 30, str(stats)[:200])
        check("今日成功数 = 1", stats.get("today_success") == 1, str(stats)[:200])
        check("今日失败数 = 0", stats.get("today_fail") == 0, str(stats)[:200])
        check("7 天成功率 = 66.7%", stats.get("success_rate_7d") == 66.7, str(stats.get("success_rate_7d")))
        check(
            "heatmap 正确按天聚合（今天 success=1）",
            stats.get("heatmap", [])[-1].get("success") == 1,
            str(stats.get("heatmap", [])[-1:]),
        )

        r = client.get("/api/records/export")
        check("CSV 导出 content-type", "text/csv" in r.headers.get("content-type", ""), r.headers.get("content-type", ""))
        check("CSV 含中文内容", "签到成功" in r.text and "历史任务" in r.text, r.text[:200])
        check("CSV 带 BOM（Excel 不乱码）", r.text.startswith("\ufeff"), repr(r.text[:8]))

        r = client.delete("/api/records?days=1")
        check("清理 1 天前记录（删 2 条）", r.json().get("deleted") == 2, r.text[:200])
        r = client.get("/api/records")
        check("清理后剩 1 条", r.json().get("total") == 1, r.text[:200])

        print("\n== 记录删除（删除选中 / 清空全部）==")
        r = client.delete("/api/records", params={"scope": "ids", "ids": "abc"})
        check("非法 ids 被拒（400）", r.status_code == 400, f"{r.status_code} {r.text[:120]}")

        r = client.delete("/api/records", params={"scope": "ids", "ids": ""})
        check("未选中任何记录时删除 0 条", r.json().get("deleted") == 0, r.text[:200])
        check("未选中时记录未被误删", client.get("/api/records").json().get("total") == 1, "")

        r = client.delete("/api/records", params={"scope": "ids", "ids": "999999"})
        check("删除不存在的 id 返回 0 条", r.json().get("deleted") == 0, r.text[:200])

        selected = [item["id"] for item in client.get("/api/records").json()["items"]]
        r = client.delete("/api/records", params={"scope": "ids", "ids": ",".join(map(str, selected))})
        check("删除选中的记录", r.json().get("deleted") == len(selected), r.text[:200])
        check("选中删除后记录清空", client.get("/api/records").json().get("total") == 0, "")

        r = client.delete("/api/records", params={"scope": "all"})
        check("清空全部（空库返回 0 条）", r.json().get("deleted") == 0, r.text[:200])

        print("\n== 系统 ==")
        r = client.get("/api/system/info")
        info = r.json() if r.status_code == 200 else {}
        check("系统信息", r.status_code == 200 and info.get("tasks_total") == 1, r.text[:300])
        check("调度任务已注册", info.get("scheduler_running") is True, str(info)[:200])

        r = client.get("/api/system/scheduler")
        check("调度器状态", r.status_code == 200 and r.json()["job_count"] >= 1, r.text[:300])

        r = client.get("/api/system/logs?limit=10")
        check("日志读取", r.status_code == 200 and len(r.json()["items"]) > 0, r.text[:200])

        r = client.put("/api/system/settings", json={"tg_proxy": "socks5://127.0.0.1:7890"})
        check("保存全局代理", r.status_code == 200, r.text[:300])
        r = client.put("/api/system/settings", json={"tg_proxy": "这不是代理"})
        check("非法代理被拒", r.status_code == 400, f"{r.status_code}")
        r = client.put("/api/system/settings", json={"timezone": "Not/AZone"})
        check("非法时区被拒", r.status_code == 400, f"{r.status_code}")

        r = client.post("/api/system/scheduler/rebuild")
        check("重建调度", r.status_code == 200, r.text[:200])

        print("\n== 密码 ==")
        r = client.post("/api/auth/password", json={"old_password": "admin123", "new_password": "newpass123"})
        check("修改密码", r.status_code == 200, r.text[:200])
        r = client.get("/api/auth/me")
        check("默认密码标记已清除", r.json().get("must_change_password") is False, r.text[:200])

        print("\n== 加密往返 ==")
        from app.security import decrypt, encrypt

        secret = "super-secret-token-12345"
        check("Fernet 加解密往返", decrypt(encrypt(secret)) == secret)
        check("非加密串原样返回", decrypt("plain-text") == "plain-text")

        print("\n== 前端静态托管 ==")
        from app.main import STATIC_DIR

        if not (STATIC_DIR / "index.html").exists():
            print("  (跳过：backend/static 不存在，需先 npm run build 并复制 dist)")
        else:
            r = client.get("/")
            check("GET / 返回 SPA", r.status_code == 200 and 'id="app"' in r.text, r.text[:150])
            r = client.get("/login")
            check("前端路由回退到 index.html", r.status_code == 200 and 'id="app"' in r.text, r.text[:150])
            asset = sorted((STATIC_DIR / "assets").glob("index-*.js"))[0].name
            r = client.get(f"/assets/{asset}")
            check("静态资源可访问", r.status_code == 200, f"{r.status_code} {asset}")
            r = client.get("/api/不存在的接口")
            check("未知 /api 路径返回 404 而非 HTML", r.status_code == 404, f"{r.status_code} {r.text[:80]}")
            r = client.get("/../.master_key")
            check("目录穿越被拦截", r.status_code in (200, 404) and b"enc::" not in r.content, str(r.status_code))
            r = client.get("/healthz")
            check("静态托管后 /healthz 仍可用", r.status_code == 200 and r.json()["ok"], r.text[:120])

        print("\n== 清理 ==")
        r = client.post(f"/api/accounts/{account_id}/check")
        check("未登录账号检测报错而非崩溃", r.status_code == 400, f"{r.status_code} {r.text[:120]}")

    print("\n" + "=" * 62)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    for item in FAILED:
        print(f"  ✗ {item}")
    print("=" * 62)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
