"""Carol combines trusted product FAQs with workspace-evidence question answering."""
from cortex import store

FAQ = {
    "What can Carol help me with?": "I am Carol. I can find evidence in your indexed workspace documents, explain filtered business metrics, and show the source and workflow behind an answer. I cannot make payments, migrate data or approve shipments by conversation.",
    "What data goes to cloud AI?": "Only explicitly enabled numeric aggregate explanations can leave the server. Names, addresses, bank details, document text and your question stay local. Internal Ollama can process relevant full content. The raw-content block is an active protection, not a disabled feature.",
    "How do I upload files safely?": "Data studio scans the complete upload with static checks and local ClamAV before parsing or splitting. Files at least 10 MiB are split into parts up to 9 MiB. CSV/JSON records and UTF-8 characters remain intact. PDF/XLSX parts require binary reassembly. No scanner guarantees a file is harmless.",
    "How can I track a delivery plan?": "Open Live logistics. An administrator must assign a RouteMind plan to your workspace. Enable 30-second polling or refresh manually. RouteMind plans may contain simulated inputs; they are not carrier GPS tracking.",
    "How long does a refund take?": None,
    "What is the standard shipping time?": None,
}


def ask(owner, question, route="documents", mode="Evidence only", frame=None):
    if question in FAQ and FAQ[question]:
        import secrets
        run_id = secrets.token_hex(12)
        steps = [{"agent": "Carol FAQ", "status": "completed", "detail": "Trusted product FAQ; no model call"}]
        store.save_run(owner, run_id, "carol_faq", "completed", 0, steps)
        store.save_message(owner, question, FAQ[question], [], run_id)
        return {"answer": FAQ[question], "run_id": run_id, "steps": steps, "hits": []}
    from cortex.agents import run_agents
    if mode == "Cloud aggregates" and not store.preferences(owner)["cloud_aggregates"]:
        raise ValueError("Enable aggregate-only cloud explanations in Security first.")
    return run_agents(owner, question, route, mode, frame)
