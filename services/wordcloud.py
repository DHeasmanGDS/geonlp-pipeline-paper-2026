from wordcloud import WordCloud
import matplotlib.pyplot as plt
import pandas as pd
from io import BytesIO
from sqlalchemy import text

def generate_wordcloud_image(engine, term: str, top_n: int = 50, colormap: str = "viridis") -> BytesIO:
    """
    Generates a word cloud image for a given term using co-occurrence probabilities.
    Returns an in-memory PNG image buffer.
    """
    query = text("""
        SELECT word_2, prob_w1w2 AS probability
        FROM term_cooccurrence
        WHERE word_1 = %s
        ORDER BY probability DESC
        LIMIT %s;
    """)

    with engine.connect() as conn:
        df = pd.read_sql_query(query, conn, params=(term.lower(), top_n))

    if df.empty:
        return None

    freq_dict = dict(zip(df["word_2"], df["probability"]))
    wc = WordCloud(width=800, height=500, background_color="white", colormap=colormap, scale=2)
    wc.generate_from_frequencies(freq_dict)

    buffer = BytesIO()
    plt.figure(figsize=(20, 10))
    plt.imshow(wc, interpolation="bilinear")
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(buffer, format="png")
    plt.close()
    buffer.seek(0)
    return buffer
