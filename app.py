from flask import Flask, render_template, request, jsonify
import hybrid_chat  # uses your existing pipeline

app = Flask(__name__)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/ask", methods=["POST"])
def ask():
    data = request.get_json()
    query = data.get("query", "").strip()

    if not query:
        return jsonify({"error": "Empty query"}), 400

    try:
        matches = hybrid_chat.pinecone_query(query)
        match_ids = [m["id"] for m in matches]
        graph_facts, city_connections = hybrid_chat.fetch_graph_context(match_ids)
        prompt = hybrid_chat.build_prompt(query, matches, graph_facts, city_connections)
        answer = hybrid_chat.call_chat(prompt)
        return jsonify({"answer": answer})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/visualize")
def visualize():
    return render_template("neo4j_viz.html")

if __name__ == "__main__":
    app.run(debug=True)
