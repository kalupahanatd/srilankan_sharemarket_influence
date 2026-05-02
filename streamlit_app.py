import streamlit as st
import pandas as pd
from neo4j import GraphDatabase
from pyvis.network import Network
import streamlit.components.v1 as components
import tempfile
import os

# =========================================================
# PAGE CONFIG
# =========================================================

st.set_page_config(
    page_title="CSE Ownership Graph",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("CSE Ownership Intelligence Graph")

# =========================================================
# SESSION STATE
# =========================================================

if "connected" not in st.session_state:
    st.session_state.connected = False

if "driver" not in st.session_state:
    st.session_state.driver = None

if "companies_df" not in st.session_state:
    st.session_state.companies_df = pd.DataFrame()

if "owners_df" not in st.session_state:
    st.session_state.owners_df = pd.DataFrame()

# =========================================================
# CONNECTION HELPERS
# =========================================================

def create_driver(uri, username, password):
    driver = GraphDatabase.driver(uri, auth=(username, password))
    with driver.session() as session:
        session.run("RETURN 1")
    return driver

def run_query(query, params=None):
    if st.session_state.driver is None:
        raise RuntimeError("Neo4j is not connected.")

    with st.session_state.driver.session() as session:
        result = session.run(query, params or {})
        return [record.data() for record in result]

def load_companies():
    rows = run_query("""
    MATCH (c:ListedCompany)
    RETURN c.name AS name, c.cse_symbol AS symbol
    ORDER BY c.name
    """)
    return pd.DataFrame(rows)

def load_owners():
    rows = run_query("""
    MATCH (o:Entity)-[r:RELATED_TO]->(:ListedCompany)
    RETURN DISTINCT o.name AS name, o.entity_type AS entity_type
    ORDER BY o.name
    """)
    return pd.DataFrame(rows)

# =========================================================
# SIDEBAR LOGIN
# =========================================================

st.sidebar.header("Neo4j Aura Login")

with st.sidebar.form("neo4j_login_form"):
    uri = st.text_input(
        "Neo4j URI",
        placeholder="neo4j+s://xxxx.databases.neo4j.io"
    )

    username = st.text_input(
        "Username",
        value="neo4j"
    )

    password = st.text_input(
        "Password",
        type="password"
    )

    connect_clicked = st.form_submit_button("Connect & Load Graph Data")

if connect_clicked:
    try:
        with st.spinner("Connecting to Neo4j Aura..."):
            driver = create_driver(uri, username, password)

            st.session_state.driver = driver
            st.session_state.connected = True
            st.session_state.companies_df = load_companies()
            st.session_state.owners_df = load_owners()

        st.sidebar.success("Connected successfully")

    except Exception as e:
        st.session_state.connected = False
        st.session_state.driver = None
        st.sidebar.error("Connection failed")
        st.sidebar.exception(e)

if not st.session_state.connected:
    st.info("Enter Neo4j Aura URI, username and password, then click **Connect & Load Graph Data**.")
    st.stop()

# =========================================================
# SIDEBAR FILTERS
# =========================================================

st.sidebar.markdown("---")
st.sidebar.header("Graph Filters")

search_mode = st.sidebar.selectbox(
    "Search mode",
    [
        "Company ownership view",
        "Owner influence view",
        "Top influential owners",
        "Full filtered graph"
    ]
)

view_mode = st.sidebar.selectbox(
    "View type",
    [
        "Network graph",
        "Hierarchical ownership tree",
        "Ownership table",
        "Influence path list"
    ],
    index=0
)

max_depth = st.sidebar.slider(
    "Relationship depth",
    min_value=1,
    max_value=6,
    value=3,
    step=1
)

min_confidence = st.sidebar.slider(
    "Minimum confidence",
    min_value=0.0,
    max_value=1.0,
    value=0.75,
    step=0.05
)

min_ownership = st.sidebar.slider(
    "Minimum ownership %",
    min_value=0.0,
    max_value=100.0,
    value=0.0,
    step=1.0
)

limit = st.sidebar.slider(
    "Max edges",
    min_value=50,
    max_value=3000,
    value=1000,
    step=50
)

physics_model = st.sidebar.selectbox(
    "Graph layout",
    [
        "Separated / readable",
        "Wide spread",
        "Compact"
    ],
    index=0
)

edge_length = st.sidebar.slider(
    "Edge length / spacing",
    min_value=100,
    max_value=1000,
    value=400,
    step=20
)

node_spacing = st.sidebar.slider(
    "Node repulsion",
    min_value=-250000,
    max_value=-5000,
    value=-120000,
    step=5000
)

show_all_connected = st.sidebar.checkbox(
    "Show full connected component for selected company",
    value=True
)

show_edge_labels = st.sidebar.checkbox(
    "Show edge labels",
    value=True
)



st.sidebar.markdown("---")
st.sidebar.caption("For manual tuning, use Network graph + Show PyVis tuning panel.")

# =========================================================
# VISUAL HELPERS
# =========================================================

def node_color(entity_type):
    colors = {
        "LISTED_COMPANY": "#1f77b4",
        "UNLISTED_COMPANY": "#17becf",
        "PERSON": "#ff7f0e",
        "GOVERNMENT": "#2ca02c",
        "FUND": "#9467bd",
        "INSTITUTION": "#8c564b",
        "UNKNOWN": "#7f7f7f"
    }
    return colors.get(entity_type, "#7f7f7f")

def edge_color(rel_type):
    colors = {
        "OWNS": "#2ca02c",
        "PARENT_OF": "#1f77b4",
        "SUBSIDIARY_OF": "#9467bd",
        "ASSOCIATE_OF": "#ff7f0e",
        "INVESTS_IN": "#d62728",
        "RELATED_TO": "#7f7f7f"
    }
    return colors.get(rel_type, "#7f7f7f")

def format_pct(x):
    if x is None:
        return ""
    try:
        return f"{float(x):.2f}%"
    except Exception:
        return ""

def node_size(entity_type):
    if entity_type == "LISTED_COMPANY":
        return 34
    if entity_type == "PERSON":
        return 28
    if entity_type == "GOVERNMENT":
        return 30
    if entity_type == "UNLISTED_COMPANY":
        return 26
    return 22

# =========================================================
# GRAPH BUILDER
# =========================================================

def build_pyvis_graph(
    rows,
    layout_mode="Separated / readable",
    show_labels=True,
    edge_length=400,
    node_spacing=-120000,
    hierarchical=False,
    show_physics_panel=False
):
    net = Network(
        height="850px",
        width="100%",
        directed=True,
        notebook=False,
        bgcolor="#ffffff",
        font_color="#222222"
    )

    added_nodes = set()

    for row in rows:
        source = row.get("source", {})
        target = row.get("target", {})
        rel = row.get("rel", {})

        source_id = source.get("node_id")
        target_id = target.get("node_id")

        if not source_id or not target_id:
            continue

        for node, node_id in [(source, source_id), (target, target_id)]:
            if node_id not in added_nodes:
                entity_type = node.get("entity_type")
                label = node.get("cse_symbol") or node.get("name") or "Unknown"

                title = f"""
                <b>{node.get('name')}</b><br>
                Type: {node.get('entity_type')}<br>
                Symbol: {node.get('cse_symbol')}<br>
                Sector: {node.get('sector')}<br>
                Industry: {node.get('industry_group')}<br>
                Company ID: {node.get('company_id')}
                """

                net.add_node(
                    node_id,
                    label=label,
                    title=title,
                    color=node_color(entity_type),
                    size=node_size(entity_type)
                )

                added_nodes.add(node_id)

        rel_type = rel.get("relationship_type", "RELATED_TO")
        pct = rel.get("ownership_percentage")
        pct_label = format_pct(pct)

        edge_label = pct_label if pct_label else rel_type
        if not show_labels:
            edge_label = ""

        edge_title = f"""
        <b>{rel_type}</b><br>
        Ownership: {pct_label}<br>
        Confidence: {rel.get('confidence')}<br>
        Source: {rel.get('source_url')}<br>
        Date: {rel.get('data_source_date')}
        """

        width = 1.5
        if pct is not None:
            try:
                width = max(1.5, min(9, float(pct) / 9))
            except Exception:
                width = 1.5

        net.add_edge(
            source_id,
            target_id,
            label=edge_label,
            title=edge_title,
            color=edge_color(rel_type),
            width=width,
            arrows="to"
        )

    if hierarchical:
        net.set_options(f"""
        {{
          "layout": {{
            "hierarchical": {{
              "enabled": true,
              "direction": "UD",
              "sortMethod": "directed",
              "levelSeparation": {edge_length},
              "nodeSpacing": 320,
              "treeSpacing": 420,
              "blockShifting": true,
              "edgeMinimization": true,
              "parentCentralization": true
            }}
          }},
          "physics": {{
            "enabled": false
          }},
          "nodes": {{
            "borderWidth": 1,
            "font": {{
              "size": 16,
              "face": "Arial"
            }}
          }},
          "edges": {{
            "font": {{
              "size": 12,
              "align": "middle"
            }},
            "smooth": {{
              "enabled": true,
              "type": "cubicBezier",
              "forceDirection": "vertical",
              "roundness": 0.4
            }}
          }},
          "interaction": {{
            "hover": true,
            "navigationButtons": true,
            "keyboard": true,
            "zoomView": true,
            "dragView": true
          }}
        }}
        """)
    else:
        if layout_mode == "Separated / readable":
            net.barnes_hut(
                gravity=node_spacing,
                central_gravity=0.025,
                spring_length=edge_length,
                spring_strength=0.010,
                damping=0.12
            )

        elif layout_mode == "Wide spread":
            net.barnes_hut(
                gravity=int(node_spacing * 1.7),
                central_gravity=0.015,
                spring_length=edge_length + 180,
                spring_strength=0.007,
                damping=0.10
            )

        else:
            net.barnes_hut(
                gravity=-15000,
                central_gravity=0.25,
                spring_length=max(120, edge_length - 180),
                spring_strength=0.04,
                damping=0.09
            )

        net.set_options(f"""
        {{
          "nodes": {{
            "borderWidth": 1,
            "font": {{
              "size": 16,
              "face": "Arial"
            }}
          }},
          "edges": {{
            "font": {{
              "size": 12,
              "align": "middle"
            }},
            "smooth": {{
              "enabled": true,
              "type": "dynamic"
            }}
          }},
          "physics": {{
            "enabled": true,
            "barnesHut": {{
              "gravitationalConstant": {node_spacing},
              "centralGravity": 0.025,
              "springLength": {edge_length},
              "springConstant": 0.010,
              "damping": 0.12,
              "avoidOverlap": 0.6
            }},
            "stabilization": {{
              "enabled": true,
              "iterations": 300,
              "updateInterval": 25
            }}
          }},
          "interaction": {{
            "hover": true,
            "navigationButtons": true,
            "keyboard": true,
            "zoomView": true,
            "dragView": true
          }}
        }}
        """)



    return net

def render_graph(net):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".html") as tmp:
        path = tmp.name

    net.write_html(path)

    with open(path, "r", encoding="utf-8") as f:
        html = f.read()

    components.html(html, height=900, scrolling=True)
    os.remove(path)

