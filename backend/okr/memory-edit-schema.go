package okr

const memoryEditSchema = `
DROP TRIGGER project_operation_identity;
DROP TRIGGER project_operation_applied;
ALTER TABLE project_operations RENAME TO project_operations_v3;
CREATE TABLE project_operations(
 project_id TEXT NOT NULL,
 operation_key TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('review','observation','memory_append','memory_edit')),
 request_sha256 TEXT NOT NULL CHECK(length(request_sha256)=64),
 intent_json TEXT NOT NULL CHECK(json_valid(intent_json)),
 state TEXT NOT NULL CHECK(state IN ('prepared','applied')),
 receipt_json TEXT CHECK(receipt_json IS NULL OR json_valid(receipt_json)),
 created_at TEXT NOT NULL,
 PRIMARY KEY(project_id,operation_key),
 CHECK((state='prepared' AND receipt_json IS NULL) OR (state='applied' AND receipt_json IS NOT NULL))
);
INSERT INTO project_operations(rowid,project_id,operation_key,kind,request_sha256,intent_json,state,receipt_json,created_at)
 SELECT rowid,project_id,operation_key,kind,request_sha256,intent_json,state,receipt_json,created_at FROM project_operations_v3 ORDER BY rowid;
DROP TABLE project_operations_v3;
CREATE TRIGGER project_operation_identity BEFORE UPDATE OF project_id,operation_key,kind,request_sha256,intent_json,created_at ON project_operations BEGIN
 SELECT RAISE(ABORT,'PROJECT_OPERATION_IMMUTABLE');
END;
CREATE TRIGGER project_operation_applied BEFORE UPDATE ON project_operations WHEN OLD.state='applied' BEGIN
 SELECT RAISE(ABORT,'PROJECT_OPERATION_IMMUTABLE');
END;
`
