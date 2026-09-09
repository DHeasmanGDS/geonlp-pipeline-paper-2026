################################################################################
# Filename: visualization.py
#
# Purpose:
# This script contains functions for visualizing co-occurrence data, word clouds,
# and mutual information charts using various techniques.
#
# Author: Drew Heasman, P.Geo
# Last Updated: 10-02-2025
#
# Organization: University of Saskatchewan
################################################################################

################################################################################
# Future Improvements
################################################################################

# - Add more charts
# - Add interactivity for mutual information and heatmap
# - Better curate categories in network graph
# - Add support for dynamic selection of color themes for all visualizations.
# - Implement interactivity for heatmaps and bar charts (hover tooltips).
# - Optimize network visualization to handle larger datasets efficiently.
# - Improve UI elements (dropdowns, sliders) for better user experience.
# - Implement auto-saving of generated visualizations for reporting.

################################################################################
# Libraries
################################################################################

# Standard Libraries
import os
import webbrowser
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import plotly.graph_objects as go
import ipywidgets as widgets
from wordcloud import WordCloud
from pyvis.network import Network
from IPython.display import display, clear_output, HTML
from dash import Dash, dcc, html, Input, Output
from sqlalchemy import text
import threading
import webbrowser
import base64
import io
from PIL import Image, ImageOps
from adjustText import adjust_text

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
# Utility fucntions
################################################################################

def format_scientific(value):
    """
    Formats a number in scientific notation with proper superscript styling for display.
    Example: 7.96×10⁻⁷
    """
    if pd.isnull(value) or value == 0:
        return "N/A"
    
    exponent = int(f"{value:.1e}".split("e")[-1])  # Extract exponent
    coefficient = float(f"{value:.4e}".split("e")[0])  # Extract coefficient
    
    # Format with superscript notation
    return f"{coefficient:.4f}×10<sup>{exponent}</sup>"


def dash_format_scientific(value):
    """
    Formats a number in scientific notation with proper Unicode superscripts.
    Example: 7.96×10⁻⁷
    """
    if pd.isnull(value) or value == 0:
        return "N/A"

    exponent = int(f"{value:.1e}".split("e")[-1])  # Extract exponent
    coefficient = float(f"{value:.4e}".split("e")[0])  # Extract coefficient

    # Unicode superscript mapping (only supports -9 to 9)
    superscript_map = {
        "-": "⁻", "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
        "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹"
    }

    # Convert exponent to Unicode superscripts
    exponent_str = "".join(superscript_map.get(char, char) for char in str(exponent))

    return f"{coefficient:.4f}×10{exponent_str}" 


################################################################################
# Co-occurrence Heatmap Visualization
################################################################################

def plot_cooccurrence_heatmap(engine, search_term, top_n=10):
    """
    Extracts and visualizes the top co-occurring words with a given search term 
    as a heatmap.

    This function queries the `term_cooccurrence` table in the database to 
    retrieve the top `top_n` words that co-occur with `search_term`, based on 
    their co-occurrence probability. The results are displayed in a heatmap.

    Parameters:
    ----------
    engine : sqlalchemy.engine.base.Engine
        The SQLAlchemy database engine connected to the PostgreSQL database.

    search_term : str
        The search term for which co-occurrence probabilities are analyzed.

    top_n : int, optional, default=10
        The number of top co-occurring words to display in the heatmap.

    Returns:
    -------
    None
        Displays a heatmap using Matplotlib and Seaborn.

    Example Usage:
    --------------
    >>> from sqlalchemy import create_engine
    >>> engine = create_engine("postgresql://user:password@localhost:5432/mydatabase")
    >>> plot_cooccurrence_heatmap(engine, "granite", top_n=15)

    Features:
    ---------
    - **Database Querying**: Retrieves top co-occurring words and their probabilities.
    - **Heatmap Visualization**: Uses Seaborn to create an annotated heatmap.
    - **Error Handling**: Handles missing data and incorrect column names.
    - **Configurable Parameters**: Allows control over the number of words displayed.

    Notes:
    ------
    - Assumes the existence of a `term_cooccurrence` table with columns:
        - `word_1` (Primary term)
        - `word_2` (Co-occurring word)
        - `prob_w1w2` (Probability of co-occurrence)
    - If no results are found, the function prints a message and exits.
    - Ensures readability by adjusting font size and rotation of annotations.
    """
    
    # SQL query to extract co-occurrence data
    query = f"""
    SELECT word_2 AS Word, prob_w1w2 AS Probability
    FROM term_cooccurrence
    WHERE word_1 = %s
    ORDER BY Probability DESC
    LIMIT {top_n};
    """

    # Execute the query and fetch data into a DataFrame
    with engine.connect() as connection:
        df = pd.read_sql_query(query, connection, params=(search_term,))

    # Check if DataFrame is empty
    if df.empty:
        print(f"No co-occurrence data found for the term '{search_term}'.")
        return

    # Prepare data for the heatmap
    try:
        heatmap_data = df.set_index('word').T  # Transpose for heatmap structure
    except KeyError:
        print("Error: Expected column 'word' not found in the DataFrame.")
        print("Available columns:", df.columns)
        return

    # Create the heatmap
    plt.figure(figsize=(12, 3))  # Adjusting size for horizontal layout
    ax = sns.heatmap(
        heatmap_data,
        annot=True,
        cmap='coolwarm',
        fmt='.2e',
        cbar_kws={'label': f'Probability of Co-occurrence with \"{search_term}\"'}
    )
    plt.title(f'Heatmap of Co-occurrence Probabilities with \"{search_term}\"')

    # Rotate annotations for better readability
    for text in ax.texts:
        text.set_rotation(90)  # Rotate text vertically
        text.set_fontsize(8)  # Adjust font size

    plt.show()


