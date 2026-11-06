CREATE TABLE swarm_post_routes(
 post_id INTEGER PRIMARY KEY REFERENCES swarm_posts(id),
 swarm_id TEXT NOT NULL REFERENCES swarm_groups(id),
 author_key TEXT NOT NULL,
 author_kind TEXT NOT NULL CHECK(author_kind IN ('human','main','member')),
 author_member_id TEXT REFERENCES swarm_members(id),
 kind TEXT NOT NULL CHECK(kind IN ('progress','question','blocker','handoff','reply')),
 message_key TEXT,
 payload_sha256 TEXT NOT NULL,
 source_task_revision INTEGER,
 source_run_id TEXT REFERENCES task_attempts(id),
 recipient_member_id TEXT REFERENCES swarm_members(id),
 reply_to_post_id INTEGER REFERENCES swarm_posts(id),
 UNIQUE(swarm_id,author_key,message_key),
 CHECK((author_kind='member')=(author_member_id IS NOT NULL)),
 CHECK((author_member_id IS NULL)=(source_run_id IS NULL)),
 CHECK((source_task_revision IS NULL)=(source_run_id IS NULL)),
 CHECK(source_task_revision IS NULL OR source_task_revision>0),
 CHECK(kind!='reply' OR reply_to_post_id IS NOT NULL)
);
CREATE TABLE swarm_inbox(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 post_id INTEGER NOT NULL REFERENCES swarm_post_routes(post_id),
 main_conversation_id TEXT REFERENCES conversations(id),
 member_id TEXT REFERENCES swarm_members(id),
 created_ms INTEGER NOT NULL,
 read_ms INTEGER,
 handled_post_id INTEGER REFERENCES swarm_posts(id),
 CHECK((main_conversation_id IS NULL)!=(member_id IS NULL))
);
CREATE UNIQUE INDEX swarm_inbox_main ON swarm_inbox(post_id,main_conversation_id)
 WHERE main_conversation_id IS NOT NULL;
CREATE UNIQUE INDEX swarm_inbox_member ON swarm_inbox(post_id,member_id)
 WHERE member_id IS NOT NULL;
CREATE INDEX swarm_inbox_main_pending ON swarm_inbox(main_conversation_id,id)
 WHERE handled_post_id IS NULL;
CREATE INDEX swarm_inbox_member_pending ON swarm_inbox(member_id,id)
 WHERE handled_post_id IS NULL;

CREATE TRIGGER swarm_post_routes_scope BEFORE INSERT ON swarm_post_routes BEGIN
 SELECT CASE WHEN NOT EXISTS(
  SELECT 1 FROM swarm_posts p WHERE p.id=NEW.post_id AND p.swarm_id=NEW.swarm_id
 ) OR (NEW.author_member_id IS NOT NULL AND NOT EXISTS(
  SELECT 1 FROM swarm_members m WHERE m.id=NEW.author_member_id AND m.swarm_id=NEW.swarm_id
 )) OR (NEW.recipient_member_id IS NOT NULL AND NOT EXISTS(
  SELECT 1 FROM swarm_members m WHERE m.id=NEW.recipient_member_id AND m.swarm_id=NEW.swarm_id
 )) OR (NEW.reply_to_post_id IS NOT NULL AND NOT EXISTS(
  SELECT 1 FROM swarm_posts p WHERE p.id=NEW.reply_to_post_id AND p.swarm_id=NEW.swarm_id
 )) THEN RAISE(ABORT,'SWARM_MESSAGE_SCOPE_CONFLICT') END;
END;
CREATE TRIGGER swarm_post_routes_immutable BEFORE UPDATE ON swarm_post_routes BEGIN
 SELECT RAISE(ABORT,'SWARM_MESSAGE_ROUTE_IMMUTABLE');
END;
CREATE TRIGGER swarm_inbox_scope BEFORE INSERT ON swarm_inbox BEGIN
 SELECT CASE WHEN NOT EXISTS(
  SELECT 1 FROM swarm_post_routes p JOIN swarm_groups g ON g.id=p.swarm_id
  WHERE p.post_id=NEW.post_id AND (
   (NEW.main_conversation_id=g.conversation_id AND NEW.member_id IS NULL)
   OR (NEW.main_conversation_id IS NULL AND EXISTS(
    SELECT 1 FROM swarm_members m WHERE m.id=NEW.member_id AND m.swarm_id=g.id
   ))
  )
 ) THEN RAISE(ABORT,'SWARM_MESSAGE_SCOPE_CONFLICT') END;
END;
CREATE TRIGGER swarm_inbox_recipient_immutable BEFORE UPDATE OF post_id,main_conversation_id,member_id ON swarm_inbox
WHEN NEW.post_id IS NOT OLD.post_id OR NEW.main_conversation_id IS NOT OLD.main_conversation_id
 OR NEW.member_id IS NOT OLD.member_id BEGIN
 SELECT RAISE(ABORT,'SWARM_MESSAGE_ROUTE_IMMUTABLE');
END;
CREATE TRIGGER swarm_inbox_response BEFORE UPDATE OF handled_post_id ON swarm_inbox
WHEN NEW.handled_post_id IS NOT OLD.handled_post_id BEGIN
 SELECT CASE WHEN OLD.handled_post_id IS NOT NULL OR NOT EXISTS(
  SELECT 1 FROM swarm_post_routes answer JOIN swarm_post_routes source ON source.post_id=OLD.post_id
  JOIN swarm_groups g ON g.id=source.swarm_id WHERE answer.post_id=NEW.handled_post_id
  AND answer.swarm_id=source.swarm_id AND answer.kind='reply' AND answer.reply_to_post_id=source.post_id
  AND ((answer.author_kind='main' AND OLD.main_conversation_id=g.conversation_id)
    OR (answer.author_kind='member' AND answer.author_member_id=OLD.member_id))
 ) THEN RAISE(ABORT,'SWARM_RESPONSE_REQUIRED') END;
END;
