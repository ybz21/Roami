#!/usr/bin/env python3
"""从 Roam 主目录的残留物重建 meta.db 的会话历史。

用途：早期版本的 sessions 表以 tmux 的 `$N` 当主键，机器重启后 `$N` 全部消失，
Reconcile 把整表当死行硬删——历史会话一条不剩，而 logs/、meta/、swarms/ 里的
证据其实都还在。这个脚本把那些证据拼回 `status='dead'` 的行，让日志重新可索引。

只补不覆盖：已有的行（尤其是活会话）一行不动。可反复跑。

    python3 scripts/dev/rebuild-session-history.py            # 只报告
    python3 scripts/dev/rebuild-session-history.py --write    # 真写

证据源，按可信度降序：
    meta/<id>/*.txt          归属目录 / 类型 / 描述 / 起始时间
    swarms/*/swarm.db        蜂群成员的 session + workdir
    meta.db swarms           指挥会话 + 目录
    meta.db plugin_sessions  labels.workdir + 起止时间
    meta.db.bak-*            更早那代表的残留（v1：会话名当主键）
    groups/*.group           任务组成员
    logs/<id>.log            存在性 + 最后活动时刻（唯一覆盖全量的源）

schema 归 ttmux CLI 所有：本脚本只 INSERT，绝不建表也绝不改结构。
库还没建起来时先跑一次 `roami db migrate`。
"""
import argparse
import fcntl
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# 会话 id 自带创建时刻：2026-0811-1629-0009
ID_RE = re.compile(r"^(\d{4})-(\d{2})(\d{2})-(\d{2})(\d{2})-[0-9a-z]{4}$")


def read(p: Path) -> str:
    try:
        return p.read_text(errors="replace").strip()
    except OSError:
        return ""


def query(db: Path, sql: str):
    """只读查询；表不存在/列对不上都当作「这个源没有」，不中断整个重建。"""
    if not db.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        return conn.execute(sql).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def rfc3339(raw: str, fallback: str = "") -> str:
    """把各源的时间写法统一成 RFC3339。认不出就用 fallback。"""
    raw = (raw or "").strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.astimezone()
            return dt.isoformat()
        except ValueError:
            continue
    return fallback


def from_epoch(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).astimezone().isoformat()


class Salvage:
    """一份「会话名 → 拼出来的元数据」。先写的源赢，后写的只补空。"""

    def __init__(self):
        self.rows: dict[str, dict] = {}

    def add(self, name: str, source: str, **fields):
        if not name:
            return
        row = self.rows.setdefault(name, {"session": name, "sources": []})
        if source not in row["sources"]:
            row["sources"].append(source)
        for k, v in fields.items():
            if v and not row.get(k):
                row[k] = v


def collect(home: Path, db_path: Path) -> Salvage:
    s = Salvage()

    for f in sorted((home / "logs").glob("*.log")):
        m = ID_RE.match(f.stem)
        started = f"{m[1]}-{m[2]}-{m[3]}T{m[4]}:{m[5]}:00" if m else ""
        s.add(f.stem, "log", created_at=rfc3339(started),
              died_at=from_epoch(f.stat().st_mtime), created_by="log")

    meta = home / "meta"
    for d in sorted(meta.iterdir()) if meta.is_dir() else []:
        if d.is_dir():
            s.add(d.name, "meta", initial_cwd=read(d / "workdir.txt"),
                  created_at=rfc3339(read(d / "started.txt")),
                  created_by=read(d / "type.txt"))

    swarm_born = {}  # 蜂群 id → 创建时刻；成员表没有时间戳，只能继承群的
    for sid, sup, created, wd in query(
            db_path,
            "select id, IFNULL(supervisor,''), created, IFNULL(dir,'') from swarms"):
        swarm_born[sid] = rfc3339(created)
        s.add(sup, "swarm-lead", initial_cwd=wd, created_at=swarm_born[sid],
              created_by="swarm")

    for sess, labels, created, updated in query(
            db_path,
            "select session, IFNULL(labels,''), created, updated from plugin_sessions"):
        try:
            wd = (json.loads(labels) or {}).get("workdir", "")
        except (ValueError, TypeError):
            wd = ""
        s.add(sess, "plugin", initial_cwd=wd, created_at=rfc3339(created),
              died_at=rfc3339(updated), created_by="plugin")

    for db in sorted((home / "swarms").glob("*/swarm.db")):
        born = swarm_born.get(db.parent.name, "")
        for name, wd, sess in query(db, "select name, IFNULL(workdir,''), IFNULL(session,'') from members"):
            s.add(sess or name, "swarm-member", initial_cwd=wd, created_by="swarm",
                  created_at=born)

    # 更早那代的整库备份（v1：会话名当主键，正好就是现在的持久 id）
    for bak in sorted(home.glob("meta.db.bak-*")):
        for sess, parent, by, at, cwd in query(
                bak, """select session, IFNULL(parent,''), IFNULL(created_by,''),
                        IFNULL(created_at,''), IFNULL(initial_cwd,'') from sessions"""):
            s.add(sess, "meta.db.bak", parent=parent, created_by=by,
                  created_at=rfc3339(at), initial_cwd=cwd)

    for g in sorted((home / "groups").glob("*.group")):
        for line in read(g).splitlines():
            s.add(line.strip(), "group", created_by="group")

    return s


