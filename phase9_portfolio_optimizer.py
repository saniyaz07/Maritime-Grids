"""
phase9_portfolio_optimizer.py — Phase 9 Candidate 3
====================================================
Fleet Portfolio Decarbonization Capital Allocation Engine

Implements the CO₂-maximizing capital allocation layer that operates on
pre-evaluated Phase 8 OptimizationCandidate objects.

Architectural boundaries:
  - Candidate 3 is an orchestration/aggregation layer ONLY.
  - It does NOT call optimize_system_sizing() — never invokes the full Phase 8
    discrete lattice search.
  - It does NOT call Phase 9 Candidate 1 (sensitivity) or Candidate 2 (speed
    co-optimizer).
  - It does NOT reimplement NPV, IRR, LCOE, cash flows, fuel models, CO₂
    conversion, physical feasibility, or battery degradation.
  - It operates on at most K=4 representative canonical vessel archetypes,
    producing at most 2^4 = 16 portfolio subsets to enumerate.

Primary reference:
  Brute-force exhaustive subset enumeration over pre-evaluated candidates.
  Tractable because K ≤ 4 and at most one candidate per vessel key is selected,
  so the combination space is at most 2^K = 16.

Tie-breaking (deterministic, documented):
  1. Higher total annual CO₂ displacement (primary objective — maximize)
  2. Lower total CAPEX
  3. Higher total NPV
  4. Lower number of selected retrofits
  5. Stable lexical ordering of selected vessel_ids (ascending)
"""

from itertools import combinations
from typing import Dict, List, Optional, Tuple

from phase9_portfolio_contracts import (
    DIAG_NO_ALLOCATION_WITHIN_CONSTRAINTS,
    DIAG_OPTIMAL_ALLOCATION,
    DIAG_ZERO_RETROFIT_ALLOCATION,
    PORTFOLIO_OBJECTIVE_MAX_CO2,
    PortfolioAllocationResult,
    PortfolioItem,
    PortfolioOptimizationParameters,
)


# ==============================================================================
# 1. Candidate Validity Filter
# ==============================================================================

def filter_eligible_portfolio_items(
    portfolio_items: List[PortfolioItem],
) -> Tuple[List[PortfolioItem], List[PortfolioItem]]:
    """
    Partition portfolio items into eligible and excluded sets.

    A portfolio item is eligible for allocation if and only if its underlying
    Phase 8 OptimizationCandidate satisfies all of:
      1. candidate_status == "VALID"
      2. is_physically_valid is True
      3. feasibility_status in ("FEASIBLE", "PARTIAL")

    Items that fail any condition are excluded and cannot enter allocation.
    This respects Phase 8 feasibility semantics without reimplementing them.

    Parameters
    ----------
    portfolio_items : list of PortfolioItem
        All candidate items supplied by the caller.

    Returns
    -------
    eligible : list of PortfolioItem
        Items that pass the Phase 8 validity gate.
    excluded : list of PortfolioItem
        Items that fail the Phase 8 validity gate.
    """
    eligible: List[PortfolioItem] = []
    excluded: List[PortfolioItem] = []

    for item in portfolio_items:
        cand = item.candidate
        is_valid = (
            cand.candidate_status == "VALID"
            and cand.is_physically_valid is True
            and cand.feasibility_status in ("FEASIBLE", "PARTIAL")
        )
        if is_valid:
            eligible.append(item)
        else:
            excluded.append(item)

    return eligible, excluded


# ==============================================================================
# 2. Mutual-Exclusion Grouping
# ==============================================================================

def group_items_by_vessel_id(
    eligible_items: List[PortfolioItem],
) -> Dict[str, List[PortfolioItem]]:
    """
    Group eligible portfolio items by vessel_id.

    Multiple candidates may exist for the same vessel_id (supplied by the
    caller), but at most one may be selected.  This function builds the
    per-vessel candidate pools used during portfolio enumeration.

    Parameters
    ----------
    eligible_items : list of PortfolioItem
        Items that passed the Phase 8 validity filter.

    Returns
    -------
    dict mapping vessel_id -> [PortfolioItem, ...]
        Preserves insertion order via dict (Python 3.7+).
    """
    groups: Dict[str, List[PortfolioItem]] = {}
    for item in eligible_items:
        if item.vessel_id not in groups:
            groups[item.vessel_id] = []
        groups[item.vessel_id].append(item)
    return groups