def get_top_cooccurring_words(engine, search_term, top_n=10):
    """
    Retrieves and displays the top N co-occurring words for a given search term
    along with their word counts, entropy, and mutual information.

    Parameters:
    ----------
    engine : sqlalchemy.engine.base.Engine
        The database engine connection.
    search_term : str
        The term for which co-occurrences will be retrieved.
    top_n : int, optional, default=10
        The number of top co-occurring words to display.

    Returns:
    -------
    pd.DataFrame
        A DataFrame containing co-occurrence word pairs, probabilities, word counts,
        entropy, and mutual information, formatted in scientific notation.
    """

    query = """
    SELECT 
        tc.word_2 AS "Word",
        tc.count AS "Co-occurrence Count",
        tc.prob_w1w2 AS "Probability",
        tc.mutual_information AS "Mutual Information",
        t.count AS "Word Count",
        t.entropy AS "Entropy"
    FROM term_cooccurrence tc
    LEFT JOIN term_counts t ON tc.word_2 = t.word
    WHERE tc.word_1 = %s
    ORDER BY tc.prob_w1w2 DESC
    LIMIT %s;
    """

    with engine.connect() as connection:
        df = pd.read_sql_query(query, connection, params=(search_term, top_n))

    if df.empty:
        print(f"No co-occurrence data found for '{search_term}'.")
        return df

    # Apply scientific notation formatting to relevant columns
    for col in ["Probability", "Mutual Information", "Entropy"]:
        df[col] = df[col].apply(format_scientific)

    # Convert DataFrame to HTML with proper formatting
    html_table = df.to_html(escape=False, index=False)  # Escape=False allows HTML formatting
    display(HTML(html_table))  # Display properly in Jupyter Notebook

    return df
    
def plot_mi_entropy_terms(engine, search_term, target_terms, category_label="Custom"):

    query = """
    SELECT 
        tc.word_2 AS word,
        tc.mutual_information,
        tc.prob_w1w2,
        tc.count AS cooccurrence_count,
        t.entropy
    FROM term_cooccurrence tc
    LEFT JOIN term_counts t ON tc.word_2 = t.word
    WHERE tc.word_1 = %s AND tc.word_2 IN %s;
    """

    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params=(search_term, tuple(target_terms)))

    if df.empty:
        print(f"⚠️ No data found for: {search_term}")
        return df

    # Check and rename columns if needed
    df = df.rename(columns={
        "word": "Word",
        "mutual_information": "MI",
        "entropy": "Entropy"
    })

    # Drop rows with missing data
    df = df.dropna(subset=["MI", "Entropy"])

    if df.empty:
        print(f"⚠️ No valid rows after filtering by MI and Entropy.")
        return df

    df["Category"] = category_label

    # Plot
    plt.figure(figsize=(10, 6))
    sns.scatterplot(data=df, x="MI", y="Entropy", color="blue", s=100)
    for _, row in df.iterrows():
        texts = [plt.text(row["MI"], row["Entropy"], row["Word"], fontsize=9) for _, row in df.iterrows()]
        adjust_text(texts, arrowprops=dict(arrowstyle="-", color='gray', lw=0.5))

    plt.title(f"{search_term.title()} – {category_label} Terms\nMutual Information vs. Entropy")
    plt.xlabel("Mutual Information")
    plt.ylabel("Entropy")
    plt.grid(True)
    plt.tight_layout()
    plt.show()

    return df


