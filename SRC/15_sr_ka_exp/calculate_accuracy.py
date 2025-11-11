import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict

# Financial columns to validate
FINANCIAL_COLS = ['Accounts_2018_19', 'Budget_2019_20', 'Revised_2019_20', 'Budget_2020_21']

def calculate_accuracy_percentage(object_sum, total_value):
    """
    Calculate accuracy percentage based on absolute difference.
    Accuracy % = 100 - (|difference| / total * 100)
    """
    if total_value == 0:
        return 100.0 if object_sum == 0 else 0.0

    abs_diff = abs(object_sum - total_value)
    error_pct = (abs_diff / abs(total_value)) * 100
    accuracy_pct = max(0, 100 - error_pct)
    return accuracy_pct

def load_data(detailed_csv):
    """Load and prepare data"""
    df = pd.read_csv(detailed_csv)

    # Fill NaN with 0 for financial columns
    for col in FINANCIAL_COLS:
        df[col] = df[col].fillna(0)

    # Fill NaN for Vote_Charge_Marker with empty string
    if 'Vote_Charge_Marker' in df.columns:
        df['Vote_Charge_Marker'] = df['Vote_Charge_Marker'].fillna('')

    return df

def calculate_accuracy_by_demand(df):
    """Calculate accuracy by Demand Number"""
    results = []

    # Get Object Head Data rows
    object_data = df[
        (df['Row_Type'] == 'Data') &
        (df['Row_Level'] == 'Object-Head')
    ].copy()

    # Get Minor Head Totals
    minor_totals = df[
        (df['Row_Type'] == 'Total') &
        (df['Row_Level'] == 'Minor-Head')
    ].copy()

    # Group by Demand
    for demand in sorted(df['Demand_Number'].dropna().unique()):
        demand_obj = object_data[object_data['Demand_Number'] == demand]
        demand_totals = minor_totals[minor_totals['Demand_Number'] == demand]

        if len(demand_obj) == 0 or len(demand_totals) == 0:
            continue

        result = {
            'Demand_Number': int(demand),
            'Object_Count': len(demand_obj),
        }

        # Calculate accuracy for each financial column
        for col in FINANCIAL_COLS:
            obj_sum = demand_obj[col].sum()
            total_sum = demand_totals[col].sum()
            accuracy = calculate_accuracy_percentage(obj_sum, total_sum)

            result[f'{col}_ObjectSum'] = round(obj_sum, 2)
            result[f'{col}_Total'] = round(total_sum, 2)
            result[f'{col}_Diff'] = round(obj_sum - total_sum, 2)
            result[f'{col}_Accuracy_%'] = round(accuracy, 2)

        results.append(result)

    return pd.DataFrame(results)

def calculate_accuracy_by_major_head(df):
    """Calculate accuracy by Major Head"""
    results = []

    # Get Object Head Data rows
    object_data = df[
        (df['Row_Type'] == 'Data') &
        (df['Row_Level'] == 'Object-Head')
    ].copy()

    # Get Minor Head Totals
    minor_totals = df[
        (df['Row_Type'] == 'Total') &
        (df['Row_Level'] == 'Minor-Head')
    ].copy()

    # Group by Major Head
    for major in sorted(df['Major_Head_Code'].dropna().unique()):
        major_obj = object_data[object_data['Major_Head_Code'] == major]
        major_totals = minor_totals[minor_totals['Major_Head_Code'] == major]

        if len(major_obj) == 0 or len(major_totals) == 0:
            continue

        major_name = major_obj['Major_Head_Name'].iloc[0] if len(major_obj) > 0 else ''

        result = {
            'Major_Head_Code': int(major),
            'Major_Head_Name': major_name,
            'Object_Count': len(major_obj),
        }

        # Calculate accuracy for each financial column
        for col in FINANCIAL_COLS:
            obj_sum = major_obj[col].sum()
            total_sum = major_totals[col].sum()
            accuracy = calculate_accuracy_percentage(obj_sum, total_sum)

            result[f'{col}_ObjectSum'] = round(obj_sum, 2)
            result[f'{col}_Total'] = round(total_sum, 2)
            result[f'{col}_Diff'] = round(obj_sum - total_sum, 2)
            result[f'{col}_Accuracy_%'] = round(accuracy, 2)

        results.append(result)

    return pd.DataFrame(results)

