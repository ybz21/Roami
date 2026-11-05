ALTER TABLE native_sessions ADD COLUMN label TEXT;
UPDATE native_sessions SET label=(
  SELECT substr(COALESCE(json_extract(t.intent_json,'$.initialIntent.title'),
    json_extract(t.intent_json,'$.title'),json_extract(t.intent_json,'$.initialIntent.goal'),
    json_extract(t.intent_json,'$.goal')),1,100)
  FROM tasks t WHERE t.id=native_sessions.task_id
);
