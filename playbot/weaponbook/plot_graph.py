import json
import os
from collections import defaultdict
from typing import Dict, List, Tuple, Set, Any


def _node_id(name: str, level: int) -> str:
    # Cytoscape node id는 전역 유일 문자열이어야 함
    return f"{level}|{name}"


def build_graph_json_from_hierarchy_dir(
    out_dir: str,
    *,
    graph_json_name: str = "graph.json",
) -> str:
    """
    Reads:
      - out_dir/index.json  (must include "tree_ids", "special_ids")
      - out_dir/hierarchy_{hid}.json for each hid in tree_ids

    Writes:
      - out_dir/graph.json (Cytoscape elements)

    Node = (name, level)
    Edge = adjacency within each hid: level -> level+1 (by order in nodes list)
    Multiple hids on same edge are aggregated into one edge with hids=[...]
    """
    idx_path = os.path.join(out_dir, "index.json")
    if not os.path.exists(idx_path):
        raise FileNotFoundError(f"index.json not found: {idx_path}")

    with open(idx_path, "r", encoding="utf-8") as f:
        index = json.load(f)

    tree_ids: List[int] = index.get("tree_ids", [])
    special_ids: Set[int] = set(index.get("special_ids", []))

    # Collect node membership and per-hid node sequences
    node_hids: Dict[str, Set[int]] = defaultdict(set)   # node_id -> set(hid)
    node_meta: Dict[str, Dict[str, Any]] = {}           # node_id -> {name, level}
    hid_nodes: Dict[int, List[str]] = {}                # hid -> [node_id in order]
    hid_special: Dict[int, bool] = {}                   # hid -> bool

    for hid in tree_ids:
        p = os.path.join(out_dir, f"hierarchy_{hid}.json")
        if not os.path.exists(p):
            # index.json은 있는데 개별 파일이 없을 수 있으니 스킵
            continue
        with open(p, "r", encoding="utf-8") as f:
            h = json.load(f)

        nodes = h.get("nodes", [])
        seq: List[str] = []
        for n in nodes:
            name = n["name"]
            level = int(n["level"])
            nid = _node_id(name, level)
            seq.append(nid)

            node_hids[nid].add(hid)
            if nid not in node_meta:
                node_meta[nid] = {"name": name, "level": level}

        hid_nodes[hid] = seq
        hid_special[hid] = bool(h.get("special", hid in special_ids))

    # Build edges: aggregate by (source, target)
    edge_hids: Dict[Tuple[str, str], Set[int]] = defaultdict(set)
    for hid, seq in hid_nodes.items():
        for a, b in zip(seq, seq[1:]):
            edge_hids[(a, b)].add(hid)

    # Layout positions (fast preset):
    # x = level * spacing
    # y = average position of the hids it belongs to (hid index * spacing)
    # This avoids heavy force-layout and still keeps "level axis" meaningful.
    hids_sorted = sorted(hid_nodes.keys())
    hid_rank = {hid: i for i, hid in enumerate(hids_sorted)}

    x_spacing = 120
    y_spacing = 18

    # Precompute each node's y as mean of its hid ranks (so shared nodes sit between stripes)
    node_pos: Dict[str, Tuple[float, float]] = {}
    for nid, hset in node_hids.items():
        lvl = int(node_meta[nid]["level"])
        x = lvl * x_spacing

        ranks = [hid_rank[h] for h in hset if h in hid_rank]
        if ranks:
            y = (sum(ranks) / len(ranks)) * y_spacing
        else:
            y = 0.0
        node_pos[nid] = (x, y)

    # Build cytoscape elements
    cy_nodes = []
    for nid, meta in node_meta.items():
        hset = sorted(node_hids.get(nid, []))
        is_special = any(h in special_ids for h in hset)

        x, y = node_pos[nid]
        cy_nodes.append({
            "data": {
                "id": nid,
                "label": f"[+{meta['level']}] {meta['name']}",
                "name": meta["name"],
                "level": int(meta["level"]),
                "hids": hset,
                "is_special": is_special,
            },
            "position": {"x": x, "y": y},
        })

    cy_edges = []
    for (src, tgt), hset in edge_hids.items():
        # edge id must be unique; aggregate all hids for same src->tgt
        eid = f"{src}__{tgt}"
        cy_edges.append({
            "data": {
                "id": eid,
                "source": src,
                "target": tgt,
                "hids": sorted(hset),
                "count": len(hset),
            }
        })

    graph = {"elements": {"nodes": cy_nodes, "edges": cy_edges}}
    out_path = os.path.join(out_dir, graph_json_name)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False)

    return out_path


def write_viewer_html(
    out_dir: str,
    *,
    graph_json_name: str = "graph.json",
    html_name: str = "viewer.html",
) -> str:
    """
    Writes a standalone HTML viewer that loads graph.json and provides:
      - name substring search
      - level range filter
      - hid filter
      - special-only toggle
      - click node details panel
    """
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Weapon Graph Viewer</title>
  <script src="https://unpkg.com/cytoscape@3.28.1/dist/cytoscape.min.js"></script>
  <style>
    body {{
      margin: 0;
      font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
      display: grid;
      grid-template-columns: 360px 1fr;
      height: 100vh;
    }}
    #panel {{
      padding: 12px;
      border-right: 1px solid #ddd;
      overflow: auto;
    }}
    #cy {{
      width: 100%;
      height: 100%;
    }}
    label {{ display:block; margin-top: 10px; font-weight: 600; }}
    input, select {{
      width: 100%;
      padding: 8px;
      box-sizing: border-box;
      margin-top: 6px;
    }}
    .row {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }}
    .small {{
      color: #666;
      font-size: 12px;
      margin-top: 6px;
      line-height: 1.3;
    }}
    .btnrow {{
      display:flex; gap:8px; margin-top: 12px;
    }}
    button {{
      padding: 8px 10px;
      cursor: pointer;
    }}
    pre {{
      white-space: pre-wrap;
      word-break: break-word;
      background: #f7f7f7;
      padding: 10px;
      border-radius: 8px;
      border: 1px solid #eee;
    }}
  </style>