def calculate_accuracy_by_minor_head(df):
    """Calculate accuracy by Major Head + Minor Head"""
    results = []

    # Get Object Head Data rows
    object_data = df[
        (df['Row_Type'] == 'Data') &
        (df['Row_Level'] == 'Object-Head')
    ].copy()

    # Get Minor Head Totals
    minor_totals = df[
        (df['Row_Type'] == 'Total') &
        (df['Row_Level'] == 'Minor-Head')
    ].copy()

    # Group by Major + Minor
    for _, total_row in minor_totals.iterrows():
        major = int(total_row['Major_Head_Code'])
        minor = int(total_row['Minor_Head_Code'])

        minor_obj = object_data[
            (object_data['Major_Head_Code'] == major) &
            (object_data['Minor_Head_Code'] == minor)
        ]

        minor_totals_filtered = minor_totals[
            (minor_totals['Major_Head_Code'] == major) &
            (minor_totals['Minor_Head_Code'] == minor)
        ]

        result = {
            'Major_Head_Code': major,
            'Major_Head_Name': total_row['Major_Head_Name'],
            'Minor_Head_Code': minor,
            'Minor_Head_Name': total_row['Minor_Head_Name'],
            'Page': total_row['Source_Page_Number'],
            'Object_Count': len(minor_obj),
        }

        # Calculate accuracy for each financial column
        for col in FINANCIAL_COLS:
            obj_sum = minor_obj[col].sum()
            total_sum = minor_totals_filtered[col].sum()
            accuracy = calculate_accuracy_percentage(obj_sum, total_sum)

            result[f'{col}_ObjectSum'] = round(obj_sum, 2)
            result[f'{col}_Total'] = round(total_sum, 2)
            result[f'{col}_Diff'] = round(obj_sum - total_sum, 2)
            result[f'{col}_Accuracy_%'] = round(accuracy, 2)

        # Only add unique minor heads (not duplicate V/C rows)
        if not any(r['Major_Head_Code'] == major and r['Minor_Head_Code'] == minor for r in results):
            results.append(result)

    return pd.DataFrame(results)

def calculate_accuracy_by_page(df):
    """Calculate accuracy by Page"""
    results = []

    # Get Object Head Data rows
    object_data = df[
        (df['Row_Type'] == 'Data') &
        (df['Row_Level'] == 'Object-Head')
    ].copy()

    # Get Minor Head Totals
    minor_totals = df[
        (df['Row_Type'] == 'Total') &
        (df['Row_Level'] == 'Minor-Head')
    ].copy()

    # Group by Page
    for page in sorted(df['Source_Page_Number'].dropna().unique()):
        page_obj = object_data[object_data['Source_Page_Number'] == page]
        page_totals = minor_totals[minor_totals['Source_Page_Number'] == page]

        if len(page_obj) == 0 or len(page_totals) == 0:
            continue

        result = {
            'Page': int(page),
            'Object_Count': len(page_obj),
        }

        # Calculate accuracy for each financial column
        for col in FINANCIAL_COLS:
            obj_sum = page_obj[col].sum()
            total_sum = page_totals[col].sum()
            accuracy = calculate_accuracy_percentage(obj_sum, total_sum)

            result[f'{col}_ObjectSum'] = round(obj_sum, 2)
            result[f'{col}_Total'] = round(total_sum, 2)
            result[f'{col}_Diff'] = round(obj_sum - total_sum, 2)
            result[f'{col}_Accuracy_%'] = round(accuracy, 2)

        results.append(result)

    return pd.DataFrame(results)

