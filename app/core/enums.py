"""
Module 478 - State Transition Governance Engine: state enum.

Source: AI Trading Platform Bible V63.0, Section 12 ("Module 478 - State
Transition Governance Engine"), states list at Section 12 / "Normal" and
"Failure/Protection" rows. SOURCE per the DPR's own Section 1.1
classification (explicitly stated in the uploaded document, not derived
or assumed).
"""
from enum import Enum


class SystemState(str, Enum):
    # --- Normal states ---
    INITIALISING = "INITIALISING"
    DATA_LOADING = "DATA_LOADING"
    DATA_VALIDATION = "DATA_VALIDATION"
    MARKET_ANALYSIS = "MARKET_ANALYSIS"
    RISK_CHECK = "RISK_CHECK"
    OPPORTUNITY_ANALYSIS = "OPPORTUNITY_ANALYSIS"
    PORTFOLIO_APPROVAL = "PORTFOLIO_APPROVAL"
    ORDER_GENERATION = "ORDER_GENERATION"
    ORDER_EXECUTION = "ORDER_EXECUTION"
    POSITION_MONITORING = "POSITION_MONITORING"
    POST_TRADE_ANALYSIS = "POST_TRADE_ANALYSIS"
    LEARNING_UPDATE = "LEARNING_UPDATE"
    SYSTEM_READY = "SYSTEM_READY"

    # --- Failure / protection states ---
    DATA_FAILURE = "DATA_FAILURE"
    BROKER_FAILURE = "BROKER_FAILURE"
    RISK_BREACH = "RISK_BREACH"
    MODEL_FAILURE = "MODEL_FAILURE"
    CAPITAL_PROTECTION_MODE = "CAPITAL_PROTECTION_MODE"
    HUMAN_OVERRIDE_REQUIRED = "HUMAN_OVERRIDE_REQUIRED"


NORMAL_STATES = frozenset(
    {
        SystemState.INITIALISING,
        SystemState.DATA_LOADING,
        SystemState.DATA_VALIDATION,
        SystemState.MARKET_ANALYSIS,
        SystemState.RISK_CHECK,
        SystemState.OPPORTUNITY_ANALYSIS,
        SystemState.PORTFOLIO_APPROVAL,
        SystemState.ORDER_GENERATION,
        SystemState.ORDER_EXECUTION,
        SystemState.POSITION_MONITORING,
        SystemState.POST_TRADE_ANALYSIS,
        SystemState.LEARNING_UPDATE,
        SystemState.SYSTEM_READY,
    }
)

FAILURE_STATES = frozenset(
    {
        SystemState.DATA_FAILURE,
        SystemState.BROKER_FAILURE,
        SystemState.RISK_BREACH,
        SystemState.MODEL_FAILURE,
        SystemState.CAPITAL_PROTECTION_MODE,
        SystemState.HUMAN_OVERRIDE_REQUIRED,
    }
)