# ==============================================================================
# 3. Portfolio Subset Enumeration
# ==============================================================================

def _portfolio_sort_key(
    selected: List[PortfolioItem],
) -> Tuple:
    """
    Deterministic sort key for a candidate portfolio subset.

    Implements the mandated tie-breaking hierarchy:
      1. Higher total annual CO₂ displacement  → negate for ascending sort
      2. Lower total CAPEX                     → ascending
      3. Higher total NPV                      → negate for ascending sort
      4. Lower number of selected retrofits    → ascending
      5. Stable lexical vessel_ids (ascending) → tuple of sorted ids

    Using Python's tuple sort: each element must produce the desired ordering.
    All keys are assembled so that a standard min() picks the preferred subset.
    """
    total_co2 = sum(i.candidate.annual_co2_displaced_kg for i in selected)
    total_capex = sum(i.candidate.total_initial_capex_usd for i in selected)
    total_npv = sum(i.candidate.net_present_value_usd for i in selected)
    count = len(selected)
    vessel_ids_key = tuple(sorted(i.vessel_id for i in selected))

    return (
        -total_co2,      # descending CO₂ (negate → ascending key → max first)
        total_capex,     # ascending CAPEX
        -total_npv,      # descending NPV
        count,           # ascending count
        vessel_ids_key,  # lexical
    )


def enumerate_feasible_portfolios(
    vessel_groups: Dict[str, List[PortfolioItem]],
    params: PortfolioOptimizationParameters,
) -> Tuple[List[List[PortfolioItem]], int]:
    """
    Exhaustively enumerate all portfolio subsets, apply constraints, and return
    the feasible set together with the total number of subsets evaluated.

    The enumeration proceeds over the Cartesian space of (vessel → one candidate
    OR no candidate), so:
      - With K distinct vessel groups, the enumeration visits at most 2^K
        subsets (including the empty set).
      - For K=4, this is 16 subsets.
      - When a vessel has multiple eligible candidates, all are evaluated as
        separate single-candidate alternatives, but still only one per vessel
        may be included in any single portfolio subset.

    The enumeration is:
      1. For each vessel group, form candidates {none, item_0, item_1, …}.
      2. Take the Cartesian product across all vessel groups.
      3. For each combined selection, check:
         a. Total CAPEX ≤ total_portfolio_capex_budget_usd
         b. Number of selected retrofits ≤ max_retrofits (if specified)
         c. Sum CO₂ ≥ min_annual_co2_displaced_kg (if > 0 and non-empty)
         d. Sum fuel ≥ min_annual_fuel_displaced_L (if > 0 and non-empty)
      4. Keep feasible subsets.

    Note: the empty portfolio (no retrofits) satisfies CAPEX and max_retrofits
    constraints by definition but may fail minimum targets.  It is included in
    the feasible set only when no minimum targets are violated.

    Parameters
    ----------
    vessel_groups : dict
        vessel_id → list of eligible PortfolioItem objects.
    params : PortfolioOptimizationParameters
        Constraints.

    Returns
    -------
    feasible : list of (list of PortfolioItem)
        All constraint-satisfying subsets, including the empty portfolio when
        it satisfies minimum targets.
    total_evaluated : int
        Total number of subsets checked (for reporting).
    """
    budget = params.total_portfolio_capex_budget_usd
    max_r = params.max_retrofits
    min_co2 = params.min_annual_co2_displaced_kg
    min_fuel = params.min_annual_fuel_displaced_L

    # Build per-vessel option lists: [None] + [item, ...]
    # None means "do not retrofit this vessel"
    vessel_keys = list(vessel_groups.keys())
    option_lists: List[List[Optional[PortfolioItem]]] = []
    for key in vessel_keys:
        option_lists.append([None] + vessel_groups[key])

    feasible: List[List[PortfolioItem]] = []
    total_evaluated = 0

    # Recursive Cartesian product via index-based iteration
    # For K ≤ 4 and small per-vessel candidate counts, this is trivially fast
    def recurse(vessel_idx: int, current_selection: List[PortfolioItem]) -> None:
        nonlocal total_evaluated
        if vessel_idx == len(option_lists):
            # Evaluate this complete selection
            total_evaluated += 1
            selected = current_selection  # already a list copy from caller

            # Constraint: total CAPEX ≤ budget
            total_capex = sum(i.candidate.total_initial_capex_usd for i in selected)
            if total_capex > budget + 1e-9:  # epsilon for floating-point tolerance
                return

            # Constraint: max retrofits
            count = len(selected)
            if max_r is not None and count > max_r:
                return

            # Minimum targets apply only to non-empty portfolios
            if count > 0:
                total_co2 = sum(i.candidate.annual_co2_displaced_kg for i in selected)
                total_fuel = sum(i.candidate.annual_fuel_displaced_L for i in selected)
                if min_co2 > 0.0 and total_co2 < min_co2 - 1e-9:
                    return
                if min_fuel > 0.0 and total_fuel < min_fuel - 1e-9:
                    return

            feasible.append(list(selected))
            return

        # Branch: each option for the current vessel (None or one of its candidates)
        for option in option_lists[vessel_idx]:
            if option is None:
                recurse(vessel_idx + 1, current_selection)
            else:
                recurse(vessel_idx + 1, current_selection + [option])

    recurse(0, [])
    return feasible, total_evaluated


