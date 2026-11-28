CREATE TABLE project_okr_main_review_models(
 owner_id TEXT NOT NULL,
 project_id TEXT NOT NULL,
 conversation_id TEXT NOT NULL PRIMARY KEY,
 model TEXT,
 free_only INTEGER NOT NULL CHECK(free_only IN (0,1)),
 revision INTEGER NOT NULL CHECK(revision>=1),
 FOREIGN KEY(owner_id,project_id,conversation_id)
  REFERENCES project_okr_mains(owner_id,project_id,conversation_id) ON DELETE CASCADE
);
