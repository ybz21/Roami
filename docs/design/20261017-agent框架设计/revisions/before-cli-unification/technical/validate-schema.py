"""Validate the candidate schema in a temporary SQLite database."""
from pathlib import Path
import json
import sqlite3
import tempfile

schema = Path(__file__).with_name('schema.sql')
checks = []

def add(db, table, **values):
    columns = ','.join(values)
    placeholders = ','.join('?' for _ in values)
    db.execute(f'INSERT INTO {table} ({columns}) VALUES ({placeholders})', tuple(values.values()))

def rejected(db, label, fn):
    try:
        fn()
    except sqlite3.IntegrityError:
        checks.append(label)
    else:
        raise AssertionError(f'Expected integrity rejection: {label}')

with tempfile.TemporaryDirectory(prefix='roami-agent-design-') as directory:
    db = sqlite3.connect(str(Path(directory) / 'candidate.db'), isolation_level=None)
    db.executescript(schema.read_text())
    assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
    assert db.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    checks.append('fresh schema / WAL / foreign keys')
    for owner, convo, branch in [('owner-a', 'c-a', 'b-a'), ('owner-b', 'c-b', 'b-b')]:
        add(db, 'owner_versions', owner_id=owner)
        add(db, 'conversations', id=convo, owner_id=owner, title='Main', created_ms=1000, updated_ms=1000)
        add(db, 'branches', id=branch, conversation_id=convo, created_ms=1000)
        db.execute('UPDATE conversations SET active_branch_id=? WHERE id=?', (branch, convo))
    add(db, 'requests', id='req-1', owner_id='owner-a', request_key='client-1', payload_sha256='sha-a', conversation_id='c-a', accepted_ms=1001)
    add(db, 'turns', id='turn-1', request_id='req-1', conversation_id='c-a', branch_id='b-a', trigger_kind='user', state='running', created_ms=1001)
    db.execute('UPDATE requests SET turn_id=? WHERE id=?', ('turn-1', 'req-1'))
    add(db, 'messages', id='msg-1', conversation_id='c-a', branch_id='b-a', seq=1, turn_id='turn-1', role='user', content_json='{"text":"记忆方案"}', status='completed', created_ms=1001)
    rejected(db, 'unique owner/request key', lambda: add(db, 'requests', id='req-2', owner_id='owner-a', request_key='client-1', payload_sha256='sha-other', conversation_id='c-a', accepted_ms=1002))
    rejected(db, 'one running turn per branch', lambda: add(db, 'turns', id='turn-2', conversation_id='c-a', branch_id='b-a', trigger_kind='completion', state='running', created_ms=1002))
    rejected(db, 'unique branch/message sequence', lambda: add(db, 'messages', id='msg-2', conversation_id='c-a', branch_id='b-a', seq=1, role='user', content_json='{}', status='completed', created_ms=1002))
    rejected(db, 'message JSON validation', lambda: add(db, 'messages', id='msg-bad', conversation_id='c-a', branch_id='b-a', seq=2, role='user', content_json='{broken', status='completed', created_ms=1002))
    add(db, 'tasks', id='task-1', owner_id='owner-a', origin_conversation_id='c-a', origin_branch_id='b-a', origin_message_id='msg-1', intent_json='{"kind":"new_session"}', state='preparing', budget_json='{}', created_ms=1002, updated_ms=1002)
    add(db, 'task_attempts', id='run-1', task_id='task-1', task_revision=1, attempt_no=1, executor_kind='cli', launch_id='launch-1', state='starting', lease_epoch=1)
    rejected(db, 'unique CLI launch identity', lambda: add(db, 'task_attempts', id='run-2', task_id='task-1', task_revision=1, attempt_no=2, executor_kind='cli', launch_id='launch-1', state='starting', lease_epoch=2))
    add(db, 'events', conversation_id='c-a', task_id='task-1', event_key='task-1:accepted:1', kind='task.accepted', payload_json='{}', created_ms=1002)
    rejected(db, 'unique durable event key', lambda: add(db, 'events', conversation_id='c-a', task_id='task-1', event_key='task-1:accepted:1', kind='task.accepted', payload_json='{}', created_ms=1002))
    for ident, owner, project in [('m-a', 'owner-a', 'project-a'), ('m-b', 'owner-b', 'project-a'), ('m-other', 'owner-a', 'project-b'), ('m-loose', 'owner-a', None)]:
        add(db, 'memory_records', id=ident, owner_id=owner, kind='decision', project_id=project, conversation_id='c-a' if ident=='m-loose' else None, title='会话记忆', body='会话按任务保存记忆方案', search_tokens='会话 记忆 方案', state='active', valid_from_ms=1000, created_ms=1000, updated_ms=1000)
    matches = db.execute('''SELECT m.id FROM memory_fts JOIN memory_records m ON m.id=memory_fts.record_id
        WHERE memory_fts MATCH ? AND m.owner_id=? AND m.project_id=? AND m.state='active' ''', ('"会话"', 'owner-a', 'project-a')).fetchall()
    assert matches == [('m-a',)], matches
    checks.append('two-character CJK FTS / owner and project predicate')
    assert db.execute('SELECT project_id FROM memory_records WHERE id=?', ('m-loose',)).fetchone()[0] is None
    checks.append('unassigned conversation memory')
    add(db, 'memory_sources', memory_id='m-a', source_key='message:msg-1', message_id='msg-1', source_sha256='sha-source')
    rejected(db, 'memory provenance foreign key', lambda: add(db, 'memory_sources', memory_id='m-a', source_key='message:missing', message_id='missing', source_sha256='sha'))
    db.execute("UPDATE memory_records SET search_tokens='新的 决策', body='新的决策', revision=2 WHERE id='m-a'")
    assert db.execute("SELECT record_id FROM memory_fts WHERE memory_fts MATCH ? AND record_id='m-a'", ('"会话"',)).fetchall() == []
    assert db.execute("SELECT record_id FROM memory_fts WHERE memory_fts MATCH ? AND record_id='m-a'", ('"决策"',)).fetchall() == [('m-a',)]
    checks.append('memory update transaction refreshes FTS')
    db.execute("UPDATE memory_records SET state='deleted' WHERE id='m-a'")
    assert db.execute("SELECT record_id FROM memory_fts WHERE record_id='m-a'").fetchall() == []
    checks.append('memory logical deletion removes FTS entry')
    db.execute("INSERT INTO memory_tombstones VALUES ('owner-a','sha-source','decision-a',1003)")
    rejected(db, 'unique deletion tombstone', lambda: db.execute("INSERT INTO memory_tombstones VALUES ('owner-a','sha-source','decision-a',1004)"))
    db.execute("BEGIN IMMEDIATE")
    add(db, 'messages', id='msg-rollback', conversation_id='c-a', branch_id='b-a', seq=2, role='assistant', content_json='{}', status='streaming', created_ms=1004)
    db.execute('ROLLBACK')
    assert db.execute("SELECT 1 FROM messages WHERE id='msg-rollback'").fetchone() is None
    checks.append('message write rollback is atomic')
    backup = sqlite3.connect(str(Path(directory) / 'backup.db'))
    db.backup(backup)
    assert backup.execute('SELECT count(*) FROM tasks').fetchone()[0] == 1
    assert backup.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    checks.append('SQLite backup restores committed WAL data')
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    checks.append('foreign-key and integrity check')
    tables = [x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND (name NOT LIKE 'memory_fts_%') ORDER BY name")]
    print(json.dumps({'sqliteVersion':sqlite3.sqlite_version, 'tables':len(tables), 'checks':checks, 'scope':'candidate DDL only; no live runtime or model benchmark'}, ensure_ascii=False, indent=2))
    backup.close()
    db.close()
