import re

with open("Script/daily_analysis.py", "r", encoding="utf-8") as f:
    content = f.read()

# Add new flow fields to results.append
old_append = """        results.append({
            "timestamp": row["timestamp"],
            "hour": row["hour"],
            "period": period,
            "pv": pv_power * dt,
            "storage_charging": storage_charging_kw * dt,
            "storage_discharging": storage_discharging_kw * dt,
            "factory_load": factory * dt,
            "charging_load": charging_load_kw * dt,
            "grid_import": grid_import_kw * dt,
            "grid_export": grid_export_kw * dt,
            "grid_cost": grid_cost,
            "charging_revenue": charging_revenue,
            "pv_grid_revenue": pv_grid_revenue,
            "net_profit": net_profit,
        })"""

new_append = """        pv_to_load = min(pv_power, total_load)
        pv_surplus = max(0, pv_power - total_load)
        pv_to_storaimport re

with open("Script/daily_analysis.py", "r", encoding="utf-, 
with opus     content = f.read()

# Add new flow fields to results.append
oal
# Add new flow fieldstoold_append = """        results.appendto            "timestamp": row["timestampto            "hour": row["hour"],
        ({            "period": period,
 ti            "pv": pv_power *":            "storage_charging":od            "storage_discharging": storage_discharging  "s            "factory_load": factory * dt,
            "charginge            "charging_load": charging_lodt            "grid_impy_load": factory * dt,
                    "grid_export": grid_export_kw * dt              "grid_cost": grid_cost,
                        "charging_revenue": ch_k            "pv_grid_revenue": pv_grid_revenue,
              "net_profit": net_profit,
                  })"""

new_append = """     ev
new_append            pv_surplus = max(0, pv_power - total_load)
        pvload * dt,
            "pv_to_storage": pv_to_storage
with open("Script/daily_anridwith opus     content = f.read()

# Add new flow fields toad
# Add new flow fields to resulragoal
# Add new flow fieldstoold_append "
# on        ({            "period": period,
 ti            "pv": pv_power *":            "storage_charging":od            "storage_dischargor ti            "pv": pv_power *":     rg            "charginge            "charging_load": charging_lodt            "grid_impy_load": factory * dt,
                    "grid_export": grid_export_kw * dt  ,                     "grid_export": grid_export_kw * dt              "grid_cost": grid_cost,
              ng                        "charging_revenue": ch_k            "pv_grid_revenue": pv_grid_revgr              "net_profit": net_profit,
                  })"""

new_append = """     ev
new_aeg                  })"""

new_append = rs
new_append = """     ge_new_aing": 0, "storage_d        pvload * dt,
            "pv_to_storage": pv_to_storagepo            "pv_to_t"with open("Script/daily_anridwith opus   0,
# Add new flow fields toad
# Add new flow fields to resulra   # Add new flow fields to st# Add new flow fieldstoold_append "rg# on        ({            "period"in ti            "pv": pv_power *":         ":                    "grid_export": grid_export_kw * dt  ,                     "grid_export": grid_export_kw * dt              "grid_cost": grid_cost,
              ng                        "charging_revenue": ch_k            "pv_grid_revenue"es              ng                        "charging_revenue": ch_k            "pv_grid_revenue": pv_grid_revgr              "net_profit": net_profit,
??                 })"""

new_append = """     ev
new_aeg                  })"""

new_append = rs
new_append = """     ge_new_aing": 0, "storage_d ?)
new_append = """     ??)new_aeg               ?(
new_append = rs
new_append =??)new_append = "?           "pv_to_storage": pv_to_storagepo            "pv_to_t"wi--# Add new flow fields toad
# Add new flow fields to resulra   # Add new flow fields to st# Add new flow fie--# Add new flow fields to ["              ng                        "charging_revenue": ch_k            "pv_grid_revenue"es              ng                        "charging_revenue": ch_k            "pv_grid_revenue": pv_grid_revgr              "net_profit": net_profit,
??                 })"""

new_append = """     ev
new_aeg                  })"""

n} ??                 })"""

new_append = """     ev
new_aeg                  })"""

new_append = rs
new_append = """     ge_new_aing": 0, "storage_d ?)
new_append = """     ??)new_aeg               ?(
new_append = rs
new_append =??)new_append ?new_append = """     入?ew_aeg             ?网
new_append = rs
new_append =|:-new_append = "--new_append = """     ??)new_aeg               ?(
n
 new_append = rs
new_append =??)new_append = "?lnew_append =??| # Add new flow fields to resulra   # Add new flow fields to st# Add new flow fie--# Add new flow fields to ["              ng]:??                 })"""

new_append = """     ev
new_aeg                  })"""

n} ??                 })"""

new_append = """     ev
new_aeg                  })"""

new_append = rs
new_append = """     ge_new_aing": 0, "storage_d ?)
new_append = """     ??)new_aeg               ?(
new_append = rs
new_append =??)new_append ?new_append = """    es
new_append = """     evp[new_aeg .3