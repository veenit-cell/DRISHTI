ALTER TABLE response_tasks
    DROP CONSTRAINT IF EXISTS response_tasks_status_check;

ALTER TABLE response_tasks
    ADD CONSTRAINT response_tasks_status_check
    CHECK (status IN ('assigned','acknowledged','en_route','on_scene','paused','completed'));
