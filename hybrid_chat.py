# hybrid_chat.py - Fixed and Enhanced Version
import json
import time
import asyncio
from typing import List, Dict, Optional
from functools import lru_cache
import hashlib
from openai import OpenAI
from pinecone import Pinecone, ServerlessSpec
from neo4j import GraphDatabase
import config

# -----------------------------
# Config
# -----------------------------
EMBED_MODEL = "text-embedding-3-small"
CHAT_MODEL = "gpt-4o-mini"
TOP_K = 5
INDEX_NAME = config.PINECONE_INDEX_NAME
EMBEDDING_CACHE = {}  # Simple in-memory cache for embeddings

# -----------------------------
# Initialize clients
# -----------------------------
print("Initializing OpenAI client...")
client = OpenAI(api_key=config.OPENAI_API_KEY)

print("Initializing Pinecone client...")
pc = Pinecone(api_key=config.PINECONE_API_KEY)

# Connect to Pinecone index (with proper initialization check)
def get_pinecone_index():
    """Get or create Pinecone index with proper initialization."""
    if INDEX_NAME not in pc.list_indexes().names():
        print(f"Creating serverless index: {INDEX_NAME}")
        pc.create_index(
            name=INDEX_NAME,
            dimension=config.PINECONE_VECTOR_DIM,
            metric="cosine",
            spec=ServerlessSpec(
                cloud="gcp",  # FIX: Changed from "aws" to match region
                region="us-east1-gcp"
            )
        )
        # Wait for index to be ready
        print("Waiting for index to initialize...")
        while not pc.describe_index(INDEX_NAME).status['ready']:
            time.sleep(1)
        print("Index ready!")
    return pc.Index(INDEX_NAME)

index = get_pinecone_index()

# Connect to Neo4j
print("Connecting to Neo4j...")
driver = GraphDatabase.driver(
    config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD)
)

# Test Neo4j connection
try:
    with driver.session() as session:
        result = session.run("RETURN 1 AS test")
        result.single()
    print("✓ Neo4j connection successful")
except Exception as e:
    print(f"✗ Neo4j connection failed: {e}")
    exit(1)

# -----------------------------
# Helper functions
# -----------------------------
def embed_text(text: str) -> List[float]:
    """Get embedding for a text string with caching."""
    # Create cache key from text hash
    cache_key = hashlib.md5(text.encode()).hexdigest()
    
    if cache_key in EMBEDDING_CACHE:
        return EMBEDDING_CACHE[cache_key]
    
    try:
        resp = client.embeddings.create(model=EMBED_MODEL, input=[text])
        embedding = resp.data[0].embedding
        EMBEDDING_CACHE[cache_key] = embedding  # Cache for future use
        return embedding
    except Exception as e:
        print(f"Error generating embedding: {e}")
        return [0.0] * config.PINECONE_VECTOR_DIM  # Return zero vector as fallback

def pinecone_query(query_text: str, top_k=TOP_K):
    """Query Pinecone index using embedding."""
    try:
        vec = embed_text(query_text)
        res = index.query(
            vector=vec,
            top_k=top_k,
            include_metadata=True,
            include_values=False
        )
        print(f"✓ Pinecone returned {len(res['matches'])} results")
        return res["matches"]
    except Exception as e:
        print(f"✗ Pinecone query failed: {e}")
        return []

