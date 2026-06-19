import os
import sys
from pathlib import Path

import pandas as pd
import psycopg2
import streamlit as st
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))
load_dotenv(BASE_DIR / ".env")

from rag.rag_pipeline import ask_rag
from rag.retriever import retrieve_documents


st.set_page_config(
    page_title="Enterprise Cortex RAG Platform",
    page_icon="🧠",
    layout="wide",
)


def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


@st.cache_data(ttl=60)
def run_query(query: str) -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df


st.sidebar.title("🧠 Enterprise Cortex")
page = st.sidebar.radio(
    "Navigation",
    [
        "📊 Analytics Dashboard",
        "💬 Ask Documents",
        "🔎 Knowledge Base Search",
    ],
)

st.title("Enterprise Cortex RAG Platform")
st.caption("PostgreSQL analytics + Pinecone RAG + Ollama")


if page == "📊 Analytics Dashboard":
    customers_count = run_query("SELECT COUNT(*) AS total FROM customers;")["total"][0]
    products_count = run_query("SELECT COUNT(*) AS total FROM products;")["total"][0]
    orders_count = run_query("SELECT COUNT(*) AS total FROM orders;")["total"][0]
    tickets_count = run_query("SELECT COUNT(*) AS total FROM support_tickets;")["total"][0]
    revenue = run_query("SELECT COALESCE(SUM(total_amount), 0) AS total FROM orders;")["total"][0]

    col1, col2, col3, col4, col5 = st.columns(5)

    col1.metric("Customers", f"{customers_count:,}")
    col2.metric("Products", f"{products_count:,}")
    col3.metric("Orders", f"{orders_count:,}")
    col4.metric("Tickets", f"{tickets_count:,}")
    col5.metric("Revenue", f"€{revenue:,.2f}")

    st.divider()

    left, right = st.columns(2)

    with left:
        st.subheader("Support Tickets by Issue Type")
        tickets_by_issue = run_query("""
            SELECT issue_type, COUNT(*) AS ticket_count
            FROM support_tickets
            GROUP BY issue_type
            ORDER BY ticket_count DESC;
        """)
        st.bar_chart(tickets_by_issue.set_index("issue_type"))

    with right:
        st.subheader("Orders by Customer City")
        orders_by_city = run_query("""
            SELECT c.city, COUNT(o.order_id) AS order_count
            FROM orders o
            JOIN customers c ON o.customer_id = c.customer_id
            GROUP BY c.city
            ORDER BY order_count DESC;
        """)
        st.bar_chart(orders_by_city.set_index("city"))

    st.divider()

    left, right = st.columns(2)

    with left:
        st.subheader("Top Products by Revenue")
        top_products = run_query("""
            SELECT 
                p.product_name,
                ROUND(SUM(oi.quantity * oi.unit_price), 2) AS revenue
            FROM order_items oi
            JOIN products p ON oi.product_id = p.product_id
            GROUP BY p.product_name
            ORDER BY revenue DESC
            LIMIT 10;
        """)
        st.dataframe(top_products, use_container_width=True)

    with right:
        st.subheader("Ticket Status Summary")
        ticket_status = run_query("""
            SELECT status, COUNT(*) AS count
            FROM support_tickets
            GROUP BY status
            ORDER BY count DESC;
        """)
        st.dataframe(ticket_status, use_container_width=True)

    st.divider()

    st.subheader("Recent Support Tickets")
    recent_tickets = run_query("""
        SELECT 
            st.ticket_id,
            c.first_name || ' ' || c.last_name AS customer_name,
            st.issue_type,
            st.status,
            st.created_at
        FROM support_tickets st
        JOIN customers c ON st.customer_id = c.customer_id
        ORDER BY st.created_at DESC
        LIMIT 20;
    """)

    st.dataframe(recent_tickets, use_container_width=True)


elif page == "💬 Ask Documents":
    st.subheader("💬 Ask Documents")
    st.write("Ask questions from refund policy, shipping policy, and FAQ documents.")

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    for item in st.session_state.chat_history:
        with st.chat_message("user"):
            st.write(item["question"])

        with st.chat_message("assistant"):
            st.write(item["answer"])
            st.caption("Sources: " + ", ".join(item["sources"]))

    question = st.chat_input("Ask a question, e.g. How long does a refund take?")

    if question:
        with st.chat_message("user"):
            st.write(question)

        with st.spinner("Retrieving documents and generating answer..."):
            result = ask_rag(question)

        answer = result["answer"]
        sources = result["sources"]
        documents = result["documents"]

        with st.chat_message("assistant"):
            st.write(answer)

            if sources:
                st.caption("Sources: " + ", ".join(sources))
            else:
                st.caption("Sources: No source found")

        st.session_state.chat_history.append(
            {
                "question": question,
                "answer": answer,
                "sources": sources,
            }
        )

        with st.expander("Retrieved chunks"):
            if documents:
                for doc in documents:
                    st.markdown(f"**{doc['source']} | Score: {round(doc['score'], 4)}**")
                    st.write(doc["text"])
                    st.divider()
            else:
                st.write("No retrieved chunks found.")


elif page == "🔎 Knowledge Base Search":
    st.subheader("🔎 Knowledge Base Search")
    st.write("This shows raw retrieved chunks from Pinecone before answer generation.")

    user_question = st.text_input("Search company policies or FAQ")

    if user_question:
        documents = retrieve_documents(user_question)

        if documents:
            for doc in documents:
                score = round(doc["score"], 4)
                document_name = doc["source"]
                text = doc["text"]

                with st.expander(f"{document_name} | Score: {score}"):
                    st.write(text)
        else:
            st.warning("No matching documents found.")