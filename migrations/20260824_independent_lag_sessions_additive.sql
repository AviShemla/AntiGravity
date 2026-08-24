-- Add explicit target-relative lag session offsets without modifying historical rows.
-- Chain position and lag horizon are separate. Apply once through the reviewed Turso
-- migration process before code that requires these columns is deployed.

ALTER TABLE predictive_screening_results ADD COLUMN lag1_sessions INTEGER;
ALTER TABLE predictive_screening_results ADD COLUMN lag2_sessions INTEGER;
ALTER TABLE predictive_screening_results ADD COLUMN lag3_sessions INTEGER;
ALTER TABLE predictive_screening_results ADD COLUMN lag4_sessions INTEGER;
ALTER TABLE predictive_screening_results ADD COLUMN lag5_sessions INTEGER;

ALTER TABLE stock_universe_config ADD COLUMN lag1_sessions INTEGER;
ALTER TABLE stock_universe_config ADD COLUMN lag2_sessions INTEGER;
ALTER TABLE stock_universe_config ADD COLUMN lag3_sessions INTEGER;
ALTER TABLE stock_universe_config ADD COLUMN lag4_sessions INTEGER;
ALTER TABLE stock_universe_config ADD COLUMN lag5_sessions INTEGER;
