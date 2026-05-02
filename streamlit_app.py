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
    layout="wide"
)

st.title("Sri Lankan CSE Ownership Intelligence Graph")

# ==============================
# SIDEBAR CONFIG
# ==============================

st.sidebar.header("Neo4j Aura Connection")

URI = st.sidebar.text_input(
    "Neo4j URI",
    value="neo4j+s://044142d8.databases.neo4j.io"
)

USERNAME = st.sidebar.text_input(
    "Username",
    value="044142d8"
)

PASSWORD = st.sidebar.text_input(
    "Password",
    type="password"
)

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

limit = st.sidebar.slider("Max edges", 50, 1000, 250, 50)

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
# HELPER FUNCTIONS
# ==============================

def get_companies():
    query = """
    MATCH (c:ListedCompany)
    RETURN c.name AS name, c.cse_symbol AS symbol
    ORDER BY c.name
    """
    rows = run_query(query)
    return pd.DataFrame(rows)

def get_owners():
    query = """
    MATCH (o:Entity)-[r:RELATED_TO]->(:ListedCompany)
    RETURN DISTINCT o.name AS name, o.entity_type AS entity_type
    ORDER BY o.name
    """
    rows = run_query(query)
    return pd.DataFrame(rows)

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
    except:
        return ""

def build_pyvis_graph(rows):
    net = Network(
        height="780px",
        width="100%",
        directed=True,
        notebook=False,
        bgcolor="#ffffff",
        font_color="#222222"
    )

    net.barnes_hut(
        gravity=-25000,
        central_gravity=0.3,
        spring_length=160,
        spring_strength=0.03,
        damping=0.09
    )

    added_nodes = set()

    for row in rows:
        source = row["source"]
        target = row["target"]
        rel = row["rel"]

        source_id = source["node_id"]
        target_id = target["node_id"]

        if source_id not in added_nodes:
            source_label = source.get("cse_symbol") or source.get("name")
            source_title = f"""
            <b>{source.get('name')}</b><br>
            Type: {source.get('entity_type')}<br>
            Symbol: {source.get('cse_symbol')}<br>
            Sector: {source.get('sector')}<br>
            Company ID: {source.get('company_id')}
            """

            net.add_node(
                source_id,
                label=source_label,
                title=source_title,
                color=node_color(source.get("entity_type")),
                size=28 if source.get("entity_type") == "LISTED_COMPANY" else 22
            )
            added_nodes.add(source_id)

        if target_id not in added_nodes:
            target_label = target.get("cse_symbol") or target.get("name")
            target_title = f"""
            <b>{target.get('name')}</b><br>
            Type: {target.get('entity_type')}<br>
            Symbol: {target.get('cse_symbol')}<br>
            Sector: {target.get('sector')}<br>
            Company ID: {target.get('company_id')}
            """

            net.add_node(
                target_id,
                label=target_label,
                title=target_title,
                color=node_color(target.get("entity_type")),
                size=30 if target.get("entity_type") == "LISTED_COMPANY" else 22
            )
            added_nodes.add(target_id)

        rel_type = rel.get("relationship_type", "RELATED_TO")
        pct = rel.get("ownership_percentage")
        pct_label = format_pct(pct)

        edge_label = pct_label if pct_label else rel_type

        edge_title = f"""
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
            title=edge_title,
            color=edge_color(rel_type),
            width=width,
            arrows="to"
        )

    net.set_options("""
    {
      "nodes": {
        "borderWidth": 1,
        "font": {
          "size": 16,
          "face": "Arial"
        }
      },
      "edges": {
        "font": {
          "size": 12,
          "align": "middle"
        },
        "smooth": {
          "type": "dynamic"
        }
      },
      "physics": {
        "enabled": true,
        "stabilization": {
          "iterations": 150
        }
      },
      "interaction": {
        "hover": true,
        "navigationButtons": true,
        "keyboard": true
      }
    }
    """)

    return net

def render_graph(net):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".html") as tmp:
        path = tmp.name

    net.write_html(path)

    with open(path, "r", encoding="utf-8") as f:
        html = f.read()

    components.html(html, height=820, scrolling=True)

    os.remove(path)

# ==============================
# QUERY BUILDERS
# ==============================

def company_ownership_query(symbol, depth, min_conf, min_own, limit):
    query = f"""
    MATCH path = (source:Entity)-[rels:RELATED_TO*1..{depth}]->(target:ListedCompany)
    WHERE target.cse_symbol = $symbol
    UNWIND rels AS r
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
    MATCH path = (source:Entity)-[rels:RELATED_TO*1..{depth}]->(target:ListedCompany)
    WHERE toUpper(source.canonical_name) CONTAINS toUpper($owner_name)
    UNWIND rels AS r
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

# ==============================
# MAIN APP
# ==============================

try:
    companies_df = get_companies()
    owners_df = get_owners()

    st.sidebar.success("Connected to Neo4j Aura")

    if search_mode == "Company ownership view":
        st.subheader("Company Ownership View")

        companies_df["display"] = companies_df["symbol"].fillna("") + " | " + companies_df["name"].fillna("")
        selected = st.selectbox("Select listed company", companies_df["display"].tolist())

        selected_symbol = selected.split(" | ")[0]

        rows = company_ownership_query(
            selected_symbol,
            max_depth,
            min_confidence,
            min_ownership,
            limit
        )

    elif search_mode == "Owner influence view":
        st.subheader("Owner Influence View")

        owners_df["display"] = owners_df["name"].fillna("") + " | " + owners_df["entity_type"].fillna("")
        selected_owner = st.selectbox("Select owner / person / institution", owners_df["display"].tolist())

        owner_name = selected_owner.split(" | ")[0]

        rows = owner_influence_query(
            owner_name,
            max_depth,
            min_confidence,
            min_ownership,
            limit
        )

    elif search_mode == "Top influential owners":
        st.subheader("Top Influential Owners")

        top_df = pd.DataFrame(run_query("""
        MATCH (owner:Entity)-[r:RELATED_TO]->(company:ListedCompany)
        WHERE coalesce(r.confidence, 0) >= $min_conf
        RETURN
            owner.name AS owner,
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

        rows = full_graph_query(
            min_confidence,
            min_ownership,
            limit
        )

    st.markdown("---")

    if not rows:
        st.warning("No graph data found for the selected filters.")
    else:
        col1, col2, col3 = st.columns(3)
        col1.metric("Edges returned", len(rows))
        col2.metric("Min confidence", min_confidence)
        col3.metric("Min ownership %", min_ownership)

        net = build_pyvis_graph(rows)
        render_graph(net)

        with st.expander("Show raw edges"):
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