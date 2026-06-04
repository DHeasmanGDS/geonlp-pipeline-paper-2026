# Notebooks

The five demonstration notebooks are provided as `.py` files in the
[Jupytext "percent" format](https://jupytext.readthedocs.io/en/latest/formats.html#the-percent-format).
This format is human-readable in any text editor and converts cleanly
to `.ipynb` for use in Jupyter.

## Convert to .ipynb

```bash
pip install jupytext
jupytext --to ipynb *.py
```

This produces one `.ipynb` file per `.py` source. Open them in
JupyterLab or VSCode's notebook interface.

## Or run as plain Python scripts

Each `.py` file is also valid Python — `# %%` and `# %% [markdown]`
markers are simply comments. Run any of them with:

```bash
python 01_setup_database.py
```

## Why this format?

- **Diffable in git** — `.ipynb` files contain serialized cell outputs
  and metadata that produce large, noisy diffs. The Jupytext `.py`
  format strips all of that, so reviewing changes is straightforward.
- **No accidental output commits** — saved Jupyter outputs can leak
  database rows, file paths, or other sensitive data. The `.py`
  format has no output cells.
- **Lower dependency surface** — readers can engage with the notebook
  content without installing Jupyter.

## What each notebook covers

| Notebook | Purpose |
|---|---|
| `01_setup_database.py` | Provision a fresh PostgreSQL database, apply schema and stored procedures |
| `02_preprocess_demo.py` | Walk through the four preprocessing steps on a sample snippet |
| `03_pmi_walkthrough.py` | Worked example of PMI and NPMI computation, with intuition |
| `04_in_stream_pruning_demo.py` | Show Strategy A (in-stream Counter pruning) on a synthetic mega-frequency term |
| `05_mine_one_term.py` | End-to-end mine of a niche term, with result inspection |
