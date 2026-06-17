# Enterprise Cortex RAG Platform

## 🚀 Overview

Enterprise Cortex RAG Platform is an end-to-end GenAI, Data Engineering, and Snowflake Cortex project designed to demonstrate enterprise-grade AI architecture patterns.

This project combines structured business data, unstructured documents, Retrieval-Augmented Generation (RAG), data warehousing, workflow automation, and cloud-native deployment into a single platform.

The goal is to simulate how modern enterprises build AI-powered knowledge assistants, analytics platforms, and intelligent decision-support systems.

---

## 🎯 Project Objectives

* Build a normalized PostgreSQL transactional database.
* Implement enterprise data warehouse architecture.
* Design Bronze, Silver, and Gold data layers.
* Implement ETL/ELT pipelines using Python and dbt.
* Build RAG pipelines using Pinecone.
* Implement Snowflake Cortex Search.
* Implement Snowflake Cortex Analyst.
* Automate ingestion using n8n.
* Build AI applications using Streamlit.
* Containerize services using Docker.
* Deploy workloads on Kubernetes (k3d).

---

## 🏗 Architecture

```text
Data Sources
│
├── PostgreSQL
├── CSV Files
├── JSON Files
├── PDF Documents
├── Support Tickets
│
▼
n8n Workflow Automation
│
▼
Python ETL / Snowpark
│
▼
Data Warehouse
│
├── Bronze Layer
├── Silver Layer
├── Gold Layer
│
▼
AI Layer
│
├── Pinecone RAG
├── Cortex Search
├── Cortex Analyst
│
▼
Streamlit Application
│
▼
Docker & Kubernetes
```

---

## 💼 Business Use Case

This platform simulates an enterprise customer support and knowledge management system.

Users can ask questions such as:

* What are customers complaining about most?
* Which products generate the highest support volume?
* What does the refund policy say?
* Which customer segments generate the most revenue?
* Summarize support tickets related to delivery delays.
* Generate insights from structured business data.

---

## 🧠 AI Capabilities

### Retrieval-Augmented Generation (RAG)

The platform supports multiple retrieval strategies:

* Naive RAG
* Hybrid RAG
* Parent-Child RAG
* Contextual Retrieval
* Agentic RAG
* Snowflake Cortex Search

### Vector Search

Supported vector databases:

* Pinecone
* Snowflake Cortex Search

### LLM Integration

Supported models:

* GPT-4
* Llama 3.x
* Mistral
* Claude
* Local Ollama Models

---

## 🏢 Data Architecture

### Bronze Layer

Raw source data.

Examples:

* raw_customers
* raw_orders
* raw_products
* raw_support_tickets
* raw_documents

### Silver Layer

Cleaned and standardized data.

Examples:

* customers_clean
* orders_clean
* products_clean
* support_tickets_clean
* document_chunks

### Gold Layer

Business-ready models.

Examples:

* dim_customer
* dim_product
* dim_date
* fact_orders
* fact_order_items
* fact_support_tickets

---

## 📊 Data Modeling

### OLTP Schema

Normalized PostgreSQL Database

Tables:

* customers
* products
* orders
* order_items
* support_tickets

### Data Warehouse Schema

Star Schema

Fact Tables:

* fact_orders
* fact_order_items
* fact_support_tickets

Dimension Tables:

* dim_customer
* dim_product
* dim_date

---

## ⚙️ Technology Stack

### Data Engineering

* PostgreSQL
* Snowflake
* Snowpark
* dbt
* Python
* Pandas

### AI Engineering

* LangChain
* LangGraph
* Pinecone
* Snowflake Cortex Search
* Snowflake Cortex Analyst
* Sentence Transformers

### Workflow Automation

* n8n

### Application Layer

* Streamlit
* FastAPI

### DevOps

* Docker
* Kubernetes (k3d)
* GitHub Actions

---

## 📂 Repository Structure

```text
enterprise-cortex-rag-platform/
│
├── data/
│   ├── raw/
│   ├── processed/
│   └── sample_documents/
│
├── database/
│   ├── postgres_schema.sql
│   ├── seed_data.sql
│   └── snowflake_schema.sql
│
├── etl/
│   ├── extract/
│   ├── transform/
│   └── load/
│
├── dbt/
│
├── rag/
│   ├── pinecone/
│   └── cortex_search/
│
├── app/
│   ├── streamlit/
│   └── fastapi/
│
├── n8n/
│   └── workflows/
│
├── docker/
│
├── k8s/
│
├── docs/
│
├── requirements.txt
├── docker-compose.yml
└── README.md
```

---

## 🔄 End-to-End Workflow

1. Data enters PostgreSQL or external files.
2. n8n triggers ingestion workflows.
3. Python ETL processes source data.
4. dbt transforms data into warehouse models.
5. Data is loaded into Snowflake.
6. Cortex Search indexes document content.
7. Cortex Analyst enables natural-language analytics.
8. Streamlit provides an AI-powered interface.
9. Docker and Kubernetes handle deployment.

---

## 📈 Future Enhancements

* Graph RAG using Neo4j
* LangSmith tracing
* RAGAS evaluation
* DeepEval testing
* Arize Phoenix monitoring
* OpenTelemetry observability
* Multi-agent workflows with LangGraph
* MCP Server Integration
* Azure OpenAI
* AWS Bedrock

---

## 🎓 Learning Outcomes

This project demonstrates practical experience in:

* Data Engineering
* AI Engineering
* Retrieval-Augmented Generation (RAG)
* Snowflake Cortex
* Data Warehousing
* Solution Architecture
* Workflow Automation
* Kubernetes
* Enterprise AI Systems

---

## 📜 License

MIT License

---

## 👨‍💻 Author

Hamza Ahmed Khan

AI/ML & Software Engineer

LinkedIn: https://linkedin.com/in/hamy-khan-0a9b5275

GitHub: https://github.com/HamzaAhmedKhan786
