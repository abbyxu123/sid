"""Decision Ledger：append-only JSONL + SQLite 索引。

所有输入、Agent 输出、工具调用、确认、错误、反馈都写进来；
记忆猫读近期记录，对照实验和证据面板从这里导出。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class Ledger:
    def __init__(self, data_dir: str | Path = "data"):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = self.dir / "ledger.jsonl"
        self._lock = threading.Lock()
        # FastAPI 线程池里跨线程访问；写入由 _lock 串行化
        self.db = sqlite3.connect(self.dir / "ledger.db", check_same_thread=False)
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                session_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL
            )"""
        )
        self.db.commit()

    def append(self, session_id: str, kind: str, payload: dict[str, Any]) -> None:
        """kind: input | structured | agent_score | audit | choice | device_event |
        confirm | action | feedback | error"""
        record = {"ts": time.time(), "session_id": session_id, "kind": kind, "payload": payload}
        with self._lock:
            with self.jsonl_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.db.execute(
                "INSERT INTO events (ts, session_id, kind, payload) VALUES (?, ?, ?, ?)",
                (record["ts"], session_id, kind, json.dumps(payload, ensure_ascii=False)),
            )
            self.db.commit()

    def recent(self, kind: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        q = "SELECT ts, session_id, kind, payload FROM events"
        args: tuple = ()
        if kind:
            q += " WHERE kind = ?"
            args = (kind,)
        q += " ORDER BY id DESC LIMIT ?"
        rows = self.db.execute(q, args + (limit,)).fetchall()
        return [
            {"ts": ts, "session_id": sid, "kind": k, "payload": json.loads(p)}
            for ts, sid, k, p in rows
        ]

    def journal(self, days: int = 30) -> list[dict[str, Any]]:
        """猫爪手账数据：每次决策一条，拼上确认与反馈（记忆模式可视化数据源）。"""
        cutoff = time.time() - days * 86400
        rows = self.db.execute(
            "SELECT ts, session_id, kind, payload FROM events WHERE ts > ?"
            " AND kind IN ('choice', 'action', 'feedback') ORDER BY id ASC",
            (cutoff,),
        ).fetchall()
        out: dict[str, dict[str, Any]] = {}
        for ts, sid, kind, raw in rows:
            p = json.loads(raw)
            if kind == "choice" and p.get("final"):
                out[sid] = {"ts": ts, "session_id": sid, "mode": str(p.get("mode") or ""),
                            "candidate_id": p["final"].get("candidate_id"),
                            "confirmed": False, "rating": None, "would_repeat": None}
            elif kind == "action" and sid in out and p.get("ok"):
                out[sid]["confirmed"] = True
            elif kind == "feedback" and sid in out:
                out[sid].update(rating=p.get("rating"), would_repeat=p.get("would_repeat"),
                                reject_reason=p.get("reject_reason") or "")
        return list(out.values())[::-1]   # 最新在前

    def recent_meals(self, days: int = 7) -> list[dict[str, Any]]:
        """记忆猫输入：近期吃过什么、拒绝过什么及原因。"""
        cutoff = time.time() - days * 86400
        rows = self.db.execute(
            "SELECT ts, kind, payload FROM events WHERE ts > ? AND kind IN ('choice', 'feedback')"
            " ORDER BY id DESC LIMIT 200",
            (cutoff,),
        ).fetchall()
        return [{"ts": ts, "kind": k, "payload": json.loads(p)} for ts, k, p in rows]
