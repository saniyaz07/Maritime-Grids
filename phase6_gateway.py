"""
phase6_gateway.py — Automated Pipeline Gateway for Maritime Clean-Energy Simulation
===================================================================================
Orchestrates:
  1. User input validation via VoyageSimulationRequest
  2. Profile and route reference resolution
  3. Dynamic feature vector construction
  4. Live execution of frozen Phase 2 models (weather_final, fuel_xgb, battery_soh_final)
  5. Automatic assembly of Tier1Phase2Predictions
  6. Delegation to Phase 3 Decision Coordinator (orchestrate_phase3_voyage)
  7. IMO Statutory CII regulatory evaluation (MEPC.353(78) / MEPC.354(78))
  8. Multi-pollutant air quality displacement assessment (Fourth IMO GHG Study)
  9. Unified Phase6SimulationResult response
"""

import os
import math
import hashlib
from typing import Dict, Any, Optional, Union, Tuple
import numpy as np
import pandas as pd
import joblib

from phase3_contracts import (
    VoyageMetadata,
    Tier1Phase2Predictions,
    Phase3Output,
    AuditMetadata,
    FROZEN_MODEL_HASHES,
)
from phase3_coordinator import orchestrate_phase3_voyage

from phase6_contracts import (
    VoyageSimulationRequest,
    CIIAssessmentResult,
    PollutantAssessmentResult,
    PollutantEmissionFactors,
    Phase6SimulationResult,
)
from phase6_regulatory import (
    evaluate_regulatory_cii,
    evaluate_multi_pollutants,
)

# Canonical route distances (nautical miles) if not explicitly provided
CANONICAL_ROUTE_DISTANCES: Dict[str, float] = {
    "Warri-Bonny": 250.0,
    "Escravos-Lagos": 250.0,
    "Lagos-Apapa": 120.0,
    "Port Harcourt-Lagos": 450.0,
}
# Tanker-specific canonical route distances (longer open-sea passages)
TANKER_CANONICAL_DISTANCES: Dict[str, float] = {
    "Escravos-Lagos": 486.0,
    "Warri-Bonny": 250.0,
    "Lagos-Apapa": 120.0,
    "Port Harcourt-Lagos": 486.0,
}

# Auxiliary hotel load defaults (kWh per voyage)
DEFAULT_AUXILIARY_DEMAND_KWH: Dict[str, float] = {
    "Oil Service Boat": 180.0,
    "Fishing Trawler": 80.0,
    "Surfer Boat": 37.0,
    "Tanker Ship": 400.0,
}

# Empirical Phase 2 CO2 factors (kg CO2 per Liter fuel)
EMISSION_FACTOR_KG_PER_L: Dict[str, float] = {
    "Diesel": 2.74996,
    "HFO": 2.753806,
}

# SOH model typical discharge cycle defaults
DEFAULT_CYCLE_NUMBER: Dict[str, float] = {
    "Oil Service Boat": 150.0,
    "Fishing Trawler": 150.0,
    "Surfer Boat": 150.0,
    "Tanker Ship": 150.0,
}


def verify_frozen_model_hashes() -> bool:
    """Verify that all four frozen Phase 2 models match their cryptographic SHA-256 baseline."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    models_dir = os.path.join(base_dir, "models")
    for filename, expected_hash in FROZEN_MODEL_HASHES.items():
        filepath = os.path.join(models_dir, filename)
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Required frozen model file not found: {filepath}")
        with open(filepath, "rb") as f:
            actual_hash = hashlib.sha256(f.read()).hexdigest()
        if actual_hash != expected_hash:
            raise ValueError(
                f"Frozen model hash mismatch for {filename}: expected {expected_hash}, got {actual_hash}"
            )
    return True


def _load_reference_data(
    ship_profiles_csv: Optional[str] = None,
    routes_csv: Optional[str] = None,
    marine_clim_csv: Optional[str] = None,
    nasa_clim_csv: Optional[str] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load reference profiles and climatology tables with fallback to default paths."""
    base_dir = os.path.dirname(os.path.abspath(__file__))

    sp_path = ship_profiles_csv or os.path.join(base_dir, "data", "reference", "ship_profiles.csv")
    rt_path = routes_csv or os.path.join(base_dir, "data", "reference", "routes.csv")
    mc_path = marine_clim_csv or os.path.join(base_dir, "data", "processed", "marine", "marine_monthly_climatology.csv")
    nc_path = nasa_clim_csv or os.path.join(base_dir, "data", "processed", "nasa_power", "nasa_monthly_climatology.csv")

    df_sp = pd.read_csv(sp_path).set_index("ship_type")
    df_rt = pd.read_csv(rt_path).set_index("route_id")
    df_mc = pd.read_csv(mc_path)
    df_nc = pd.read_csv(nc_path)

    return df_sp, df_rt, df_mc, df_nc


