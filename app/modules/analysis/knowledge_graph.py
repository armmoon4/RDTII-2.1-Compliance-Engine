"""
Module 2 — Legal Knowledge Graph
Builds a directed graph using NetworkX to map article cross-references and supersession edges.
Processes FULL document text to extract all section/article references.
"""
import logging
import re
import networkx as nx

logger = logging.getLogger(__name__)

# Patterns tested on legal text from SG, MY, AU, UK, US jurisdictions
_SECTION_HEADING_RE = re.compile(
    r"(?i)^\s*(?:(?:part|chapter|title)\s+\d+[\.\d]*\s*[-–—]?\s*.*"
    r"|(?:section|article|clause|regulation|rule|paragraph|subsection|schedule|appendix|annex)\s+\d+[\.\d]*)\s*$",
)

_ARTICLE_DEF_RE = re.compile(
    r"(?i)(?:article|section|clause|regulation|rule|paragraph|subsection)\s+(\d+[A-Za-z]?[\.\d]*)"
)

_CROSS_REF_RE = re.compile(
    r"(?i)(?:subject to|pursuant to|in accordance with|under|by virtue of|as per|consistent with|set out in|referred to in|for the purposes of)\s+"
    r"(?:article|section|clause|regulation|rule|paragraph|subsection)\s+(\d+[A-Za-z]?[\.\d]*)"
)

_AMEND_RE = re.compile(
    r"(?i)(?:amends?|replaces?|supersedes?|repeals?|revokes?|substitutes?|inserts?|deletes?)\s+"
    r"(?:article|section|clause|regulation|rule|paragraph)\s+(\d+[A-Za-z]?[\.\d]*)"
)

# Detect law/act names in text
_LAW_NAME_RE = re.compile(
    r"(?i)\b((?:[A-Z][a-z]+(?:\s+(?:[A-Z][a-z]+|of|the|and|for|in|on|to|by|at|or|an|as))*)"
    r"\s+(?:Act|Regulation|Code|Order|Rule|Directive|Standard|Policy|Decree|Ordinance|Statute|Convention|Treaty|Protocol|Framework|Agreement|Law)"
    r"(?:\s*\(?[12]\d{3}\)?)?)"
)

# Detect date/timeframe mentions
_TIMEFRAME_RE = re.compile(
    r"(?i)(?:since|enacted|commenced|in force|adopted|passed|gazetted|notified|published|last amended|amended|revised|consolidated|updated)"
    r"\s*(?::?\s*)?"
    r"(?:"
    r"\d{1,2}\s+(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4}"
    r"|"
    r"(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},?\s+\d{4}"
    r"|"
    r"\d{4}"
    r")",
    re.IGNORECASE,
)


class LegalKnowledgeGraph:
    """Directed graph representing relationships between legal provisions."""

    def __init__(self):
        self.graph = nx.DiGraph()

    def add_document(self, text: str, source_id: str) -> None:
        """Parse full document text — extract all sections, references, amendments, law names, timeframes."""
        if not text or len(text.strip()) < 50:
            return

        # Use local caches for O(1) duplicate checks (avoid networkx overhead for large graphs)
        known_nodes: set[str] = set()
        known_edges: set[tuple[str, str, str]] = set()

        lines = text.split("\n")
        current_section = None

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue

            heading_match = _SECTION_HEADING_RE.match(stripped)
            if heading_match:
                current_section = f"{source_id}_L{i}"
                node_label = stripped[:120]
                if current_section not in known_nodes:
                    known_nodes.add(current_section)
                    self.graph.add_node(
                        current_section,
                        label=node_label,
                        line=i,
                        source_id=source_id,
                    )

            art_match = _ARTICLE_DEF_RE.search(stripped)
            if art_match:
                art_num = art_match.group(1)
                node_id = f"{source_id}_Art_{art_num}"
                if node_id not in known_nodes:
                    context = "\n".join(lines[max(0, i - 1): min(len(lines), i + 8)])
                    known_nodes.add(node_id)
                    self.graph.add_node(
                        node_id,
                        label=f"Article/Section {art_num}",
                        text=context[:600],
                        line=i,
                        source_id=source_id,
                    )
                current_section = node_id

            for ref in _CROSS_REF_RE.finditer(stripped):
                ref_num = ref.group(1)
                target = f"{source_id}_Art_{ref_num}"
                source = current_section or f"{source_id}_General"
                ek = (source, target, "cross_reference")
                if ek not in known_edges:
                    known_edges.add(ek)
                    self.graph.add_edge(source, target, relation="cross_reference")

            for amd in _AMEND_RE.finditer(stripped):
                ref_num = amd.group(1)
                target = f"{source_id}_Art_{ref_num}"
                source = current_section or f"{source_id}_General"
                ek = (source, target, "supersedes")
                if ek not in known_edges:
                    known_edges.add(ek)
                    self.graph.add_edge(source, target, relation="supersedes")

        # 5. Extract law names — only search first 100K chars (names always in title/header area)
        search_text = text[:100_000] if len(text) > 100_000 else text
        for match in _LAW_NAME_RE.finditer(search_text):
            law_name = match.group(1).strip()
            node_id = f"law_{law_name.lower().replace(' ', '_')[:80]}"
            if node_id not in known_nodes:
                known_nodes.add(node_id)
                self.graph.add_node(node_id, label=law_name, type="law", source_id=source_id)

        general = f"{source_id}_General"
        if general not in known_nodes:
            known_nodes.add(general)
            self.graph.add_node(general, label=f"Document {source_id}", text=text[:500], source_id=source_id)

        logger.info(
            f"[Graph] Document {source_id}: {len(known_nodes)} nodes, "
            f"{len(known_edges)} edges"
        )

    def resolve_supersession(self, node_id: str) -> str:
        """Traverse supersession chain to find the active node."""
        if not self.graph.has_node(node_id):
            return node_id
        overriding = [
            u for u, v, d in self.graph.in_edges(node_id, data=True)
            if d.get("relation") == "supersedes"
        ]
        if overriding:
            return self.resolve_supersession(overriding[0])
        return node_id

    def find_relevant_sections(self, keywords: list[str], source_id: str | None = None) -> list[str]:
        """Find node IDs whose label or text matches the given keywords."""
        matches = []
        for node, data in self.graph.nodes(data=True):
            if source_id and data.get("source_id") != source_id:
                continue
            label = (data.get("label") or "").lower()
            text = (data.get("text") or "").lower()
            combined = label + " " + text
            if any(kw.lower() in combined for kw in keywords):
                matches.append(node)
        return matches

    def get_document_sections(self, source_id: str) -> list[dict]:
        """Return all section/article nodes for a given document."""
        sections = []
        for node, data in self.graph.nodes(data=True):
            if data.get("source_id") == source_id and "Art_" in node:
                sections.append({
                    "node_id": node,
                    "label": data.get("label", ""),
                    "text": data.get("text", ""),
                    "line": data.get("line", 0),
                })
        return sorted(sections, key=lambda s: s["line"])
