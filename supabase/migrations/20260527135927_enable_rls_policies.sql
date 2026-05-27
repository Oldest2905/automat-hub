-- Enable Row Level Security for all tables
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE fleets ENABLE ROW LEVEL SECURITY;
ALTER TABLE tracked_vehicles ENABLE ROW LEVEL SECURITY;
ALTER TABLE hourly_scans ENABLE ROW LEVEL SECURITY;
ALTER TABLE vehicle_alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE location_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE dcp_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE inspection_details ENABLE ROW LEVEL SECURITY;
ALTER TABLE verification_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE dcp_hash_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE escrow_deals ENABLE ROW LEVEL SECURITY;
ALTER TABLE escrow_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE workshops ENABLE ROW LEVEL SECURITY;
ALTER TABLE mechanics ENABLE ROW LEVEL SECURITY;
ALTER TABLE repair_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE reseller_api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;

-- 1. Users Table
CREATE POLICY admin_all_users ON users FOR ALL USING (current_setting('app.current_role', true) = 'admin');
CREATE POLICY user_read_self ON users FOR SELECT USING (user_id = current_setting('app.current_user_id', true));
CREATE POLICY user_update_self ON users FOR UPDATE USING (user_id = current_setting('app.current_user_id', true));

-- 2. Fleets Table
CREATE POLICY admin_all_fleets ON fleets FOR ALL USING (current_setting('app.current_role', true) = 'admin');
CREATE POLICY owner_all_fleets ON fleets FOR ALL USING (owner_id = current_setting('app.current_user_id', true));

-- 3. Tracked Vehicles Table
CREATE POLICY admin_all_vehicles ON tracked_vehicles FOR ALL USING (current_setting('app.current_role', true) = 'admin');
CREATE POLICY owner_all_vehicles ON tracked_vehicles FOR ALL USING (owner_id = current_setting('app.current_user_id', true));

-- 4. Hourly Scans Table
CREATE POLICY admin_all_scans ON hourly_scans FOR ALL USING (current_setting('app.current_role', true) = 'admin');
CREATE POLICY owner_read_scans ON hourly_scans FOR SELECT USING (
    vehicle_id IN (SELECT vehicle_id FROM tracked_vehicles WHERE owner_id = current_setting('app.current_user_id', true))
);

-- 5. Vehicle Alerts Table
CREATE POLICY admin_all_alerts ON vehicle_alerts FOR ALL USING (current_setting('app.current_role', true) = 'admin');
CREATE POLICY owner_all_alerts ON vehicle_alerts FOR ALL USING (user_id = current_setting('app.current_user_id', true));

-- 6. Location History Table
CREATE POLICY admin_all_locations ON location_history FOR ALL USING (current_setting('app.current_role', true) = 'admin');
CREATE POLICY owner_read_locations ON location_history FOR SELECT USING (
    vehicle_id IN (SELECT vehicle_id FROM tracked_vehicles WHERE owner_id = current_setting('app.current_user_id', true))
);

-- 7. DCP Records Table (Publicly verifiable)
CREATE POLICY admin_all_dcps ON dcp_records FOR ALL USING (current_setting('app.current_role', true) = 'admin');
CREATE POLICY inspector_insert_dcps ON dcp_records FOR INSERT WITH CHECK (
    auditor_id = current_setting('app.current_user_id', true) AND current_setting('app.current_role', true) = 'inspector'
);
CREATE POLICY public_read_dcps ON dcp_records FOR SELECT USING (true);

-- 8. DCP Hash Ledger (Append-only / Publicly verifiable)
CREATE POLICY admin_all_dcp_ledgers ON dcp_hash_ledger FOR ALL USING (current_setting('app.current_role', true) = 'admin');
CREATE POLICY inspector_insert_dcp_ledgers ON dcp_hash_ledger FOR INSERT WITH CHECK (current_setting('app.current_role', true) = 'inspector');
CREATE POLICY public_read_dcp_ledgers ON dcp_hash_ledger FOR SELECT USING (true);

-- 9. Inspection Details
CREATE POLICY admin_all_inspection_details ON inspection_details FOR ALL USING (current_setting('app.current_role', true) = 'admin');
CREATE POLICY public_read_inspection_details ON inspection_details FOR SELECT USING (true);

-- 10. Verification Log
CREATE POLICY admin_all_verification_logs ON verification_log FOR ALL USING (current_setting('app.current_role', true) = 'admin');
CREATE POLICY public_insert_verification_logs ON verification_log FOR INSERT WITH CHECK (true);

-- 11. Escrow Deals
CREATE POLICY admin_all_escrow_deals ON escrow_deals FOR ALL USING (current_setting('app.current_role', true) = 'admin');
CREATE POLICY public_read_escrow_deals ON escrow_deals FOR SELECT USING (true);
CREATE POLICY public_insert_escrow_deals ON escrow_deals FOR INSERT WITH CHECK (true);
CREATE POLICY public_update_escrow_deals ON escrow_deals FOR UPDATE USING (true);

-- 12. Escrow Events
CREATE POLICY admin_all_escrow_events ON escrow_events FOR ALL USING (current_setting('app.current_role', true) = 'admin');
CREATE POLICY public_read_escrow_events ON escrow_events FOR SELECT USING (true);
CREATE POLICY public_insert_escrow_events ON escrow_events FOR INSERT WITH CHECK (true);

-- 13. Workshops
CREATE POLICY admin_all_workshops ON workshops FOR ALL USING (current_setting('app.current_role', true) = 'admin');
CREATE POLICY owner_all_workshops ON workshops FOR ALL USING (owner_user_id = current_setting('app.current_user_id', true));
CREATE POLICY public_read_workshops ON workshops FOR SELECT USING (status = 'active');

-- 14. Mechanics
CREATE POLICY admin_all_mechanics ON mechanics FOR ALL USING (current_setting('app.current_role', true) = 'admin');
CREATE POLICY owner_all_mechanics ON mechanics FOR ALL USING (
    workshop_id IN (SELECT workshop_id FROM workshops WHERE owner_user_id = current_setting('app.current_user_id', true))
);

-- 15. Repair Jobs
CREATE POLICY admin_all_repair_jobs ON repair_jobs FOR ALL USING (current_setting('app.current_role', true) = 'admin');
CREATE POLICY owner_read_repair_jobs ON repair_jobs FOR SELECT USING (
    vehicle_id IN (SELECT vehicle_id FROM tracked_vehicles WHERE owner_id = current_setting('app.current_user_id', true))
);
CREATE POLICY workshop_all_repair_jobs ON repair_jobs FOR ALL USING (
    workshop_id IN (SELECT workshop_id FROM workshops WHERE owner_user_id = current_setting('app.current_user_id', true))
);

-- 16. Reseller API Keys
CREATE POLICY admin_all_reseller_api_keys ON reseller_api_keys FOR ALL USING (current_setting('app.current_role', true) = 'admin');
CREATE POLICY owner_all_reseller_api_keys ON reseller_api_keys FOR ALL USING (user_id = current_setting('app.current_user_id', true));

-- 17. Subscriptions
CREATE POLICY admin_all_subscriptions ON subscriptions FOR ALL USING (current_setting('app.current_role', true) = 'admin');
CREATE POLICY owner_read_subscriptions ON subscriptions FOR SELECT USING (user_id = current_setting('app.current_user_id', true));