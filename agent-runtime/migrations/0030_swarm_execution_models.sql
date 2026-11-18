ALTER TABLE swarm_work_items ADD COLUMN model TEXT;
ALTER TABLE swarm_members ADD COLUMN model TEXT;
ALTER TABLE swarm_work_items ADD COLUMN execution_generation INTEGER NOT NULL DEFAULT 1 CHECK(execution_generation>0);
