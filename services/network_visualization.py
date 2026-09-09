################################################################################
# Filename: network_visualization.py
#
# Purpose:
# This script contains functions for visualizing word networks in literature
#           using pyvis.
#
# Author: Drew Heasman, P.Geo
# Last Updated: 30-06-2025
#
# Organization: University of Saskatchewan
################################################################################

################################################################################
# Future Improvements
################################################################################

# - Better curate categories in network graph
# - Add support for dynamic selection of color themes for all visualizations.
# - Optimize network visualization to handle larger datasets efficiently.

################################################################################
# Libraries
################################################################################

# Standard Libraries
import os
import pandas as pd
import numpy as np
from pyvis.network import Network
from sqlalchemy import text


################################################################################
# Global Variables
################################################################################

CATEGORIES = {
    "Lithology": [
        "granite", "granodiorite", "tonalite", "diorite", "gabbro", "anorthosite", "peridotite", "komatiite",
        "pegmatite", "rhyolite", "dacite", "andesite", "basalt", "trachyte", "phonolite", "ignimbrite", "tuff",
        "breccia", "conglomerate", "sandstone", "siltstone", "shale", "mudstone", "chert", "limestone", "dolostone",
        "chalk", "coal", "ironstone", "phosphorite", "marl", "evaporite", "gypsum", "halite", "quartzite",
        "slate", "phyllite", "schist", "gneiss", "migmatite", "marble", "soapstone", "amphibolite", "eclogite",
        "skarn", "hornfels", "cataclasite", "mylonite"
    ],
    "Mineralogy": [
        "quartz", "feldspar", "microcline", "orthoclase", "plagioclase", "muscovite", "biotite", "chlorite",
        "pyroxene", "amphibole", "hornblende", "actinolite", "tremolite", "augite", "olivine", "garnet", "staurolite",
        "kyanite", "andalusite", "sillimanite", "zircon", "tourmaline", "apatite", "fluorite", "corundum",
        "diamond", "graphite", "hematite", "magnetite", "goethite", "ilmenite", "rutile", "chromite", "cassiterite",
        "pyrite", "chalcopyrite", "sphalerite", "galena", "arsenopyrite", "bornite", "covellite", "chalcocite",
        "tetrahedrite", "bismuthinite", "molybdenite", "cinnabar", "realgar", "orpiment", "pentlandite", "marcasite",
        "cerussite", "anglesite", "wulfenite", "vanadinite", "barite", "celestite", "gypsum", "anhydrite",
        "malachite", "azurite", "smithsonite", "rhodochrosite", "siderite", "ankerite", "dolomite", "calcite",
        "sodalite", "nepheline", "leucite", "serpentine", "talc", "kaolinite", "montmorillonite", "vermiculite",
        "chloritoid", "prehnite", "pumpellyite"
    ],
    "Elements": [
        "h", "he", "li", "be", "b", "c", "n", "o", "f", "ne", "na", "mg", "al", "si", "p", "s", "cl", "ar", "k", "ca",
        "sc", "ti", "v", "cr", "mn", "fe", "co", "ni", "cu", "zn", "ga", "ge", "as", "se", "br", "kr", "rb", "sr",
        "y", "zr", "nb", "mo", "tc", "ru", "rh", "pd", "ag", "cd", "in", "sn", "sb", "te", "i", "xe", "cs", "ba",
        "la", "ce", "pr", "nd", "pm", "sm", "eu", "gd", "tb", "dy", "ho", "er", "tm", "yb", "lu", "hf", "ta", "w",
        "re", "os", "ir", "pt", "au", "hg", "tl", "pb", "bi", "po", "at", "rn", "fr", "ra", "ac", "th", "pa", "u",
        "np", "pu", "am", "cm", "bk", "cf", "es", "fm", "md", "no", "lr"
    ],
    "General Terms": [
        "carbonate", "siliciclastic", "clay", "mafic", "felsic", "intermediate", "ultramafic", "volcanic", "plutonic",
        "metamorphic", "sedimentary", "igneous", "hydrothermal", "vein", "ore", "skarn", "pegmatitic", "porphyritic",
        "regional metamorphism", "contact metamorphism", "ductile deformation", "brittle deformation", "fault",
        "shear zone", "fracture", "joint", "fold", "syncline", "anticline", "thrust", "normal fault", "strike-slip",
        "subduction", "accretionary wedge", "ophiolite", "island arc", "rift", "mid-ocean ridge", "continental shelf",
        "craton", "shield", "platform", "terrane", "orogeny", "forearc basin", "backarc basin", "magmatism",
        "metasomatism", "weathering", "erosion", "deposition"
    ]
}

