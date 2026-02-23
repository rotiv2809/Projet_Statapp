REQUIRED_SLOTS_BY_INTENT = {
    "aggregation" : ["metric", "time_range"], #total amount in the period
    "listing": ["time_range"], #for listing we need the period
    "comparison":  ["time_range"], #same (but 2)
}

DEFAULTS = {
    #if there is a default rule, ex: status= "approved"
    "filters": {"transaction_status": "approved"}
}