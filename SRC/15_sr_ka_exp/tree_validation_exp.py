import pandas as pd
from pathlib import Path
from collections import defaultdict
from zss import Node, simple_distance


# ---------- STEP 1: BUILD TREE FROM CSV ---------- #

def build_tree_from_csv(csv_path):
    """Builds a nested tree {Major: {Sub: {Minor}}} from a CSV file."""
    if not csv_path.exists():
        print(f"⚠️ Missing file: {csv_path}")
        return defaultdict(lambda: defaultdict(set))

    df = pd.read_csv(csv_path, dtype=str)

    required_cols = {"Major_Head_Code", "Sub_Major_Head_Code", "Minor_Head_Code"}
    available_cols = [c for c in required_cols if c in df.columns]
    df = df[available_cols].drop_duplicates().astype(str).apply(lambda x: x.str.strip())
    df = df.dropna()

    tree = defaultdict(lambda: defaultdict(set))
    for _, row in df.iterrows():
        major = row.get("Major_Head_Code", "")
        sub_major = row.get("Sub_Major_Head_Code", "")
        minor = row.get("Minor_Head_Code", "")

        if not major or major.lower() == "nan":
            continue
        if sub_major and sub_major.lower() != "nan":
            if minor and minor.lower() != "nan":
                tree[major][sub_major].add(minor)
            else:
                tree[major][sub_major]  # ensure node exists
        else:
            tree[major]  # ensure node exists
    return tree


# ---------- STEP 2: CONVERT TREE TO ZSS STRUCTURE ---------- #

def dict_to_zss_tree(name, subtree):
    """Recursively convert a nested dict/set to a zss.Node tree."""
    node = Node(name)
    if isinstance(subtree, dict):
        for k, v in subtree.items():
            node.addkid(dict_to_zss_tree(k, v))
    elif isinstance(subtree, set):
        for item in sorted(subtree):
            node.addkid(Node(item))
    return node


# ---------- STEP 3: RENDER TREE AS TEXT ---------- #

def render_tree_text(tree_dict):
    """Render tree structure as indented text for human verification."""
    lines = []
    for major, sub_dict in sorted(tree_dict.items(), key=lambda x: x[0]):
        lines.append(f"{major}")
        for sub_major, minors in sorted(sub_dict.items(), key=lambda x: x[0]):
            lines.append(f"  └── {sub_major}")
            for minor in sorted(minors):
                lines.append(f"       └── {minor}")
    return "\n".join(lines)


# ---------- STEP 4: COMPARE TREES BY MAJOR HEAD ---------- #

def compare_trees_by_major(tree1, tree2, output_dir):
    """Compute tree edit distance, save comparison files, and return distances."""
    all_majors = set(tree1.keys()) | set(tree2.keys())
    distances = {}

    output_dir.mkdir(parents=True, exist_ok=True)

    for major in sorted(all_majors):
        t1 = dict_to_zss_tree(major, tree1.get(major, {}))
        t2 = dict_to_zss_tree(major, tree2.get(major, {}))
        dist = simple_distance(t1, t2)
        distances[major] = dist

        # Save comparison file
        file_path = output_dir / f"{major}.txt"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"Major_Head_Code: {major}\n")
            f.write(f"Tree Edit Distance: {dist}\n")
            f.write("\n=== Tree from CSV 1 ===\n")
            f.write(render_tree_text({major: tree1.get(major, {})}) or "(empty)")
            f.write("\n\n=== Tree from CSV 2 ===\n")
            f.write(render_tree_text({major: tree2.get(major, {})}) or "(empty)")

    return distances


# ---------- STEP 5: RUN FOR ALL SUBDIRECTORIES ---------- #

base_dir = Path(__file__).resolve().parents[2] / "OUT" / "15_viki_ka_exp"

for sub_dir in sorted(base_dir.iterdir()):
    if not sub_dir.is_dir():
        continue

    print(f"\n🔹 Processing directory: {sub_dir.name}")

    csv_path_1 = sub_dir / "final_minor_head_summary.csv"
    csv_path_2 = sub_dir / "final_object_head_summary.csv"
    output_dir = sub_dir / "TED_VALIDATION"

    # Skip if input files missing
    if not csv_path_1.exists() or not csv_path_2.exists():
        print(f"⚠️ Skipping {sub_dir.name} (missing input files)")
        continue

    # Build trees
    tree1 = build_tree_from_csv(csv_path_1)
    tree2 = build_tree_from_csv(csv_path_2)

    # Compute distances
    distances = compare_trees_by_major(tree1, tree2, output_dir)

    # Save summary CSV
    total = len(distances)
    perfect_matches = sum(1 for d in distances.values() if d == 0)
    accuracy = (perfect_matches / total * 100) if total > 0 else 0.0
    summary_path = output_dir / "tree_edit_summary.csv"

    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("Major_Head_Code,Tree_Edit_Distance\n")
        for major, dist in sorted(distances.items()):
            f.write(f"{major},{dist}\n")

        f.write("\nSummary:\n")
        f.write(f"Total Comparisons: {total}\n")
        f.write(f"Perfect Matches (TED = 0): {perfect_matches}\n")
        f.write(f"Accuracy Score: {accuracy:.2f}%\n")

    print(f"✅ Completed {sub_dir.name}")
    print(f"   Accuracy: {accuracy:.2f}% | Results saved to {summary_path}")


print("\n🎯 Batch tree comparison completed for all subdirectories.")
