# Validation Report

## Run Metadata
- Generated At (UTC): 2026-04-21 09:16:30 UTC
- Input Base: `LOCAL/ocr_self_correction/outputs/runs/FULL_23_27`
- Output Base: `LOCAL/ocr_self_correction/outputs/runs/FULL_23_27/validation`
- Processed Volumes: 28

## Coverage
- Volume list: 2023-24_expvol_1, 2023-24_expvol_2, 2023-24_expvol_3, 2023-24_expvol_4, 2023-24_expvol_5, 2023-24_expvol_6, 2023-24_expvol_7, 2024-25_expvol_1, 2024-25_expvol_2, 2024-25_expvol_3, 2024-25_expvol_4, 2024-25_expvol_5, 2024-25_expvol_6, 2024-25_expvol_7, 2025-26_expvol_1, 2025-26_expvol_2, 2025-26_expvol_3, 2025-26_expvol_4, 2025-26_expvol_5, 2025-26_expvol_6, 2025-26_expvol_7, 2026-27_expvol_1, 2026-27_expvol_2, 2026-27_expvol_3, 2026-27_expvol_4, 2026-27_expvol_5, 2026-27_expvol_6, 2026-27_expvol_7

## Overall Mode-Level Results
| Validation_Mode | Compared_Keys | Passed | Failed | Pass_Rate_% |
| --------------- | ------------- | ------ | ------ | ----------- |
| in_schema       | 11908         | 11823  | 85     | 99.29       |

## Check-Level Average Results (Across Volumes)
| Validation_Mode | Check_ID | Validation_Check                                                    | Compared_Keys      | Passed             | Failed             | Pass_Rate_%       |
| --------------- | -------- | ------------------------------------------------------------------- | ------------------ | ------------------ | ------------------ | ----------------- |
| in_schema       | W01      | Object Data -> Minor Total (within object_head)                     | 2.3333333333333335 | 2.0                | 0.3333333333333333 | 66.66666666666667 |
| in_schema       | W06      | Object Data -> Detailed-Head Total (HOA Total) (within object_head) | 392.7857142857143  | 390.85714285714283 | 1.9285714285714286 | 99.50071428571428 |
| in_schema       | W07      | Object Data -> Major-Head Total (within object_head)                | 32.25              | 31.178571428571427 | 1.0714285714285714 | 96.90107142857143 |

## Lowest Pass-Rate Volume Checks (Top 20)
| Volume           | Validation_Mode | Check_ID | Validation_Check                                                    | Compared_Keys | Passed | Failed | Pass_Rate_% |
| ---------------- | --------------- | -------- | ------------------------------------------------------------------- | ------------- | ------ | ------ | ----------- |
| 2025-26_expvol_5 | in_schema       | W01      | Object Data -> Minor Total (within object_head)                     | 1             | 0      | 1      | 0.0         |
| 2024-25_expvol_3 | in_schema       | W07      | Object Data -> Major-Head Total (within object_head)                | 31            | 27     | 4      | 87.1        |
| 2024-25_expvol_4 | in_schema       | W07      | Object Data -> Major-Head Total (within object_head)                | 30            | 27     | 3      | 90.0        |
| 2024-25_expvol_5 | in_schema       | W07      | Object Data -> Major-Head Total (within object_head)                | 34            | 31     | 3      | 91.18       |
| 2025-26_expvol_2 | in_schema       | W07      | Object Data -> Major-Head Total (within object_head)                | 25            | 23     | 2      | 92.0        |
| 2023-24_expvol_2 | in_schema       | W07      | Object Data -> Major-Head Total (within object_head)                | 25            | 23     | 2      | 92.0        |
| 2023-24_expvol_3 | in_schema       | W07      | Object Data -> Major-Head Total (within object_head)                | 33            | 31     | 2      | 93.94       |
| 2023-24_expvol_5 | in_schema       | W07      | Object Data -> Major-Head Total (within object_head)                | 34            | 32     | 2      | 94.12       |
| 2023-24_expvol_1 | in_schema       | W07      | Object Data -> Major-Head Total (within object_head)                | 63            | 60     | 3      | 95.24       |
| 2024-25_expvol_2 | in_schema       | W07      | Object Data -> Major-Head Total (within object_head)                | 26            | 25     | 1      | 96.15       |
| 2026-27_expvol_3 | in_schema       | W07      | Object Data -> Major-Head Total (within object_head)                | 27            | 26     | 1      | 96.3        |
| 2023-24_expvol_4 | in_schema       | W07      | Object Data -> Major-Head Total (within object_head)                | 29            | 28     | 1      | 96.55       |
| 2026-27_expvol_1 | in_schema       | W07      | Object Data -> Major-Head Total (within object_head)                | 61            | 59     | 2      | 96.72       |
| 2026-27_expvol_5 | in_schema       | W07      | Object Data -> Major-Head Total (within object_head)                | 31            | 30     | 1      | 96.77       |
| 2025-26_expvol_1 | in_schema       | W07      | Object Data -> Major-Head Total (within object_head)                | 63            | 61     | 2      | 96.83       |
| 2024-25_expvol_3 | in_schema       | W06      | Object Data -> Detailed-Head Total (HOA Total) (within object_head) | 298           | 293    | 5      | 98.32       |
| 2024-25_expvol_1 | in_schema       | W07      | Object Data -> Major-Head Total (within object_head)                | 60            | 59     | 1      | 98.33       |
| 2025-26_expvol_2 | in_schema       | W06      | Object Data -> Detailed-Head Total (HOA Total) (within object_head) | 392           | 387    | 5      | 98.72       |
| 2026-27_expvol_7 | in_schema       | W06      | Object Data -> Detailed-Head Total (HOA Total) (within object_head) | 178           | 176    | 2      | 98.88       |
| 2025-26_expvol_3 | in_schema       | W06      | Object Data -> Detailed-Head Total (HOA Total) (within object_head) | 312           | 309    | 3      | 99.04       |

## Output Files
- `validation_summary.csv`
- Per-volume detailed CSVs under `volumes/<volume>/`
