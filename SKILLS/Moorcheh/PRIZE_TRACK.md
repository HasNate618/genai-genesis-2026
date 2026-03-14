# Best use of Moorcheh

**Our Socials:**        🌐 [**Website**](https://moorcheh.ai)       🗨️ [Discord](https://discord.gg/cR7GzHZnBj) ****    🤖 [**LinkedIn](https://www.linkedin.com/company/moorcheh-ai/)**     

# **🤖 About**

[**Moorcheh**](https://www.moorcheh.ai/) is the semantic engine that combines high-fidelity storage, stateful context, and explainable retrieval. Built specifically for agentic AI and RAG applications, Moorcheh provides a powerful foundation for building intelligent systems that can understand, remember, and reason about information.

🔑 Get API Key : https://console.moorcheh.ai/

# 🏆 Challenge Brief

This challenge invites developers to build intelligent applications using Moorcheh.

Moorcheh enables applications to:

- Store structured or unstructured knowledge
- Retrieve relevant context through semantic search
- Generate explainable AI responses

Participants are encouraged to build **AI-powered tools** that demonstrate how Moorcheh can power:

- context-aware AI agents
- intelligent search systems
- knowledge-driven applications

**Note:**

Using a chatbot boilerplate is **not required**. However, to qualify for the challenge, your project **must integrate the Moorcheh API**.

# 🛠️ What Developers Can Build

Below are example ideas that can be built using Moorcheh. These are only suggestions -participants are encouraged to explore creative use cases.

- **AI Agent With Moorcheh memory**
    
    Create an agent that:
    
    - Stores interactions
    - Recalls previous conversations
    - Uses contextual reasoning
- AI Research Assistant
    
    Build an assistant that:
    
    - Stores research papers
    - Retrieves relevant sections
    - Answers questions with citations
- Smart Customer Support Bot
    - Store company documentation
    - Retrieve relevant information
    - Generate contextual answers
- Knowledge Search Engine
    - Index large document collections
    - Provide semantic search
    - Show explainable retrieval

# 🧩 Core Concepts

## 🗃️ Namespaces

Namespaces act as **logical isolation layers** within your account. They help organize and separate different datasets.

Namespaces can be of two types:

**Text Namespaces**

- Moorcheh automatically handles embeddings for you.
- You only upload the raw text data.

**Vector Namespaces**

- Developers provide their own embeddings.
- Useful when using external embedding models.

Documentation:

https://docs.moorcheh.ai/api-reference/namespaces/create

## 📤 Uploading Files

Moorcheh allows you to ingest data in multiple formats.

### Upload Large Files

Use the **Upload File URL endpoint** to upload large files.

- Recommended file size: up to **100 MB**

Docs:

https://docs.moorcheh.ai/api-reference/data/upload-file-urlUpload Text or Vector Data

## 🧾 Upload Text or Vector Data

You can upload structured data directly using API endpoints.

**Text Upload**

https://docs.moorcheh.ai/api-reference/data/upload-text

**Vector Upload**

https://docs.moorcheh.ai/api-reference/data/upload-vector

**Tip**

If you upload vector embeddings, include the **original text in metadata**.

This makes it easier to display context during semantic search.

## 🔍 Search and Answer

These endpoints allow you to retrieve and generate information from your stored knowledge.

### Search

The search endpoint performs **semantic retrieval**.

For **text namespaces**

- Use natural language queries.

For **vector namespaces**

- Provide embedding vectors for search.

Documentation:

https://docs.moorcheh.ai/api-reference/search/query

---

### Answer

The Answer endpoint performs:

1. Semantic search
2. Context retrieval
3. LLM generation on top of retrieved results

This allows you to build **RAG pipelines easily**.

Docs:

https://docs.moorcheh.ai/api-reference/ai/generate

## 📚 Developer Resource :

1. Docs ( mostly can find all resources here as well )  : https://docs.moorcheh.ai/
2. Chat boilerplate : https://docs.moorcheh.ai/integrations/chat-boilerplate/overview
3. Python SDK : https://github.com/moorcheh-ai/moorcheh-python-sdk
4. **Agent Skills (Prebuilt AI Agent Capabilities) :** https://github.com/moorcheh-ai/agent-skills
5. MCP ( recommended if you are using any agentic IDE ) : https://docs.moorcheh.ai/integrations/mcp/overview
6. Langchain  : https://docs.moorcheh.ai/integrations/langchain/overview
7. LlamaIndex **** : https://docs.moorcheh.ai/integrations/llamaindex/overview
8. Firecrawl : https://github.com/moorcheh-ai/moorcheh-examples/tree/main/AnalyzingMoorchehWebsite_WithFirecrawl
