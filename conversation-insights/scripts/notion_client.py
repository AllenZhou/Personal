"""
Notion API v1 client wrapper using only Python standard library.

Zero external dependencies -- uses urllib.request + json for HTTP,
and a hand-rolled YAML-subset parser for config loading.

Covers database CRUD, page/block operations, search, and provides
static builder helpers for Notion block objects and property values.

Usage:
    from notion_client import NotionClient

    client = NotionClient(api_key="ntn_xxxx")
    results = client.query_database("db-id-here")

Or load from config.yaml:
    client = NotionClient.load_config("path/to/config.yaml")
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"
_MAX_RETRIES = 3
_INITIAL_BACKOFF_SECONDS = 1.0
_HTTP_TIMEOUT_SECONDS = 30.0
_MAX_TEXT_CHUNK = 2000  # Notion rich-text limit per element
_MAX_BLOCKS_PER_REQUEST = 100  # Notion append-children limit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_text(text: str, limit: int = _MAX_TEXT_CHUNK) -> List[str]:
    """Split *text* into chunks of at most *limit* characters.

    Tries to break on the last newline or space before the limit so that
    words and lines are not split mid-stream.  Falls back to a hard cut
    when no suitable break-point exists.
    """
    if not text:
        return [""]
    chunks: List[str] = []
    while len(text) > limit:
        # Prefer breaking on newline, then space
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = text.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    chunks.append(text)
    return chunks


def _rich_text_array(text: str) -> List[Dict[str, Any]]:
    """Build a Notion ``rich_text`` array, splitting at 2000-char boundaries."""
    return [
        {"type": "text", "text": {"content": chunk}}
        for chunk in _split_text(text)
    ]


# ---------------------------------------------------------------------------
# Minimal YAML parser (covers the config.yaml structure we need)
# ---------------------------------------------------------------------------

def _parse_simple_yaml(text: str) -> Dict[str, Any]:
    """Parse a minimal YAML subset into a nested dict.

    Supports:
      - Scalar values (strings, numbers, booleans)
      - Nested mappings via indentation (consistent 2-space indent)
      - Quoted and unquoted string values
      - Comments (``#``)

    This is intentionally *not* a full YAML parser.  It handles exactly the
    config.yaml structure described in the project docs.
    """
    root: Dict[str, Any] = {}
    # Stack of (indent_level, current_dict)
    stack: List[tuple] = [(-1, root)]

    for raw_line in text.splitlines():
        # Strip comments (but not inside quotes)
        line = raw_line.split("#")[0] if '"' not in raw_line else raw_line
        stripped = line.rstrip()
        if not stripped or stripped.lstrip().startswith("#"):
            continue

        indent = len(stripped) - len(stripped.lstrip())
        content = stripped.lstrip()

        # Pop stack until we find the parent for this indent
        while stack and stack[-1][0] >= indent:
            stack.pop()

        if ":" not in content:
            continue

        key, _, value = content.partition(":")
        key = key.strip()
        value = value.strip()

        parent = stack[-1][1]

        if not value:
            # Mapping key with no inline value -- create sub-dict
            new_dict: Dict[str, Any] = {}
            parent[key] = new_dict
            stack.append((indent, new_dict))
        else:
            # Scalar value
            # Strip surrounding quotes
            if (value.startswith('"') and value.endswith('"')) or \
               (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            parent[key] = value

    return root


# ---------------------------------------------------------------------------
# NotionClient
# ---------------------------------------------------------------------------

class NotionClient:
    """Notion API v1 client using only the Python standard library.

    Parameters
    ----------
    api_key : str
        Notion internal integration token (starts with ``ntn_``).
    base_url : str, optional
        Override the Notion API base URL (useful for testing).
    """

    def __init__(self, api_key: str, *, base_url: str = _BASE_URL) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": _NOTION_VERSION,
            "Content-Type": "application/json",
        }
        # Reusable SSL context -- avoids creating one per request
        self._ssl_ctx = ssl.create_default_context()

    # ------------------------------------------------------------------
    # HTTP layer
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute an HTTP request against the Notion API.

        Handles:
          - JSON serialisation / deserialisation
          - Retries with exponential back-off on HTTP 429 (rate-limited)
          - Raises ``RuntimeError`` for non-retryable failures

        Parameters
        ----------
        method : str
            HTTP method (``GET``, ``POST``, ``PATCH``, ``DELETE``).
        path : str
            API path **without** the base URL (e.g. ``/databases/{id}/query``).
        data : dict, optional
            JSON-serialisable body payload.

        Returns
        -------
        dict
            Parsed JSON response.
        """
        url = f"{self.base_url}{path}"
        body = json.dumps(data).encode("utf-8") if data is not None else None

        backoff = _INITIAL_BACKOFF_SECONDS
        last_error: Optional[Exception] = None

        for attempt in range(1, _MAX_RETRIES + 1):
            req = urllib.request.Request(
                url,
                data=body,
                headers=self._headers,
                method=method,
            )
            try:
                with urllib.request.urlopen(
                    req,
                    context=self._ssl_ctx,
                    timeout=_HTTP_TIMEOUT_SECONDS,
                ) as resp:
                    resp_body = resp.read().decode("utf-8")
                    if not resp_body:
                        return {}
                    return json.loads(resp_body)

            except urllib.error.HTTPError as exc:
                status = exc.code
                error_body = ""
                try:
                    error_body = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    pass

                if status == 429:
                    # Rate-limited -- honour Retry-After if present, else backoff
                    retry_after = exc.headers.get("Retry-After")
                    wait = float(retry_after) if retry_after else backoff
                    if attempt < _MAX_RETRIES:
                        time.sleep(wait)
                        backoff *= 2
                        last_error = exc
                        continue

                raise RuntimeError(
                    f"Notion API error {status} {method} {path}: {error_body}"
                ) from exc

            except urllib.error.URLError as exc:
                # Network-level errors -- retry with backoff
                if attempt < _MAX_RETRIES:
                    time.sleep(backoff)
                    backoff *= 2
                    last_error = exc
                    continue
                raise RuntimeError(
                    f"Network error on {method} {path}: {exc.reason}"
                ) from exc
            except TimeoutError as exc:
                # Socket-level timeout may bypass URLError on some environments.
                if attempt < _MAX_RETRIES:
                    time.sleep(backoff)
                    backoff *= 2
                    last_error = exc
                    continue
                raise RuntimeError(
                    f"Network timeout on {method} {path}: {exc}"
                ) from exc

        # Should be unreachable, but just in case
        raise RuntimeError(
            f"Request failed after {_MAX_RETRIES} attempts: {last_error}"
        )

    # ------------------------------------------------------------------
    # Database operations
    # ------------------------------------------------------------------

    def query_database(
        self,
        db_id: str,
        filter: Optional[Dict[str, Any]] = None,
        sorts: Optional[List[Dict[str, Any]]] = None,
        page_size: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query a Notion database with automatic pagination.

        Iterates through all pages of results, returning the complete list.

        Parameters
        ----------
        db_id : str
            The database ID to query.
        filter : dict, optional
            Notion filter object.
        sorts : list[dict], optional
            Notion sorts array.
        page_size : int
            Results per page (max 100).

        Returns
        -------
        list[dict]
            All matching page objects.
        """
        results: List[Dict[str, Any]] = []
        has_more = True
        start_cursor: Optional[str] = None

        while has_more:
            payload: Dict[str, Any] = {"page_size": min(page_size, 100)}
            if filter is not None:
                payload["filter"] = filter
            if sorts is not None:
                payload["sorts"] = sorts
            if start_cursor is not None:
                payload["start_cursor"] = start_cursor

            resp = self._request("POST", f"/databases/{db_id}/query", payload)
            results.extend(resp.get("results", []))
            has_more = resp.get("has_more", False)
            start_cursor = resp.get("next_cursor")

        return results

    def create_page(
        self,
        parent_id: str,
        properties: Dict[str, Any],
        children: Optional[List[Dict[str, Any]]] = None,
        is_database: bool = True,
        icon: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a new page in a database or under a parent page.

        Parameters
        ----------
        parent_id : str
            The parent database or page ID.
        properties : dict
            Notion property values for the page.
        children : list[dict], optional
            Block children to include in the page body.  If more than 100
            blocks are supplied, the first 100 are included in creation and
            the rest are appended in follow-up requests.
        is_database : bool
            If ``True`` (default), *parent_id* is treated as a database ID.
            Otherwise it is treated as a page ID.
        icon : dict, optional
            Page icon (e.g. ``{"type": "emoji", "emoji": "🧠"}``).

        Returns
        -------
        dict
            The created page object.
        """
        parent_key = "database_id" if is_database else "page_id"
        payload: Dict[str, Any] = {
            "parent": {parent_key: parent_id},
            "properties": properties,
        }
        if icon is not None:
            payload["icon"] = icon

        # Notion allows at most 100 children on page creation
        initial_children: List[Dict[str, Any]] = []
        overflow_children: List[Dict[str, Any]] = []

        if children:
            initial_children = children[:_MAX_BLOCKS_PER_REQUEST]
            overflow_children = children[_MAX_BLOCKS_PER_REQUEST:]
            payload["children"] = initial_children

        page = self._request("POST", "/pages", payload)

        # Append any overflow blocks
        if overflow_children:
            page_id = page["id"]
            self.append_blocks(page_id, overflow_children)

        return page

    def update_page(
        self,
        page_id: str,
        properties: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update properties of an existing page.

        Parameters
        ----------
        page_id : str
            The page to update.
        properties : dict
            Property values to set (partial update).

        Returns
        -------
        dict
            The updated page object.
        """
        return self._request("PATCH", f"/pages/{page_id}", {"properties": properties})

    def archive_page(self, page_id: str) -> Dict[str, Any]:
        """Archive (soft-delete) a page.

        Parameters
        ----------
        page_id : str
            The page to archive.

        Returns
        -------
        dict
            The updated page object.
        """
        return self._request("PATCH", f"/pages/{page_id}", {"archived": True})

    # ------------------------------------------------------------------
    # Page / Block operations
    # ------------------------------------------------------------------

    def get_page(self, page_id: str) -> Dict[str, Any]:
        """Retrieve a page object by ID.

        Parameters
        ----------
        page_id : str
            The page ID.

        Returns
        -------
        dict
            The page object.
        """
        return self._request("GET", f"/pages/{page_id}")

    def get_blocks(self, block_id: str) -> List[Dict[str, Any]]:
        """Retrieve all child blocks of a page or block, with pagination.

        Parameters
        ----------
        block_id : str
            The parent block (or page) ID.

        Returns
        -------
        list[dict]
            All child block objects.
        """
        results: List[Dict[str, Any]] = []
        has_more = True
        start_cursor: Optional[str] = None

        while has_more:
            path = f"/blocks/{block_id}/children?page_size=100"
            if start_cursor:
                path += f"&start_cursor={start_cursor}"

            resp = self._request("GET", path)
            results.extend(resp.get("results", []))
            has_more = resp.get("has_more", False)
            start_cursor = resp.get("next_cursor")

        return results

    def append_blocks(
        self,
        page_id: str,
        blocks: List[Dict[str, Any]],
    ) -> None:
        """Append block children to a page, respecting the 100-block limit.

        Automatically batches the blocks into groups of 100 and sends
        multiple requests if necessary.

        Parameters
        ----------
        page_id : str
            The target page (or block) ID.
        blocks : list[dict]
            Block objects to append.
        """
        for i in range(0, len(blocks), _MAX_BLOCKS_PER_REQUEST):
            batch = blocks[i : i + _MAX_BLOCKS_PER_REQUEST]
            self._request(
                "PATCH",
                f"/blocks/{page_id}/children",
                {"children": batch},
            )

    def delete_block(self, block_id: str) -> None:
        """Delete (archive) a block.

        Parameters
        ----------
        block_id : str
            The block to delete.
        """
        self._request("DELETE", f"/blocks/{block_id}")

    def clear_page(self, page_id: str) -> None:
        """Remove all child blocks from a page.

        Useful for replacing a page's body content entirely.

        Parameters
        ----------
        page_id : str
            The page whose children should be deleted.
        """
        blocks = self.get_blocks(page_id)
        for block in blocks:
            self.delete_block(block["id"])

    # ------------------------------------------------------------------
    # Database creation
    # ------------------------------------------------------------------

    def create_database(
        self,
        parent_page_id: str,
        title: str,
        properties_schema: Dict[str, Any],
        icon: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a new database as a child of a page.

        Parameters
        ----------
        parent_page_id : str
            The parent page ID under which the database is created.
        title : str
            Human-readable database title.
        properties_schema : dict
            Notion property schema definitions.  Each key is the property
            name and the value is the schema object (e.g.
            ``{"rich_text": {}}``).
        icon : dict, optional
            Database icon (e.g. ``{"type": "emoji", "emoji": "📊"}``).

        Returns
        -------
        dict
            The created database object.
        """
        payload: Dict[str, Any] = {
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "title": [{"type": "text", "text": {"content": title}}],
            "properties": properties_schema,
        }
        if icon is not None:
            payload["icon"] = icon
        return self._request("POST", "/databases", payload)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        filter_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search across the workspace for pages and databases.

        Parameters
        ----------
        query : str
            The search term.
        filter_type : str, optional
            Restrict results to ``"page"`` or ``"database"``.

        Returns
        -------
        list[dict]
            Matching page and/or database objects.
        """
        results: List[Dict[str, Any]] = []
        has_more = True
        start_cursor: Optional[str] = None

        while has_more:
            payload: Dict[str, Any] = {"query": query, "page_size": 100}
            if filter_type is not None:
                payload["filter"] = {"value": filter_type, "property": "object"}
            if start_cursor is not None:
                payload["start_cursor"] = start_cursor

            resp = self._request("POST", "/search", payload)
            results.extend(resp.get("results", []))
            has_more = resp.get("has_more", False)
            start_cursor = resp.get("next_cursor")

        return results

    # ------------------------------------------------------------------
    # Static block builders
    # ------------------------------------------------------------------

    @staticmethod
    def heading(text: str, level: int = 2) -> Dict[str, Any]:
        """Build a heading block.

        Parameters
        ----------
        text : str
            Heading text content.
        level : int
            Heading level -- 1, 2, or 3.

        Returns
        -------
        dict
            A Notion heading block object.
        """
        if level not in (1, 2, 3):
            raise ValueError(f"Heading level must be 1, 2, or 3, got {level}")
        key = f"heading_{level}"
        return {
            "object": "block",
            "type": key,
            key: {"rich_text": _rich_text_array(text[:_MAX_TEXT_CHUNK])},
        }

    @staticmethod
    def paragraph(text: str) -> Dict[str, Any]:
        """Build a paragraph block.

        Handles text exceeding 2000 characters by splitting into multiple
        rich-text elements within the same paragraph.

        Parameters
        ----------
        text : str
            Paragraph content.

        Returns
        -------
        dict
            A Notion paragraph block object.
        """
        return {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": _rich_text_array(text)},
        }

    @staticmethod
    def bulleted_list(text: str) -> Dict[str, Any]:
        """Build a bulleted list item block.

        Parameters
        ----------
        text : str
            List item content.

        Returns
        -------
        dict
            A Notion bulleted_list_item block object.
        """
        return {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": _rich_text_array(text)},
        }

    @staticmethod
    def numbered_list(text: str) -> Dict[str, Any]:
        """Build a numbered list item block.

        Parameters
        ----------
        text : str
            List item content.

        Returns
        -------
        dict
            A Notion numbered_list_item block object.
        """
        return {
            "object": "block",
            "type": "numbered_list_item",
            "numbered_list_item": {"rich_text": _rich_text_array(text)},
        }

    @staticmethod
    def toggle(
        title: str,
        children: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Build a toggle block.

        Parameters
        ----------
        title : str
            Toggle heading text.
        children : list[dict], optional
            Nested block children shown when the toggle is expanded.

        Returns
        -------
        dict
            A Notion toggle block object.
        """
        block: Dict[str, Any] = {
            "object": "block",
            "type": "toggle",
            "toggle": {"rich_text": _rich_text_array(title)},
        }
        if children:
            block["toggle"]["children"] = children
        return block

    @staticmethod
    def callout(text: str, emoji: str = "\U0001f4a1") -> Dict[str, Any]:
        """Build a callout block with an emoji icon.

        Parameters
        ----------
        text : str
            Callout body text.
        emoji : str
            Emoji character for the callout icon.

        Returns
        -------
        dict
            A Notion callout block object.
        """
        return {
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": _rich_text_array(text),
                "icon": {"type": "emoji", "emoji": emoji},
            },
        }

    @staticmethod
    def divider() -> Dict[str, Any]:
        """Build a divider block.

        Returns
        -------
        dict
            A Notion divider block object.
        """
        return {"object": "block", "type": "divider", "divider": {}}

    @staticmethod
    def table_of_contents() -> Dict[str, Any]:
        """Build a table-of-contents block.

        Returns
        -------
        dict
            A Notion table_of_contents block object.
        """
        return {
            "object": "block",
            "type": "table_of_contents",
            "table_of_contents": {},
        }

    @staticmethod
    def code_block(code: str, language: str = "python") -> Dict[str, Any]:
        """Build a code block.

        Parameters
        ----------
        code : str
            Source code content.
        language : str
            Programming language identifier (e.g. ``python``, ``javascript``).

        Returns
        -------
        dict
            A Notion code block object.
        """
        return {
            "object": "block",
            "type": "code",
            "code": {
                "rich_text": _rich_text_array(code),
                "language": language,
            },
        }

    @staticmethod
    def quote(text: str) -> Dict[str, Any]:
        """Build a quote block.

        Parameters
        ----------
        text : str
            Quoted text content.

        Returns
        -------
        dict
            A Notion quote block object.
        """
        return {
            "object": "block",
            "type": "quote",
            "quote": {"rich_text": _rich_text_array(text)},
        }

    # ------------------------------------------------------------------
    # Static property builders
    # ------------------------------------------------------------------

    @staticmethod
    def prop_title(text: str) -> Dict[str, Any]:
        """Build a title property value.

        Parameters
        ----------
        text : str
            Title text.

        Returns
        -------
        dict
            Notion title property value.
        """
        return {"title": _rich_text_array(text)}

    @staticmethod
    def prop_rich_text(text: str) -> Dict[str, Any]:
        """Build a rich_text property value.

        Parameters
        ----------
        text : str
            Text content.

        Returns
        -------
        dict
            Notion rich_text property value.
        """
        return {"rich_text": _rich_text_array(text)}

    @staticmethod
    def prop_number(value: float) -> Dict[str, Any]:
        """Build a number property value.

        Parameters
        ----------
        value : float | int
            Numeric value.

        Returns
        -------
        dict
            Notion number property value.
        """
        return {"number": value}

    @staticmethod
    def prop_select(name: str) -> Dict[str, Any]:
        """Build a select property value.

        Parameters
        ----------
        name : str
            Option name to select.

        Returns
        -------
        dict
            Notion select property value.
        """
        return {"select": {"name": name}}

    @staticmethod
    def prop_multi_select(names: List[str]) -> Dict[str, Any]:
        """Build a multi_select property value.

        Parameters
        ----------
        names : list[str]
            Option names to select.

        Returns
        -------
        dict
            Notion multi_select property value.
        """
        return {"multi_select": [{"name": n} for n in names]}

    @staticmethod
    def prop_date(date_str: str) -> Dict[str, Any]:
        """Build a date property value.

        Parameters
        ----------
        date_str : str
            ISO-8601 date or datetime string (e.g. ``2024-01-15`` or
            ``2024-01-15T10:30:00``).

        Returns
        -------
        dict
            Notion date property value.
        """
        return {"date": {"start": date_str}}

    @staticmethod
    def prop_checkbox(checked: bool) -> Dict[str, Any]:
        """Build a checkbox property value.

        Parameters
        ----------
        checked : bool
            Whether the checkbox is checked.

        Returns
        -------
        dict
            Notion checkbox property value.
        """
        return {"checkbox": checked}

    @staticmethod
    def prop_url(url: str) -> Dict[str, Any]:
        """Build a URL property value.

        Parameters
        ----------
        url : str
            The URL string.

        Returns
        -------
        dict
            Notion url property value.
        """
        return {"url": url}

    # ------------------------------------------------------------------
    # Config loader
    # ------------------------------------------------------------------

    @classmethod
    def load_config(cls, config_path: str) -> "NotionClient":
        """Create a ``NotionClient`` from a YAML configuration file.

        The expected YAML structure::

            notion:
              api_key: "ntn_xxxx"
              databases:
                conversations: "db-id"
                ...
              pages:
                user_profile: "page-id"
                root: "page-id"

        The returned client has two extra attributes attached:

        - ``databases`` -- dict mapping logical names to database IDs
        - ``pages`` -- dict mapping logical names to page IDs

        Parameters
        ----------
        config_path : str
            Path to the YAML config file.

        Returns
        -------
        NotionClient
            A configured client instance.

        Raises
        ------
        FileNotFoundError
            If *config_path* does not exist.
        KeyError
            If required keys are missing from the config.
        """
        config_path = os.path.expanduser(config_path)
        with open(config_path, "r", encoding="utf-8") as fh:
            raw = fh.read()

        config = _parse_simple_yaml(raw)

        notion_cfg = config.get("notion")
        if not notion_cfg or not isinstance(notion_cfg, dict):
            raise KeyError(
                "Config file must contain a top-level 'notion' mapping"
            )

        api_key = notion_cfg.get("api_key")
        if not api_key:
            raise KeyError("'notion.api_key' is required in config")

        client = cls(api_key=str(api_key))

        # Attach convenience mappings
        client.databases: Dict[str, str] = {}  # type: ignore[attr-defined]
        if "databases" in notion_cfg and isinstance(notion_cfg["databases"], dict):
            client.databases = {
                k: str(v) for k, v in notion_cfg["databases"].items()
            }

        client.pages: Dict[str, str] = {}  # type: ignore[attr-defined]
        if "pages" in notion_cfg and isinstance(notion_cfg["pages"], dict):
            client.pages = {
                k: str(v) for k, v in notion_cfg["pages"].items()
            }

        return client


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

def _smoke_test() -> None:
    """Run a basic connectivity check against the Notion API.

    Reads the API key from the ``NOTION_API_KEY`` environment variable or,
    if a ``config.yaml`` exists next to this script, loads it from there.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "..", "config.yaml")

    client: Optional[NotionClient] = None

    if os.path.isfile(config_path):
        print(f"Loading config from {config_path}")
        try:
            client = NotionClient.load_config(config_path)
        except Exception as exc:
            print(f"Failed to load config: {exc}")

    if client is None:
        api_key = os.environ.get("NOTION_API_KEY", "")
        if not api_key:
            print(
                "No config.yaml found and NOTION_API_KEY env var is not set.\n"
                "Set NOTION_API_KEY or create config.yaml to run the smoke test."
            )
            sys.exit(1)
        client = NotionClient(api_key=api_key)

    print("Searching Notion workspace for 'test'...")
    try:
        results = client.search("test")
        print(f"Search returned {len(results)} result(s).")
        for item in results[:5]:
            obj_type = item.get("object", "unknown")
            title_parts = []
            if obj_type == "page":
                props = item.get("properties", {})
                for prop in props.values():
                    if prop.get("type") == "title":
                        title_parts = [
                            t.get("plain_text", "")
                            for t in prop.get("title", [])
                        ]
                        break
            elif obj_type == "database":
                title_parts = [
                    t.get("plain_text", "")
                    for t in item.get("title", [])
                ]
            title = "".join(title_parts) or "(untitled)"
            print(f"  [{obj_type}] {title}  (id: {item.get('id', 'n/a')})")
        print("\nConnectivity check passed.")
    except RuntimeError as exc:
        print(f"API request failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    _smoke_test()