def plot_multi_terrane_mi_entropy(engine, terrane_terms_dict, category_label="Custom", max_labels=40):
    """
    Plot MI vs. Entropy for multiple terranes using a shared list of terms.
    
    Parameters:
    -----------
    engine : SQLAlchemy engine
    terrane_terms_dict : dict
        Dictionary where keys are terrane names and values are lists of word_2 terms.
    category_label : str
        Category to display in the plot (e.g., 'Age', 'Lithology').
    max_labels : int
        Max number of labels to annotate on the plot.
    
    Returns:
    --------
    pd.DataFrame of all retrieved data
    """
    full_df = []

    query = """
    SELECT 
        tc.word_2 AS word,
        tc.mutual_information,
        tc.entropy_w1w2,
        tc.prob_w1w2,
        tc.count AS cooccurrence_count,
        t.entropy
    FROM term_cooccurrence tc
    LEFT JOIN term_counts t ON tc.word_2 = t.word
    WHERE tc.word_1 = %s AND tc.word_2 IN %s;
    """

    for terrane, terms in terrane_terms_dict.items():
        with engine.connect() as conn:
            df = pd.read_sql(query, conn, params=(terrane, tuple(terms)))
        if not df.empty:
            df = df.rename(columns={
                "word": "Word",
                "mutual_information": "MI",
                "entropy": "Entropy",
                "entropy_w1w2": "Joint Entropy"
            })
            df["Terrane"] = terrane
            df["Category"] = category_label
            full_df.append(df)

    if not full_df:
        print("⚠️ No data returned for any terranes.")
        return pd.DataFrame()

    df_all = pd.concat(full_df, ignore_index=True).dropna(subset=["MI", "Entropy"])

    # Plot
    plt.figure(figsize=(10, 6))
    sns.scatterplot(data=df_all, x="MI", y="Entropy", hue="Terrane", s=100)

    # Annotate top terms across all terranes
    label_df = df_all.sort_values("MI", ascending=False).head(max_labels)
    texts = [
        plt.text(row["MI"], row["Entropy"], f"{row['Word']}", fontsize=9)
        for _, row in label_df.iterrows()
    ]
    adjust_text(texts, arrowprops=dict(arrowstyle="-", color='gray', lw=0.5))

    plt.title(f"MI vs Entropy – {category_label} Terms across Terranes")
    plt.xlabel("Mutual Information")
    plt.ylabel("Entropy H(w2)")
    plt.grid(True)
    plt.tight_layout()
    plt.show()

    return df_all

################################################################################
# Mutual Information Visualization - Dash APP
################################################################################

def fetch_wordcloud_data(engine, search_term, top_n=50):
    """
    Fetches co-occurrence data from the database to generate a word cloud.
    
    Parameters:
    ----------
    engine : sqlalchemy.engine.base.Engine
        The database engine connected to PostgreSQL.
    search_term : str
        The primary term for which co-occurrence data is retrieved.
    top_n : int, optional, default=50
        The number of most frequent words to include in the word cloud.
    
    Returns:
    -------
    dict
        A dictionary of words and their probabilities.
    """
    query = """
    SELECT word_2, prob_w1w2 AS probability
    FROM term_cooccurrence
    WHERE LOWER(word_1) = LOWER(:search_term)
    ORDER BY probability DESC
    LIMIT :top_n;
    """

    with engine.connect() as connection:
        df = pd.read_sql_query(text(query), connection, params={"search_term": search_term, "top_n": top_n})

    if df.empty:
        return {}

    return dict(zip(df["word_2"], df["probability"]))


