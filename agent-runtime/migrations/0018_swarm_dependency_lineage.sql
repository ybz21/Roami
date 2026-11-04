ALTER TABLE swarm_work_items
ADD COLUMN required_task_revision INTEGER NOT NULL DEFAULT 1 CHECK(required_task_revision >= 1);