################################################################################
# Interactive Co-occurrence Network Visualization
################################################################################
def plot_interactive_cooccurrence_network(engine, search_term, top_n=10, threshold=1e-10, depth=3, output_filename=None):
    """
    Generates an interactive co-occurrence network visualization using Pyvis.

    Saves and returns the filename for external serving, rather than opening it locally.
    """
    net = Network(height="100vh", width="100vw", directed=False, notebook=False, cdn_resources="remote")

    # ✅ Color map by depth
    color_map = {0: "red", 1: "blue", 2: "green", 3: "gray"}

    # ✅ Fetch data with node depths
    cooccurrence_data, probabilities, seen_nodes, node_depth = fetch_cooccurrence_data(
        engine, search_term, top_n, depth
    )

    if not probabilities:
        print("❌ No co-occurrence probabilities found. Aborting visualization.")
        return None

    # ✅ Build graph
    node_connections, node_colors, node_categories = add_nodes_and_edges(
        net, cooccurrence_data, seen_nodes, node_depth, CATEGORIES, color_map, search_term
    )

    apply_dynamic_node_sizing(net, node_connections, node_colors)

    if not net.get_nodes():
        print("❌ ERROR: Pyvis Network has NO nodes. Aborting visualization.")
        return None

    # ✅ Save CSV
    csv_filename = save_network_as_csv(cooccurrence_data)

    # ✅ Log-scale range for filtering
    min_prob = min(probabilities.values())
    min_log, max_log = np.floor(np.log10(min_prob)), np.ceil(np.log10(max(probabilities.values())))

    ui_html = generate_ui_controls(min_log, max_log, min_prob, node_colors, node_categories, search_term, csv_filename)

    # ✅ File output name
    if output_filename is None:
        output_filename = f"{search_term.replace(' ', '_')}.html"

    filename = os.path.join("static", "network", output_filename)

    # ✅ Save but don't open
    net.save_graph(filename)

    # ✅ Inject UI panel
    with open(filename, "r", encoding="utf-8") as f:
        html_content = f.read()

    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_content.replace("<body>", "<body>" + ui_html))

    return filename