# =========================================================
# QUERY FUNCTIONS
# =========================================================

def company_ownership_query(symbol, depth, min_conf, min_own, limit, connected_component=True):
    if connected_component:
        query = f"""
        MATCH (seed:ListedCompany {{cse_symbol: $symbol}})
        MATCH path = (seed)-[:RELATED_TO*1..{depth}]-(connected:Entity)
        UNWIND relationships(path) AS r
        WITH DISTINCT startNode(r) AS s, r, endNode(r) AS t
        WHERE coalesce(r.confidence, 0) >= $min_conf
          AND coalesce(r.ownership_percentage, 0) >= $min_own
        RETURN
            properties(s) AS source,
            properties(r) AS rel,
            properties(t) AS target
        LIMIT $limit
        """
    else:
        query = f"""
        MATCH path = (owner:Entity)-[:RELATED_TO*1..{depth}]->(target:ListedCompany {{cse_symbol: $symbol}})
        UNWIND relationships(path) AS r
        WITH DISTINCT startNode(r) AS s, r, endNode(r) AS t
        WHERE coalesce(r.confidence, 0) >= $min_conf
          AND coalesce(r.ownership_percentage, 0) >= $min_own
        RETURN
            properties(s) AS source,
            properties(r) AS rel,
            properties(t) AS target
        LIMIT $limit
        """

    return run_query(query, {
        "symbol": symbol,
        "min_conf": min_conf,
        "min_own": min_own,
        "limit": limit
    })

