-- Proves the enforcement layer actually enforces.
-- Each block attempts a violation that CLAUDE.md forbids; the required
-- outcome is that the database refuses it. Runs entirely inside a
-- transaction that is rolled back, so it is safe against a live database.
--
--   sudo -u ecowitt psql -q ecowitt -f verify_constraints.sql
--
-- Every line must read 'rejected, as required'. A WARNING means a rule
-- that was supposed to be structural has become advisory.
--
-- Verified passing 2026-08-02 against PostgreSQL 16.14 on ecowitt-db.
BEGIN;

INSERT INTO run_log (run_id, trigger, mode, status, started_at)
VALUES ('11111111-1111-1111-1111-111111111111', 'manual', 'test', 'running', now());

INSERT INTO metric_catalog VALUES
  ('outdoor.temperature','instantaneous','ºF','mean',true,null),
  ('wind.wind_direction','circular','º','vector_mean',true,null);

DO $$
DECLARE ok boolean;
BEGIN
  -- 1. credential leak into raw_payload
  BEGIN
    INSERT INTO raw_payload (run_id, endpoint, label, requested_at, request_url,
                             http_status, body, body_sha256, body_bytes)
    VALUES ('11111111-1111-1111-1111-111111111111','device/real_time','t',now(),
            'https://api.ecowitt.net/x?application_key=SECRET123&api_key=SECRET456',
            200,'{}'::jsonb,'\x00'::bytea,2);
    RAISE WARNING '1. credential CHECK  -> NOT ENFORCED (leak accepted)';
  EXCEPTION WHEN check_violation THEN
    RAISE NOTICE '1. credential CHECK  -> rejected, as required';
  END;

  -- 2. raw_payload immutability
  INSERT INTO raw_payload (run_id, endpoint, label, requested_at, request_url,
                           http_status, body, body_sha256, body_bytes)
  VALUES ('11111111-1111-1111-1111-111111111111','device/real_time','t',now(),
          'https://api.ecowitt.net/x?application_key=REDACTED&api_key=REDACTED',
          200,'{}'::jsonb,'\x00'::bytea,2);
  BEGIN
    UPDATE raw_payload SET http_status = 500;
    RAISE WARNING '2. append-only trigger -> NOT ENFORCED (mutation accepted)';
  EXCEPTION WHEN raise_exception THEN
    RAISE NOTICE '2. append-only trigger -> rejected, as required';
  END;

  -- 3. circular metric with a linear resample rule
  BEGIN
    INSERT INTO metric_catalog VALUES ('bad.dir','circular','º','mean',true,null);
    RAISE WARNING '3. circular=vector_mean -> NOT ENFORCED (linear accepted)';
  EXCEPTION WHEN check_violation THEN
    RAISE NOTICE '3. circular=vector_mean -> rejected, as required';
  END;

  -- 4. status metric marked resamplable
  BEGIN
    INSERT INTO metric_catalog VALUES ('bad.status','status','','last',true,null);
    RAISE WARNING '4. status not resamplable -> NOT ENFORCED';
  EXCEPTION WHEN check_violation THEN
    RAISE NOTICE '4. status not resamplable -> rejected, as required';
  END;

  -- 5. a 5min run claiming success without measuring spacing
  BEGIN
    INSERT INTO run_log (run_id, trigger, mode, cycle_type, status, started_at, ended_at)
    VALUES ('22222222-2222-2222-2222-222222222222','scheduled','incremental',
            '5min','succeeded', now(), now());
    RAISE WARNING '5. 5min spacing verified -> NOT ENFORCED (silent downgrade recordable)';
  EXCEPTION WHEN check_violation THEN
    RAISE NOTICE '5. 5min spacing verified -> rejected, as required';
  END;

  -- 6. change_log row where nothing changed
  BEGIN
    INSERT INTO change_log (station_id, ts_utc, metric, old_value, new_value,
                            old_unit, new_unit, run_id, reason)
    VALUES ('s',now(),'outdoor.temperature','70','70','ºF','ºF',
            '11111111-1111-1111-1111-111111111111','blind upsert');
    RAISE WARNING '6. change_log real change -> NOT ENFORCED';
  EXCEPTION WHEN check_violation THEN
    RAISE NOTICE '6. change_log real change -> rejected, as required';
  END;
END $$;

ROLLBACK;