def fetch_graph_context(node_ids: List[str], neighborhood_depth=1):
    """
    Fetch neighboring nodes from Neo4j with enhanced relationship traversal.
    Now includes city-to-city connections for multi-day itinerary planning.
    """
    facts = []
    city_connections = []
    
    with driver.session() as session:
        for nid in node_ids:
            # Fetch direct relationships (attractions, hotels, activities in cities)
            q1 = (
                "MATCH (n:Entity {id:$nid})-[r]-(m:Entity) "
                "RETURN type(r) AS rel, labels(m) AS labels, m.id AS id, "
                "m.name AS name, m.type AS type, m.description AS description, "
                "m.tags AS tags "
                "LIMIT 10"
            )
            try:
                recs = session.run(q1, nid=nid)
                for r in recs:
                    facts.append({
                        "source": nid,
                        "rel": r["rel"],
                        "target_id": r["id"],
                        "target_name": r["name"],
                        "target_type": r["type"],
                        "target_desc": (r["description"] or "")[:400],
                        "target_tags": r.get("tags", []),
                        "labels": r["labels"]
                    })
            except Exception as e:
                print(f"Error fetching graph context for {nid}: {e}")
        
        # Fetch city-to-city connections for itinerary planning
        city_ids = [f["source"] for f in facts if "City" in f.get("labels", [])]
        if city_ids:
            q2 = (
                "MATCH (c1:City)-[r:Connected_To]->(c2:City) "
                "WHERE c1.id IN $city_ids "
                "RETURN c1.id AS from_city, c2.id AS to_city, c2.name AS to_city_name "
                "LIMIT 5"
            )
            try:
                city_recs = session.run(q2, city_ids=city_ids)
                city_connections = [dict(rec) for rec in city_recs]
            except Exception as e:
                print(f"Error fetching city connections: {e}")
    
    print(f"✓ Neo4j returned {len(facts)} relationships + {len(city_connections)} city connections")
    return facts, city_connections

def filter_by_theme(facts: List[Dict], theme: str) -> List[Dict]:
    """Filter attractions/activities by theme tags."""
    theme_keywords = {
        "romantic": ["romantic", "couple", "sunset", "beach", "spa", "dinner", "cruise"],
        "adventure": ["hiking", "trekking", "mountain", "adventure", "rafting", "cycling"],
        "cultural": ["temple", "museum", "historical", "culture", "heritage", "traditional"],
        "family": ["family", "kids", "zoo", "park", "entertainment"]
    }
    
    keywords = theme_keywords.get(theme.lower(), [])
    if not keywords:
        return facts
    
    filtered = []
    for fact in facts:
        tags = fact.get("target_tags", [])
        desc = fact.get("target_desc", "").lower()
        name = fact.get("target_name", "").lower()
        
        # Check if any keyword matches tags or description
        if any(kw in str(tags).lower() or kw in desc or kw in name for kw in keywords):
            filtered.append(fact)
    
    return filtered if filtered else facts[:10]  # Fallback to top results

def summarize_top_nodes(matches: List[Dict]) -> str:
    """Create a concise summary of top search results."""
    if not matches:
        return "No relevant results found."
    
    summary_parts = []
    for i, match in enumerate(matches[:3], 1):
        meta = match.get("metadata", {})
        score = match.get("score", 0)
        summary_parts.append(
            f"{i}. {meta.get('name', 'Unknown')} ({meta.get('type', 'N/A')}) "
            f"in {meta.get('city', 'N/A')} - Relevance: {score:.2f}"
        )
    
    return "\n".join(summary_parts)

def build_prompt(user_query, pinecone_matches, graph_facts, city_connections):
    """
    Build an enhanced chat prompt with chain-of-thought reasoning.
    Now includes better structure for itinerary generation.
    """
    system = """You are an expert Vietnam travel assistant specializing in creating personalized itineraries.

Your approach:
1. ANALYZE the user's preferences (duration, theme, interests)
2. IDENTIFY the most relevant cities and attractions from the provided context
3. STRUCTURE a day-by-day itinerary with logical flow
4. INCLUDE specific node IDs as references (e.g., [attraction_123])
5. PROVIDE practical tips (travel time, best times to visit)

Format your response as:
- Brief introduction matching the theme
- Day-by-day breakdown with morning/afternoon/evening activities
- Accommodation suggestions
- Practical travel tips

Be concise but detailed. Cite node IDs for credibility."""

    # Extract theme from query
    theme = ""
    if "romantic" in user_query.lower():
        theme = "romantic"
    elif "adventure" in user_query.lower():
        theme = "adventure"
    elif "cultural" in user_query.lower():
        theme = "cultural"
    elif "family" in user_query.lower():
        theme = "family"
    
    # Filter facts by theme if detected
    if theme and graph_facts:
        graph_facts = filter_by_theme(graph_facts, theme)

    # Build vector context (top semantic matches)
    vec_context = []
    for m in pinecone_matches[:8]:
        meta = m.get("metadata", {})
        score = m.get("score", 0)
        snippet = (
            f"- [{m['id']}] {meta.get('name', 'N/A')} ({meta.get('type', 'N/A')}) "
            f"in {meta.get('city', 'N/A')} - Score: {score:.3f}"
        )
        if meta.get("tags"):
            snippet += f" | Tags: {', '.join(meta.get('tags', [])[:3])}"
        vec_context.append(snippet)

    # Build graph context (relationships and details)
    graph_context = []
    for f in graph_facts[:20]:
        relation = (
            f"- [{f['source']}] --{f['rel']}--> [{f['target_id']}] "
            f"{f['target_name']} ({f['target_type']}): {f['target_desc'][:200]}"
        )
        if f.get('target_tags'):
            relation += f" | Tags: {', '.join(f['target_tags'][:3])}"
        graph_context.append(relation)

    # Build city connections context
    city_context = ""
    if city_connections:
        city_context = "\n\nCity Connections (for multi-day planning):\n" + "\n".join([
            f"- {c['from_city']} → {c['to_city_name']}"
            for c in city_connections
        ])

    prompt = [
        {"role": "system", "content": system},
        {"role": "user", "content": (
            f"User Query: {user_query}\n\n"
            f"=== TOP SEMANTIC MATCHES (from vector search) ===\n"
            f"{chr(10).join(vec_context[:10])}\n\n"
            f"=== KNOWLEDGE GRAPH RELATIONSHIPS ===\n"
            f"{chr(10).join(graph_context[:20])}"
            f"{city_context}\n\n"
            f"Based on the above context, create a detailed response. "
            f"Use node IDs in [brackets] when referencing specific places."
        )}
    ]
    return prompt

