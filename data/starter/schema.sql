CREATE TABLE facility (
  facility_id TEXT NOT NULL,
  name TEXT NOT NULL,
  city TEXT NOT NULL,
  timezone TEXT NOT NULL,
  open_time TEXT NOT NULL,
  close_time TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('ACTIVE','INACTIVE')),
  PRIMARY KEY(facility_id)
);
CREATE TABLE dock (
  dock_id TEXT NOT NULL,
  facility_id TEXT NOT NULL,
  dock_type TEXT NOT NULL CHECK(dock_type IN ('INBOUND','OUTBOUND','BOTH')),
  supports_reefer INTEGER NOT NULL CHECK(supports_reefer IN (0,1)),
  supports_hazmat INTEGER NOT NULL CHECK(supports_hazmat IN (0,1)),
  max_concurrent_trucks INTEGER NOT NULL,
  effective_from TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('ACTIVE','INACTIVE')),
  PRIMARY KEY(dock_id),
  FOREIGN KEY(facility_id) REFERENCES facility(facility_id)
);
CREATE TABLE yard_slot (
  yard_slot_id TEXT NOT NULL,
  facility_id TEXT NOT NULL,
  slot_type TEXT NOT NULL CHECK(slot_type IN ('STANDARD','REEFER','HAZMAT')),
  status TEXT NOT NULL CHECK(status IN ('ACTIVE','INACTIVE')),
  PRIMARY KEY(yard_slot_id),
  FOREIGN KEY(facility_id) REFERENCES facility(facility_id)
);
CREATE TABLE carrier (
  carrier_id TEXT NOT NULL,
  name TEXT NOT NULL,
  scac_code TEXT NOT NULL UNIQUE,
  effective_from TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('ACTIVE','INACTIVE')),
  PRIMARY KEY(carrier_id)
);
CREATE TABLE carrier_facility (
  carrier_id TEXT NOT NULL,
  facility_id TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  PRIMARY KEY(carrier_id,facility_id,effective_from),
  FOREIGN KEY(carrier_id) REFERENCES carrier(carrier_id),
  FOREIGN KEY(facility_id) REFERENCES facility(facility_id)
);
CREATE TABLE vehicle (
  vehicle_id TEXT NOT NULL,
  carrier_id TEXT NOT NULL,
  vehicle_type TEXT NOT NULL CHECK(vehicle_type IN ('DRY_VAN','REEFER_TRAILER')),
  hazmat_certified INTEGER NOT NULL CHECK(hazmat_certified IN (0,1)),
  plate_no TEXT NOT NULL,
  capacity_pallets INTEGER NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('ACTIVE','INACTIVE')),
  PRIMARY KEY(vehicle_id),
  FOREIGN KEY(carrier_id) REFERENCES carrier(carrier_id)
);
CREATE TABLE handling_requirement (
  requirement_id TEXT NOT NULL,
  requirement_code TEXT NOT NULL UNIQUE CHECK(requirement_code IN ('DRY','REEFER','HAZMAT')),
  base_service_min INTEGER NOT NULL,
  per_pallet_min REAL NOT NULL,
  labor_required INTEGER NOT NULL,
  needs_reefer_dock INTEGER NOT NULL CHECK(needs_reefer_dock IN (0,1)),
  needs_hazmat_dock INTEGER NOT NULL CHECK(needs_hazmat_dock IN (0,1)),
  yard_slot_type TEXT NOT NULL CHECK(yard_slot_type IN ('STANDARD','REEFER','HAZMAT')),
  PRIMARY KEY(requirement_id)
);
CREATE TABLE appointment (
  appointment_id TEXT NOT NULL,
  facility_id TEXT NOT NULL,
  dock_id TEXT,
  yard_slot_id TEXT,
  carrier_id TEXT NOT NULL,
  vehicle_id TEXT,
  direction TEXT NOT NULL CHECK(direction IN ('INBOUND','OUTBOUND')),
  requested_start TEXT NOT NULL,
  requested_end TEXT NOT NULL,
  scheduled_start TEXT,
  scheduled_end TEXT,
  planned_service_min INTEGER NOT NULL,
  created_ts TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('SCHEDULED','COMPLETED','NO_SHOW','REJECTED')),
  PRIMARY KEY(appointment_id),
  FOREIGN KEY(facility_id) REFERENCES facility(facility_id),
  FOREIGN KEY(dock_id) REFERENCES dock(dock_id),
  FOREIGN KEY(yard_slot_id) REFERENCES yard_slot(yard_slot_id),
  FOREIGN KEY(carrier_id) REFERENCES carrier(carrier_id),
  FOREIGN KEY(vehicle_id) REFERENCES vehicle(vehicle_id)
);
CREATE TABLE shipment (
  shipment_id TEXT NOT NULL,
  appointment_id TEXT NOT NULL UNIQUE,
  requirement_id TEXT NOT NULL,
  pallets INTEGER NOT NULL,
  weight_kg INTEGER NOT NULL,
  temperature_setpoint_c INTEGER,
  hazmat_class TEXT,
  PRIMARY KEY(shipment_id),
  FOREIGN KEY(appointment_id) REFERENCES appointment(appointment_id),
  FOREIGN KEY(requirement_id) REFERENCES handling_requirement(requirement_id)
);
CREATE TABLE labor_shift (
  shift_id TEXT NOT NULL,
  facility_id TEXT NOT NULL,
  shift_date TEXT NOT NULL,
  shift_code TEXT NOT NULL CHECK(shift_code IN ('A','B')),
  start_time TEXT NOT NULL,
  end_time TEXT NOT NULL,
  headcount INTEGER NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('ACTIVE','CANCELLED')),
  PRIMARY KEY(shift_id),
  FOREIGN KEY(facility_id) REFERENCES facility(facility_id)
);
CREATE TABLE check_in_event (
  event_id TEXT NOT NULL,
  appointment_id TEXT NOT NULL,
  event_seq INTEGER NOT NULL,
  event_type TEXT NOT NULL CHECK(event_type IN ('SCHEDULED','CHECK_IN','SERVICE_START','SERVICE_END','DEPARTED','NO_SHOW','REJECTED')),
  event_ts TEXT NOT NULL,
  PRIMARY KEY(event_id),
  FOREIGN KEY(appointment_id) REFERENCES appointment(appointment_id)
);
CREATE TABLE exception_record (
  exception_id TEXT NOT NULL,
  appointment_id TEXT NOT NULL,
  cause_code TEXT NOT NULL CHECK(cause_code IN ('NO_SHOW','EARLY_ARRIVAL','LATE_ARRIVAL','CONGESTION_DELAY','REJECTED_NO_CAPACITY','OVERLAP_CAPACITY','INCOMPATIBLE_LOAD','CHECKIN_BEFORE_DATE','LABOR_UNAVAILABLE','NOSHOW_UNRECORDED')),
  severity TEXT NOT NULL CHECK(severity IN ('INFO','WARN','CRITICAL')),
  detected_by TEXT NOT NULL CHECK(detected_by IN ('SIMULATION','RULE_ENGINE')),
  detected_ts TEXT NOT NULL,
  details TEXT NOT NULL,
  PRIMARY KEY(exception_id),
  FOREIGN KEY(appointment_id) REFERENCES appointment(appointment_id)
);