def fetch_mutual_information(engine, search_term, top_n=20, normalize=True):
    """
    Fetches mutual information values for a given search term from the database.
    Normalizes values if required.

    Parameters:
    ----------
    engine : sqlalchemy.engine.base.Engine
        The database engine connected to PostgreSQL.

    search_term : str
        The primary term for which Mutual Information scores are calculated.

    top_n : int, optional, default=20
        The number of top words to include in the visualization.

    normalize : bool, optional, default=True
        Whether to normalize MI scores between 0 and 1.

    Returns:
    -------
    pandas.DataFrame
        A DataFrame containing the words and their respective MI scores.
    """
    query = """
    SELECT word_2, CAST(mutual_information AS FLOAT) AS mutual_information
    FROM term_cooccurrence
    WHERE LOWER(word_1) = LOWER(:search_term)
    AND mutual_information IS NOT NULL
    ORDER BY mutual_information DESC
    LIMIT :top_n;
    """

    with engine.connect() as connection:
        df = pd.read_sql_query(text(query), connection, params={"search_term": search_term, "top_n": top_n})

    if df.empty:
        return df

    # Normalize MI values
    df["mutual_information"] = pd.to_numeric(df["mutual_information"], errors="coerce")
    df.dropna(subset=["mutual_information"], inplace=True)

    if normalize:
        df["mutual_information"] = (df["mutual_information"] - df["mutual_information"].min()) / \
                                   (df["mutual_information"].max() - df["mutual_information"].min())

    return df