def owner_influence_query(owner_name, depth, min_conf, min_own, limit):
    query = f"""
    MATCH path = (source:Entity)-[:RELATED_TO*1..{depth}]->(target:ListedCompany)
    WHERE toUpper(source.canonical_name) CONTAINS toUpper($owner_name)
    UNWIND relationships(path) AS r
    WITH DISTINCT startNode(r) AS s, r, endNode(r) AS t
    WHERE coalesce(r.confidence, 0) >= $min_conf
      AND coalesce(r.ownership_percentage, 0) >= $min_own
    RETURN
        properties(s) AS source,
        properties(r) AS rel,
        properties(t) AS target
    LIMIT $limit
    """

    return run_query(query, {
        "owner_name": owner_name,
        "min_conf": min_conf,
        "min_own": min_own,
        "limit": limit
    })

def full_graph_query(min_conf, min_own, limit):
    query = """
    MATCH (s:Entity)-[r:RELATED_TO]->(t:Entity)
    WHERE coalesce(r.confidence, 0) >= $min_conf
      AND coalesce(r.ownership_percentage, 0) >= $min_own
    RETURN
        properties(s) AS source,
        properties(r) AS rel,
        properties(t) AS target
    LIMIT $limit
    """

    return run_query(query, {
        "min_conf": min_conf,
        "min_own": min_own,
        "limit": limit
    })