def call_chat(prompt_messages):
    """Call OpenAI ChatCompletion with error handling."""
    try:
        resp = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=prompt_messages,
            max_tokens=800,
            temperature=0.3  # Lower temp for more consistent itineraries
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"Error calling OpenAI: {e}"

# -----------------------------
# Interactive chat
# -----------------------------
def interactive_chat():
    """Enhanced interactive chat with better user experience."""
    print("\n" + "="*60)
    print("🌏 HYBRID VIETNAM TRAVEL ASSISTANT 🌏")
    print("="*60)
    print("\nCombining Vector Search (Pinecone) + Knowledge Graph (Neo4j)")
    print("Powered by OpenAI GPT-4o-mini\n")
    print("Examples:")
    print("  - 'Create a romantic 4-day itinerary for Vietnam'")
    print("  - 'Best adventure activities in Sapa and Ha Long Bay'")
    print("  - 'Family-friendly attractions in Ho Chi Minh City'\n")
    print("Type 'exit' or 'quit' to end the session.\n")
    print("="*60 + "\n")
    
    while True:
        query = input("🔍 Enter your travel question: ").strip()
        
        if not query or query.lower() in ("exit", "quit"):
            print("\n👋 Thank you for using the Hybrid Travel Assistant!")
            break

        print("\n⏳ Processing your query...")
        print("  [1/4] Searching vector database...")
        matches = pinecone_query(query, top_k=TOP_K)
        
        print("  [2/4] Extracting node IDs...")
        match_ids = [m["id"] for m in matches]
        
        print("  [3/4] Fetching knowledge graph relationships...")
        graph_facts, city_connections = fetch_graph_context(match_ids)
        
        print("  [4/4] Generating AI response...\n")
        prompt = build_prompt(query, matches, graph_facts, city_connections)
        answer = call_chat(prompt)
        
        print("\n" + "="*60)
        print("🤖 ASSISTANT RESPONSE")
        print("="*60 + "\n")
        print(answer)
        print("\n" + "="*60)
        
        # Show summary statistics
        print(f"\n📊 Context Used:")
        print(f"  • Vector matches: {len(matches)}")
        print(f"  • Graph relationships: {len(graph_facts)}")
        print(f"  • City connections: {len(city_connections)}")
        print(f"  • Cached embeddings: {len(EMBEDDING_CACHE)}")
        print("\n" + "="*60 + "\n")
# -----------------------------
# Flask integration helper
# -----------------------------
# -----------------------------
# Main entry point
# -----------------------------
if __name__ == "__main__":
    try:
        interactive_chat()
    except KeyboardInterrupt:
        print("\n\n👋 Session interrupted. Goodbye!")
    finally:
        driver.close()
        print("✓ Connections closed successfully.")