def mutual_information_dash_app(engine):
    """
    Launches a compact Dash web app to visualize Mutual Information values and an interactive Word Cloud.

    Improvements:
    ------------
    - More compact **input controls** at the top (uses a flexible grid layout).
    - **Reduces empty space** around the Word Cloud.
    - **Balances** the layout with a side-by-side visualization.
    - **Allows Word Cloud Download** directly from the app.
    """
    app = Dash(__name__)

    app.layout = html.Div([
        html.H1("Mutual Information & Word Cloud", style={"text-align": "center", "margin-bottom": "10px"}),

        ####### 🔹 Compact Controls Layout 🔹 #######
        html.Div([
            html.Div([
                html.Label("Search Term:", style={"font-weight": "bold"}),
                dcc.Input(id="search-term", type="text", value="volcanic arc", debounce=True, style={"width": "100%"}),
            ], style={"width": "10%", "display": "inline-block", "padding": "5px"}),

            html.Div([
                html.Label("Top N Words:", style={"font-weight": "bold"}),
                dcc.Slider(id="top-n", min=10, max=200, step=10, value=50,
                           marks={i: str(i) for i in range(10, 210, 20)},
                           tooltip={"placement": "bottom", "always_visible": True}),
            ], style={"width": "70%", "display": "inline-block", "padding": "5px"}),

            html.Div([
                html.Label("Word Cloud Color:", style={"font-weight": "bold"}),
                dcc.Dropdown(
                    id="wordcloud-color",
                    options=[{"label": cmap, "value": cmap} for cmap in ["viridis", "plasma", "inferno", "cividis", "Blues", "Reds"]],
                    value="viridis",
                    style={"width": "100%"}
                ),
            ], style={"width": "15%", "display": "inline-block", "padding": "5px"}),

            html.Div([
                html.Label(" ", style={"visibility": "hidden"}),  # Spacer for alignment
                html.Button("Download Word Cloud", id="download-wordcloud", n_clicks=0, style={"width": "100%"}),
            ], style={"width": "5%", "display": "inline-block", "padding": "5px"}),
        ], style={"display": "flex", "justify-content": "center", "align-items": "center"}),

        ####### 🔹 Graphs Layout 🔹 #######
        html.Div([
            html.Div([dcc.Graph(id="mi-chart")], style={"width": "48%", "display": "inline-block", "padding": "5px"}),

            html.Div([dcc.Graph(id="wordcloud")], style={"width": "48%", "display": "inline-block", "padding": "5px", "height": "450px"}),
        ], style={"display": "flex", "justify-content": "center"}),

        html.Div(id="word-details", style={"marginTop": "10px", "fontSize": "16px", "fontWeight": "bold", "text-align": "center"}),

        dcc.Download(id="wordcloud-download")
    ])

    @app.callback(
        [Output("mi-chart", "figure"),
         Output("wordcloud", "figure"),
         Output("word-details", "children"),
         Output("wordcloud-download", "data")],
        [Input("search-term", "value"),
         Input("top-n", "value"),
         Input("wordcloud-color", "value"),
         Input("download-wordcloud", "n_clicks")]
    )
    def update_visuals(search_term, top_n, wordcloud_color, download_clicks):
        """
        Updates both the Mutual Information bar chart and the high-resolution Word Cloud visualization.
        """
        ####### 1️⃣ Fetch Mutual Information Data #######
        df_mi = fetch_mutual_information(engine, search_term, top_n)
        if df_mi.empty:
            return go.Figure(), go.Figure(), "No data available.", None

        ####### 2️⃣ Create Mutual Information Bar Chart #######
        mi_fig = go.Figure(go.Bar(
            y=df_mi["word_2"],
            x=df_mi["mutual_information"],
            orientation="h",
            marker=dict(color=df_mi["mutual_information"], colorscale="Viridis"),
            hoverinfo="y+x",
        ))
        mi_fig.update_layout(
            title=f"Mutual Information for '{search_term}'",
            xaxis_title="Mutual Information Score",
            yaxis=dict(autorange="reversed"),
            height=500,
            width=600,
            margin=dict(l=100, r=50, t=50, b=50),
        )

        ####### 3️⃣ Fetch Word Cloud Data #######
        word_freq = fetch_wordcloud_data(engine, search_term, top_n)

        # Generate High-Resolution Word Cloud
        wordcloud = WordCloud(
            width=600, height=500,  # Increased resolution for better quality
            background_color="white",
            colormap=wordcloud_color,
            scale=1  # Improves text clarity
        ).generate_from_frequencies(word_freq)

        # Convert to PIL Image & Trim Whitespace
        wordcloud_image = wordcloud.to_image()
        wordcloud_image = ImageOps.expand(wordcloud_image, border=10, fill="white")  # Adds padding to prevent cropping
        wordcloud_image = trim_whitespace(wordcloud_image)  # Removes excess whitespace

        # Convert to NumPy Array for Plotly
        wordcloud_array = np.array(wordcloud_image)

        # Convert to Byte Buffer for Download
        img_buffer = io.BytesIO()
        wordcloud_image.save(img_buffer, format="PNG")
        img_buffer.seek(0)

        # Create Word Cloud Plotly Figure
        wordcloud_fig = go.Figure()
        wordcloud_fig.add_trace(go.Image(z=wordcloud_array))
        wordcloud_fig.update_layout(
            title=f"Word Cloud for '{search_term}'",
            xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
            yaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
            height=500,
            width=600,
            margin=dict(l=0, r=0, t=30, b=0),  # Eliminates extra spacing
        )

        ####### 4️⃣ Handle Word Cloud Download #######
        download_data = None
        if download_clicks > 0:
            download_data = dict(content=img_buffer.getvalue(), filename=f"{search_term}_wordcloud.png")

        return mi_fig, wordcloud_fig, f"Showing {len(df_mi)} words for '{search_term}'", download_data

    def trim_whitespace(img):
        """
        Trims excess whitespace from a PIL image.
        """
        img_array = np.array(img)
        non_empty_columns = np.where(img_array.max(axis=0) > 0)[0]
        non_empty_rows = np.where(img_array.max(axis=1) > 0)[0]
        crop_box = (min(non_empty_columns), min(non_empty_rows), max(non_empty_columns), max(non_empty_rows))
        return img.crop(crop_box)

    def open_browser():
        """Opens the Dash app in the default web browser."""
        webbrowser.open("http://127.0.0.1:8050")

    threading.Thread(target=open_browser).start()
    app.run_server(mode="external", debug=False, use_reloader=False)
    
    