def top_influential_owners_query(min_conf):
    query = """
    MATCH (owner:Entity)-[r:RELATED_TO]->(company:ListedCompany)
    WHERE coalesce(r.confidence, 0) >= $min_conf
    RETURN
        owner.name AS owner,
        owner.entity_type AS type,
        count(DISTINCT company) AS listed_companies,
        avg(r.ownership_percentage) AS avg_ownership
    ORDER BY listed_companies DESC
    LIMIT 30
    """
    return run_query(query, {"min_conf": min_conf})

# =========================================================
# MAIN APP
# =========================================================

companies_df = st.session_state.companies_df.copy()
owners_df = st.session_state.owners_df.copy()

rows = []

if search_mode == "Company ownership view":
    st.subheader("Company Ownership View")

    if companies_df.empty:
        st.warning("No listed companies found in Neo4j.")
        st.stop()

    companies_df["display"] = companies_df["symbol"].fillna("") + " | " + companies_df["name"].fillna("")
    selected = st.selectbox("Select listed company", companies_df["display"].tolist())

    selected_symbol = selected.split(" | ")[0]

    rows = company_ownership_query(
        symbol=selected_symbol,
        depth=max_depth,
        min_conf=min_confidence,
        min_own=min_ownership,
        limit=limit,
        connected_component=show_all_connected
    )

