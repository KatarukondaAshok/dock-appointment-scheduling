# Data dictionary
Generated from `dock_scheduling/schema.py`. All timestamps are ISO-8601 local time (naive). Units: minutes, pallets, kg, deg C.

## Relationships and cardinality
| Parent | Child | Cardinality | Optional? | Notes |
|---|---|---|---|---|
| facility | dock / yard_slot / labor_shift | 1:N | no | dock and yard IDs embed the facility ID |
| carrier | vehicle | 1:N | no | |
| carrier <-> facility | carrier_facility (bridge) | N:M | no | effective-dated approval; appointments only for approved pairs |
| facility, carrier | appointment | 1:N | no | |
| dock, yard_slot, vehicle | appointment | 1:N | yes (null when REJECTED) | dock capacity 1; no overlap in valid data |
| appointment | shipment | 1:1 | no | shipment carries the handling requirement |
| handling_requirement | shipment | 1:N | no | |
| appointment | check_in_event | 1:N | no | append-only; state changes never overwrite history |
| appointment | exception_record | 1:N | yes | every exception has a cause code |

Lifecycle states (appointment.status, derived from last event): SCHEDULED -> COMPLETED | NO_SHOW; REJECTED (terminal at creation).
Event order: SCHEDULED, CHECK_IN, SERVICE_START, SERVICE_END, DEPARTED (or SCHEDULED, NO_SHOW).
`[U]` in a rule = unique constraint besides the primary key.

## facility  (PK: facility_id)
| Field | Type | Required | Rule / allowed values / units | FK |
|---|---|---|---|---|
| facility_id | TEXT | Y | FAC-NNN; unique; immutable |  |
| name | TEXT | Y | display name |  |
| city | TEXT | Y | free text |  |
| timezone | TEXT | Y | IANA tz name |  |
| open_time | TEXT | Y | HH:MM local; < close_time |  |
| close_time | TEXT | Y | HH:MM local |  |
| effective_from | TEXT | Y | ISO date; <= first appointment date |  |
| status | TEXT | Y | enum:ACTIVE / INACTIVE |  |

## dock  (PK: dock_id)
| Field | Type | Required | Rule / allowed values / units | FK |
|---|---|---|---|---|
| dock_id | TEXT | Y | DOCK-<facility_id>-NNN; unique |  |
| facility_id | TEXT | Y | parent facility | facility.facility_id |
| dock_type | TEXT | Y | enum:INBOUND / OUTBOUND / BOTH; direction handled |  |
| supports_reefer | INTEGER | Y | enum:0 / 1; 1 = refrigerated-capable |  |
| supports_hazmat | INTEGER | Y | enum:0 / 1; 1 = hazmat-capable |  |
| max_concurrent_trucks | INTEGER | Y | trucks; fixed 1 (capacity rule) |  |
| effective_from | TEXT | Y | ISO date |  |
| status | TEXT | Y | enum:ACTIVE / INACTIVE |  |

## yard_slot  (PK: yard_slot_id)
| Field | Type | Required | Rule / allowed values / units | FK |
|---|---|---|---|---|
| yard_slot_id | TEXT | Y | YARD-<facility_id>-NNN; unique |  |
| facility_id | TEXT | Y | parent facility | facility.facility_id |
| slot_type | TEXT | Y | enum:STANDARD / REEFER / HAZMAT |  |
| status | TEXT | Y | enum:ACTIVE / INACTIVE |  |

## carrier  (PK: carrier_id)
| Field | Type | Required | Rule / allowed values / units | FK |
|---|---|---|---|---|
| carrier_id | TEXT | Y | CAR-NNN; unique |  |
| name | TEXT | Y | free text |  |
| scac_code | TEXT | Y | [U] carrier code |  |
| effective_from | TEXT | Y | ISO date |  |
| status | TEXT | Y | enum:ACTIVE / INACTIVE |  |

## carrier_facility  (PK: carrier_id, facility_id, effective_from)
| Field | Type | Required | Rule / allowed values / units | FK |
|---|---|---|---|---|
| carrier_id | TEXT | Y | bridge N:M carrier<->facility | carrier.carrier_id |
| facility_id | TEXT | Y | bridge N:M | facility.facility_id |
| effective_from | TEXT | Y | ISO date approval start |  |
| effective_to | TEXT | N | ISO date; null = open-ended |  |

## vehicle  (PK: vehicle_id)
| Field | Type | Required | Rule / allowed values / units | FK |
|---|---|---|---|---|
| vehicle_id | TEXT | Y | VEH-NNNN; unique |  |
| carrier_id | TEXT | Y | owning carrier | carrier.carrier_id |
| vehicle_type | TEXT | Y | enum:DRY_VAN / REEFER_TRAILER |  |
| hazmat_certified | INTEGER | Y | enum:0 / 1 |  |
| plate_no | TEXT | Y | synthetic plate |  |
| capacity_pallets | INTEGER | Y | pallets |  |
| status | TEXT | Y | enum:ACTIVE / INACTIVE |  |

