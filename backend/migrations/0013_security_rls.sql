-- Deployment-ready policies. Enable RLS only after the API sets these transaction-local values:
-- SET LOCAL app.tenant_id = '<tenant>'; SET LOCAL app.workspace_id = '<workspace>'.
DO $$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['resources','response_queue_items','response_tasks','route_observations','shelters','shelter_observations','shelter_state_snapshots'] LOOP
    EXECUTE format('DROP POLICY IF EXISTS ev2_scope_%s ON %I', table_name, table_name);
    EXECUTE format('CREATE POLICY ev2_scope_%s ON %I USING (organization_id = current_setting(''app.tenant_id'', true) AND workspace_id = current_setting(''app.workspace_id'', true))', table_name, table_name);
  END LOOP;
END $$;