elif search_mode == "Owner influence view":
    st.subheader("Owner Influence View")

    if owners_df.empty:
        st.warning("No owners found in Neo4j.")
        st.stop()

    owners_df["display"] = owners_df["name"].fillna("") + " | " + owners_df["entity_type"].fillna("")
    selected_owner = st.selectbox("Select owner / person / institution", owners_df["display"].tolist())

    owner_name = selected_owner.split(" | ")[0]

    rows = owner_influence_query(
        owner_name=owner_name,
        depth=max_depth,
        min_conf=min_confidence,
        min_own=min_ownership,
        limit=limit
    )

elif search_mode == "Top influential owners":
    st.subheader("Top Influential Owners")

    top_df = pd.DataFrame(top_influential_owners_query(min_confidence))
    st.dataframe(top_df, use_container_width=True)

    rows = full_graph_query(
        min_conf=min_confidence,
        min_own=min_ownership,
        limit=limit
    )

else:
    st.subheader("Full Filtered Ownership Graph")

    rows = full_graph_query(
        min_conf=min_confidence,
        min_own=min_ownership,
        limit=limit
    )

st.markdown("---")

if not rows:
    st.warning("No graph data found for the selected filters.")
else:
    unique_nodes = set()
    for r in rows:
        if r.get("source", {}).get("node_id"):
            unique_nodes.add(r["source"]["node_id"])
        if r.get("target", {}).get("node_id"):
            unique_nodes.add(r["target"]["node_id"])

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Edges returned", len(rows))
    col2.metric("Nodes shown", len(unique_nodes))
    col3.metric("Depth", max_depth)
    col4.metric("Min confidence", min_confidence)

    if view_mode == "Network graph":
        net = build_pyvis_graph(
                rows,
                layout_mode=physics_model,
                show_labels=show_edge_labels,
                edge_length=edge_length,
                node_spacing=node_spacing,
                hierarchical=False,
                show_physics_panel=False
            )
        render_graph(net)

    elif view_mode == "Hierarchical ownership tree":
        net = build_pyvis_graph(
            rows,
            layout_mode=physics_model,
            show_labels=show_edge_labels,
            edge_length=edge_length,
            node_spacing=node_spacing,
            hierarchical=True,
            show_physics_panel=False
        )
        render_graph(net)

    elif view_mode == "Ownership table":
        table_df = pd.DataFrame([
            {
                "owner": r["source"].get("name"),
                "owner_type": r["source"].get("entity_type"),
                "relationship": r["rel"].get("relationship_type"),
                "ownership_%": r["rel"].get("ownership_percentage"),
                "target": r["target"].get("name"),
                "target_type": r["target"].get("entity_type"),
                "target_symbol": r["target"].get("cse_symbol"),
                "confidence": r["rel"].get("confidence"),
                "source_url": r["rel"].get("source_url")
            }
            for r in rows
        ])
        st.dataframe(table_df, use_container_width=True)

    else:
        path_df = pd.DataFrame([
            {
                "from": r["source"].get("name"),
                "from_type": r["source"].get("entity_type"),
                "relation": r["rel"].get("relationship_type"),
                "ownership_%": r["rel"].get("ownership_percentage"),
                "to": r["target"].get("name"),
                "to_type": r["target"].get("entity_type"),
                "to_symbol": r["target"].get("cse_symbol"),
                "confidence": r["rel"].get("confidence")
            }
            for r in rows
        ])
        st.dataframe(path_df, use_container_width=True)

    with st.expander("Show raw edges"):
        raw_df = pd.DataFrame([
            {
                "source": r["source"].get("name"),
                "source_type": r["source"].get("entity_type"),
                "relationship": r["rel"].get("relationship_type"),
                "ownership_percentage": r["rel"].get("ownership_percentage"),
                "target": r["target"].get("name"),
                "target_type": r["target"].get("entity_type"),
                "target_symbol": r["target"].get("cse_symbol"),
                "confidence": r["rel"].get("confidence"),
                "source_url": r["rel"].get("source_url")
            }
            for r in rows
        ])
        st.dataframe(raw_df, use_container_width=True)
