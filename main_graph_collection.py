import os
import shutil

from playbot.weaponbook import build_graph_json_from_hierarchy_dir, write_viewer_html

OUT_DIR = "data/weapon_trees"
UPDATE_DOCS = False
DOCS_DIR = "docs/"

if __name__ == "__main__":
    graph_path = build_graph_json_from_hierarchy_dir(OUT_DIR)
    html_path = write_viewer_html(OUT_DIR)
    print("[OK] wrote:", graph_path)
    print("[OK] wrote:", html_path)
    print("\nOpen with a local server, e.g.:")
    print(f"  cd {OUT_DIR}")
    print("  python -m http.server 8000")
    print("Then open http://localhost:8000/viewer.html")

    if UPDATE_DOCS:
        shutil.copyfile(os.path.join(OUT_DIR, "graph.json"), os.path.join(DOCS_DIR, "graph.json"))
        shutil.copyfile(os.path.join(OUT_DIR, "viewer.html"), os.path.join(DOCS_DIR, "viewer.html"))