## handling_requirement  (PK: requirement_id)
| Field | Type | Required | Rule / allowed values / units | FK |
|---|---|---|---|---|
| requirement_id | TEXT | Y | HR-NNN; unique |  |
| requirement_code | TEXT | Y | [U] enum:DRY / REEFER / HAZMAT |  |
| base_service_min | INTEGER | Y | minutes fixed service time |  |
| per_pallet_min | REAL | Y | minutes per pallet |  |
| labor_required | INTEGER | Y | workers held for the whole service window |  |
| needs_reefer_dock | INTEGER | Y | enum:0 / 1 |  |
| needs_hazmat_dock | INTEGER | Y | enum:0 / 1 |  |
| yard_slot_type | TEXT | Y | enum:STANDARD / REEFER / HAZMAT |  |

## appointment  (PK: appointment_id)
| Field | Type | Required | Rule / allowed values / units | FK |
|---|---|---|---|---|
| appointment_id | TEXT | Y | APPT-2026-NNNNNN; unique; numbered by request creation time |  |
| facility_id | TEXT | Y | facility | facility.facility_id |
| dock_id | TEXT | N | null when REJECTED; dock must belong to facility | dock.dock_id |
| yard_slot_id | TEXT | N | null when REJECTED | yard_slot.yard_slot_id |
| carrier_id | TEXT | Y | must be approved at facility | carrier.carrier_id |
| vehicle_id | TEXT | N | null when REJECTED; must belong to carrier | vehicle.vehicle_id |
| direction | TEXT | Y | enum:INBOUND / OUTBOUND |  |
| requested_start | TEXT | Y | ISO datetime; start of 4h request window |  |
| requested_end | TEXT | Y | ISO datetime; > requested_start |  |
| scheduled_start | TEXT | N | ISO datetime within facility hours; null when REJECTED |  |
| scheduled_end | TEXT | N | start + planned_service_min |  |
| planned_service_min | INTEGER | Y | minutes = ceil((base+per_pallet*pallets)/15)*15 (derived) |  |
| created_ts | TEXT | Y | ISO datetime; < scheduled_start |  |
| status | TEXT | Y | enum:SCHEDULED / COMPLETED / NO_SHOW / REJECTED; derived from last event |  |

## shipment  (PK: shipment_id)
| Field | Type | Required | Rule / allowed values / units | FK |
|---|---|---|---|---|
| shipment_id | TEXT | Y | SHP-2026-NNNNNN; unique |  |
| appointment_id | TEXT | Y | [U] 1:1 with appointment | appointment.appointment_id |
| requirement_id | TEXT | Y | handling requirement | handling_requirement.requirement_id |
| pallets | INTEGER | Y | pallets 4..26 |  |
| weight_kg | INTEGER | Y | kg > 0 |  |
| temperature_setpoint_c | INTEGER | N | deg C; required iff REEFER |  |
| hazmat_class | TEXT | N | UN class; required iff HAZMAT |  |

## labor_shift  (PK: shift_id)
| Field | Type | Required | Rule / allowed values / units | FK |
|---|---|---|---|---|
| shift_id | TEXT | Y | SHIFT-<facility_id>-YYYYMMDD-<A / B>; unique |  |
| facility_id | TEXT | Y | facility | facility.facility_id |
| shift_date | TEXT | Y | ISO date |  |
| shift_code | TEXT | Y | enum:A / B |  |
| start_time | TEXT | Y | HH:MM |  |
| end_time | TEXT | Y | HH:MM |  |
| headcount | INTEGER | Y | workers; 0 iff CANCELLED |  |
| status | TEXT | Y | enum:ACTIVE / CANCELLED |  |

## check_in_event  (PK: event_id)
| Field | Type | Required | Rule / allowed values / units | FK |
|---|---|---|---|---|
| event_id | TEXT | Y | CHECK-<appointment_id>-NN; unique; append-only history |  |
| appointment_id | TEXT | Y | appointment | appointment.appointment_id |
| event_seq | INTEGER | Y | 1..n contiguous per appointment |  |
| event_type | TEXT | Y | enum:SCHEDULED / CHECK_IN / SERVICE_START / SERVICE_END / DEPARTED / NO_SHOW / REJECTED |  |
| event_ts | TEXT | Y | ISO datetime; non-decreasing in event_seq |  |

## exception_record  (PK: exception_id)
| Field | Type | Required | Rule / allowed values / units | FK |
|---|---|---|---|---|
| exception_id | TEXT | Y | EXC-2026-NNNNNN; unique |  |
| appointment_id | TEXT | Y | appointment | appointment.appointment_id |
| cause_code | TEXT | Y | enum:NO_SHOW / EARLY_ARRIVAL / LATE_ARRIVAL / CONGESTION_DELAY / REJECTED_NO_CAPACITY / OVERLAP_CAPACITY / INCOMPATIBLE_LOAD / CHECKIN_BEFORE_DATE / LABOR_UNAVAILABLE / NOSHOW_UNRECORDED |  |
| severity | TEXT | Y | enum:INFO / WARN / CRITICAL |  |
| detected_by | TEXT | Y | enum:SIMULATION / RULE_ENGINE |  |
| detected_ts | TEXT | Y | ISO datetime |  |
| details | TEXT | Y | human-readable cause |  |