################################################################################
# Entropy Visualization - Dash APP
################################################################################
def fetch_entropy_data(engine, search_term, top_n=20, normalize=False):
    """
    Fetches entropy values for a given search term.
    Normalizes values if required.

    Parameters:
    ----------
    engine : sqlalchemy.engine.base.Engine
        Database engine connected to PostgreSQL.

    search_term : str
        The primary term for which entropy values are analyzed.

    top_n : int, optional, default=20
        Number of co-occurring words to include in the visualization.

    normalize : bool, optional, default=False
        Whether to normalize entropy values between 0 and 1.

    Returns:
    -------
    tuple(pd.DataFrame, float)
        - A DataFrame with co-occurrence entropy values.
        - A float representing the single-term entropy.
    """
    # Fetch entropy for the single term from `term_counts`
    single_term_query = """
    SELECT CAST(entropy AS FLOAT) AS entropy
    FROM term_counts
    WHERE LOWER(word) = LOWER(:search_term);
    """

    # Fetch entropy for co-occurring terms from `term_cooccurrence`
    cooccurrence_query = """
    SELECT word_2, CAST(entropy_w1w2 AS FLOAT) AS entropy
    FROM term_cooccurrence
    WHERE LOWER(word_1) = LOWER(:search_term)
    AND entropy_w1w2 IS NOT NULL
    ORDER BY entropy_w1w2 DESC
    LIMIT :top_n;
    """

    with engine.connect() as connection:
        # Get single-term entropy
        single_entropy_result = connection.execute(text(single_term_query), {"search_term": search_term}).fetchone()
        single_entropy = single_entropy_result[0] if single_entropy_result else None

        # Get co-occurrence entropy
        df = pd.read_sql_query(text(cooccurrence_query), connection, params={"search_term": search_term, "top_n": top_n})

    if df.empty:
        return df, single_entropy

    # Convert entropy values to numeric
    df["entropy"] = pd.to_numeric(df["entropy"], errors="coerce")
    df.dropna(subset=["entropy"], inplace=True)

    # Normalize entropy values if enabled
    if normalize and df["entropy"].max() > df["entropy"].min():
        df["entropy"] = (df["entropy"] - df["entropy"].min()) / (df["entropy"].max() - df["entropy"].min())

    return df, single_entropy


def fetch_entropy_range(engine):
    """
    Fetches the global min and max entropy values from `term_counts`.

    Parameters:
    ----------
    engine : sqlalchemy.engine.base.Engine
        Database engine connected to PostgreSQL.

    Returns:
    -------
    tuple(float, float)
        - Minimum entropy in the dataset
        - Maximum entropy in the dataset
    """
    query = """
    SELECT MIN(entropy) AS min_entropy, MAX(entropy) AS max_entropy
    FROM term_counts
    WHERE entropy IS NOT NULL;
    """

    with engine.connect() as connection:
        result = connection.execute(text(query)).fetchone()
        return result if result else (None, None)


