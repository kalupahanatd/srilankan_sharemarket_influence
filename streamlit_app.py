import streamlit as st
import pandas as pd
from neo4j import GraphDatabase
from pyvis.network import Network
import streamlit.components.v1 as components
import tempfile
import os

# ==============================
# PAGE CONFIG
# ==============================

st.set_page_config(
    page_title="CSE Ownership Graph",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ==============================
# MOBILE FRIENDLY CSS
# ==============================

st.markdown("""
<style>
.block-container {
    padding-top: 1rem;
    padding-left: 1rem;
    padding-right: 1rem;
}

@media (max-width: 768px) {
    .block-container {
        padding-left: 0.5rem;
        padding-right: 0.5rem;
    }

    h1 {
        font-size: 1.5rem !important;
    }

    h2, h3 {
        font-size: 1.1rem !important;
    }

    .stMetric {
        padding: 0.2rem;
    }
}
</style>
""", unsafe_allow_html=True)

st.title("CSE Ownership Intelligence Graph")

# ==============================
# APP PASSWORD GATE
# ==============================

APP_PASSWORD = st.secrets.get("app_password", "")

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.subheader("Access Required")

    password_input = st.text_input(
        "Enter app password",
        type="password"
    )

    if st.button("Load App"):
        if APP_PASSWORD and password_input == APP_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Invalid password")

    st.stop()

# ==============================
# NEO4J CONFIG FROM SECRETS
# ==============================

URI = st.secrets["neo4j"]["uri"]
USERNAME = st.secrets["neo4j"]["username"]
PASSWORD = st.secrets["neo4j"]["password"]

# ==============================
# SIDEBAR FILTERS
# ==============================

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

max_depth = st.sidebar.slider("Relationship depth", 1, 5, 2)

min_confidence = st.sidebar.slider(
    "Minimum confidence",
    0.0,
    1.0,
    0.80,
    0.05
)

min_ownership = st.sidebar.slider(
    "Minimum ownership %",
    0.0,
    100.0,
    0.0,
    1.0
)

limit = st.sidebar.slider("Max edges", 25, 500, 150, 25)

st.sidebar.markdown("---")
run_graph = st.sidebar.button("Load / Refresh Graph", type="primary")

if "run_graph" not in st.session_state:
    st.session_state.run_graph = False

if run_graph:
    st.session_state.run_graph = True

# ==============================
# NEO4J CONNECTION
# ==============================

@st.cache_resource
def get_driver(uri, username, password):
    return GraphDatabase.driver(uri, auth=(username, password))

def run_query(query, params=None):
    driver = get_driver(URI, USERNAME, PASSWORD)
    with driver.session() as session:
        result = session.run(query, params or {})
        return [record.data() for record in result]

# ==============================
# DATA LOADERS
# ==============================

@st.cache_data(ttl=600)
def get_companies():
    query = """
    MATCH (c:ListedCompany)
    RETURN c.name AS name, c.cse_symbol AS symbol
    ORDER BY c.name
    """
    rows = run_query(query)
    return pd.DataFrame(rows)

@st.cache_data(ttl=600)
def get_owners():
    query = """
    MATCH (o:Entity)-[r:RELATED_TO]->(:ListedCompany)
    RETURN DISTINCT o.name AS name, o.entity_type AS entity_type
    ORDER BY o.name
    """
    rows = run_query(query)
    return pd.DataFrame(rows)

# ==============================
# STYLING HELPERS
# ==============================

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
        return f"{float(x):.1f}%"
    except:
        return ""

# ==============================
# GRAPH BUILDER
# ==============================

def build_pyvis_graph(rows, mobile=False):
    height = "620px" if mobile else "760px"

    net = Network(
        height=height,
        width="100%",
        directed=True,
        notebook=False,
        bgcolor="#ffffff",
        font_color="#222222"
    )

    net.barnes_hut(
        gravity=-18000 if mobile else -25000,
        central_gravity=0.35,
        spring_length=120 if mobile else 160,
        spring_strength=0.04,
        damping=0.1
    )

    added_nodes = set()

    for row in rows:
        source = row["source"]
        target = row["target"]
        rel = row["rel"]

        source_id = source["node_id"]
        target_id = target["node_id"]

        for node, node_id in [(source, source_id), (target, target_id)]:
            if node_id in added_nodes:
                continue

            label = node.get("cse_symbol") or node.get("name")
            if mobile and label and len(label) > 16:
                label = label[:16] + "..."

            title = f"""
            <b>{node.get('name')}</b><br>
            Type: {node.get('entity_type')}<br>
            Symbol: {node.get('cse_symbol')}<br>
            Sector: {node.get('sector')}<br>
            Company ID: {node.get('company_id')}
            """

            base_size = 24 if mobile else 30
            if node.get("entity_type") == "PERSON":
                base_size = 22 if mobile else 26

            net.add_node(
                node_id,
                label=label,
                title=title,
                color=node_color(node.get("entity_type")),
                size=base_size
            )

            added_nodes.add(node_id)

        rel_type = rel.get("relationship_type", "RELATED_TO")
        pct = rel.get("ownership_percentage")
        pct_label = format_pct(pct)
        edge_label = pct_label if pct_label else rel_type

        title = f"""
        <b>{rel_type}</b><br>
        Ownership: {pct_label}<br>
        Confidence: {rel.get('confidence')}<br>
        Source: {rel.get('source_url')}<br>
        Date: {rel.get('data_source_date')}
        """

        width = 1
        if pct is not None:
            try:
                width = max(1, min(8, float(pct) / 10))
            except:
                width = 1

        net.add_edge(
            source_id,
            target_id,
            label=edge_label,
            title=title,
            color=edge_color(rel_type),
            width=width,
            arrows="to"
        )

    font_size = 10 if mobile else 14
    edge_font_size = 9 if mobile else 12

    net.set_options(f"""
    {{
      "nodes": {{
        "borderWidth": 1,
        "font": {{
          "size": {font_size},
          "face": "Arial"
        }}
      }},
      "edges": {{
        "font": {{
          "size": {edge_font_size},
          "align": "middle"
        }},
        "smooth": {{
          "type": "dynamic"
        }}
      }},
      "physics": {{
        "enabled": true,
        "stabilization": {{
          "iterations": 120
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

def render_graph(net, mobile=False):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".html") as tmp:
        path = tmp.name

    net.write_html(path)

    with open(path, "r", encoding="utf-8") as f:
        html = f.read()

    height = 660 if mobile else 810
    components.html(html, height=height, scrolling=True)

    os.remove(path)

# ==============================
# QUERY FUNCTIONS
# ==============================

def company_ownership_query(symbol, depth, min_conf, min_own, limit):
    query = f"""
    MATCH path = (source:Entity)-[rels:RELATED_TO*1..{depth}]->(target:ListedCompany)
    WHERE target.cse_symbol = $symbol
    UNWIND rels AS r
    WITH DISTINCT startNode(r) AS s, r, endNode(r) AS t
    WHERE coalesce(r.confidence, 0) >= $min_conf
      AND coalesce(r.ownership_percentage, 0) >= $min_own
    RETURN properties(s) AS source,
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
    MATCH path = (source:Entity)-[rels:RELATED_TO*1..{depth}]->(target:ListedCompany)
    WHERE toUpper(source.canonical_name) CONTAINS toUpper($owner_name)
    UNWIND rels AS r
    WITH DISTINCT startNode(r) AS s, r, endNode(r) AS t
    WHERE coalesce(r.confidence, 0) >= $min_conf
      AND coalesce(r.ownership_percentage, 0) >= $min_own
    RETURN properties(s) AS source,
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
    RETURN properties(s) AS source,
           properties(r) AS rel,
           properties(t) AS target
    LIMIT $limit
    """
    return run_query(query, {
        "min_conf": min_conf,
        "min_own": min_own,
        "limit": limit
    })

# ==============================
# MAIN UI
# ==============================

try:
    companies_df = get_companies()
    owners_df = get_owners()

    st.success("Connected to Neo4j Aura")

    mobile_mode = st.toggle("Mobile friendly rendering", value=False)

    if search_mode == "Company ownership view":
        st.subheader("Company Ownership View")

        companies_df["display"] = (
            companies_df["symbol"].fillna("") + " | " + companies_df["name"].fillna("")
        )

        selected = st.selectbox(
            "Select listed company",
            companies_df["display"].tolist()
        )

        selected_symbol = selected.split(" | ")[0]

        st.info("Change filters from the sidebar, then click **Load / Refresh Graph**.")

        if not st.session_state.run_graph:
            st.stop()

        rows = company_ownership_query(
            selected_symbol,
            max_depth,
            min_confidence,
            min_ownership,
            limit
        )

    elif search_mode == "Owner influence view":
        st.subheader("Owner Influence View")

        owners_df["display"] = (
            owners_df["name"].fillna("") + " | " + owners_df["entity_type"].fillna("")
        )

        selected_owner = st.selectbox(
            "Select owner / person / institution",
            owners_df["display"].tolist()
        )

        owner_name = selected_owner.split(" | ")[0]

        st.info("Change filters from the sidebar, then click **Load / Refresh Graph**.")

        if not st.session_state.run_graph:
            st.stop()

        rows = owner_influence_query(
            owner_name,
            max_depth,
            min_confidence,
            min_ownership,
            limit
        )

    elif search_mode == "Top influential owners":
        st.subheader("Top Influential Owners")

        if not st.session_state.run_graph:
            st.info("Click **Load / Refresh Graph** in the sidebar.")
            st.stop()

        top_df = pd.DataFrame(run_query("""
        MATCH (owner:Entity)-[r:RELATED_TO]->(company:ListedCompany)
        WHERE coalesce(r.confidence, 0) >= $min_conf
        RETURN owner.name AS owner,
               owner.entity_type AS type,
               count(DISTINCT company) AS listed_companies,
               avg(r.ownership_percentage) AS avg_ownership
        ORDER BY listed_companies DESC
        LIMIT 30
        """, {"min_conf": min_confidence}))

        st.dataframe(top_df, use_container_width=True)

        rows = full_graph_query(
            min_confidence,
            min_ownership,
            limit
        )

    else:
        st.subheader("Full Filtered Ownership Graph")

        if not st.session_state.run_graph:
            st.info("Click **Load / Refresh Graph** in the sidebar.")
            st.stop()

        rows = full_graph_query(
            min_confidence,
            min_ownership,
            limit
        )

    if not rows:
        st.warning("No graph data found for selected filters.")
    else:
        col1, col2, col3 = st.columns(3)
        col1.metric("Edges", len(rows))
        col2.metric("Min confidence", min_confidence)
        col3.metric("Min ownership", f"{min_ownership:.0f}%")

        net = build_pyvis_graph(rows, mobile=mobile_mode)
        render_graph(net, mobile=mobile_mode)

        with st.expander("Raw edge data"):
            raw_df = pd.DataFrame([
                {
                    "source": r["source"].get("name"),
                    "source_type": r["source"].get("entity_type"),
                    "relationship": r["rel"].get("relationship_type"),
                    "ownership_percentage": r["rel"].get("ownership_percentage"),
                    "target": r["target"].get("name"),
                    "target_symbol": r["target"].get("cse_symbol"),
                    "confidence": r["rel"].get("confidence"),
                    "source_url": r["rel"].get("source_url")
                }
                for r in rows
            ])
            st.dataframe(raw_df, use_container_width=True)

except Exception as e:
    st.error("Could not connect or query Neo4j.")
    st.exception(e)
