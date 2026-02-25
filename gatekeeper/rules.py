REQUIRED_SLOTS_BY_INTENT = {
    "aggregation" : ["metric", "time_range"],
    "listing": ["time_range"], 
    "comparison":  ["time_range"], 
}

DEFAULTS = {
    "filters": {"transaction_status": "approved"}
}