def fetch_cooccurrence_data(engine, search_term, top_n, depth):
    from collections import deque

    cooccurrence_data = []
    probabilities = {}
    seen_nodes = set()
    node_depth = {search_term: 0}
    queue = deque([(search_term, 0)])

    MAX_NODES_PER_LEVEL = 150
    MAX_TOTAL_NODES = 600

    edge_tracker = set()  # To avoid duplicate edges

    while queue:
        node, level = queue.popleft()

        if level >= depth:
            print("level >= depth")
            continue
        if node in seen_nodes:
            print("node in seen_nodes")
            continue
    
        seen_nodes.add(node)

        query = """
        SELECT word_1, word_2, prob_w1w2 AS probability
        FROM term_cooccurrence
        WHERE word_1 = %s OR word_2 = %s
        ORDER BY prob_w1w2 DESC
        LIMIT %s
        """
        with engine.connect() as conn:
            df = pd.read_sql_query(query, conn, params=(node, node, top_n))

        if df.empty:
            continue

        for _, row in df.iterrows():
            word1 = row["word_1"]
            word2 = row["word_2"]
            prob = row["probability"]

            # Normalize direction
            if word1 == node:
                source, target = word1, word2
            else:
                source, target = word2, word1

            edge_key = (min(source, target), max(source, target))
            if edge_key in edge_tracker:
                continue
            edge_tracker.add(edge_key)

            cooccurrence_data.append({
                "word_1": source,
                "word_2": target,
                "probability": prob
            })
            probabilities[f"{source}_{target}"] = prob

            # Only assign depth & queue if not already discovered
            if target not in node_depth:
                node_depth[target] = level + 1
                if level + 1 < depth and len(seen_nodes) + len(queue) < MAX_TOTAL_NODES:
                    print(f"Queuing {target} at depth {level+1}")
                    queue.append((target, level + 1))
                else:
                    print(f"NOT queuing {target} (level+1={level+1}, depth={depth})")
            else:
                print(f"{target} already in node_depth at depth {node_depth[target]}")

            print(f"🧠 Seen Nodes: {len(seen_nodes)} | Queue: {len(queue)} | Depth: {level}")
        
        if len(seen_nodes) > MAX_TOTAL_NODES:
            print(f"⚠️ Reached global node limit of {MAX_TOTAL_NODES}. Stopping expansion.")
            break
        
    return cooccurrence_data, probabilities, seen_nodes, node_depth


def apply_dynamic_node_sizing(net, node_connections, node_colors):
    """
    Adjusts node sizes dynamically based on their degree centrality within the network.

    This function scales node sizes proportionally to the number of connections (edges) 
    each node has. Nodes with more connections appear larger, while nodes with fewer 
    connections are smaller. This provides a clearer visual representation of 
    highly connected vs. less connected nodes.

    Parameters:
    ----------
    net : pyvis.network.Network
        The Pyvis network graph where nodes and edges are being visualized.

    node_connections : dict
        A dictionary mapping each node to the number of edges (connections) it has.

    node_colors : dict
        A dictionary mapping nodes to their respective color categories.

    Returns:
    -------
    None
        The function updates the network `net` by modifying node sizes based on 
        their connectivity.

    Notes:
    ------
    - Uses a **linear scaling approach** to distribute node sizes between a minimum 
      (`min_size=10`) and maximum (`max_size=40`).
    - Prevents division errors by setting a default minimum of 1 connection.
    - Ensures nodes exist in `node_colors` before attempting to modify them.

    Example Usage:
    --------------
    >>> apply_dynamic_node_sizing(net, node_connections, node_colors)

    """

    min_size, max_size = 10, 40
    min_connections = min(node_connections.values(), default=1)
    max_connections = max(node_connections.values(), default=1)

    for node, connections in node_connections.items():
        range_connections = max_connections - min_connections or 1
        size = min_size + (max_size - min_size) * (connections - min_connections) / range_connections

        # ✅ Fixed: label=node
        if node in node_colors:
            net.add_node(node, label=node, color=node_colors[node], font={"size": 24, "color": [node], "face": "Roboto", "bold": True}, title=str(node))



def save_network_as_csv(cooccurrence_data, filename="cooccurrence_data.csv"):
    """
    Saves co-occurrence data to a CSV file for further analysis.

    This function converts a list of dictionaries representing co-occurrence relationships
    into a pandas DataFrame and saves it as a CSV file. The resulting file can be used
    for external data analysis, debugging, or sharing results.

    Parameters:
    ----------
    cooccurrence_data : list of dict
        A list where each dictionary contains co-occurrence relationships 
        between words, along with probabilities.

    filename : str, optional
        The name of the output CSV file (default is "cooccurrence_data.csv").

    Returns:
    -------
    str
        The filename where the CSV is saved.

    Example Usage:
    --------------
    >>> cooccurrence_data = [{"word_1": "granite", "word_2": "quartz", "prob_w1w2": 0.05}]
    >>> save_network_as_csv(cooccurrence_data, "output.csv")
    'output.csv'

    Notes:
    ------
    - The function **overwrites** an existing file with the same name.
    - If `cooccurrence_data` is empty, an empty CSV is still created.
    - The saved CSV maintains the same structure as `cooccurrence_data`.

    """
    df_cooccurrence = pd.DataFrame(cooccurrence_data)
    df_cooccurrence.to_csv(filename, index=False)
    return filename


