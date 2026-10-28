# Desktop Extension (.mcpb)

This folder builds the one-click install file for Claude Desktop. It does not copy the server: it
declares a dependency on the published `gazzetta-mcp` package from PyPI and starts it
(`server.py`).

## Build

```bash
npx @anthropic-ai/mcpb validate mcpb/manifest.json
npx @anthropic-ai/mcpb pack mcpb dist/gazzetta-mcp-<version>.mcpb
```

Attach the resulting file to the GitHub release of the same version.

## At every release

Update these three places together, after the new version is on PyPI:

- `version` in `manifest.json`
- `version` and the pinned `gazzetta-mcp==...` dependency in `pyproject.toml`
- the file name used in the README (`gazzetta-mcp-<version>.mcpb`)