def calculate_overall_accuracy(df):
    """Calculate overall accuracy across all data"""
    results = []

    # Get Object Head Data rows
    object_data = df[
        (df['Row_Type'] == 'Data') &
        (df['Row_Level'] == 'Object-Head')
    ].copy()

    # Get Minor Head Totals
    minor_totals = df[
        (df['Row_Type'] == 'Total') &
        (df['Row_Level'] == 'Minor-Head')
    ].copy()

    result = {
        'Metric': 'Overall',
        'Object_Count': len(object_data),
        'Total_Count': len(minor_totals),
    }

    # Calculate accuracy for each financial column
    for col in FINANCIAL_COLS:
        obj_sum = object_data[col].sum()
        total_sum = minor_totals[col].sum()
        accuracy = calculate_accuracy_percentage(obj_sum, total_sum)

        result[f'{col}_ObjectSum'] = round(obj_sum, 2)
        result[f'{col}_Total'] = round(total_sum, 2)
        result[f'{col}_Diff'] = round(obj_sum - total_sum, 2)
        result[f'{col}_Accuracy_%'] = round(accuracy, 2)

    results.append(result)
    return pd.DataFrame(results)

def main():
    """Main function"""
    PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
    OUT_DIR = PROJECT_ROOT / 'OUT' / '15_sr_ka_exp'
    detailed_csv = OUT_DIR / 'final_detailed_expenditure_breakdown.csv'

    print("=" * 80)
    print("KARNATAKA BUDGET ACCURACY ANALYSIS")
    print("=" * 80)

    print("\n1. Loading data...")
    df = load_data(detailed_csv)
    print(f"   ✓ Loaded {len(df)} rows")

    print("\n2. Calculating accuracy metrics...")

    # Overall accuracy
    print("   → Overall accuracy...")
    overall = calculate_overall_accuracy(df)

    # By Demand
    print("   → Accuracy by Demand Number...")
    by_demand = calculate_accuracy_by_demand(df)

    # By Major Head
    print("   → Accuracy by Major Head...")
    by_major = calculate_accuracy_by_major_head(df)

    # By Minor Head
    print("   → Accuracy by Minor Head...")
    by_minor = calculate_accuracy_by_minor_head(df)

    # By Page
    print("   → Accuracy by Page...")
    by_page = calculate_accuracy_by_page(df)

    print("\n3. Saving results...")

    # Save all results
    overall.to_csv(OUT_DIR / 'accuracy_overall.csv', index=False)
    by_demand.to_csv(OUT_DIR / 'accuracy_by_demand.csv', index=False)
    by_major.to_csv(OUT_DIR / 'accuracy_by_major_head.csv', index=False)
    by_minor.to_csv(OUT_DIR / 'accuracy_by_minor_head.csv', index=False)
    by_page.to_csv(OUT_DIR / 'accuracy_by_page.csv', index=False)

    print(f"   ✓ {OUT_DIR / 'accuracy_overall.csv'}")
    print(f"   ✓ {OUT_DIR / 'accuracy_by_demand.csv'}")
    print(f"   ✓ {OUT_DIR / 'accuracy_by_major_head.csv'}")
    print(f"   ✓ {OUT_DIR / 'accuracy_by_minor_head.csv'}")
    print(f"   ✓ {OUT_DIR / 'accuracy_by_page.csv'}")

    print("\n" + "=" * 80)
    print("OVERALL ACCURACY")
    print("=" * 80)
    print(overall.to_string(index=False))

    print("\n" + "=" * 80)
    print("ACCURACY BY MAJOR HEAD")
    print("=" * 80)
    print(by_major[['Major_Head_Code', 'Major_Head_Name', 'Object_Count',
                     'Accounts_2018_19_Accuracy_%', 'Budget_2019_20_Accuracy_%',
                     'Revised_2019_20_Accuracy_%', 'Budget_2020_21_Accuracy_%']].to_string(index=False))

    print("\n" + "=" * 80)
    print("ACCURACY BY DEMAND NUMBER")
    print("=" * 80)
    print(by_demand[['Demand_Number', 'Object_Count',
                      'Accounts_2018_19_Accuracy_%', 'Budget_2019_20_Accuracy_%',
                      'Revised_2019_20_Accuracy_%', 'Budget_2020_21_Accuracy_%']].to_string(index=False))

if __name__ == '__main__':
    main()