def generate_ui_controls(min_log, max_log, min_prob, node_colors, node_categories, search_term, csv_filename):
    """
    Generates JavaScript and HTML for UI controls to interact with a co-occurrence network visualization.

    This function dynamically creates UI elements such as sliders, search boxes, category filters, 
    and export buttons to interact with a Pyvis network graph. These controls allow users to filter
    nodes and edges based on probability, search for specific words, categorize words, and export 
    the network as a PNG or CSV.

    Parameters:
    ----------
    min_log : float
        The minimum logarithmic value for the probability slider.
    
    max_log : float
        The maximum logarithmic value for the probability slider.
    
    min_prob : float
        The minimum probability value displayed on the slider.
    
    node_colors : dict
        A dictionary mapping each node to its respective color.
    
    node_categories : dict
        A dictionary mapping each node to its assigned category (e.g., "Lithology", "Mineralogy").
    
    search_term : str
        The root search term for which the co-occurrence network is generated.
    
    csv_filename : str
        The filename for downloading the co-occurrence data as a CSV.

    Returns:
    -------
    str
        A string containing the JavaScript and HTML code for UI controls.

    Example Usage:
    --------------
    >>> js_ui = generate_ui_controls(-10, 0, 1e-10, node_colors, node_categories, "volcanic arc", "network_data.csv")
    >>> print(js_ui)  # Outputs JavaScript and HTML elements

    Features:
    ---------
    - **Edge Filtering**: Uses a logarithmic slider to hide edges below a certain probability.
    - **Node Search**: Highlights and enlarges nodes matching the search term.
    - **Category Filtering**: Filters nodes by predefined geological categories.
    - **Network Exporting**: Allows downloading the visualization as a PNG or CSV.

    Notes:
    ------
    - The UI dynamically updates based on the network data.
    - Filtering uses **Dijkstra's Algorithm** to maintain a shortest path from category-filtered nodes to the root word.
    - Uses `dom-to-image` for exporting PNG snapshots of the visualization.
    - The function generates UI code, which must be injected into an HTML file containing the Pyvis network.

    """

    return f"""
        <script>
            var network;
            var originalColors = {str(node_colors)};
            var nodeCategories = {str(node_categories)};
            var rootWord = "{search_term}".replace('"', '\\"');

            function startNetwork() {{
                if (window.visNetwork) {{
                    network = window.visNetwork;

                    var nodes = network.body.data.nodes.get();
                    nodes.forEach(node => {{
                        originalColors[node.id] = node.color;
                    }});

                    updateEdges();
                }} else {{
                    setTimeout(startNetwork, 100);
                }}
            }}

            function updateEdges() {{
                var logThreshold = document.getElementById('thresholdSlider').value;
                var threshold = Math.pow(10, logThreshold);
                document.getElementById('sliderValue').innerText = threshold.toExponential(2);

                var edges = network.body.data.edges.get();
                edges.forEach(edge => {{
                    var edgeValue = parseFloat(edge.title);
                    edge.hidden = edgeValue < threshold;
                }});

                network.body.data.edges.update(edges);
            }}

            function searchNode() {{
                var query = document.getElementById('searchBox').value.toLowerCase();
                var nodes = network.body.data.nodes.get();

                nodes.forEach(node => {{
                    node.color = originalColors[node.id] || "gray";
                    node.size = 10;
                }});

                nodes.forEach(node => {{
                    if (node.label.toLowerCase().includes(query) && query.length > 0) {{
                        node.color = "yellow"; 
                        node.size = 30;
                    }}
                }});

                network.body.data.nodes.update(nodes);
            }}

            function clearSearch() {{
                var nodes = network.body.data.nodes.get();
                nodes.forEach(node => {{
                    node.color = originalColors[node.id] || "gray";  
                    node.size = 10;
                }});
                network.body.data.nodes.update(nodes);
                document.getElementById('searchBox').value = "";
            }}

            function filterByCategory() {{
                var selectedCategory = document.getElementById('categoryDropdown').value;
                var nodes = network.body.data.nodes.get();
                var edges = network.body.data.edges.get();

                console.log("🔍 Selected Category:", selectedCategory);

                if (selectedCategory === "All") {{
                    nodes.forEach(node => node.hidden = false);
                    edges.forEach(edge => edge.hidden = false);
                    network.body.data.nodes.update(nodes);
                    network.body.data.edges.update(edges);
                    console.log("✅ Showing all nodes & edges.");
                    return;
                }}

                var visibleNodes = new Set();
                var bestPaths = new Map();  
                visibleNodes.add(rootWord);
                bestPaths.set(rootWord, 0);

                console.log("🔴 Root Word Always Visible:", rootWord);

                var categoryNodes = [];
                nodes.forEach(node => {{
                    var nodeCategory = nodeCategories[node.label] || "Other";  
                    if (nodeCategory === selectedCategory) {{
                        categoryNodes.push(node.id);
                        bestPaths.set(node.id, Infinity);  
                        visibleNodes.add(node.id);
                        console.log("✅ Keeping Category Node:", node.label);
                    }}
                }});

                console.log("🔵 Category Nodes Identified:", categoryNodes);

                var pq = [];
                categoryNodes.forEach(node => pq.push([node, Infinity]));  
                pq.push([rootWord, 0]);  

                var parentMap = new Map(); 

                while (pq.length > 0) {{
                    pq.sort((a, b) => a[1] - b[1]);  
                    var [currentNode, currentDist] = pq.shift();

                    edges.forEach(edge => {{
                        var neighbor = null;
                        if (edge.to === currentNode) neighbor = edge.from;
                        if (edge.from === currentNode) neighbor = edge.to;

                        if (neighbor && bestPaths.has(currentNode)) {{
                            let edgeWeight = parseFloat(edge.title);
                            let newDist = currentDist + (1 / edgeWeight);

                            if (!bestPaths.has(neighbor) || newDist < bestPaths.get(neighbor)) {{
                                bestPaths.set(neighbor, newDist);
                                parentMap.set(neighbor, currentNode);
                                pq.push([neighbor, newDist]);
                            }}
                        }}
                    }});
                }}

                console.log("🔗 Best Paths Found:", parentMap);

                var finalVisibleNodes = new Set();
                finalVisibleNodes.add(rootWord);

                categoryNodes.forEach(node => {{
                    var current = node;
                    while (current && !finalVisibleNodes.has(current)) {{
                        finalVisibleNodes.add(current);
                        current = parentMap.get(current);
                    }}
                }});

                console.log("🟢 Final Visible Nodes:", Array.from(finalVisibleNodes));

                nodes.forEach(node => {{
                    node.hidden = !finalVisibleNodes.has(node.id);
                }});
                edges.forEach(edge => {{
                    edge.hidden = !(finalVisibleNodes.has(edge.from) && finalVisibleNodes.has(edge.to));
                }});

                console.log("📌 Nodes After Filtering:", JSON.stringify(nodes));
                console.log("📌 Edges After Filtering:", JSON.stringify(edges));

                network.body.data.nodes.update(nodes);
                network.body.data.edges.update(edges);
                console.log("✅ Filter Applied.");
            }}

            function saveAsPNG() {{
                domtoimage.toPng(document.body)
                    .then(function (dataUrl) {{
                        var link = document.createElement('a');
                        link.href = dataUrl;
                        link.download = 'network_visualization.png';
                        link.click();
                    }})
                    .catch(function (error) {{
                        console.error('Error saving PNG:', error);
                    }});
            }}

            function toggleUIPanel() {{
                const panel = document.getElementById('uiPanel');
                const showBtn = document.getElementById('showUIPanelBtn');

                if (panel.style.display === 'none') {{
                    panel.style.display = 'block';
                    showBtn.style.display = 'none';
                }} else {{
                    panel.style.display = 'none';
                    showBtn.style.display = 'block';
                }}
            }}

            window.addEventListener('load', startNetwork);
        </script>

        <script src="https://cdn.jsdelivr.net/npm/dom-to-image@2.6.0/dist/dom-to-image.min.js"></script>

        <div id="uiPanel" style="position: fixed; top: 10px; left: 10px; z-index: 1000; background: white; padding: 10px; border-radius: 5px; max-width: 300px;">
            <button onclick="toggleUIPanel()" style="float: right;">✖</button>

            <label for="thresholdSlider"><strong>Filter Edges by Probability (Log Scale):</strong></label><br>
            <input type="range" id="thresholdSlider" min="{min_log}" max="{max_log}" step="0.1" value="{min_log}" oninput="updateEdges()">
            <span id="sliderValue">{min_prob:.8e}</span>
            <br><br>

            <label for="searchBox"><strong>Search Node:</strong></label><br>
            <input type="text" id="searchBox" oninput="searchNode()" placeholder="Enter word...">
            <button onclick="clearSearch()">Clear</button>
            <br><br>

            <label for="categoryDropdown"><strong>Filter by Category:</strong></label><br>
            <select id="categoryDropdown" onchange="filterByCategory()">
                <option value="All">All</option>
                <option value="General Terms">General Terms</option>
                <option value="Lithology">Lithology</option>
                <option value="Mineralogy">Mineralogy</option>
                <option value="Elements">Elements</option>
            </select>
            <br><br>

            <button onclick="saveAsPNG()">Save as PNG</button>
            <br><br>

            <a href="{csv_filename}" download>Download Co-occurrence CSV</a>
        </div>

        <button id="showUIPanelBtn" onclick="toggleUIPanel()" style="display:none; position: fixed; top: 10px; left: 10px; z-index: 1000;">☰ Show UI</button>
        """
        

    
