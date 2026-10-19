CREATE TABLE session_dispatches (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  request_key TEXT NOT NULL,
  request_digest TEXT NOT NULL,
  conversation_id TEXT NOT NULL REFERENCES conversations(id),
  branch_id TEXT NOT NULL REFERENCES branches(id),
  turn_id TEXT NOT NULL REFERENCES turns(id),
  origin_message_id TEXT NOT NULL REFERENCES messages(id),
  session_id TEXT NOT NULL,
  prompt TEXT NOT NULL,
  delivery_state TEXT NOT NULL DEFAULT 'prepared' CHECK(delivery_state IN ('prepared','delivered','unknown','failed')),
  delivery_receipt_json TEXT CHECK(delivery_receipt_json IS NULL OR json_valid(delivery_receipt_json)),
  final_status TEXT CHECK(final_status IN ('completed','failed')),
  created_ms INTEGER NOT NULL,
  updated_ms INTEGER NOT NULL,
  UNIQUE(owner_id,request_key)
);
CREATE INDEX session_dispatches_origin ON session_dispatches(conversation_id,created_ms);
CREATE TABLE session_dispatch_reports (
  dispatch_id TEXT NOT NULL REFERENCES session_dispatches(id),
  report_key TEXT NOT NULL,
  result_json TEXT NOT NULL CHECK(json_valid(result_json)),
  receipt_json TEXT NOT NULL CHECK(json_valid(receipt_json)),
  created_ms INTEGER NOT NULL,
  PRIMARY KEY(dispatch_id,report_key)
);