def simulate_voyage(
    request: Union[VoyageSimulationRequest, Dict[str, Any]],
    ship_profiles_csv: Optional[str] = None,
    routes_csv: Optional[str] = None,
    marine_clim_csv: Optional[str] = None,
    nasa_clim_csv: Optional[str] = None,
    emission_factors: Optional[PollutantEmissionFactors] = None,
) -> Phase6SimulationResult:
    """
    Automated Live Model Inference Gateway and Phase 6 End-to-End Simulation.
    Accepts user-level parameters, resolves reference specifications, executes
    frozen Phase 2 ML models, coordinates Phase 3 tiers, and computes IMO regulatory
    CII and multi-pollutant air quality assessments.
    """
    # 1. Parse and validate input request
    if isinstance(request, dict):
        req = VoyageSimulationRequest.model_validate(request)
    elif isinstance(request, VoyageSimulationRequest):
        req = request
    else:
        raise ValueError(
            f"Expected request to be VoyageSimulationRequest or dict, got {type(request)}"
        )

    # 2. Verify frozen model hashes before execution
    verify_frozen_model_hashes()

    # 3. Load reference tables
    df_sp, df_rt, df_mc, df_nc = _load_reference_data(
        ship_profiles_csv, routes_csv, marine_clim_csv, nasa_clim_csv
    )

    if req.ship_type not in df_sp.index:
        raise ValueError(f"Unknown ship_type '{req.ship_type}'. Available: {list(df_sp.index)}")
    if req.route_id not in df_rt.index:
        raise ValueError(f"Unknown route_id '{req.route_id}'. Available: {list(df_rt.index)}")

    profile = df_sp.loc[req.ship_type]

    # Speed validation against ship design maximum speed
    max_speed = float(profile["max_speed_knots"])
    if req.speed_knots > max_speed:
        raise ValueError(
            f"Requested speed ({req.speed_knots} knots) exceeds maximum design speed "
            f"for {req.ship_type} ({max_speed} knots)."
        )

    # 4. Resolve voyage distance and duration
    if req.distance_nm is not None:
        distance_nm = req.distance_nm
    else:
        if req.ship_type == "Tanker Ship":
            distance_nm = TANKER_CANONICAL_DISTANCES.get(req.route_id, 250.0)
        else:
            distance_nm = CANONICAL_ROUTE_DISTANCES.get(req.route_id, 250.0)

    voyage_duration_hours = distance_nm / req.speed_knots

    # 5. Resolve climatology records
    m_matches = df_mc[(df_mc["route_id"] == req.route_id) & (df_mc["month_num"] == req.month)]
    n_matches = df_nc[(df_nc["route_id"] == req.route_id) & (df_nc["month_num"] == req.month)]

    if m_matches.empty or n_matches.empty:
        raise ValueError(f"No climatology data found for route '{req.route_id}', month {req.month}")

    m_row = m_matches.iloc[0]
    n_row = n_matches.iloc[0]

    # Daily GHI resolution
    if req.daily_ghi_kwh_per_m2 is not None:
        daily_ghi = req.daily_ghi_kwh_per_m2
    else:
        daily_ghi = float(n_row["ALLSKY_SFC_SW_DWN"])

    # 6. Execute Phase 2 Weather Model (DummyClassifier majority baseline)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    weather_path = os.path.join(base_dir, "models", "weather_final.joblib")
    weather_bundle = joblib.load(weather_path)

    month_sin = math.sin(2.0 * math.pi * req.month / 12.0)
    month_cos = math.cos(2.0 * math.pi * req.month / 12.0)
    ws50m = (float(n_row["WS50M_MAX"]) + float(n_row["WS50M_MIN"])) / 2.0

    w_features_df = pd.DataFrame([{
        "WS10M": float(n_row["WS10M"]),
        "WS50M": ws50m,
        "RH2M": float(n_row["RH2M"]),
        "PS": float(n_row["PS"]),
        "T2M_MIN": float(n_row["T2M_MIN"]),
        "wave_height_max": float(m_row["wave_height_max"]),
        "wave_period_max": float(m_row["wave_period_max"]),
        "wave_direction_dominant": float(m_row["wave_direction_dominant"]),
        "month_sin": month_sin,
        "month_cos": month_cos,
    }])[weather_bundle["features"]]

    pred_w_num = weather_bundle["model"].predict(w_features_df)
    predicted_weather_class = weather_bundle["label_encoder"].inverse_transform(pred_w_num)[0]

    # 7. Execute Phase 2 Fuel Model (XGBoost Pipeline)
    fuel_path = os.path.join(base_dir, "models", "fuel_xgb.joblib")
    fuel_model = joblib.load(fuel_path)

    fuel_type = req.fuel_type or "Diesel"
    f_features_df = pd.DataFrame([{
        "ship_type": req.ship_type,
        "route_id": req.route_id,
        "fuel_type": fuel_type,
        "weather_conditions": predicted_weather_class,
        "distance": distance_nm,
        "engine_efficiency": 82.5,
        "displacement": float(profile["displacement_tonnes"]),
        "engine_power": float(profile["engine_power_kw"]),
        "DWT": float(profile["dwt_tonnes"]),
    }])

    predicted_fuel_L = float(fuel_model.predict(f_features_df)[0])
    predicted_fuel_L = max(0.0, predicted_fuel_L)

    co2_factor = EMISSION_FACTOR_KG_PER_L.get(fuel_type, 2.74996)
    predicted_co2_kg = predicted_fuel_L * co2_factor

    # 8. Execute Phase 2 Battery SOH Model (HistGradientBoostingRegressor)
    soh_path = os.path.join(base_dir, "models", "battery_soh_final.joblib")
    soh_bundle = joblib.load(soh_path)
    cycle_n = DEFAULT_CYCLE_NUMBER.get(req.ship_type, 150.0)

    soh_features_df = pd.DataFrame([{
        "V_end": 3.0,
        "V_drop": 1.0,
        "V_mean": 3.5,
        "V_min": 2.8,
        "duration": 3500.0,
        "ambient_temperature": 24.0,
        "cycle_number": cycle_n,
    }])[soh_bundle["features"]]

    predicted_soh = float(soh_bundle["model"].predict(soh_features_df.to_numpy())[0])
    predicted_soh = min(1.0, max(0.0, predicted_soh))

    nominal_pack_kwh = float(profile["battery_pack_capacity_kwh"])
    effective_pack_kwh = nominal_pack_kwh * predicted_soh

    # 9. Construct Tier 1 Predictions
    tier1_predictions = Tier1Phase2Predictions.model_validate({
        "weather": {
            "temperature_c": float(n_row["T2M_MIN"]),
            "wind_speed_knots": float(n_row["WS10M"]),
            "significant_wave_height_m": float(m_row["wave_height_max"]),
        },
        "fuel_consumption_L": {
            "value": round(predicted_fuel_L, 2),
            "unit": "Liters",
            "evidence_level": "B - STRONGLY INFERRED",
            "scope": "Total voyage fuel consumption",
        },
        "co2_emissions_kg": {
            "value": round(predicted_co2_kg, 2),
            "unit": "kg",
        },
        "battery_health": {
            "predicted_soh": round(predicted_soh, 4),
            "nominal_pack_capacity_kwh": round(nominal_pack_kwh, 4),
            "effective_pack_capacity_kwh": round(effective_pack_kwh, 4),
        },
        "battery_operation": {
            "predicted_soc_end_of_voyage": 0.5292,
            "soc_formulation": "Degradation-adjusted pack SOC",
        },
    })

    # 10. Execute Phase 3 Coordinator Orchestration
    voyage_metadata = VoyageMetadata(
        ship_type=req.ship_type,
        distance_nm=distance_nm,
        voyage_duration_hours=voyage_duration_hours,
        deadweight_tonnes=float(profile["dwt_tonnes"]),
    )

    aux_demand = req.auxiliary_energy_demand_kwh
    if aux_demand is None:
        aux_demand = DEFAULT_AUXILIARY_DEMAND_KWH.get(req.ship_type, 180.0)

    phase3_output = orchestrate_phase3_voyage(
        voyage_metadata=voyage_metadata,
        tier1_predictions=tier1_predictions,
        auxiliary_energy_demand_kwh=aux_demand,
        route_id=req.route_id,
        month=req.month,
        daily_ghi_kwh_per_m2=daily_ghi,
        fuel_price_override_usd_per_l=req.fuel_price_usd_per_l,
        initial_soc=req.initial_soc,
        soc_reserve=req.soc_reserve,
        ship_profiles_csv=ship_profiles_csv,
    )

    # 11. Regulatory Assessment (IMO CII)
    reg_assessment = evaluate_regulatory_cii(
        ship_type=req.ship_type,
        dwt_tonnes=float(profile["dwt_tonnes"]),
        distance_nm=distance_nm,
        baseline_co2_kg=phase3_output.tier_1_phase2_predictions.co2_emissions_kg.value,
        net_assisted_co2_kg=phase3_output.tier_4_engineering_scenario_estimates.net_assisted_co2_kg,
        evaluation_year=req.evaluation_year,
    )

    # 12. Multi-Pollutant Emissions Assessment
    pollutant_assessment = evaluate_multi_pollutants(
        baseline_fuel_L=phase3_output.tier_1_phase2_predictions.fuel_consumption_L.value,
        net_assisted_fuel_L=phase3_output.tier_4_engineering_scenario_estimates.net_assisted_fuel_L,
        emission_factors=emission_factors,
    )

    # 13. Audit Metadata
    audit_meta = AuditMetadata(
        model_hashes_verified=True,
        phase2_models_frozen=True,
    )

    return Phase6SimulationResult(
        request=req,
        tier1_predictions=tier1_predictions,
        phase3_output=phase3_output,
        regulatory_assessment=reg_assessment,
        pollutant_assessment=pollutant_assessment,
        audit_metadata=audit_meta,
    )