def entropy_visualization_dash_app(engine):
    """
    Dash web app to visualize entropy values.

    - Displays co-occurrence entropy as a bar chart.
    - Displays single-term entropy as a gauge indicator.
    """
    app = Dash(__name__)

    ####### 🔹 Fetch Global Entropy Range from Database 🔹 #######
    H_min, H_max = fetch_entropy_range(engine)
    if H_max is None:
        H_max = 1e-3  # Default small range if database query fails
    if H_min is None:
        H_min = 0

    app.layout = html.Div([
        html.H1("Entropy Visualization", style={"text-align": "center", "margin-bottom": "10px"}),

        ####### 🔹 Controls Layout 🔹 #######
        html.Div([
            html.Div([
                html.Label("Search Term:", style={"font-weight": "bold"}),
                dcc.Input(id="search-term", type="text", value="volcanic arc", debounce=True, style={"width": "100%"}),
            ], style={"width": "40%", "display": "inline-block", "padding": "5px"}),

            html.Div([
                html.Label("Top N Words:", style={"font-weight": "bold"}),
                dcc.Slider(id="top-n", min=5, max=50, step=5, value=20,
                           marks={i: str(i) for i in range(5, 55, 5)},
                           tooltip={"placement": "bottom", "always_visible": True}),
            ], style={"width": "50%", "display": "inline-block", "padding": "5px"}),
        ], style={"display": "flex", "justify-content": "center", "align-items": "center"}),

        ####### 🔹 Graphs Layout 🔹 #######
        html.Div([
            html.Div([dcc.Graph(id="entropy-chart")], style={"width": "48%", "display": "inline-block", "padding": "5px"}),

            html.Div([dcc.Graph(id="entropy-indicator")], style={"width": "48%", "display": "inline-block", "padding": "5px"}),
        ], style={"display": "flex", "justify-content": "center"}),

        html.Div(id="entropy-details", style={"marginTop": "10px", "fontSize": "16px", "fontWeight": "bold", "text-align": "center"}),
    ])

        ####### 🔹 Callbacks 🔹 #######
    @dash_app.callback(
        [Output("mi-chart", "figure"),
         Output("mi-indicator", "figure"),
         Output("entropy-chart", "figure"),
         Output("entropy-indicator", "figure"),
         Output("wordcloud", "figure"),
         Output("entropy-details", "children")],
        [Input("search-term", "value"),
         Input("top-n", "value"),
         Input("normalize-toggle", "value")]  # ✅ Added normalization toggle
    )
    def update_visuals(search_term, top_n, normalize_option):
        """
        Updates all visual elements: Mutual Information, Entropy, and Word Cloud.
        """
        normalize = "normalize" in normalize_option  # ✅ Ensures correct handling of normalization checkbox

        ####### 1️⃣ Fetch Mutual Information Data #######
        df_mi = fetch_mutual_information(engine, search_term, top_n)  # ✅ No normalize option needed

        ####### 2️⃣ Fetch Entropy Data #######
        df_entropy, single_entropy = fetch_entropy_data(engine, search_term, top_n, normalize=normalize)  # ✅ Pass normalize

        if df_entropy.empty or df_mi.empty:
            return go.Figure(), go.Figure(), go.Figure(), go.Figure(), go.Figure(), "No data available."

        ####### ✅ Continue with plotting logic as before #######


        ####### 2️⃣ Create Entropy Bar Chart (Co-occurrence) #######
        entropy_fig = go.Figure(go.Bar(
            y=df_entropy["word_2"],
            x=df_entropy["entropy"],
            orientation="h",
            marker=dict(color=df_entropy["entropy"], colorscale="Blues"),
            hoverinfo="y+x",
        ))
        entropy_fig.update_layout(
            title=f"Co-occurrence Entropy for '{search_term}'",
            xaxis_title="Normalized Entropy Score",
            xaxis_type="log",  # ✅ Use log scale for clarity
            yaxis=dict(autorange="reversed"),
            height=500,
            width=600,
            margin=dict(l=100, r=50, t=50, b=50),
        )

        ####### 3️⃣ Normalize & Scale Single-Term Entropy for Gauge #######
        if single_entropy is not None and single_entropy > 0:
            entropy_display = f" Single-term entropy: {dash_format_scientific(single_entropy)}"  # ✅ Scientific notation for display

            # ✅ Make gauge_max slightly larger than single_entropy without overshooting
            gauge_max = 0.008
            gauge_min = H_min
        else:
            entropy_display = "No entropy data"
            gauge_max = 1  # Default small range
            gauge_min = 0

        indicator_fig = go.Figure(go.Indicator(
            mode="gauge+number",
            value=single_entropy if single_entropy is not None else 0,
            title={"text": f"Entropy: {dash_format_scientific(single_entropy)}"},
            gauge={
                "axis": {"range": [0, gauge_max]},
                "bar": {"color": "darkblue"},  # Dark Blue Pointer
                "steps": [
                    {"range": [0, gauge_max * 0.1], "color": "green"},  # 🟢 Very Low (specific term)
                    {"range": [gauge_max * 0.1, gauge_max * 0.4], "color": "yellow"},  # 🟡 Moderate entropy (less useful)
                    {"range": [gauge_max * 0.4, gauge_max * 0.6], "color": "red"},  # 🔴 High uncertainty (mixed meaning)
                    {"range": [gauge_max * 0.6, gauge_max * 0.9], "color": "yellow"},  # 🟡 Moderate entropy
                    {"range": [gauge_max * 0.9, gauge_max], "color": "green"},  # 🟢 Very high entropy (broad context)
                ],
            }
        ))


        ####### 4️⃣ Display Entropy Details #######
        entropy_details = f"Showing {len(df_entropy)} co-occurring words for '{search_term}'."
        if single_entropy is not None:
            entropy_details += f" Single-term entropy: {entropy_display}"

        return entropy_fig, indicator_fig, entropy_details



    ####### 🔹 Start the App 🔹 #######
    def open_browser():
        """Opens the Dash app in the default web browser."""
        webbrowser.open("http://127.0.0.1:8050")

    threading.Thread(target=open_browser).start()
    app.run_server(mode="external", debug=False, use_reloader=False)