def live_sessions() -> set[str]:
    """当前活着的会话名。问不出 tmux 返回空集（宁可少补，不覆盖活行）。"""
    try:
        out = subprocess.run([os.environ.get("TMUX_BIN", "tmux"), "list-sessions",
                              "-F", "#{session_name}"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return set()
    if out.returncode != 0:
        return set()
    return {n.strip() for n in out.stdout.splitlines() if n.strip()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="真写入（默认只报告）")
    ap.add_argument("--home", type=Path, default=None, help="Roam 主目录（默认 $ROAM_HOME 或 ~/.roam）")
    args = ap.parse_args()

    command = ["roami"]
    if args.home:
        command += ["--home", str(args.home.resolve())]
    command += ["db", "status", "--json"]
    status = subprocess.run(command, check=True, capture_output=True, text=True)
    state = json.loads(status.stdout)
    if state.get("mode") != "sqlite":
        print("先完成 roami db migrate；不会回退旧数据库路径", file=sys.stderr)
        return 1
    home = Path(state["paths"]["dataRoot"])
    db_path = Path(state["path"])
    lock_dir = home / "locks"
    lock_dir.mkdir(mode=0o700, exist_ok=True)
    lease = (lock_dir / "storage.lock").open("a+b")
    fcntl.flock(lease, fcntl.LOCK_SH | fcntl.LOCK_NB)

    conn = sqlite3.connect(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}
    if "status" not in cols:
        print("sessions 还是老表结构：先用新版 ttmux 跑一次 `roami session ls --tree` 完成迁移",
              file=sys.stderr)
        return 1

    salvage = collect(home, db_path)
    existing = {r[0] for r in conn.execute("select id from sessions")}
    alive = live_sessions()

    todo = [r for name, r in sorted(salvage.rows.items())
            if name not in existing and name not in alive]
    skipped_live = sum(1 for n in salvage.rows if n in alive)

    print(f"残骸        {len(salvage.rows)} 个会话")
    print(f"  已在表里  {sum(1 for n in salvage.rows if n in existing)}")
    print(f"  当前活着  {skipped_live}（不动）")
    print(f"  待补      {len(todo)}")
    print(f"    有归属目录 {sum(1 for r in todo if r.get('initial_cwd'))}")
    print(f"    有起始时间 {sum(1 for r in todo if r.get('created_at'))}")
    if not args.write:
        print("\n（只报告；加 --write 真写）")
        return 0

    now = datetime.now().astimezone().isoformat()
    for r in todo:
        created = r.get("created_at") or r.get("died_at") or now
        conn.execute(
            """INSERT OR IGNORE INTO sessions
               (id, parent_id, created_by, created_at, initial_cwd,
                status, died_at, died_reason, tmux_id, tmux_epoch)
               VALUES (?,?,?,?,?, 'dead', ?, 'host-restart', NULL, NULL)""",
            (r["session"], r.get("parent") or None, r.get("created_by", ""),
             created, r.get("initial_cwd", ""), r.get("died_at") or created))
    conn.commit()
    n = conn.execute("select count(*) from sessions where status='dead'").fetchone()[0]
    conn.close()
    print(f"\n已写入；表里现有 {n} 条历史会话")
    return 0


if __name__ == "__main__":
    sys.exit(main())