def add_nodes_and_edges(net, cooccurrence_data, seen_nodes, node_depth, categories, color_map, search_term):
    """
    Adds nodes and edges to a Pyvis network visualization for co-occurrence relationships.

    This function ensures that all nodes exist before adding edges. Nodes are color-coded 
    based on depth and categorized according to geological classifications. The function 
    also tracks node connections to enable dynamic sizing.

    Parameters:
    ----------
    net : pyvis.network.Network
        The Pyvis network object where nodes and edges will be added.
    
    cooccurrence_data : list of dict
        A list of dictionaries containing co-occurrence data with keys:
        - 'word_1' (str): First term in the co-occurrence pair.
        - 'word_2' (str): Second term in the co-occurrence pair.
        - 'probability' (float): Co-occurrence probability between the terms.
    
    seen_nodes : set
        A set containing all unique nodes (words) that should be included in the network.
    
    node_depth : dict
        A dictionary mapping each node to its depth in the network, where the search term 
        starts at depth 0 and connected words increase in depth.
    
    categories : dict
        A dictionary mapping geological categories (e.g., "Lithology", "Mineralogy") 
        to lists of words belonging to those categories.
    
    color_map : dict
        A dictionary mapping depth levels to specific colors.
    
    search_term : str
        The root word for which the co-occurrence network is built.

    Returns:
    -------
    tuple
        - node_connections (dict): A dictionary mapping nodes to their number of connections.
        - node_colors (dict): A dictionary mapping nodes to their assigned colors.
        - node_categories (dict): A dictionary mapping nodes to their assigned category.

    Example Usage:
    --------------
    >>> net = Network()
    >>> cooccurrence_data = [{'word_1': 'granite', 'word_2': 'rhyolite', 'probability': 0.003}]
    >>> seen_nodes = {'granite', 'rhyolite'}
    >>> node_depth = {'granite': 0, 'rhyolite': 1}
    >>> categories = {'Lithology': ['granite', 'rhyolite']}
    >>> color_map = {0: "red", 1: "blue"}
    >>> search_term = "granite"
    >>> add_nodes_and_edges(net, cooccurrence_data, seen_nodes, node_depth, categories, color_map, search_term)

    Features:
    ---------
    - **Color Mapping by Depth**: Nodes are assigned colors based on their depth in the network.
    - **Geological Categorization**: Words are classified into categories (e.g., "Lithology", "Mineralogy").
    - **Search Term Highlighting**: The main search term is always colored red and sized larger.
    - **Edge Weighting**: Co-occurrence probabilities determine edge thickness.
    - **Dynamic Node Connections**: Tracks the number of connections for each node.

    Notes:
    ------
    - Ensures that all nodes exist before attempting to add edges.
    - If a word belongs to multiple categories, only the first matching category is assigned.
    - Uses logarithmic scaling to determine edge weights based on probabilities.
    - Prints a warning if an edge references nodes that are not in the network.

    """

    node_colors = {}
    node_categories = {}
    node_connections = {}  

    # ✅ Step 1: Add **All** seen_nodes to Pyvis with correct colors
    for node in seen_nodes:
        if node != search_term:
            depth = node_depth.get(node, 1)  # ✅ Use stored depth
            node_color = color_map.get(depth, "gray")  # ✅ Assign correct color
            node_colors[node] = node_color
            node_connections[node] = 0  

                        # ✅ Assign category (fix substring issue)
            assigned_category = "Other"
            for category, keywords in categories.items():
                if category == "Elements":
                    if node.lower() in keywords:  # ✅ Exact match
                        assigned_category = category
                        break
                else:
                    if any(node.lower() == kw for kw in keywords):  # ✅ Full-word match for rocks & minerals
                        assigned_category = category
                        break
            node_categories[node] = assigned_category  # ✅ Store corrected category
            
            net.add_node(node, label=node, color=node_color, font={"size": 24, "color": "black", "face": "Roboto", "bold": True}, title=node)

    # ✅ Step 2: Add Search Term First
    if search_term not in net.get_nodes():
        node_categories[search_term] = "General"
        node_connections[search_term] = 0  
        net.add_node(search_term, label=search_term, font={"size": 36, "color": "red", "face": "Roboto", "bold": True}, title=search_term)

    # ✅ Step 3: Add edges
    existing_nodes = set(net.get_nodes())  

    for row in cooccurrence_data:
        word1, word2 = row['word_1'], row['word_2']
        probability = row["probability"]

        if word1 in existing_nodes and word2 in existing_nodes:
            net.add_edge(word1, word2, value=probability * 100, title=f"{probability:.8e}")
            node_connections[word1] = node_connections.get(word1, 0) + 1
            node_connections[word2] = node_connections.get(word2, 0) + 1
        else:
            # Enhanced diagnostics
            word1_exists = word1 in existing_nodes
            word2_exists = word2 in existing_nodes

            if not word1_exists and word2_exists:
                reverse_exists = word1 in seen_nodes and word2 in seen_nodes
                print(f"⚠️ Node '{word1}' missing, but '{word2}' exists for edge {word1} -- {word2}. Reverse seen? {reverse_exists}")
            elif word1_exists and not word2_exists:
                reverse_exists = word1 in seen_nodes and word2 in seen_nodes
                print(f"⚠️ Node '{word2}' missing, but '{word1}' exists for edge {word1} -- {word2}. Reverse seen? {reverse_exists}")
            else:
                print(f"⚠️ Both nodes missing in Pyvis for edge {word1} -- {word2}")
 

    return node_connections, node_colors, node_categories  