</head>
<body>
  <div id="panel">
    <h3 style="margin-top:0">Weapon Graph</h3>

    <label>Name contains</label>
    <input id="qName" placeholder="e.g. 불꽃, 수르트, 검 ..."/>

    <div class="row">
      <div>
        <label>Level min</label>
        <input id="qLmin" type="number" placeholder="e.g. 0"/>
      </div>
      <div>
        <label>Level max</label>
        <input id="qLmax" type="number" placeholder="e.g. 18"/>
      </div>
    </div>

    <label>HID filter (optional)</label>
    <input id="qHid" placeholder="e.g. 1 or 1234"/>

    <label>
      <input id="qSpecial" type="checkbox" style="width:auto; margin-right:8px"/>
      Special only
    </label>

    <div class="btnrow">
      <button id="btnApply">Apply</button>
      <button id="btnReset">Reset</button>
      <button id="btnFit">Fit</button>
    </div>

    <div class="small">
      Tips:
      <ul>
        <li>검색 후 <b>Apply</b>를 누르세요.</li>
        <li>노드 클릭하면 상세가 아래에 표시됩니다.</li>
        <li>그래프가 안 뜨면 로컬 서버로 여세요 (예: <code>python -m http.server</code>).</li>
      </ul>
    </div>

    <h4>Selected</h4>
    <pre id="sel">(none)</pre>
  </div>

  <div id="cy"></div>

<script>
async function main() {{
  const res = await fetch("{graph_json_name}");
  const graph = await res.json();

  const cy = cytoscape({{
    container: document.getElementById('cy'),
    elements: graph.elements,
    layout: {{ name: 'preset' }},
    style: [
      {{
        selector: 'node',
        style: {{
          'label': 'data(label)',
          'font-size': 10,
          'text-wrap': 'wrap',
          'text-max-width': 140,
          'background-color': '#888',
          'width': 10,
          'height': 10,
          'text-valign': 'top',
          'text-halign': 'center',
        }}
      }},
      {{
        selector: 'node[is_special]',
        style: {{
          'border-width': 2,
          'border-color': '#d33'
        }}
      }},
      {{
        selector: 'edge',
        style: {{
          'width': 1,
          'line-color': '#bbb',
          'target-arrow-shape': 'triangle',
          'target-arrow-color': '#bbb',
          'curve-style': 'bezier'
        }}
      }},
      {{
        selector: '.faded',
        style: {{
          'opacity': 0.08
        }}
      }},
      {{
        selector: '.highlight',
        style: {{
          'opacity': 1.0,
          'background-color': '#111',
          'line-color': '#111',
          'target-arrow-color': '#111',
          'border-color': '#111'
        }}
      }}
    ]
  }});

  const sel = document.getElementById('sel');
  cy.on('tap', 'node', (evt) => {{
    const d = evt.target.data();
    sel.textContent = JSON.stringify(d, null, 2);
    // neighborhood highlight
    cy.elements().removeClass('highlight');
    cy.elements().addClass('faded');
    evt.target.removeClass('faded').addClass('highlight');
    evt.target.neighborhood().removeClass('faded').addClass('highlight');
  }});

  function applyFilter() {{
    const qName = document.getElementById('qName').value.trim();
    const qLmin = document.getElementById('qLmin').value.trim();
    const qLmax = document.getElementById('qLmax').value.trim();
    const qHid  = document.getElementById('qHid').value.trim();
    const specialOnly = document.getElementById('qSpecial').checked;

    const lmin = qLmin === "" ? null : parseInt(qLmin, 10);
    const lmax = qLmax === "" ? null : parseInt(qLmax, 10);
    const hid  = qHid  === "" ? null : parseInt(qHid, 10);

    cy.elements().removeClass('faded highlight');

    const nodes = cy.nodes().filter(n => {{
      const d = n.data();
      if (qName && !String(d.name).includes(qName)) return false;
      if (lmin !== null && d.level < lmin) return false;
      if (lmax !== null && d.level > lmax) return false;
      if (specialOnly && !d.is_special) return false;
      if (hid !== null) {{
        const hs = d.hids || [];
        if (!hs.includes(hid)) return false;
      }}
      return true;
    }});

    // show: nodes + their connecting edges (within visible nodes)
    const visible = nodes.union(nodes.connectedEdges());

    cy.elements().addClass('faded');
    visible.removeClass('faded').addClass('highlight');
  }}

  function resetFilter() {{
    document.getElementById('qName').value = "";
    document.getElementById('qLmin').value = "";
    document.getElementById('qLmax').value = "";
    document.getElementById('qHid').value = "";
    document.getElementById('qSpecial').checked = false;
    sel.textContent = "(none)";
    cy.elements().removeClass('faded highlight');
  }}

  document.getElementById('btnApply').onclick = applyFilter;
  document.getElementById('btnReset').onclick = resetFilter;
  document.getElementById('btnFit').onclick = () => cy.fit();

  // initial fit
  cy.fit();
}}

main().catch(err => {{
  document.getElementById('sel').textContent = "Failed to load graph.json.\\n" + err;
}});
</script>
</body>
</html>
"""
    out_path = os.path.join(out_dir, html_name)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path
