import argparse
import os
import glob
import pandas as pd

def clean_code(val):
    if pd.isna(val):
        return ""
    val_str = str(val).strip()
    if val_str == "":
        return ""
    try:
        # Convert to int then string to consistently handle '00' -> '0', '03' -> '3'
        return str(int(float(val_str)))
    except ValueError:
        return val_str

def process_volume(summary_path, validation_path, output_path):
    print(f"Loading summary file: {summary_path}")
    df_summary = pd.read_csv(summary_path, sep='|', dtype=str)
    
    print(f"Loading validation file: {validation_path}")
    df_val = pd.read_csv(validation_path, sep=',', dtype=str)
    
    # The common HOA columns to merge on
    hoa_cols = [
        "Demand_Number",
        "Major_Head_Code",
        "Sub_Major_Head_Code",
        "Minor_Head_Code",
        "Sub_Head_Code",
        "Detailed_Head_Code"
    ]
    
    # Check if all hoa_cols exist in both dataframes
    for col in hoa_cols:
        if col not in df_summary.columns:
            raise ValueError(f"Column '{col}' not found in summary file.")
        if col not in df_val.columns:
            raise ValueError(f"Column '{col}' not found in validation file.")
            
    if "Avg_Accuracy_%" not in df_val.columns:
        raise ValueError(f"Column 'Avg_Accuracy_%' not found in validation file.")
        
    # Clean the HOA columns for merging
    for col in hoa_cols:
        df_summary[f"join_{col}"] = df_summary[col].apply(clean_code)
        df_val[f"join_{col}"] = df_val[col].apply(clean_code)
        
    join_cols = [f"join_{col}" for col in hoa_cols]
    
    # We only want to bring 'Avg_Accuracy_%' from validation
    val_subset = df_val[join_cols + ["Avg_Accuracy_%"]].drop_duplicates(subset=join_cols)
    
    # Left merge
    print("Merging dataframes...")
    df_merged = pd.merge(df_summary, val_subset, on=join_cols, how='left')
    
    # Drop the temporary join columns
    df_merged = df_merged.drop(columns=join_cols)
    
    # Write to output file
    print(f"Saving merged output to: {output_path}")
    df_merged.to_csv(output_path, sep='|', index=False)
    
    print(f"Merge complete! Output saved. Output has {len(df_merged)} rows (original had {len(df_summary)}).")
    
    return len(df_summary), len(df_merged)

def main():
    parser = argparse.ArgumentParser(description="Merge Avg_Accuracy_% from validation into summary.")
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_run_dir1 = os.path.join(script_dir, "..", "outputs", "runs", "FULL_18_22")
    default_run_dir2 = os.path.join(script_dir, "..", "outputs", "runs", "FULL_23_27")
    
    parser.add_argument("--run_dirs", nargs='+', default=[os.path.normpath(default_run_dir1), os.path.normpath(default_run_dir2)], help="Paths to the run directories to batch process all volumes.")
    parser.add_argument("--summary_file", help="Path to a single final_object_head_summary.csv (overrides batch processing)")
    parser.add_argument("--validation_file", help="Path to a single in_schema validation CSV (overrides batch processing)")
    parser.add_argument("--output_file", required=False, help="Path to the single output merged CSV. Defaults to out_object_head_summary.csv in summary file's directory.")
    
    args = parser.parse_args()

    results = []

    if args.summary_file and args.validation_file:
        summary_path = args.summary_file
        validation_path = args.validation_file
        if args.output_file:
            output_path = args.output_file
        else:
            output_dir = os.path.dirname(os.path.abspath(summary_path))
            output_path = os.path.join(output_dir, "out_object_head_summary.csv")
            
        print(f"Running in single-file mode for {summary_path}...")
        try:
            original_rows, output_rows = process_volume(summary_path, validation_path, output_path)
            results.append({"volume": "single_file", "Original rows": original_rows, "Output rows": output_rows, "merge status": "Success"})
        except Exception as e:
            print(f"Error processing single file: {e}")
            results.append({"volume": "single_file", "Original rows": "N/A", "Output rows": "N/A", "merge status": f"Fail ({e})"})
    else:
        for run_dir in args.run_dirs:
            print(f"\nRunning in batch mode for run directory: {run_dir}")
            validation_vols_dir = os.path.join(run_dir, "validation", "volumes")
            
            if not os.path.exists(validation_vols_dir):
                print(f"Directory {validation_vols_dir} does not exist. Skipping.")
                continue
                
            # Find all volume directories
            for vol_name in sorted(os.listdir(validation_vols_dir)):
                vol_dir = os.path.join(validation_vols_dir, vol_name)
                if not os.path.isdir(vol_dir):
                    continue
                    
                summary_path = os.path.join(run_dir, vol_name, "final_object_head_summary.csv")
                
                # Use glob to find the validation file since it might be named slightly differently
                val_pattern = os.path.join(vol_dir, "in_schema_*_object_data_to_detailed_head_total_hoa_*.csv")
                val_files = glob.glob(val_pattern)
                
                if not os.path.exists(summary_path):
                    print(f"Skipping {vol_name}: Missing summary file at {summary_path}")
                    results.append({"volume": vol_name, "Original rows": "N/A", "Output rows": "N/A", "merge status": "Fail (Missing summary file)"})
                    continue
                    
                if not val_files:
                    print(f"Skipping {vol_name}: Missing validation file matching {val_pattern}")
                    results.append({"volume": vol_name, "Original rows": "N/A", "Output rows": "N/A", "merge status": "Fail (Missing validation file)"})
                    continue
                    
                validation_path = val_files[0]
                output_path = os.path.join(run_dir, vol_name, "out_object_head_summary.csv")
                
                print(f"\n--- Processing Volume: {vol_name} ---")
                try:
                    original_rows, output_rows = process_volume(summary_path, validation_path, output_path)
                    results.append({"volume": vol_name, "Original rows": original_rows, "Output rows": output_rows, "merge status": "Success"})
                except Exception as e:
                    print(f"Error processing {vol_name}: {e}")
                    results.append({"volume": vol_name, "Original rows": "N/A", "Output rows": "N/A", "merge status": f"Fail ({e})"})

    # Print tabular summary
    print("\n\n=== Merge Processing Summary ===")
    df_results = pd.DataFrame(results)
    if not df_results.empty:
        try:
            print(df_results.to_markdown(index=False))
        except ImportError:
            print(df_results.to_string(index=False))
    else:
        print("No volumes processed.")

if __name__ == "__main__":
    main()
