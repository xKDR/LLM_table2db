"""Shared schema definitions for Karnataka Budget Extraction.

This module contains the standard CSV schemas used across the extraction pipeline.
These schemas are used for validation, cleaning, and combining CSVs.

All schemas follow the hierarchical budget structure:
- Sub-Major Head (16 cols)
- Minor Head (18 cols)
- Sub-Head (20 cols)
- Detailed Head (22 cols)
- Object Head (24 cols - most granular)
"""

from typing import Dict, List


def get_schemas(financial_years: List[str]) -> Dict[str, List[str]]:
    """Generates schema definitions for different budget hierarchy levels.

    Args:
        financial_years: A list of strings representing the financial year column
            names to be included in the schemas.

    Returns:
        A dictionary mapping level names (e.g., 'object_head') to their
        respective list of column names.
    """
    # Base columns common to all schemas
    base_cols = [
        "Source_Page_Number",
        "Volume_Number",
        "Demand_Number",
        "Major_Head_Code",
        "Major_Head_Name",
        "Sub_Major_Head_Code",
        "Sub_Major_Head_Name",
    ]

    # Specific columns for each level
    minor_cols = base_cols + ["Minor_Head_Code", "Minor_Head_Name"]
    sub_cols = minor_cols + ["Sub_Head_Code", "Sub_Head_Name"]
    detailed_cols = sub_cols + ["Detailed_Head_Code", "Detailed_Head_Name"]
    object_cols = detailed_cols + ["Object_Head_Code", "Object_Head_Description"]

    # Common tail columns
    tail_cols = [
        "Full_Account_Code",
        "Description",
        "Vote_Charge_Marker",
        "Row_Type",
        "Row_Level",
    ]

    # Combine with financial years
    sub_major_schema = base_cols + tail_cols + financial_years
    minor_schema = minor_cols + tail_cols + financial_years
    sub_schema = sub_cols + tail_cols + financial_years
    detailed_schema = detailed_cols + tail_cols + financial_years
    object_schema = object_cols + tail_cols + financial_years

    return {
        "sub_major_head": sub_major_schema,
        "minor_head": minor_schema,
        "sub_head": sub_schema,
        "detailed_head": detailed_schema,
        "object_head": object_schema,
    }


DEFAULT_FINANCIAL_YEARS = [
    "Accounts_2018_19",
    "Budget_2019_20",
    "Revised_2019_20",
    "Budget_2020_21",
]

_defaults = get_schemas(DEFAULT_FINANCIAL_YEARS)

SUB_MAJOR_HEAD_SCHEMA = _defaults["sub_major_head"]
MINOR_HEAD_SCHEMA = _defaults["minor_head"]
SUB_HEAD_SCHEMA = _defaults["sub_head"]
DETAILED_HEAD_SCHEMA = _defaults["detailed_head"]
OBJECT_HEAD_SCHEMA = _defaults["object_head"]
