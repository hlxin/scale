# Use SCALE from your own agent

Two files make any MCP-capable agent (Claude Code, Claude Desktop, Cursor, …) or GraphRAG workflow use the SCALE
catalysis knowledge base, and know **when** to use it.

| file | what it does | where it goes |
|---|---|---|
| [`catalysis-agent.md`](catalysis-agent.md) | when to query SCALE (catalyst search under conditions, "has this been done?", negative results), and how to answer from it with evidence | your project's `CLAUDE.md` / `AGENTS.md`, or the system prompt |
| [`mcp.json`](mcp.json) | registers the SCALE tools over MCP | your project's `.mcp.json` (Claude Code) or your host's MCP settings |

## Set up in two minutes

Needs only [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`).

```bash
# 1. the knowledge base: the graphs and worked query plans
git clone --depth 1 https://github.com/hlxin/scale && cd scale

# 2. the tools, for your agent (Claude Code shown; or copy agents/mcp.json into .mcp.json)
claude mcp add scale -- uvx scale-catal mcp

# 3. the instructions
cp agents/catalysis-agent.md CLAUDE.md          # or append to the one you have
```

Then ask your agent, for example:

- *"Using the methanol graph, which Cu catalysts were tested at or below 300 °C and 100 atm, and what did they
  produce?"*
- *"Has CO2 hydrogenation to methanol over Cu–Zn been reported before 1966?"*
- *"Which methanol catalysts were found nearly inactive, and why?"*

The graphs are `graphs/methanol-synthesis-pre1966` (105 sources) and `examples/methanol-synthesis-public` (its 55
public-domain sources, with full quotes). Each answer the agent gives should cite source, page and quote.

## Without MCP

- **Shell / any agent framework:** `uvx scale-catal call query '{"path": "...", "plan": {...}}'` prints JSON
  ([docs/integrate.md](../docs/integrate.md)).
- **Python / GraphRAG:** `from scale.api import ScaleToolkit; ScaleToolkit().call("query", {...})`;
  `scale graph search` returns evidence quotes ranked by words and meaning, ready to pass to a retriever.
- **Browser, nothing to install:** [the graph explorer](https://hlxin.github.io/scale/).

## What is ready now vs. what needs setup

| | ready now | needs setup |
|---|---|---|
| browse a graph, read evidence | the explorer, in a browser | — |
| query from an agent | MCP or `uvx` (above) | uv |
| curate and contribute a paper | `/first-paper <DOI>` in Claude Code in a clone; or the web service, if it is running for you | uv, plus Tesseract for scanned PDFs — see [CONTRIBUTE.md](../CONTRIBUTE.md) |
