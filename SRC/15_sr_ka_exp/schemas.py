"""
Shared schema definitions for Karnataka Budget Extraction
==========================================================
This module contains the standard CSV schemas used across the extraction pipeline.
These schemas are used for validation, cleaning, and combining CSVs.

All schemas follow the hierarchical budget structure:
- Sub-Major Head (16 cols)
- Minor Head (18 cols)
- Sub-Head (20 cols)
- Detailed Head (22 cols)
- Object Head (24 cols - most granular)

Usage:
    from schemas import SUB_MAJOR_HEAD_SCHEMA, MINOR_HEAD_SCHEMA, SUB_HEAD_SCHEMA, DETAILED_HEAD_SCHEMA, OBJECT_HEAD_SCHEMA
"""

# Schema for Sub-Major Head Summary CSV (16 columns)
SUB_MAJOR_HEAD_SCHEMA = [
    "Source_Page_Number", "Volume_Number", "Demand_Number", "Major_Head_Code",
    "Major_Head_Name", "Sub_Major_Head_Code", "Sub_Major_Head_Name",
    "Full_Account_Code", "Description", "Vote_Charge_Marker", "Row_Type",
    "Row_Level", "Accounts_2018_19", "Budget_2019_20", "Revised_2019_20",
    "Budget_2020_21"
]

# Schema for Minor Head Summary CSV (18 columns)
MINOR_HEAD_SCHEMA = [
    "Source_Page_Number", "Volume_Number", "Demand_Number", "Major_Head_Code",
    "Major_Head_Name", "Sub_Major_Head_Code", "Sub_Major_Head_Name",
    "Minor_Head_Code", "Minor_Head_Name", "Full_Account_Code", "Description",
    "Vote_Charge_Marker", "Row_Type", "Row_Level", "Accounts_2018_19",
    "Budget_2019_20", "Revised_2019_20", "Budget_2020_21"
]

# Schema for Sub-Head Summary CSV (20 columns)
SUB_HEAD_SCHEMA = [
    "Source_Page_Number", "Volume_Number", "Demand_Number", "Major_Head_Code",
    "Major_Head_Name", "Sub_Major_Head_Code", "Sub_Major_Head_Name",
    "Minor_Head_Code", "Minor_Head_Name", "Sub_Head_Code", "Sub_Head_Name",
    "Full_Account_Code", "Description", "Vote_Charge_Marker", "Row_Type",
    "Row_Level", "Accounts_2018_19", "Budget_2019_20", "Revised_2019_20",
    "Budget_2020_21"
]

# Schema for Detailed Head Summary CSV (22 columns)
DETAILED_HEAD_SCHEMA = [
    "Source_Page_Number", "Volume_Number", "Demand_Number", "Major_Head_Code",
    "Major_Head_Name", "Sub_Major_Head_Code", "Sub_Major_Head_Name",
    "Minor_Head_Code", "Minor_Head_Name", "Sub_Head_Code", "Sub_Head_Name",
    "Detailed_Head_Code", "Detailed_Head_Name", "Full_Account_Code",
    "Description", "Vote_Charge_Marker", "Row_Type", "Row_Level",
    "Accounts_2018_19", "Budget_2019_20", "Revised_2019_20", "Budget_2020_21"
]

# Schema for Object Head Summary CSV (24 columns) - Most granular level
OBJECT_HEAD_SCHEMA = [
    "Source_Page_Number", "Volume_Number", "Demand_Number", "Major_Head_Code",
    "Major_Head_Name", "Sub_Major_Head_Code", "Sub_Major_Head_Name",
    "Minor_Head_Code", "Minor_Head_Name", "Sub_Head_Code", "Sub_Head_Name",
    "Detailed_Head_Code", "Detailed_Head_Name", "Object_Head_Code",
    "Object_Head_Description", "Full_Account_Code", "Description",
    "Vote_Charge_Marker", "Row_Type", "Row_Level", "Accounts_2018_19",
    "Budget_2019_20", "Revised_2019_20", "Budget_2020_21"
]