# ==============================================================================
# 4. Primary Public API
# ==============================================================================

def optimize_portfolio(
    portfolio_items: List[PortfolioItem],
    params: PortfolioOptimizationParameters,
) -> PortfolioAllocationResult:
    """
    Execute CO₂-maximizing fleet portfolio capital allocation.

    This is the primary entry point for Candidate 3.  It accepts pre-evaluated
    Phase 8 candidates wrapped in PortfolioItem objects and returns the optimal
    capital allocation.

    The function DOES NOT:
      - Call optimize_system_sizing (full Phase 8 grid search).
      - Call evaluate_single_sizing_candidate.
      - Call any Phase 9 Candidate 1 or Candidate 2 function.
      - Reimplement any financial or physical equation.

    Steps
    -----
    1. Filter eligible items (Phase 8 validity gate).
    2. Group by vessel_id (enforce mutual exclusion structure).
    3. Enumerate all portfolio subsets via exhaustive search.
    4. Apply constraints (CAPEX, max_retrofits, min_co2, min_fuel).
    5. Select the best feasible portfolio using deterministic tie-breaking.
    6. Aggregate metrics from selected items.
    7. Construct and validate PortfolioAllocationResult.

    Parameters
    ----------
    portfolio_items : list of PortfolioItem
        Pre-evaluated Phase 8 candidates with vessel identity context.
        May include multiple candidates per vessel_id.
    params : PortfolioOptimizationParameters
        Portfolio-level constraints and settings.

    Returns
    -------
    PortfolioAllocationResult
        Fully validated allocation result with aggregate metrics and diagnostics.
    """
    import time
    _t0 = time.perf_counter()

    warnings: List[str] = []

    # ── Step 1: Phase 8 validity filter ────────────────────────────────────────
    eligible, excluded = filter_eligible_portfolio_items(portfolio_items)

    excluded_count = len(excluded)
    if excluded_count > 0:
        warnings.append(
            f"{excluded_count} portfolio item(s) excluded: failed Phase 8 "
            f"validity gate (candidate_status != 'VALID', is_physically_valid != True, "
            f"or feasibility_status not in ('FEASIBLE', 'PARTIAL'))."
        )

    # ── Step 2: Group by vessel_id ──────────────────────────────────────────────
    vessel_groups = group_items_by_vessel_id(eligible)

    num_vessel_slots = len(vessel_groups)
    if num_vessel_slots == 0:
        # No eligible items at all — return zero-retrofit result
        return PortfolioAllocationResult(
            parameters=params,
            selected_items=[],
            total_capex_usd=0.0,
            total_annual_co2_displaced_kg=0.0,
            total_annual_fuel_displaced_L=0.0,
            total_npv_usd=0.0,
            selected_retrofit_count=0,
            portfolios_evaluated=0,
            eligible_items_count=0,
            excluded_items_count=excluded_count,
            diagnostics=DIAG_NO_ALLOCATION_WITHIN_CONSTRAINTS,
            warnings=warnings + ["No eligible candidates after Phase 8 validity filter."],
        )

    # Warn if multiple candidates for same vessel (multi-config)
    for vid, items in vessel_groups.items():
        if len(items) > 1:
            warnings.append(
                f"Vessel '{vid}' has {len(items)} eligible candidate(s); "
                f"at most one will be selected (mutual exclusion enforced)."
            )

    # ── Step 3–4: Exhaustive subset enumeration with constraint filtering ───────
    feasible_portfolios, portfolios_evaluated = enumerate_feasible_portfolios(
        vessel_groups, params
    )

    # Separate out the empty portfolio (it's always a subset of feasible if
    # no minimum targets fail)
    non_empty_feasible = [p for p in feasible_portfolios if len(p) > 0]

    # ── Step 5: Select optimal portfolio by deterministic tie-breaking ──────────
    if non_empty_feasible:
        # Sort by the tie-breaking key; the first element is the best.
        non_empty_feasible.sort(key=_portfolio_sort_key)
        best_portfolio = non_empty_feasible[0]
        diagnostics = DIAG_OPTIMAL_ALLOCATION
    else:
        # No non-empty portfolio satisfies the constraints.
        # The empty portfolio may or may not be in feasible_portfolios
        # depending on minimum targets.
        best_portfolio = []
        if len(feasible_portfolios) > 0:
            # Empty portfolio satisfies CAPEX and max_retrofits (0 ≤ any budget,
            # 0 ≤ any max_retrofits), but min targets prevent non-empty ones.
            diagnostics = DIAG_NO_ALLOCATION_WITHIN_CONSTRAINTS
        else:
            # Even the empty portfolio was rejected (should not happen in
            # practice since empty trivially satisfies CAPEX ≤ budget when
            # budget > 0, but guard anyway)
            diagnostics = DIAG_NO_ALLOCATION_WITHIN_CONSTRAINTS
            warnings.append(
                "Budget constraint or min targets prevented all subsets including "
                "empty portfolio from being feasible."
            )

    # Determine whether result is a zero-retrofit allocation
    if len(best_portfolio) == 0 and len(feasible_portfolios) > 0:
        # Empty set is the only feasible option (non-empty ones all violated
        # budget or max_retrofits)
        diagnostics = DIAG_NO_ALLOCATION_WITHIN_CONSTRAINTS

    # ── Step 6: Aggregate metrics ───────────────────────────────────────────────
    total_capex = sum(i.candidate.total_initial_capex_usd for i in best_portfolio)
    total_co2 = sum(i.candidate.annual_co2_displaced_kg for i in best_portfolio)
    total_fuel = sum(i.candidate.annual_fuel_displaced_L for i in best_portfolio)
    total_npv = sum(i.candidate.net_present_value_usd for i in best_portfolio)
    retrofit_count = len(best_portfolio)

    # ── Step 7: Performance note ────────────────────────────────────────────────
    elapsed = time.perf_counter() - _t0
    if elapsed > 1.0:
        warnings.append(
            f"Portfolio allocation completed in {elapsed:.3f}s, which exceeds "
            f"the expected sub-second runtime for K≤4 vessels."
        )

    return PortfolioAllocationResult(
        parameters=params,
        selected_items=best_portfolio,
        total_capex_usd=round(total_capex, 6),
        total_annual_co2_displaced_kg=round(total_co2, 6),
        total_annual_fuel_displaced_L=round(total_fuel, 6),
        total_npv_usd=round(total_npv, 6),
        selected_retrofit_count=retrofit_count,
        portfolios_evaluated=portfolios_evaluated,
        eligible_items_count=len(eligible),
        excluded_items_count=excluded_count,
        diagnostics=diagnostics,
        warnings=warnings,
    )


# ==============================================================================
# 5. Convenience Helpers
# ==============================================================================

def make_portfolio_item(
    vessel_id: str,
    ship_type: str,
    route_id: str,
    candidate,  # OptimizationCandidate
    annual_voyages: int = 52,
) -> PortfolioItem:
    """
    Convenience constructor for PortfolioItem.

    Useful in tests and integration scripts when building portfolio items from
    pre-evaluated Phase 8 candidates.  Does not call any Phase 8 evaluation.

    Parameters
    ----------
    vessel_id : str
        Unique vessel key within the portfolio.
    ship_type : str
        Must be one of SUPPORTED_PORTFOLIO_SHIP_TYPES.
    route_id : str
        Route at which the candidate was evaluated.
    candidate : OptimizationCandidate
        Pre-evaluated Phase 8 sizing candidate.
    annual_voyages : int
        Annual voyage count used when the candidate was evaluated.

    Returns
    -------
    PortfolioItem
    """
    return PortfolioItem(
        vessel_id=vessel_id,
        ship_type=ship_type,
        route_id=route_id,
        annual_voyages=annual_voyages,
        candidate=candidate,
    )
